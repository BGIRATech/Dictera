"""Presse-papiers Win32 : instantané multi-format, écriture du texte, restauration.

L'instantané copie toutes les données de type mémoire globale (texte, HTML, RTF,
images DIB, listes de fichiers, formats privés des applis…). Les formats à base de
handles GDI (CF_BITMAP, métafichiers…) ne sont pas copiables tels quels : CF_BITMAP
est de toute façon resynthétisé par Windows à partir de CF_DIB.
"""

import ctypes
import logging
import time
from dataclasses import dataclass, field

from . import win32

log = logging.getLogger(__name__)
u32, k32 = win32.user32, win32.kernel32

# Formats non copiables par mémoire globale : handles GDI, affichage par le propriétaire.
_HANDLE_FORMATS = {2, 3, 9, 14, 0x80, 0x82, 0x83, 0x8E}
_GDIOBJ_RANGE = range(0x300, 0x400)
_PRIVATE_RANGE = range(0x200, 0x300)

# Formats reconnus par Windows : le contenu marqué n'entre ni dans l'historique (Win+V)
# ni dans le presse-papiers cloud synchronisé entre appareils.
_NO_HISTORY_FORMATS = {
    "ExcludeClipboardContentFromMonitorProcessing": b"\x00",
    "CanIncludeInClipboardHistory": b"\x00\x00\x00\x00",
    "CanUploadToCloudClipboard": b"\x00\x00\x00\x00",
}


class ClipboardError(RuntimeError):
    pass


@dataclass
class Snapshot:
    formats: list[tuple[int, bytes]] = field(default_factory=list)
    skipped: list[int] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not self.formats and not self.skipped


class _Open:
    """Ouvre le presse-papiers avec réessais : une autre appli peut le tenir un instant."""

    def __init__(self, retries: int = 40, delay_s: float = 0.01):
        self.retries, self.delay_s = retries, delay_s

    def __enter__(self):
        for _ in range(self.retries):
            if u32.OpenClipboard(None):
                return self
            time.sleep(self.delay_s)
        raise ClipboardError("presse-papiers occupé par une autre application")

    def __exit__(self, *_exc):
        u32.CloseClipboard()


def sequence() -> int:
    return u32.GetClipboardSequenceNumber()


def _read_hglobal(handle) -> bytes | None:
    size = k32.GlobalSize(handle)
    ptr = k32.GlobalLock(handle)
    if not ptr:
        return None
    try:
        return ctypes.string_at(ptr, size)
    finally:
        k32.GlobalUnlock(handle)


def _write(fmt: int, data: bytes) -> None:
    handle = k32.GlobalAlloc(win32.GMEM_MOVEABLE, max(len(data), 1))
    if not handle:
        raise ClipboardError("allocation mémoire impossible")
    ptr = k32.GlobalLock(handle)
    ctypes.memmove(ptr, data, len(data))
    k32.GlobalUnlock(handle)
    if not u32.SetClipboardData(fmt, handle):
        k32.GlobalFree(handle)  # sinon, la mémoire appartient désormais au presse-papiers
        raise ClipboardError(f"écriture du format {fmt} refusée")


def _mark_no_history() -> None:
    for name, data in _NO_HISTORY_FORMATS.items():
        _write(u32.RegisterClipboardFormatW(name), data)


def snapshot() -> Snapshot:
    snap = Snapshot()
    with _Open():
        fmt = u32.EnumClipboardFormats(0)
        while fmt:
            if fmt in _HANDLE_FORMATS or fmt in _GDIOBJ_RANGE or fmt in _PRIVATE_RANGE:
                snap.skipped.append(fmt)
            else:
                handle = u32.GetClipboardData(fmt)
                data = _read_hglobal(handle) if handle else None
                if data is None:
                    snap.skipped.append(fmt)
                else:
                    snap.formats.append((fmt, data))
            fmt = u32.EnumClipboardFormats(fmt)
    return snap


def restore(snap: Snapshot, no_history: bool = True) -> None:
    """Remet le contenu de l'instantané (un presse-papiers vide est restauré vide)."""
    with _Open():
        u32.EmptyClipboard()
        for fmt, data in snap.formats:
            try:
                _write(fmt, data)
            except ClipboardError as e:
                log.warning("Restauration partielle du presse-papiers : %s", e)
        if no_history and snap.formats:
            _mark_no_history()  # l'original est déjà dans l'historique : pas de doublon


def set_text(text: str, no_history: bool = True) -> None:
    data = (text + "\0").encode("utf-16-le")
    with _Open():
        u32.EmptyClipboard()
        _write(win32.CF_UNICODETEXT, data)
        if no_history:
            _mark_no_history()
    if get_text() != text:
        raise ClipboardError("vérification de l'écriture échouée (contenu différent)")


def get_text() -> str | None:
    with _Open():
        handle = u32.GetClipboardData(win32.CF_UNICODETEXT)
        data = _read_hglobal(handle) if handle else None
    if data is None:
        return None
    return data.decode("utf-16-le", errors="replace").split("\0", 1)[0]
