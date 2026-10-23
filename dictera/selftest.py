"""Autotest : `Dictera.exe --self-test [phrase.wav]` (ou `python -m dictera --self-test`).

Vérifie, sans hook clavier, sans fenêtre visible et sans toucher aux données de
l'utilisateur, que tout ce dont la dictée a besoin est présent et fonctionne : GPU et
DLL CUDA, modèle Whisper (et une vraie transcription si un WAV est fourni), PortAudio,
Qt (plugins et polices), SQLite. Indispensable pour valider l'application packagée.

Rapport : %LOCALAPPDATA%\\Dictera\\logs\\self-test.txt (+ sortie standard si présente).
Code de retour : 0 si tout est OK, 1 sinon.
"""

import sys
import tempfile
import time
import traceback
import wave
from pathlib import Path

from . import __version__
from .config import log_dir


def run(wav: Path | None = None) -> int:
    lines: list[str] = []
    failures = 0

    def step(name: str, fn) -> object:
        nonlocal failures
        t0 = time.perf_counter()
        try:
            detail = fn()
            suffix = f" — {detail}" if isinstance(detail, str) and detail else ""
            lines.append(f"[OK]    {name} ({(time.perf_counter() - t0) * 1000:.0f} ms){suffix}")
            return detail
        except Exception as e:
            failures += 1
            lines.append(f"[ÉCHEC] {name} — {e}")
            lines.extend("        " + x for x in traceback.format_exc().strip().splitlines()[-6:])
            return None

    frozen = getattr(sys, "frozen", False)
    lines.append(f"Dictera {__version__} — autotest — {'application packagée' if frozen else 'environnement Python'}")
    lines.append(f"exécutable : {sys.executable}")

    from .gpu import probe_gpu
    report = step("Sonde GPU (CUDA, float16, cuBLAS, cuDNN)", probe_gpu)
    if report is not None:
        lines.extend("        " + x for x in report.lines())

    from .transcriber import Transcriber
    transcriber = Transcriber()

    def load():
        name = transcriber.load()
        return f"{name}, préchauffage GPU {transcriber.warmup():.0f} ms"

    loaded = step("Modèle Whisper (disque local, sans réseau)", load)

    if wav and loaded:
        def transcribe():
            import numpy as np
            with wave.open(str(wav), "rb") as w:
                pcm = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768
            t = transcriber.transcribe(pcm)
            from .reformulate import Reformulator
            final, _, _ = Reformulator("rules").process(t.text)
            return f"{t.latency_ms:.0f} ms — « {final} »"

        step(f"Transcription de {wav.name}", transcribe)

    def audio():
        import sounddevice as sd
        dev = sd.query_devices(kind="input")
        sd.check_input_settings(samplerate=16000, channels=1, dtype="float32")
        return f"micro par défaut : {dev['name']} (16 kHz mono OK)"

    step("PortAudio et micro", audio)

    tmp = Path(tempfile.mkdtemp(prefix="dictera-selftest-"))

    def storage():
        from .storage import Database
        db = Database(tmp / "selftest.db")
        n = len(db.words())
        db.close()
        return f"base temporaire créée, {n} mots pré-remplis"

    step("SQLite", storage)

    def ui():
        from .app import create_qt_app
        from .config import Config
        from .storage import Database
        from .ui.context import UiContext
        from .ui.window import MainWindow
        from .vocabulary import Vocabulary
        create_qt_app()
        db = Database(tmp / "ui.db")
        win = MainWindow(UiContext(db, Config(), Vocabulary()))
        for i in range(len(win.pages)):
            win.show_page(i)
        win.quitting = True
        win.close()
        db.close()
        from PySide6.QtGui import QFontDatabase
        missing = [f for f in ("Segoe UI Variable Text", "Segoe Fluent Icons") if f not in QFontDatabase.families()]
        return "4 pages construites" + (f" ; polices absentes : {', '.join(missing)}" if missing else "")

    step("Interface Qt", ui)

    lines.append("RÉSULTAT : " + ("OK" if not failures else f"{failures} échec(s)"))
    text = "\n".join(lines)
    out = log_dir() / "self-test.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text + "\n", encoding="utf-8")
    if sys.stdout is not None:
        print(text)
    return 0 if not failures else 1
