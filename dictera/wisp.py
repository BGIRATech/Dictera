"""Lien vers Wisp, le compagnon de bureau : Dictera lui dit ce qu'il fait (écoute,
transcription, résultat, erreur) par le bus local ``\\\\.\\pipe\\wisp-bus``.
Protocole : D:\\Wisp\\docs\\bus.md.

Trois règles :
- **jamais bloquant** : ``send()`` dépose le message dans une petite file et rend la main
  tout de suite. Un thread dédié écrit dans le pipe. Le hook clavier et le moteur n'attendent
  jamais Wisp, même s'il est figé.
- **jamais indispensable** : Wisp fermé = messages perdus, sans erreur visible. Une nouvelle
  tentative de connexion a lieu au plus toutes les 2 s, et Dictera se reconnecte tout seul
  quand Wisp redémarre.
- **rien de privé ne sort** : seulement un état, un nombre de mots, un niveau de micro.
  Jamais le texte dicté, jamais le nom de l'appli cible.

Pendant l'écoute, le niveau du micro est envoyé 15 fois par seconde (état ``listening``,
durée de vie 1,5 s) : la flamme de Wisp pulse au rythme de la voix. Si Dictera plante en
pleine dictée, Wisp arrête d'écouter de lui-même au bout de 1,5 s.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import sys
import threading
import time
from typing import Callable, Protocol

log = logging.getLogger(__name__)

PIPE = r"\\.\pipe\wisp-bus"
SOURCE = "dictera"
LEVEL_HZ = 15
RETRY_S = 2.0
LISTEN_TTL_MS = 1500  # renouvelée à chaque niveau envoyé
THINK_TTL_MS = 30_000
LOADING_TTL_MS = 120_000  # premier lancement : le modèle peut mettre du temps à charger
QUEUE_SIZE = 32


class PipeWriter(Protocol):
    def write(self, data: bytes) -> None: ...
    def close(self) -> None: ...


class _NamedPipe:
    """Extrémité cliente du pipe, ouverte en écriture seule.

    ``os.open`` ouvre un fichier existant (OPEN_EXISTING) : il échoue si Wisp n'écoute pas,
    sans rien créer.
    """

    def __init__(self, path: str = PIPE):
        self._fd = os.open(path, os.O_WRONLY | getattr(os, "O_BINARY", 0))

    def write(self, data: bytes) -> None:
        view = memoryview(data)
        while view:
            n = os.write(self._fd, view)
            view = view[n:]

    def close(self) -> None:
        try:
            os.close(self._fd)
        except OSError:
            pass


def _open_pipe() -> PipeWriter:
    if sys.platform != "win32":
        raise OSError("bus Wisp : Windows uniquement")
    return _NamedPipe()


_STOP = object()
_WAKE = object()  # réveille le thread : le flux de niveaux commence


class WispLink:
    """Client du bus Wisp. Méthodes appelables depuis n'importe quel thread."""

    def __init__(
        self,
        enabled: bool = True,
        opener: Callable[[], PipeWriter] = _open_pipe,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.enabled = enabled
        self._open = opener
        self._clock = clock
        self._queue: queue.Queue = queue.Queue(maxsize=QUEUE_SIZE)
        self._level_fn: Callable[[], float] | None = None
        self._pipe: PipeWriter | None = None
        self._next_try = 0.0
        self._next_level = 0.0
        self._thread: threading.Thread | None = None
        self.sent = 0  # compteurs, pour les tests et le journal
        self.dropped = 0

    # -- cycle de vie -------------------------------------------------------------------

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="dictera-wisp", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        """Vide la file (le dernier ``idle`` part), puis ferme le pipe."""
        self._level_fn = None
        if self._thread is not None:
            try:
                self._queue.put(_STOP, timeout=0.5)
            except queue.Full:
                pass
            self._thread.join(1.0)
            self._thread = None

    def set_enabled(self, enabled: bool) -> None:
        if not enabled and self.enabled:
            self.idle()  # Wisp efface la pastille tout de suite, au lieu d'attendre son expiration
        self.enabled = enabled
        if not enabled:
            self._level_fn = None

    # -- ce que Dictera raconte ---------------------------------------------------------

    def listening(self, level: Callable[[], float]) -> None:
        """Touche maintenue : niveau du micro envoyé en continu jusqu'au prochain état."""
        if not self.enabled:
            return
        self._next_level = 0.0  # premier niveau tout de suite
        self._level_fn = level
        try:
            self._queue.put_nowait(_WAKE)
        except queue.Full:
            pass

    def thinking(self, engine_ready: bool = True) -> None:
        self._state("thinking",
                    label="Transcription…" if engine_ready else "Chargement du moteur…",
                    ttl_ms=THINK_TTL_MS if engine_ready else LOADING_TTL_MS)

    def done(self, words: int) -> None:
        self._state("finished", label=f"+{words} mot{'s' if words > 1 else ''}", emote="wink")

    def copied(self) -> None:
        """Collage impossible : le texte attend dans le presse-papiers."""
        self._state("finished", label="Copié : Ctrl+V pour coller", ttl_ms=6000)

    def error(self, message: str) -> None:
        self._state("error", label=message.splitlines()[0] if message else "Erreur")

    def idle(self) -> None:
        self._state("idle")

    # -- interne ------------------------------------------------------------------------

    def _state(self, state: str, **fields) -> None:
        # Arrêter le flux de niveaux AVANT de mettre en file : le thread relit _level_fn
        # après chaque message, donc aucun « listening » ne peut passer après cet état.
        self._level_fn = None
        self.send(state=state, **fields)

    def send(self, **fields) -> None:
        if not self.enabled:
            return
        msg = {"v": 1, "source": SOURCE, **fields}
        try:
            self._queue.put_nowait(msg)
        except queue.Full:  # Wisp ne lit plus (figé) : on jette plutôt que d'attendre
            self.dropped += 1

    def _level_message(self, fn: Callable[[], float]) -> dict:
        try:
            level = max(0.0, min(1.0, float(fn())))
        except Exception:
            level = 0.0
        return {"v": 1, "source": SOURCE, "state": "listening", "label": "J'écoute…",
                "level": round(level, 2), "ttl_ms": LISTEN_TTL_MS}

    def _run(self) -> None:
        period = 1.0 / LEVEL_HZ
        while True:
            streaming = self._level_fn is not None
            try:
                item = self._queue.get(timeout=period if streaming else 0.5)
            except queue.Empty:
                item = None
            if item is _STOP:
                break
            if item is not None and item is not _WAKE:
                self._write(item)
            fn = self._level_fn  # relu APRÈS le message : voir _state()
            if fn is not None and self._clock() >= self._next_level:
                self._next_level = self._clock() + period
                self._write(self._level_message(fn))
        self._close()

    def _write(self, msg: dict) -> None:
        data = (json.dumps(msg, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        for attempt in (1, 2):  # 2e essai : Wisp a redémarré, l'ancienne connexion est morte
            if self._pipe is None and not self._connect(force=attempt == 2):
                return
            try:
                self._pipe.write(data)
                self.sent += 1
                return
            except OSError:
                log.info("Wisp : connexion perdue")
                self._close()

    def _connect(self, force: bool = False) -> bool:
        now = self._clock()
        if not force and now < self._next_try:
            return False
        try:
            self._pipe = self._open()
        except OSError:
            self._next_try = now + RETRY_S
            return False
        log.info("Wisp : connecté")
        return True

    def _close(self) -> None:
        if self._pipe is not None:
            self._pipe.close()
            self._pipe = None
