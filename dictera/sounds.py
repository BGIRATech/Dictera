"""Sons de début et de fin de dictée, synthétisés en mémoire (aucun fichier).

Lus par un flux sounddevice ouvert une fois : winsound.PlaySound bloquait la capture
micro pendant ≈400 ms (mesuré en Phase 1) et retardait le son par l'ouverture du pilote.
"""

import logging
import threading

import numpy as np
import sounddevice as sd

log = logging.getLogger(__name__)

_RATE = 44_100


def _tone(freqs: list[float], note_s: float = 0.07, volume: float = 0.18) -> np.ndarray:
    """Petite suite de notes sinusoïdales avec enveloppe douce (float32 mono)."""
    t = np.arange(int(_RATE * note_s)) / _RATE
    fade = np.minimum(1.0, np.minimum(t, t[::-1]) / 0.012)  # 12 ms d'attaque et de chute
    notes = [np.sin(2 * np.pi * f * t) * fade for f in freqs]
    return (np.concatenate(notes) * volume).astype(np.float32)


START_SOUND = _tone([880.0, 1318.5])  # montant : la capture commence
STOP_SOUND = _tone([1318.5, 880.0])  # descendant : la capture s'arrête


class SoundPlayer:
    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self._lock = threading.Lock()
        self._stream: sd.OutputStream | None = None
        self._buffer = np.zeros(0, np.float32)
        self._pos = 0

    def open(self) -> None:
        """Ouvre la sortie audio à l'avance (à appeler au lancement)."""
        with self._lock:
            self._ensure_open()

    def close(self) -> None:
        with self._lock:
            if self._stream is not None:
                self._stream.close(ignore_errors=True)
                self._stream = None

    def start(self) -> None:
        self._play(START_SOUND)

    def stop(self) -> None:
        self._play(STOP_SOUND)

    def _play(self, data: np.ndarray) -> None:
        if not self.enabled:
            return
        with self._lock:
            try:
                stream = self._ensure_open()
                stream.stop(ignore_errors=True)  # interrompt un son encore en cours
                self._buffer, self._pos = data, 0
                stream.start()
            except sd.PortAudioError as e:
                log.warning("Lecture du son impossible : %s", e)
                if self._stream is not None:
                    self._stream.close(ignore_errors=True)
                    self._stream = None

    def _ensure_open(self) -> sd.OutputStream:
        if self._stream is None:
            self._stream = sd.OutputStream(
                samplerate=_RATE, channels=1, dtype="float32", latency="low", callback=self._callback
            )
        return self._stream

    def _callback(self, outdata, frames, _time, _status) -> None:
        chunk = self._buffer[self._pos:self._pos + frames]
        outdata[:len(chunk), 0] = chunk
        outdata[len(chunk):] = 0
        self._pos += frames
        if self._pos >= len(self._buffer):
            raise sd.CallbackStop
