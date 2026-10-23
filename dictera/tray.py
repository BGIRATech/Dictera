"""Icône de la zone de notification (logo : onde sonore blanche dans un carré turquoise).

Qt (QSystemTrayIcon) : une seule boucle d'événements pour l'icône et la fenêtre.
Les méthodes publiques peuvent être appelées depuis n'importe quel thread (hook clavier,
moteur) : elles passent par des signaux, exécutés dans le thread de l'interface.
"""

from typing import Callable

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from .ui import theme as t


class TrayIcon(QObject):
    _recording = Signal(bool)
    _notify = Signal(str)

    def __init__(
        self,
        hotkey_label: str,
        sounds_enabled: Callable[[], bool],
        on_toggle_sounds: Callable[[], None],
        on_quit: Callable[[], None],
        on_open: Callable[[], None] = lambda: None,
    ):
        super().__init__()
        self._hotkey_label = hotkey_label
        self._idle_icon = QIcon(t.logo_pixmap(64))
        self._rec_icon = QIcon(t.logo_pixmap(64, recording=True))
        self._icon = QSystemTrayIcon(self._idle_icon)
        menu = QMenu()
        menu.addAction("Ouvrir Dictera", on_open)
        self._hint = menu.addAction("")
        self._hint.setEnabled(False)
        menu.addSeparator()
        self._sounds = QAction("Sons de début et de fin", menu, checkable=True)
        self._sounds.setChecked(sounds_enabled())
        self._sounds.triggered.connect(lambda _c: on_toggle_sounds())
        menu.aboutToShow.connect(lambda: self._sounds.setChecked(sounds_enabled()))
        menu.addAction(self._sounds)
        menu.addAction("Quitter Dictera", on_quit)
        self._menu = menu
        self._icon.setContextMenu(menu)
        self._icon.activated.connect(
            lambda reason: on_open() if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                                                   QSystemTrayIcon.ActivationReason.DoubleClick) else None)
        self._recording.connect(self._apply_recording)
        self._notify.connect(lambda msg: self._icon.showMessage("Dictera", msg, self._idle_icon, 6000))
        self.set_hotkey_label(hotkey_label)

    def show(self) -> None:
        self._icon.show()

    def set_hotkey_label(self, hotkey_label: str) -> None:
        self._hotkey_label = hotkey_label
        self._hint.setText(f"Maintenir {hotkey_label} pour dicter")
        self._apply_recording(False)

    def set_recording(self, recording: bool) -> None:
        self._recording.emit(recording)

    def notify(self, message: str) -> None:
        self._notify.emit(message)

    def _apply_recording(self, recording: bool) -> None:
        self._icon.setIcon(self._rec_icon if recording else self._idle_icon)
        self._icon.setToolTip("Dictera — enregistrement…" if recording
                              else f"Dictera — prêt (maintenir {self._hotkey_label})")

    def stop(self) -> None:
        self._icon.hide()
