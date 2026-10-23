"""Transcription locale : faster-whisper sur CUDA, float16, langue fr.

Les modèles sont lus uniquement sur le disque (%LOCALAPPDATA%\\Dictera\\models) :
aucune connexion réseau pendant la dictée. Le téléchargement initial est une étape
explicite (scripts/fetch_models.py).
"""

import logging
import os
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .audio import SAMPLE_RATE, trim_silence
from .gpu import COMPUTE_TYPE, register_cuda_dlls
from .vocabulary import Vocabulary

log = logging.getLogger(__name__)

DEFAULT_MODEL = "large-v3-turbo"
FALLBACK_MODEL = "large-v3"
MODELS = (DEFAULT_MODEL, FALLBACK_MODEL)


def models_dir() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Dictera" / "models"


def bundled_model_dir(name: str) -> Path | None:
    """Modèle livré avec l'application packagée (dossier models\\<nom> à côté de
    Dictera.exe) : utilisable sans aucun téléchargement."""
    if not getattr(sys, "frozen", False):
        return None
    path = Path(sys.executable).parent / "models" / name
    return path if (path / "model.bin").is_file() else None


class ModelNotAvailable(RuntimeError):
    """Aucun modèle utilisable n'est présent ou chargeable."""


@dataclass
class Transcript:
    raw_text: str  # sortie brute de Whisper
    text: str  # après corrections automatiques
    corrections: list[tuple[str, str]] = field(default_factory=list)
    audio_s: float = 0.0  # durée enregistrée
    speech_s: float = 0.0  # durée envoyée au modèle, après rognage des silences
    latency_ms: float = 0.0  # du relâchement de la touche au texte prêt
    model: str = ""
    final_text: str = ""  # après reformulation (Phase 3) ; = text si désactivée
    reformulation: str = "off"  # moteur de reformulation utilisé : off | rules | ollama
    reformulation_ms: float = 0.0
    context: object = None  # donnée opaque de l'appelant (fenêtre cible), rendue avec le résultat

    @property
    def empty(self) -> bool:
        return not self.text


class Transcriber:
    def __init__(self, model: str = DEFAULT_MODEL, language: str = "fr", vocabulary: Vocabulary | None = None):
        self.requested_model = model
        self.language = language
        self.vocabulary = vocabulary or Vocabulary()
        self.model_name = ""
        self._model = None
        self._lock = threading.Lock()  # un seul décodage à la fois sur le GPU

    @property
    def ready(self) -> bool:
        return self._model is not None

    def load(self, allow_download: bool = False) -> str:
        """Charge le modèle demandé, sinon le repli. Renvoie le nom du modèle chargé."""
        register_cuda_dlls()
        os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
        from faster_whisper import WhisperModel

        candidates = [self.requested_model] + [m for m in MODELS if m != self.requested_model]
        errors = []
        for name in candidates:
            t0 = time.perf_counter()
            bundled = bundled_model_dir(name)
            try:
                model = WhisperModel(
                    str(bundled) if bundled else name,
                    device="cuda",
                    compute_type=COMPUTE_TYPE,
                    download_root=str(models_dir()),
                    local_files_only=not allow_download,
                )
            except Exception as e:  # modèle absent du disque ou chargement GPU impossible
                errors.append(f"{name} : {e}")
                log.warning("Modèle %s indisponible : %s", name, e)
                continue
            self._model, self.model_name = model, name
            log.info("Modèle %s chargé sur cuda/%s en %.1f s (%s)", name, COMPUTE_TYPE, time.perf_counter() - t0,
                     "livré avec l'application" if bundled else models_dir())
            return name
        raise ModelNotAvailable(
            "Aucun modèle Whisper n'a pu être chargé :\n  " + "\n  ".join(errors) + "\n"
            "Téléchargez-le une fois (seule étape réseau), dans D:\\Dictera :\n"
            f"  .venv\\Scripts\\python scripts\\fetch_models.py {self.requested_model}"
        )

    def warmup(self) -> float:
        """Étage réel de la sonde GPU : un décodage sur 1 s de silence (encodeur => cuDNN).
        Initialise aussi les noyaux CUDA pour que la première vraie dictée soit rapide."""
        t0 = time.perf_counter()
        with self._lock:
            segments, _ = self._model.transcribe(
                np.zeros(SAMPLE_RATE, np.float32), language=self.language, beam_size=1,
                without_timestamps=True, condition_on_previous_text=False,
            )
            list(segments)
        ms = (time.perf_counter() - t0) * 1000
        log.info("Préchauffage du modèle : %.0f ms", ms)
        return ms

    def transcribe(self, samples: np.ndarray, released_at: float | None = None) -> Transcript:
        """Transcrit un enregistrement 16 kHz mono. `released_at` (perf_counter du
        relâchement) sert de point de départ à la latence ; sinon, l'appel lui-même."""
        t0 = released_at if released_at is not None else time.perf_counter()
        audio_s = len(samples) / SAMPLE_RATE
        speech = trim_silence(samples)
        if not len(speech):
            # Whisper invente du texte sur le silence (« Sous-titres réalisés par… ») : on s'abstient.
            return Transcript("", "", audio_s=audio_s, latency_ms=(time.perf_counter() - t0) * 1000,
                              model=self.model_name)
        with self._lock:
            segments, _info = self._model.transcribe(
                speech,
                language=self.language,
                initial_prompt=self.vocabulary.initial_prompt(),
                beam_size=5,
                vad_filter=False,
                without_timestamps=True,
                condition_on_previous_text=False,
            )
            raw = " ".join(s.text.strip() for s in segments).strip()  # le générateur décode ici
        text, applied = self.vocabulary.apply_corrections(raw)
        return Transcript(
            raw_text=raw,
            text=text,
            corrections=applied,
            audio_s=audio_s,
            speech_s=len(speech) / SAMPLE_RATE,
            latency_ms=(time.perf_counter() - t0) * 1000,
            model=self.model_name,
        )
