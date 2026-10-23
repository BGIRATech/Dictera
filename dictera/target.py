"""Fenêtre cible : capturée à l'APPUI de la touche, pour coller au bon endroit même si
le focus a changé pendant la dictée ou la transcription."""

import ctypes
import logging
import time
from dataclasses import dataclass
from ctypes import wintypes
from pathlib import PureWindowsPath

from . import win32

log = logging.getLogger(__name__)
u32, k32 = win32.user32, win32.kernel32


@dataclass(frozen=True)
class Target:
    hwnd: int  # fenêtre de premier plan
    focus_hwnd: int  # contrôle qui avait le focus clavier (0 si inconnu)
    pid: int
    thread_id: int
    exe: str  # ex. "notepad.exe" ; sert aussi à étiqueter l'historique (Phase 4)
    title: str  # en mémoire seulement (site reconnu dans le navigateur) : ni journalisé ni stocké
    elevated: bool | None  # None : jeton illisible (typiquement une fenêtre administrateur)
    exe_path: str = ""  # chemin complet : nom lisible de l'appli (app_names.display_name)

    def __str__(self) -> str:
        # Sans le titre : il peut contenir un sujet de mail ou un nom de document, et ceci
        # finit dans les journaux sur disque.
        return f"{self.exe} (hwnd=0x{self.hwnd:X})"


def _text(fn, hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(512)
    fn(hwnd, buf, len(buf))
    return buf.value


def _process_info(pid: int) -> tuple[str, str, bool | None]:
    handle = k32.OpenProcess(win32.PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return "", "", None
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buf))
        path = buf.value if k32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)) else ""
        return PureWindowsPath(path).name.lower(), path, win32.process_elevated(handle)
    finally:
        k32.CloseHandle(handle)


def self_elevated() -> bool:
    return bool(win32.process_elevated(k32.GetCurrentProcess()))


def capture_foreground() -> Target | None:
    hwnd = u32.GetForegroundWindow()
    if not hwnd:
        return None
    pid = wintypes.DWORD()
    tid = u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    info = win32.GUITHREADINFO(cbSize=ctypes.sizeof(win32.GUITHREADINFO))
    focus = info.hwndFocus if u32.GetGUIThreadInfo(tid, ctypes.byref(info)) and info.hwndFocus else 0
    exe, exe_path, elevated = _process_info(pid.value)
    return Target(hwnd, focus or 0, pid.value, tid, exe, _text(u32.GetWindowTextW, hwnd), elevated, exe_path)


def is_alive(target: Target) -> bool:
    return bool(u32.IsWindow(target.hwnd))


def is_foreground(target: Target) -> bool:
    return u32.GetForegroundWindow() == target.hwnd


def focus(target: Target, timeout_s: float = 0.5) -> bool:
    """Ramène la fenêtre cible au premier plan et y redonne le focus au contrôle d'origine.

    SetForegroundWindow est refusé à un processus d'arrière-plan ; en attachant notre
    file d'entrée à celles de la fenêtre active et de la cible, Windows l'autorise.
    """
    if not is_alive(target):
        return False
    if u32.IsIconic(target.hwnd):
        u32.ShowWindow(target.hwnd, win32.SW_RESTORE)
    if not is_foreground(target) or target.focus_hwnd:
        me = k32.GetCurrentThreadId()
        fg = u32.GetForegroundWindow()
        fg_tid = u32.GetWindowThreadProcessId(fg, None) if fg else 0
        attached = [t for t in {fg_tid, target.thread_id} if t and t != me and u32.AttachThreadInput(me, t, True)]
        try:
            u32.BringWindowToTop(target.hwnd)
            u32.SetForegroundWindow(target.hwnd)
            if target.focus_hwnd and u32.IsWindow(target.focus_hwnd):
                u32.SetFocus(target.focus_hwnd)
        finally:
            for t in attached:
                u32.AttachThreadInput(me, t, False)
    deadline = time.perf_counter() + timeout_s
    while not is_foreground(target):
        if time.perf_counter() > deadline:
            log.warning("Impossible de ramener %s au premier plan", target)
            return False
        time.sleep(0.01)
    return True
