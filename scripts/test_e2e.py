"""Test de bout en bout : la vraie DicteraApp, de la touche au texte collé et enregistré.

Chaîne réelle : hook clavier (WH_KEYBOARD_LL) -> capture de la fenêtre cible à l'appui
-> moteur GPU (Whisper) -> corrections -> reformulation -> collage (presse-papiers +
SendInput) -> restauration du presse-papiers -> historique SQLite -> rafraîchissement
de l'interface. Le tout dans la boucle Qt réelle (exec), comme DicteraApp.run().

Seul le micro est remplacé : il « entend » une phrase synthétisée hors ligne (voix
fr-FR). Pour ne pas gêner une instance de Dictera déjà lancée (Ctrl droit), le test
écoute F24, et travaille sur une base et une config temporaires. Votre presse-papiers
réel est remis à la fin.
"""

import json
import subprocess
import sys
import tempfile
import threading
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import numpy as np  # noqa: E402
from PySide6.QtCore import QTimer  # noqa: E402

from dictera import clipboard, stats, target as tgt, win32  # noqa: E402
from dictera.app import DicteraApp  # noqa: E402
from dictera.audio import SAMPLE_RATE, Recording  # noqa: E402
from dictera.config import Config  # noqa: E402
from dictera.storage import Database  # noqa: E402

PHRASE = "Euh, bonjour, je teste Dictera de bout en bout avec un nouveau ski pour Claude Code."
VK_F24 = 0x87


class SpeechRecorder:
    """Remplace le micro : renvoie la phrase synthétisée, avec la même interface que Recorder."""

    def __init__(self, samples: np.ndarray):
        self.samples, self.recording, self.started = samples, False, 0

    def open(self): pass
    def close(self): pass

    def start(self):
        self.recording, self.started = True, self.started + 1

    def stop(self):
        if not self.recording:
            return None
        self.recording = False
        return Recording(self.samples, SAMPLE_RATE, 0.0, False, 0)

    def cancel(self):
        self.recording = False


def main() -> int:
    from test_phase2 import synthesize

    tmp = Path(tempfile.mkdtemp(prefix="dictera-e2e-"))
    wav = tmp / "phrase.wav"
    synthesize(PHRASE, wav)
    with wave.open(str(wav), "rb") as w:
        speech = np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(np.float32) / 32768

    cfg = Config(hotkey="F24", sounds_enabled=False, reformulation="rules", first_name="Test")
    cfg.save = lambda path=None: Config.save(cfg, tmp / "config.json")  # jamais la vraie config
    db = Database(tmp / "dictera.db")
    app = DicteraApp(cfg, db=db)
    app.recorder = SpeechRecorder(speech)
    saved = threading.Event()
    app.ctx.listeners.append(saved.set)  # appelé dans le thread de l'interface après l'enregistrement
    real_clipboard = clipboard.snapshot()
    target_app = subprocess.Popen([sys.executable, str(ROOT / "scripts" / "_target_window.py")],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding="utf-8")
    hwnds = json.loads(target_app.stdout.readline())
    result: dict = {}

    def scenario():
        """Thread du « faux utilisateur » : la boucle Qt tourne pendant ce temps (exec)."""
        try:
            t0 = time.time()
            while not (app.engine.ready or app.engine.error):
                time.sleep(0.1)
            result["engine"] = app.engine.error or f"prêt en {time.time() - t0:.1f} s"
            original = f"Presse-papiers d'origine (bout en bout) {time.strftime('%H:%M:%S')}"
            clipboard.set_text(original)
            result["original"] = original
            target = tgt.Target(hwnds["target"], 0, 0, tgt.u32.GetWindowThreadProcessId(hwnds["target"], None),
                                "", "", False)
            tgt.focus(target, 2.0)
            time.sleep(0.3)
            win32.send_key(VK_F24, up=False)  # l'utilisateur maintient la touche…
            time.sleep(1.0)
            other = tgt.Target(hwnds["other"], 0, 0, tgt.u32.GetWindowThreadProcessId(hwnds["other"], None),
                               "", "", False)
            tgt.focus(other, 2.0)  # … change de fenêtre pendant la dictée…
            time.sleep(0.3)
            released = time.perf_counter()
            win32.send_key(VK_F24, up=True)  # … et relâche.
            result["saved"] = saved.wait(30)
            result["release_to_saved_ms"] = (time.perf_counter() - released) * 1000
            time.sleep(0.8)  # restauration du presse-papiers (restore_delay_ms = 500)
            result["clipboard"] = clipboard.get_text()
            target_app.stdin.write("dump\n")
            target_app.stdin.flush()
            result["texts"] = json.loads(target_app.stdout.readline())
        except Exception as e:  # le rapport doit sortir même en cas d'échec
            result["error"] = repr(e)
        finally:
            QTimer.singleShot(0, app.quit)

    app.engine.start()
    app.hook.start()
    app.window.show()
    app._status_timer.start()
    threading.Thread(target=scenario, daemon=True).start()
    watchdog = QTimer(singleShot=True, interval=180_000, timeout=app.quit)
    watchdog.start()
    app.qt.exec()

    target_app.stdin.write("quit\n")
    target_app.stdin.flush()
    clipboard.restore(real_clipboard)
    db = Database(tmp / "dictera.db")
    rows = db.query_dictations()
    s = stats.dashboard(db, cfg.typing_wpm)

    print(f"moteur                  : {result.get('engine')}")
    if "error" in result:
        print(f"ERREUR du scénario      : {result['error']}")
    texts = result.get("texts", {"target": "", "other": ""})
    print(f"fenêtre Cible           : « {texts['target']} »")
    print(f"autre fenêtre           : « {texts['other']} »")
    print(f"presse-papiers après    : « {result.get('clipboard')} »")
    print(f"relâchement -> historique : {result.get('release_to_saved_ms', 0):.0f} ms")
    if rows:
        d = rows[0]
        print(f"historique              : {d.app_name} · {d.words} mots · {d.wpm:.0f} mots/min · "
              f"{d.corrections} correction(s) · {d.reformulation} · insertion {d.insertion}")
        print(f"  brut                  : {d.raw_text}")
    checks = {
        "le hook a déclenché la capture (F24)": app.recorder.started == 1,
        "dictée enregistrée et interface notifiée": bool(result.get("saved")),
        "texte collé dans la fenêtre capturée à l'APPUI": bool(rows) and texts["target"] == rows[0].final_text,
        "rien dans la fenêtre qui avait le focus au relâchement": texts["other"] == "",
        "hésitation retirée et correction ski -> skill": bool(rows) and rows[0].final_text.startswith("Bonjour")
        and "skill" in rows[0].final_text,
        "presse-papiers d'origine restauré": result.get("clipboard") == result.get("original"),
        "historique : 1 dictée, collée": len(rows) == 1 and rows[0].insertion == "pasted",
        "tableau de bord à jour": s.total_dictations == 1 and s.words_today == rows[0].words if rows else False,
    }
    for label, ok in checks.items():
        print(f"[{'OK' if ok else 'ÉCHEC'}] {label}")
    db.close()
    ok = all(checks.values())
    print("SUCCÈS" if ok else "ÉCHEC")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
