"""Orchestration : touche push-to-talk -> capture (+ fenêtre cible) -> transcription
locale -> reformulation -> insertion dans la fenêtre cible -> historique -> interface.

Threads : l'interface Qt et la zone de notification vivent dans le thread principal ;
le hook clavier, la capture et le moteur ont les leurs. Tout ce qui touche l'interface
depuis un autre thread passe par un signal Qt.

Le journal ne contient jamais le texte dicté : seulement nombres de mots et durées.
"""

import logging
import logging.handlers
import os
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from . import APP_NAME, __version__
from .audio import Recorder, Recording
from .config import Config, log_dir
from .engine import DictationEngine
from .hotkey import PushToTalkHook
from .inserter import CLIPBOARD_ONLY, Inserter
from .reformulate import OFF, RULES, OpenAICompatClient, Reformulator
from .sounds import SoundPlayer
from .storage import Database, record_transcript
from .target import Target, capture_foreground
from .transcriber import Transcript
from .tray import TrayIcon
from .ui import theme
from .ui.context import EngineInfo, UiContext, microphone_access
from .ui.window import MainWindow
from .vocabulary import Vocabulary
from .win32 import SingleInstance

log = logging.getLogger(__name__)

# Canal local (canal nommé, propre à la session) : un second lancement demande à
# l'instance en cours d'afficher sa fenêtre, puis s'arrête.
ACTIVATE_SERVER = f"Dictera.Activate.{os.environ.get('USERNAME', 'user')}"


def setup_logging() -> None:
    directory = log_dir()
    directory.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [
        logging.handlers.RotatingFileHandler(
            directory / "dictera.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
        )
    ]
    if sys.stderr is not None:  # absent quand l'exécutable est lancé sans console
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        handlers=handlers,
    )


def create_qt_app() -> QApplication:
    qt = QApplication.instance() or QApplication(sys.argv)
    qt.setApplicationName(APP_NAME)
    qt.setQuitOnLastWindowClosed(False)  # fenêtre fermée = Dictera reste dans la zone de notification
    qt.setFont(theme.font(9.5))
    qt.setStyleSheet(theme.STYLESHEET)
    return qt


class _Bridge(QObject):
    """Signaux émis depuis les threads de travail, reçus dans le thread de l'interface."""
    dictation_saved = Signal()


class DicteraApp:
    def __init__(self, config: Config, db: Database | None = None):
        self.config = config
        self.qt = create_qt_app()
        self.sounds = SoundPlayer(config.sounds_enabled)
        self.recorder = Recorder(config.input_device, config.max_record_s)
        self.hook = PushToTalkHook(config.hotkey_vk, self._on_press, self._on_release, self._on_cancel)
        self.db = db or Database()  # base fournie : tests de bout en bout sur une base temporaire
        self.vocabulary = Vocabulary()
        self.vocabulary.reload(self.db.words(), self.db.corrections())  # la base fait foi
        self.engine = DictationEngine(
            config.whisper_model, config.language, self._on_transcript, self._on_engine_error,
            vocabulary=self.vocabulary, reformulator=self._make_reformulator(),
        )
        self.inserter = Inserter(
            config.paste_delay_ms, config.restore_delay_ms, config.paste_keys,
            config.shift_insert_apps, config.restore_clipboard, config.clipboard_no_history,
        )
        self._target: Target | None = None
        self._reform_status = "Vérification du LLM local…"

        self.bridge = _Bridge()
        self.ctx = UiContext(self.db, config, self.vocabulary, engine_info=self._engine_info,
                             on_setting_changed=self._apply_setting, on_vocabulary_changed=self._reload_vocabulary)
        self.window = MainWindow(self.ctx)
        self.bridge.dictation_saved.connect(self._notify_listeners)
        self.tray = TrayIcon(
            config.hotkey_label,
            sounds_enabled=lambda: self.sounds.enabled,
            on_toggle_sounds=self._toggle_sounds,
            on_quit=self.quit,
            on_open=self.window.bring_to_front,
        )
        self._status_timer = QTimer(interval=1000, timeout=self._update_status)
        self._activation = QLocalServer()
        self._activation.newConnection.connect(self._on_activation)

    # -- cycle de vie -------------------------------------------------------------------

    def run(self) -> int:
        log.info("%s %s démarre (touche : %s)", APP_NAME, __version__, self.config.hotkey_label)
        try:
            self.recorder.open()
        except Exception as e:  # le micro sera rouvert au premier appui
            log.error("Ouverture du micro impossible au lancement : %s", e)
        try:
            self.sounds.open()
        except Exception as e:
            log.warning("Sortie audio indisponible : %s", e)
        self.engine.start()  # sonde GPU + chargement du modèle en arrière-plan
        self.hook.start()
        self._refresh_reform_status()
        self.tray.show()
        self.window.show()  # spec § 9 : au lancement, le Tableau de bord
        self._status_timer.start()
        self._update_status()
        QLocalServer.removeServer(ACTIVATE_SERVER)  # canal laissé par une instance qui aurait planté
        if not self._activation.listen(ACTIVATE_SERVER):
            log.warning("Canal d'activation indisponible : %s", self._activation.errorString())
        allowed, why = microphone_access()
        if allowed is False:
            self.tray.notify(f"{why}. Ouvrez Réglages > Autorisations pour l'activer.")
        code = self.qt.exec()
        log.info("%s arrêté", APP_NAME)
        return code

    def _on_activation(self) -> None:
        while (conn := self._activation.nextPendingConnection()) is not None:
            conn.disconnectFromServer()
            log.info("Second lancement : affichage de la fenêtre")
            self.window.bring_to_front()

    def quit(self) -> None:
        self._activation.close()
        self._status_timer.stop()
        self.hook.stop()
        self.engine.stop()
        self.recorder.cancel()
        self.recorder.close()
        self.sounds.close()
        self.db.close()
        self.tray.stop()
        self.window.quitting = True
        self.window.close()
        self.qt.quit()

    # -- dictée (threads du hook et du moteur) ------------------------------------------

    def _on_press(self, _injected: bool) -> None:
        # La cible est figée à l'appui : c'est là que l'utilisateur veut écrire.
        self._target = capture_foreground()
        try:
            self.recorder.start()
        except Exception as e:
            log.error("Impossible d'ouvrir le micro : %s", e)
            self.tray.notify("Micro indisponible. Vérifiez le périphérique d'entrée et les "
                             "réglages de confidentialité Windows (Microphone).")
            return
        self.sounds.start()
        self.tray.set_recording(True)

    def _on_release(self) -> None:
        released_at = time.perf_counter()
        rec = self.recorder.stop()
        self.tray.set_recording(False)
        if rec is None:
            return
        self.sounds.stop()
        target, self._target = self._target, None
        self._handle_recording(rec, released_at, target)

    def _on_cancel(self) -> None:
        self.recorder.cancel()
        self._target = None
        self.tray.set_recording(False)
        log.info("Dictée annulée : autre touche pressée pendant le maintien (raccourci)")

    def _handle_recording(self, rec: Recording, released_at: float, target: Target | None) -> None:
        if rec.duration_s * 1000 < self.config.min_hold_ms:
            log.info("Appui trop court (%.0f ms) : ignoré", rec.duration_s * 1000)
            return
        self.engine.submit(rec, released_at, context=target)

    def _on_transcript(self, t: Transcript) -> None:
        """Appelé par le thread du moteur : les dictées sont donc insérées une par une, dans l'ordre."""
        if t.empty:
            log.info("Aucune parole détectée (%.2f s d'audio) : rien à transcrire", t.audio_s)
            return
        log.info("Transcription (%s) : %d mots, %.2f s de parole, latence %.0f ms, corrections %s, "
                 "reformulation %s en %.0f ms", t.model, len(t.final_text.split()), t.speech_s,
                 t.latency_ms, t.corrections or "aucune", t.reformulation, t.reformulation_ms)
        try:
            result = self.inserter.insert(t.final_text, t.context)
            status = result.status
        except Exception as e:
            log.exception("Échec de l'insertion")
            self.tray.notify(f"Insertion impossible : {e}")
            status = "error"
        else:
            if result.status == CLIPBOARD_ONLY:
                self.tray.notify(f"Texte copié dans le presse-papiers ({result.reason}). Collez-le avec Ctrl+V.")
        # Même non collée, la dictée est gardée : l'historique permet de la recopier.
        try:
            record_transcript(self.db, t, t.context, status)
        except Exception:
            log.exception("Enregistrement de la dictée dans l'historique impossible")
            return
        self.bridge.dictation_saved.emit()

    def _on_engine_error(self, message: str) -> None:
        self.tray.notify(message.splitlines()[0])

    # -- interface (thread principal) ---------------------------------------------------

    def _notify_listeners(self) -> None:
        for listener in self.ctx.listeners:
            listener()

    def _engine_info(self) -> EngineInfo:
        gpu = self.engine.gpu
        device = "CUDA · " + gpu.device.replace("NVIDIA GeForce ", "") if gpu and gpu.device else "CUDA"
        return EngineInfo(model=self.engine.transcriber.model_name if self.engine.ready else "",
                          device=device, error=self.engine.error or "", reformulation=self._reform_status)

    def _update_status(self) -> None:
        info = self._engine_info()
        if info.error:
            self.window.set_status("Moteur indisponible : voir Réglages.")
            self._status_timer.stop()
        elif info.model:
            self.window.set_status(f"Moteur prêt · {info.model}\n{self.config.hotkey_label} pour dicter")
            self._status_timer.stop()
            self.window.refresh_current()
        else:
            self.window.set_status("Chargement du moteur…")

    def _make_reformulator(self) -> Reformulator:
        c = self.config
        llm = None
        if c.llm_enabled:
            try:
                llm = OpenAICompatClient(c.llm_url, c.llm_model, c.llm_timeout_s, c.llm_temperature)
            except ValueError as e:
                log.error("%s : reformulation par règles", e)
                return Reformulator(RULES if c.reformulation != OFF else OFF, keep_terms=self.vocabulary.words)
        return Reformulator(c.reformulation, c.ollama_url, c.ollama_model, c.ollama_timeout_s,
                            keep_terms=self.vocabulary.words, llm=llm)

    def _refresh_reform_status(self) -> None:
        """L'état d'Ollama demande une requête locale (jusqu'à 1,5 s) : jamais dans le thread de l'interface."""
        reformulator = self.engine.reformulator

        def work():
            self._reform_status = reformulator.status()
            log.info("Reformulation : %s", self._reform_status)
            self.bridge.dictation_saved.emit()  # simple rafraîchissement de la page visible

        threading.Thread(target=work, name="dictera-ollama-probe", daemon=True).start()

    def _apply_setting(self, key: str) -> None:
        c = self.config
        if key == "hotkey":
            self.hook.set_key(c.hotkey_vk)
            self.tray.set_hotkey_label(c.hotkey_label)
            self._update_status()
        elif key == "sounds_enabled":
            self.sounds.enabled = c.sounds_enabled
        elif key == "restore_clipboard":
            self.inserter.restore_clipboard = c.restore_clipboard
        elif key == "reformulation" or key.startswith("llm_"):
            self.engine.reformulator = self._make_reformulator()
            self._refresh_reform_status()
        elif key == "language":
            self.engine.transcriber.language = c.language  # lu à chaque transcription
        elif key == "input_device" and not self.recorder.recording:
            self.recorder.close()
            self.recorder.device = c.input_device
            try:
                self.recorder.open()
            except Exception as e:
                log.error("Micro « %s » indisponible : %s", c.input_device, e)
                self.tray.notify("Ce micro ne peut pas être ouvert. Choisissez-en un autre dans les Réglages.")
        log.info("Réglage modifié : %s", key)

    def _reload_vocabulary(self) -> None:
        self.vocabulary.reload(self.db.words(), self.db.corrections())

    def _toggle_sounds(self) -> None:
        self.sounds.enabled = self.config.sounds_enabled = not self.sounds.enabled
        self.config.save()
        self.window.refresh_current()


def _activate_running_instance() -> bool:
    sock = QLocalSocket()
    sock.connectToServer(ACTIVATE_SERVER)
    ok = sock.waitForConnected(1500)
    sock.disconnectFromServer()
    return ok


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    setup_logging()
    if argv[:1] == ["--self-test"]:
        from . import selftest
        return selftest.run(Path(argv[1]) if len(argv) > 1 else None)
    instance = SingleInstance("Local\\Dictera.SingleInstance")
    if instance.already_running:
        shown = _activate_running_instance()
        log.info("Dictera tourne déjà : %s", "fenêtre affichée" if shown else "instance injoignable")
        return 0
    try:
        return DicteraApp(Config.load()).run()
    finally:
        instance.release()
