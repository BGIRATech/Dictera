"""Touche push-to-talk via un hook clavier bas niveau (WH_KEYBOARD_LL).

Maintenir la touche = enregistrer ; la relâcher = arrêter. Si une autre touche est
enfoncée pendant le maintien (ex. Ctrl droit + C), la dictée est annulée : l'utilisateur
faisait un raccourci, pas une dictée. La touche n'est jamais avalée, les raccourcis
restent fonctionnels.

Le callback du hook ne fait que poser un événement dans une file : Windows retire les
hooks trop lents (LowLevelHooksTimeout). Un thread séparé appelle les callbacks.
"""

import ctypes
import logging
import queue
import threading
import time
from ctypes import wintypes
from typing import Callable

from . import win32

log = logging.getLogger(__name__)

PRESS, RELEASE, CANCEL = "press", "release", "cancel"


class PushToTalkHook:
    def __init__(
        self,
        vk: int,
        on_press: Callable[[bool], None],
        on_release: Callable[[], None],
        on_cancel: Callable[[], None],
    ):
        self.vk = vk
        self._on_press = on_press
        self._on_release = on_release
        self._on_cancel = on_cancel
        self._events: queue.Queue = queue.Queue()
        self._held = False
        self._cancelled = False
        self._hook = None
        self._proc = win32.HOOKPROC(self._hook_proc)  # référence gardée : sinon le GC la libère
        self._hook_tid = 0
        self._ready = threading.Event()
        self._start_error: OSError | None = None
        self._hook_thread = threading.Thread(target=self._hook_loop, name="dictera-hook", daemon=True)
        self._dispatch_thread = threading.Thread(target=self._dispatch_loop, name="dictera-ptt", daemon=True)

    def start(self) -> None:
        self._dispatch_thread.start()
        self._hook_thread.start()
        self._ready.wait(5)
        if self._start_error:
            raise self._start_error
        if not self._hook:
            raise TimeoutError("Le hook clavier ne s'est pas installé à temps")

    def stop(self) -> None:
        if self._hook_tid:
            win32.user32.PostThreadMessageW(self._hook_tid, win32.WM_QUIT, 0, 0)
        if self._hook_thread.is_alive():
            self._hook_thread.join(2)
        self._events.put(None)
        if self._dispatch_thread.is_alive():
            self._dispatch_thread.join(2)

    def set_key(self, vk: int) -> None:
        self._held = False
        self.vk = vk

    def _hook_loop(self) -> None:
        self._hook_tid = win32.kernel32.GetCurrentThreadId()
        self._hook = win32.user32.SetWindowsHookExW(
            win32.WH_KEYBOARD_LL, self._proc, win32.kernel32.GetModuleHandleW(None), 0
        )
        if not self._hook:
            self._start_error = ctypes.WinError(ctypes.get_last_error())
            self._ready.set()
            return
        log.info("Hook clavier installé (vk=0x%02X)", self.vk)
        self._ready.set()
        msg = wintypes.MSG()
        while win32.user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            win32.user32.TranslateMessage(ctypes.byref(msg))
            win32.user32.DispatchMessageW(ctypes.byref(msg))
        win32.user32.UnhookWindowsHookEx(self._hook)
        self._hook = None
        log.info("Hook clavier retiré")

    def _hook_proc(self, n_code: int, w_param: int, l_param: int) -> int:
        if n_code == win32.HC_ACTION:
            kb = ctypes.cast(l_param, ctypes.POINTER(win32.KBDLLHOOKSTRUCT)).contents
            if kb.dwExtraInfo == win32.DICTERA_INPUT_TAG:  # Ctrl+V simulé par Dictera lui-même
                return win32.user32.CallNextHookEx(None, n_code, w_param, l_param)
            down = w_param in (win32.WM_KEYDOWN, win32.WM_SYSKEYDOWN)
            up = w_param in (win32.WM_KEYUP, win32.WM_SYSKEYUP)
            if kb.vkCode == self.vk:
                if down and not self._held:  # l'auto-répétition renvoie des KEYDOWN : ignorés
                    self._held = True
                    self._cancelled = False
                    self._events.put((PRESS, time.perf_counter(), bool(kb.flags & win32.LLKHF_INJECTED)))
                elif up and self._held:
                    self._held = False
                    if not self._cancelled:
                        self._events.put((RELEASE, time.perf_counter(), False))
            elif down and self._held and not self._cancelled:
                self._cancelled = True
                self._events.put((CANCEL, time.perf_counter(), False))
        return win32.user32.CallNextHookEx(None, n_code, w_param, l_param)

    def _dispatch_loop(self) -> None:
        while (event := self._events.get()) is not None:
            kind, _, injected = event
            try:
                if kind == PRESS:
                    self._on_press(injected)
                elif kind == RELEASE:
                    self._on_release()
                else:
                    self._on_cancel()
            except Exception:
                log.exception("Erreur dans le callback push-to-talk (%s)", kind)
