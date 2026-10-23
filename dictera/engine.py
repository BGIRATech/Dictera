"""Moteur de dictée : sonde GPU -> chargement du modèle -> préchauffage, puis une file
de dictées traitée par un thread dédié (le hook clavier n'attend jamais le GPU) :
transcription -> reformulation (optionnelle) -> on_result."""

import logging
import queue
import threading
from typing import Callable

from .audio import Recording
from .gpu import GpuProbeError, GpuReport, probe_gpu
from .reformulate import Reformulator
from .transcriber import ModelNotAvailable, Transcriber, Transcript
from .vocabulary import Vocabulary

log = logging.getLogger(__name__)


class DictationEngine:
    def __init__(
        self,
        model: str,
        language: str,
        on_result: Callable[[Transcript], None],
        on_error: Callable[[str], None],
        vocabulary: Vocabulary | None = None,
        reformulator: Reformulator | None = None,
    ):
        self.transcriber = Transcriber(model, language, vocabulary)
        self.reformulator = reformulator
        self.gpu: GpuReport | None = None
        self.error: str | None = None
        self._on_result = on_result
        self._on_error = on_error
        self._ready = threading.Event()
        self._jobs: queue.Queue = queue.Queue()
        self._worker = threading.Thread(target=self._run, name="dictera-engine", daemon=True)

    @property
    def ready(self) -> bool:
        return self._ready.is_set()

    def start(self) -> None:
        self._worker.start()

    def wait_ready(self, timeout: float | None = None) -> bool:
        self._ready.wait(timeout)
        return self.ready

    def stop(self) -> None:
        self._jobs.put(None)
        if self._worker.is_alive():
            self._worker.join(5)

    def submit(self, rec: Recording, released_at: float, context: object = None) -> None:
        if self.error:
            self._on_error(self.error)
            return
        if not self.ready:
            log.info("Moteur en cours de chargement : la dictée sera transcrite dès qu'il sera prêt")
        self._jobs.put((rec, released_at, context))

    def _initialize(self) -> bool:
        try:
            self.gpu = probe_gpu()
            self.transcriber.load()
            self.transcriber.warmup()
        except (GpuProbeError, ModelNotAvailable) as e:
            self.error = str(e)
        except Exception as e:  # ex. erreur CUDA/cuDNN au premier passage réel sur le GPU
            log.exception("Initialisation du moteur impossible")
            self.error = f"Le moteur de transcription n'a pas pu démarrer sur le GPU : {e}"
        if self.error:
            log.error("%s", self.error)
            self._on_error(self.error)
            return False
        self._ready.set()
        return True

    def _run(self) -> None:
        if not self._initialize():
            while self._jobs.get() is not None:  # vider la file sans traiter
                pass
            return
        while (job := self._jobs.get()) is not None:
            rec, released_at, context = job
            try:
                transcript = self.transcriber.transcribe(rec.samples, released_at)
            except Exception as e:
                log.exception("Échec de la transcription")
                self._on_error(f"Échec de la transcription : {e}")
                continue
            transcript.context = context
            transcript.final_text = transcript.text
            if self.reformulator and transcript.text:
                try:
                    transcript.final_text, transcript.reformulation, transcript.reformulation_ms = \
                        self.reformulator.process(transcript.text)
                except Exception:  # la dictée ne doit jamais être perdue pour un souci de mise au propre
                    log.exception("Échec de la reformulation : texte de Whisper conservé")
            try:
                self._on_result(transcript)
            except Exception:
                log.exception("Erreur dans le traitement du résultat")
