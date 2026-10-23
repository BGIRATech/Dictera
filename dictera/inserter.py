"""Insertion du texte dans la fenêtre cible.

Séquence :
  1. attendre que l'utilisateur ait relâché ses touches de modification ;
  2. ramener la fenêtre capturée à l'appui au premier plan ;
  3. instantané du presse-papiers ;
  4. écriture du texte (vérifiée par relecture) ;
  5. paste_delay_ms, puis Ctrl+V (ou Shift+Insert) simulé via SendInput ;
  6. restore_delay_ms (l'appli cible lit le presse-papiers à son rythme), puis
     restauration de l'original — sauf si quelqu'un a copié autre chose entre-temps.
Si coller est impossible (fenêtre fermée, focus refusé, fenêtre administrateur), le
texte est laissé dans le presse-papiers pour un Ctrl+V manuel.
"""

import logging
import time
from dataclasses import dataclass, field

from . import clipboard, target as tgt, win32
from .target import Target

log = logging.getLogger(__name__)

PASTED, CLIPBOARD_ONLY, SKIPPED = "pasted", "clipboard_only", "skipped"
CTRL_V, SHIFT_INSERT = "ctrl+v", "shift+insert"
_MODIFIERS = (win32.VK_SHIFT, win32.VK_CONTROL, win32.VK_MENU, win32.VK_LWIN, win32.VK_RWIN)


@dataclass
class InsertResult:
    status: str
    reason: str = ""
    keys: str = ""
    restored: bool = False
    timings_ms: dict[str, float] = field(default_factory=dict)


class Inserter:
    def __init__(
        self,
        paste_delay_ms: int = 80,
        restore_delay_ms: int = 500,
        paste_keys: str = CTRL_V,
        shift_insert_apps: list[str] | None = None,
        restore_clipboard: bool = True,
        no_history: bool = True,
    ):
        self.paste_delay_ms = paste_delay_ms
        self.restore_delay_ms = restore_delay_ms
        self.paste_keys = paste_keys
        self.shift_insert_apps = {a.lower() for a in shift_insert_apps or []}
        self.restore_clipboard = restore_clipboard
        self.no_history = no_history

    def keys_for(self, target: Target) -> str:
        return SHIFT_INSERT if self.paste_keys == SHIFT_INSERT or target.exe in self.shift_insert_apps else CTRL_V

    def insert(self, text: str, target: Target | None) -> InsertResult:
        if not text:
            return InsertResult(SKIPPED, "texte vide")
        if target is None or not tgt.is_alive(target):
            return self._clipboard_only(text, "la fenêtre cible n'existe plus")
        if target.elevated is not False and not tgt.self_elevated():
            # UIPI : Windows ignore silencieusement les frappes simulées vers une fenêtre administrateur.
            return self._clipboard_only(text, "fenêtre administrateur (lancez Dictera en administrateur "
                                              "pour y coller automatiquement)")
        t: dict[str, float] = {}
        t0 = time.perf_counter()
        self._wait_modifiers_released()
        t["modifiers"] = _ms(t0)
        if not tgt.focus(target):
            return self._clipboard_only(text, "la fenêtre cible n'a pas pu reprendre le focus")
        t["focus"] = _ms(t0)

        snap = clipboard.snapshot() if self.restore_clipboard else None
        clipboard.set_text(text, self.no_history)
        written_seq = clipboard.sequence()
        t["clipboard_write"] = _ms(t0)

        time.sleep(self.paste_delay_ms / 1000)
        if not tgt.is_foreground(target) and not tgt.focus(target):
            # Le texte reste dans le presse-papiers : ne surtout pas restaurer.
            return InsertResult(CLIPBOARD_ONLY, "focus perdu juste avant le collage", timings_ms=t)
        keys = self.keys_for(target)
        if keys == SHIFT_INSERT:
            win32.send_chord(win32.VK_SHIFT, win32.VK_INSERT)
        else:
            win32.send_chord(win32.VK_CONTROL, win32.VK_V)
        t["paste_sent"] = _ms(t0)

        restored = False
        if snap is not None:
            time.sleep(self.restore_delay_ms / 1000)
            if clipboard.sequence() == written_seq:
                clipboard.restore(snap, self.no_history)
                restored = True
            else:
                log.info("Presse-papiers modifié pendant le collage : original non restauré")
            t["restored"] = _ms(t0)
        log.info("Texte collé dans %s via %s (%d caractères)", target, keys, len(text))
        return InsertResult(PASTED, keys=keys, restored=restored, timings_ms=t)

    def _clipboard_only(self, text: str, reason: str) -> InsertResult:
        log.warning("Collage impossible : %s. Texte laissé dans le presse-papiers.", reason)
        try:
            clipboard.set_text(text, self.no_history)
        except clipboard.ClipboardError as e:
            return InsertResult(SKIPPED, f"{reason} ; presse-papiers indisponible : {e}")
        return InsertResult(CLIPBOARD_ONLY, reason)

    @staticmethod
    def _wait_modifiers_released(timeout_s: float = 1.0) -> None:
        """Un Ctrl+V envoyé pendant que l'utilisateur tient Maj ou Alt deviendrait Ctrl+Maj+V…"""
        deadline = time.perf_counter() + timeout_s
        while any(win32.key_down(vk) for vk in _MODIFIERS) and time.perf_counter() < deadline:
            time.sleep(0.01)


def _ms(t0: float) -> float:
    return round((time.perf_counter() - t0) * 1000, 1)
