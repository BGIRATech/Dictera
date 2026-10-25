"""Réglages (spec § 7). Chaque modification est enregistrée dans config.json et appliquée
à chaud par l'application ; seul le changement de modèle Whisper attend un redémarrage."""

import os
import threading
import urllib.error

import sounddevice as sd
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (QAbstractButton, QDoubleSpinBox, QHBoxLayout, QLineEdit, QSpinBox, QVBoxLayout,
                               QWidget)

from ...config import HOTKEYS
from ...reformulate import AUTO, OFF, RULES, OpenAICompatClient, is_local_url
from ...transcriber import MODELS
from .. import theme as t
from ..context import UiContext, microphone_access
from ..widgets import Badge, Card, Combo, Toggle, button, label, separator
from .base import Page

# Whisper transcrit ces langues ; la mise au propre (règles, consigne du LLM) vise le français.
_LANGUAGES = (("fr", "Français"), ("en", "Anglais"), ("es", "Espagnol"), ("de", "Allemand"), ("it", "Italien"))


def _llm_model(cfg) -> str:
    return cfg.llm_model if cfg.llm_enabled else cfg.ollama_model


def _llm_on(cfg) -> bool:
    return cfg.reformulation not in (OFF, RULES) and cfg.llm_enabled


class _ModelsBridge(QObject):
    """Liste des modèles de LM Studio, lue dans un thread, reçue dans le thread de l'interface."""
    loaded = Signal(object, str)  # (liste [(id, chargé)] ou None si hors ligne, URL interrogée)


CONTROL_WIDTH = 300  # toutes les listes et champs alignés sur la même colonne


def _row(title: str, hint: str, control: QWidget) -> QHBoxLayout:
    if not isinstance(control, (QAbstractButton, Badge)):
        control.setFixedWidth(CONTROL_WIDTH)
    row = QHBoxLayout()
    row.setSpacing(24)
    text = QVBoxLayout()
    text.setSpacing(2)
    text.addWidget(label(title))
    if hint:
        text.addWidget(label(hint, "muted", wrap=True))
    row.addLayout(text, 1)
    row.addWidget(control)
    return row


def input_devices() -> list[str]:
    """Micros du système (API d'entrée par défaut, sans doublons d'API)."""
    try:
        api = sd.default.hostapi
        return [d["name"] for d in sd.query_devices() if d["max_input_channels"] > 0 and d["hostapi"] == api]
    except Exception:
        return []


class SettingsPage(Page):
    title = "Réglages"

    def __init__(self, ctx: UiContext):
        super().__init__(ctx)
        cfg = ctx.config

        # Moteur & vie privée
        engine = Card()
        engine.body.addWidget(label("Moteur et vie privée", "section"))
        badges = QHBoxLayout()
        badges.setSpacing(10)
        self.b_asr = Badge("Transcription")
        self.b_reform = Badge("Reformulation")
        self.b_hist = Badge("Historique · Local (SQLite)")
        for b in (self.b_asr, self.b_reform, self.b_hist):
            badges.addWidget(b)
        badges.addStretch()
        engine.body.addLayout(badges)
        promise = label(f"<span style='font-family:\"{t.ICON_FONT}\"; color:{t.ACCENT}'>{t.Icon.LOCK}</span>"
                        "&nbsp;&nbsp;Ta voix ne quitte jamais ce PC.")
        promise.setStyleSheet("font-size: 10.5pt; font-weight: 600; padding: 4px 0;")
        engine.body.addWidget(promise)
        engine.body.addWidget(separator())
        self.model = Combo()
        for m in MODELS:
            self.model.addItem({"large-v3-turbo": "large-v3-turbo · rapide (défaut)",
                                "large-v3": "large-v3 · précision maximale"}.get(m, m), m)
        self.model.setCurrentIndex(max(self.model.findData(cfg.whisper_model), 0))
        self.model.currentIndexChanged.connect(lambda _i: self._set("whisper_model", self.model.currentData()))
        engine.body.addLayout(_row("Modèle Whisper", "Pris en compte au prochain démarrage de Dictera.", self.model))
        self.device = Combo()
        self.device.setMinimumWidth(280)
        self.device.addItem("Micro par défaut de Windows", None)
        for name in input_devices():
            self.device.addItem(name, name)
        self.device.setCurrentIndex(max(self.device.findData(cfg.input_device), 0))
        self.device.currentIndexChanged.connect(lambda _i: self._set("input_device", self.device.currentData()))
        engine.body.addLayout(_row("Micro", "", self.device))
        self.root.addWidget(engine)

        # Autorisations
        perms = Card()
        perms.body.addWidget(label("Autorisations", "section"))
        self.mic_state = Badge("Micro")
        open_btn = button("Ouvrir les réglages de confidentialité Windows (Microphone)", None,
                          lambda: os.startfile("ms-settings:privacy-microphone"))
        perms.body.addLayout(_row("Accès au micro", "", self.mic_state))
        perms.body.addWidget(open_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        perms.body.addWidget(label("Coller dans une fenêtre lancée en administrateur exige de lancer Dictera "
                                   "en administrateur. Sinon, le texte reste dans le presse-papiers.", "muted", wrap=True))
        self.root.addWidget(perms)

        # Dictée
        dictation = Card()
        dictation.body.addWidget(label("Dictée", "section"))
        self.hotkey = Combo()
        for key, (name, _vk) in HOTKEYS.items():
            self.hotkey.addItem(name, key)
        self.hotkey.setCurrentIndex(max(self.hotkey.findData(cfg.hotkey), 0))
        self.hotkey.currentIndexChanged.connect(lambda _i: self._set("hotkey", self.hotkey.currentData()))
        dictation.body.addLayout(_row("Touche à maintenir", "Maintenir pour dicter, relâcher pour écrire.",
                                      self.hotkey))
        self.lang = Combo()
        for code, name in _LANGUAGES:
            self.lang.addItem(name, code)
        self.lang.setCurrentIndex(max(self.lang.findData(cfg.language), 0))
        self.lang.currentIndexChanged.connect(lambda _i: self._set("language", self.lang.currentData()))
        dictation.body.addLayout(_row("Langue", "La mise au propre est prévue pour le français.", self.lang))
        self.sounds = Toggle(cfg.sounds_enabled)
        self.sounds.toggled.connect(lambda v: self._set("sounds_enabled", v))
        dictation.body.addLayout(_row("Sons de début et de fin", "", self.sounds))
        self.restore = Toggle(cfg.restore_clipboard)
        self.restore.toggled.connect(lambda v: self._set("restore_clipboard", v))
        dictation.body.addLayout(_row("Restaurer le presse-papiers",
                                      "Remet son contenu d'origine après chaque collage.", self.restore))
        self.wisp = Toggle(cfg.wisp_enabled)
        self.wisp.toggled.connect(lambda v: self._set("wisp_enabled", v))
        dictation.body.addLayout(_row("Montrer la dictée dans Wisp",
                                      "Le compagnon Wisp écoute avec vous. Seul l'état est envoyé, jamais le texte.",
                                      self.wisp))
        self.root.addWidget(dictation)

        # Mise au propre
        clean = Card()
        clean.body.addWidget(label("Mise au propre", "section"))
        self.reform_on = Toggle(cfg.reformulation != OFF)
        self.reform_on.toggled.connect(lambda _v: self._set_reformulation())
        clean.body.addLayout(_row("Reformulation", "Retire les « euh », corrige ponctuation et majuscules.",
                                  self.reform_on))
        self.llm_on = Toggle(_llm_on(cfg))
        self.llm_on.toggled.connect(lambda _v: self._set_reformulation())
        clean.body.addLayout(_row("Reformulation LLM (LM Studio)",
                                  "Éteinte, ou si le LLM ne répond pas à temps : règles simples.", self.llm_on))
        self.llm_model = Combo()
        self.llm_model.currentIndexChanged.connect(self._model_chosen)
        self.llm_refresh = button("Rafraîchir la liste", None, self._load_models)
        clean.body.addLayout(_row("Modèle LLM", "Un modèle non chargé dans LM Studio l'est à la première dictée, "
                                  "qui passe alors par les règles (chargement plus long que le délai).",
                                  self.llm_model))
        refresh_row = QHBoxLayout()
        self.llm_state = label("", "muted", wrap=True)
        refresh_row.addWidget(self.llm_state, 1)
        refresh_row.addWidget(self.llm_refresh)
        clean.body.addLayout(refresh_row)
        self.llm_url = QLineEdit(cfg.llm_url)
        self.llm_url.editingFinished.connect(self._url_edited)
        clean.body.addLayout(_row("URL du serveur LLM", "Sur ce PC uniquement (localhost ou 127.0.0.1).",
                                  self.llm_url))
        self.llm_timeout = QDoubleSpinBox()
        self.llm_timeout.setRange(1.0, 10.0)
        self.llm_timeout.setSingleStep(0.5)
        self.llm_timeout.setDecimals(1)
        self.llm_timeout.setSuffix(" s")
        self.llm_timeout.setValue(cfg.llm_timeout_s)
        self.llm_timeout.editingFinished.connect(lambda: self._set_number("llm_timeout_s", self.llm_timeout))
        clean.body.addLayout(_row("Délai maximal", "Au-delà, le texte nettoyé par les règles est collé.",
                                  self.llm_timeout))
        self.llm_temp = QDoubleSpinBox()
        self.llm_temp.setRange(0.0, 1.0)
        self.llm_temp.setSingleStep(0.1)
        self.llm_temp.setDecimals(1)
        self.llm_temp.setValue(cfg.llm_temperature)
        self.llm_temp.editingFinished.connect(lambda: self._set_number("llm_temperature", self.llm_temp))
        clean.body.addLayout(_row("Température", "Basse : fidèle à la dictée. Haute : plus libre (déconseillé).",
                                  self.llm_temp))
        self.reform_model = label("", "muted", wrap=True)
        clean.body.addWidget(self.reform_model)
        self.root.addWidget(clean)
        self._models_bridge = _ModelsBridge()
        self._models_bridge.loaded.connect(self._models_loaded)
        self._fill_models(None)
        self._llm_controls_enabled()
        self._load_models()

        # Stats
        st = Card()
        st.body.addWidget(label("Statistiques", "section"))
        self.wpm = QSpinBox()
        self.wpm.setRange(10, 200)
        self.wpm.setSuffix(" mots/min")
        self.wpm.setValue(cfg.typing_wpm)
        self.wpm.valueChanged.connect(lambda v: self._set("typing_wpm", v))
        st.body.addLayout(_row("Ma vitesse au clavier", "Sert à calculer le temps gagné.", self.wpm))
        self.root.addWidget(st)
        self.root.addStretch()

    def refresh(self) -> None:
        cfg = self.ctx.config
        for toggle, value in ((self.sounds, cfg.sounds_enabled), (self.restore, cfg.restore_clipboard),
                              (self.wisp, cfg.wisp_enabled),
                              (self.reform_on, cfg.reformulation != OFF), (self.llm_on, _llm_on(cfg))):
            toggle.blockSignals(True)  # ex. « Sons » basculé depuis la zone de notification
            toggle.setChecked(value)
            toggle.blockSignals(False)
            toggle.update()
        info = self.ctx.engine_info()
        if info.error:
            self.b_asr.set("Transcription · indisponible", ok=False)
        elif info.model:
            self.b_asr.set(f"Transcription · Local ({info.model}, {info.device or 'CUDA'})")
        else:
            self.b_asr.set("Transcription · Local (chargement…)", ok=False)
        mode = self.ctx.config.reformulation
        if mode == OFF:
            self.b_reform.set("Reformulation · Désactivée", ok=False)
        elif mode == RULES or "repli" in info.reformulation:
            self.b_reform.set("Reformulation · Local (règles)")
        else:
            self.b_reform.set(f"Reformulation · Local ({_llm_model(self.ctx.config)})")
        self.reform_model.setText(info.reformulation)
        ok, text = microphone_access()
        self.mic_state.set(text, ok is not False)
        self._llm_controls_enabled()

    # -- LLM ---------------------------------------------------------------------------

    def _set_reformulation(self) -> None:
        """Un seul état : désactivée, règles, ou LLM (LM Studio) avec repli sur les règles."""
        cfg = self.ctx.config
        if self.reform_on.isChecked() and self.llm_on.isChecked():
            cfg.llm_enabled = True  # l'interrupteur LLM désigne LM Studio, pas l'ancien Ollama
        self._set("reformulation", OFF if not self.reform_on.isChecked()
                  else AUTO if self.llm_on.isChecked() else RULES)

    def _llm_controls_enabled(self) -> None:
        self.llm_on.setEnabled(self.reform_on.isChecked())
        on = self.reform_on.isChecked() and self.llm_on.isChecked()
        for w in (self.llm_model, self.llm_refresh, self.llm_url, self.llm_timeout, self.llm_temp):
            w.setEnabled(on)

    def _load_models(self) -> None:
        """GET /v1/models hors du thread de l'interface : un serveur lent ne gèle pas la page."""
        url, model = self.ctx.config.llm_url, self.ctx.config.llm_model
        self.llm_state.setText("Interrogation de LM Studio…")

        def work():
            try:
                models = OpenAICompatClient(url, model).list_models()
            except (urllib.error.URLError, OSError, ValueError):
                models = None
            self._models_bridge.loaded.emit(models, url)

        threading.Thread(target=work, name="dictera-llm-models", daemon=True).start()

    def _models_loaded(self, models, url: str) -> None:
        if url != self.ctx.config.llm_url:
            return  # réponse pour une URL qui a changé depuis
        self._fill_models(models)
        current = self.ctx.config.llm_model
        if models is None:
            self.llm_state.setText("LM Studio hors ligne : le modèle actuel est gardé.")
        elif not models:
            self.llm_state.setText("LM Studio ne propose aucun modèle de conversation.")
        else:
            states = dict(models)
            n = f"{len(models)} modèle{'s' if len(models) > 1 else ''} dans LM Studio"
            if current not in states:
                detail = f"« {current} » n'y figure pas : choisissez-en un."
            elif states[current] is None:
                detail = f"« {current} » disponible."
            elif states[current]:
                detail = f"« {current} » chargé en mémoire."
            else:
                detail = f"« {current} » non chargé : il le sera à la première dictée."
            self.llm_state.setText(f"{n} · {detail}")

    def _fill_models(self, models) -> None:
        current = self.ctx.config.llm_model
        self.llm_model.blockSignals(True)
        self.llm_model.clear()
        for model_id, loaded in models or []:
            name = model_id.rsplit("/", 1)[-1]  # « mistralai/… » : l'id exact reste la donnée de l'item
            self.llm_model.addItem(f"{name} · chargé" if loaded else name, model_id)
            self.llm_model.setItemData(self.llm_model.count() - 1, model_id, Qt.ItemDataRole.ToolTipRole)
        if self.llm_model.findData(current) < 0:  # hors ligne ou modèle retiré : le réglage est gardé
            self.llm_model.addItem(current if models is None else f"{current} (absent)", current)
        self.llm_model.setCurrentIndex(self.llm_model.findData(current))
        self.llm_model.blockSignals(False)

    def _model_chosen(self, _i: int) -> None:
        model = self.llm_model.currentData()
        if model and model != self.ctx.config.llm_model:
            self._set("llm_model", model)
            self._load_models()  # met à jour « chargé / non chargé »

    def _url_edited(self) -> None:
        url = self.llm_url.text().strip()
        if url == self.ctx.config.llm_url:
            return
        if not is_local_url(url):
            self.llm_url.setText(self.ctx.config.llm_url)
            self.llm_state.setText(f"URL refusée : « {url} » n'est pas sur ce PC, la dictée ne doit pas en sortir.")
            return
        self._set("llm_url", url)
        self._load_models()

    def _set_number(self, key: str, box: QDoubleSpinBox) -> None:
        if round(box.value(), 2) != round(getattr(self.ctx.config, key), 2):
            self._set(key, round(box.value(), 2))

    def _set(self, key: str, value) -> None:
        setattr(self.ctx.config, key, value)
        self.ctx.config.save()
        self.ctx.on_setting_changed(key)
        self.refresh()
