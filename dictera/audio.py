"""Capture micro 16 kHz mono, en mémoire uniquement (jamais écrite sur disque).

Aucun traitement du signal demandé au pilote (pas d'annulation d'écho, de réduction
de bruit ni de gain automatique) : Whisper préfère le signal brut.

Le flux est *ouvert* une fois (≈260 ms, mesuré) mais n'est *démarré* que pendant le
maintien de la touche (≈0–5 ms) : sinon le début de chaque phrase serait coupé.
Hors maintien, aucun échantillon n'est lu.
"""

import logging
import math
import threading
import time
from dataclasses import dataclass

import numpy as np
import sounddevice as sd

log = logging.getLogger(__name__)

SAMPLE_RATE = 16_000
BLOCK_SIZE = 320  # 20 ms
# Niveau affiché (Wisp) : -50 dBFS -> 0, -10 dBFS -> 1 ; retombée d'environ 15 % par bloc.
LEVEL_FLOOR_DB, LEVEL_CEIL_DB, LEVEL_RELEASE = -50.0, -10.0, 0.85


@dataclass(frozen=True)
class Recording:
    samples: np.ndarray  # float32 mono dans [-1, 1]
    sample_rate: int
    startup_ms: float  # délai entre la demande et l'ouverture effective du flux
    truncated: bool  # True si la durée maximale a été atteinte
    xruns: int  # blocs signalés en dépassement par PortAudio

    @property
    def duration_s(self) -> float:
        return len(self.samples) / self.sample_rate

    @property
    def rms_dbfs(self) -> float:
        if not len(self.samples):
            return -math.inf
        rms = float(np.sqrt(np.mean(np.square(self.samples, dtype=np.float64))))
        return 20 * math.log10(rms) if rms > 0 else -math.inf

    @property
    def peak_dbfs(self) -> float:
        if not len(self.samples):
            return -math.inf
        peak = float(np.max(np.abs(self.samples)))
        return 20 * math.log10(peak) if peak > 0 else -math.inf


def trim_silence(samples: np.ndarray, sample_rate: int = SAMPLE_RATE, pad_ms: int = 200) -> np.ndarray:
    """Rogne les silences de début et de fin (pas de détection de parole : la touche
    maintenue délimite déjà la dictée). Renvoie un tableau vide si tout est silence.

    Énergie par trames de 20 ms ; une trame est « parlée » si elle dépasse à la fois
    -55 dBFS et le plancher de bruit estimé (10e centile) + 12 dB.
    """
    frame = sample_rate // 50
    n = len(samples) // frame
    if n == 0:
        return samples[:0]
    frames = samples[: n * frame].reshape(n, frame).astype(np.float64)
    db = 10 * np.log10(np.mean(frames ** 2, axis=1) + 1e-12)
    threshold = max(-55.0, float(np.percentile(db, 10)) + 12.0)
    voiced = np.flatnonzero(db > threshold)
    if voiced.size == 0:
        return samples[:0]
    pad = pad_ms * sample_rate // 1000
    start = max(0, voiced[0] * frame - pad)
    end = min(len(samples), (voiced[-1] + 1) * frame + pad)
    return samples[start:end]


class Recorder:
    def __init__(self, device: str | int | None = None, max_seconds: int = 600):
        self.device = device
        self.max_frames = max_seconds * SAMPLE_RATE
        self._lock = threading.Lock()
        self._stream: sd.InputStream | None = None
        self._recording = False
        self._chunks: list[np.ndarray] = []
        self._frames = 0
        self._xruns = 0
        self._truncated = False
        self._startup_ms = 0.0
        self._level = 0.0

    @property
    def recording(self) -> bool:
        return self._recording

    @property
    def level(self) -> float:
        """Niveau de la voix pendant la capture, de 0 à 1 (pour l'affichage seulement)."""
        return self._level if self._recording else 0.0

    def open(self) -> None:
        """Ouvre le flux sans le démarrer (à appeler au lancement)."""
        with self._lock:
            self._ensure_open()

    def close(self) -> None:
        with self._lock:
            self._recording = False
            if self._stream is not None:
                self._stream.close(ignore_errors=True)
                self._stream = None

    def start(self) -> None:
        with self._lock:
            if self._recording:
                return
            self._chunks, self._frames, self._xruns, self._truncated = [], 0, 0, False
            self._level = 0.0
            t0 = time.perf_counter()
            stream = self._ensure_open()
            try:
                stream.start()
            except sd.PortAudioError:
                # Périphérique débranché ou changé depuis l'ouverture : on rouvre une fois.
                log.warning("Flux micro invalide, réouverture")
                stream.close(ignore_errors=True)
                self._stream = None
                self._ensure_open().start()
            self._startup_ms = (time.perf_counter() - t0) * 1000
            self._recording = True
        log.info("Capture démarrée (démarrage du flux : %.0f ms)", self._startup_ms)

    def stop(self) -> Recording | None:
        if not self._halt():
            return None
        samples = np.concatenate(self._chunks)[:, 0] if self._chunks else np.zeros(0, np.float32)
        self._chunks = []
        rec = Recording(samples, SAMPLE_RATE, self._startup_ms, self._truncated, self._xruns)
        log.info(
            "Capture arrêtée : %.2f s, RMS %.1f dBFS, crête %.1f dBFS%s",
            rec.duration_s, rec.rms_dbfs, rec.peak_dbfs, " (tronquée)" if rec.truncated else "",
        )
        return rec

    def cancel(self) -> None:
        if self._halt():
            self._chunks = []
            log.info("Capture annulée")

    def _ensure_open(self) -> sd.InputStream:
        if self._stream is None:
            t0 = time.perf_counter()
            self._stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="float32",
                blocksize=BLOCK_SIZE,
                device=self.device,
                latency="low",
                callback=self._callback,
            )
            log.info("Flux micro ouvert en %.0f ms (%s)", (time.perf_counter() - t0) * 1000,
                     sd.query_devices(self._stream.device)["name"])
        return self._stream

    def _halt(self) -> bool:
        """Arrête la capture ; le flux reste ouvert pour la prochaine dictée."""
        with self._lock:
            if not self._recording:
                return False
            self._recording = False
            if self._stream is not None:
                self._stream.stop(ignore_errors=True)  # attend la fin des tampons en cours
        return True

    def _callback(self, indata, frames, _time, status) -> None:
        if status.input_overflow:
            self._xruns += 1
        if self._frames >= self.max_frames:
            self._truncated = True
            return
        self._chunks.append(indata.copy())
        self._frames += frames
        # 320 échantillons : quelques microsecondes, sans effet sur la capture.
        rms = float(np.sqrt(np.mean(np.square(indata, dtype=np.float32))))
        db = 20 * math.log10(rms) if rms > 1e-9 else -120.0
        level = min(1.0, max(0.0, (db - LEVEL_FLOOR_DB) / (LEVEL_CEIL_DB - LEVEL_FLOOR_DB)))
        self._level = max(level, self._level * LEVEL_RELEASE)
