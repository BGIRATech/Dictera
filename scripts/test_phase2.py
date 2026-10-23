"""Test de la Phase 2 : sonde GPU, puis transcription locale d'un court audio français.

Par défaut, l'audio est synthétisé hors ligne par la voix Windows « Hortense » (fr-FR,
SAPI) en 16 kHz mono. Il passe ensuite par le même chemin que l'application
(DictationEngine.submit, appelé par _handle_recording), plusieurs fois, pour mesurer
la latence à froid puis à chaud.

Usage : .venv\\Scripts\\python scripts\\test_phase2.py [--wav fichier.wav] [--runs 3]
"""

import argparse
import subprocess
import sys
import tempfile
import threading
import time
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402

from dictera.audio import SAMPLE_RATE, Recording  # noqa: E402
from dictera.engine import DictationEngine  # noqa: E402
from dictera.gpu import GpuProbeError, probe_gpu  # noqa: E402
from dictera.transcriber import Transcript  # noqa: E402

PHRASE = ("Bonjour, ceci est un test de dictée locale avec Claude Code. "
          "J'ai écrit un nouveau ski pour améliorer mon prompt, et c'est sur ma to-do liste.")


def synthesize(text: str, path: Path) -> None:
    """Synthèse vocale locale (System.Speech), WAV PCM 16 kHz 16 bits mono."""
    ps = f"""
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$v = $s.GetInstalledVoices() | Where-Object {{ $_.VoiceInfo.Culture.Name -eq 'fr-FR' -and $_.Enabled }} | Select-Object -First 1
if (-not $v) {{ Write-Error 'Aucune voix fr-FR installée'; exit 3 }}
$s.SelectVoice($v.VoiceInfo.Name)
$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
$s.SetOutputToWaveFile('{path}', $fmt)
$s.Speak($env:DICTERA_TTS_TEXT)
$s.Dispose()
"""
    env = {**__import__("os").environ, "DICTERA_TTS_TEXT": text}
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True, env=env,
                   creationflags=subprocess.CREATE_NO_WINDOW)


def read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        if (w.getframerate(), w.getnchannels(), w.getsampwidth()) != (SAMPLE_RATE, 1, 2):
            raise SystemExit(f"{path} doit être en WAV PCM 16 bits, mono, {SAMPLE_RATE} Hz")
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
    return pcm.astype(np.float32) / 32768.0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wav", type=Path, help="WAV 16 kHz mono 16 bits (sinon synthèse fr-FR)")
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args()

    print("1) Sonde GPU")
    try:
        report = probe_gpu()
    except GpuProbeError as e:
        print(f"   ÉCHEC\n{e}")
        return 1
    print("   OK")
    for line in report.lines():
        print(f"   {line}")

    print("\n2) Audio de test")
    if args.wav:
        wav = args.wav
    else:
        wav = Path(tempfile.mkdtemp(prefix="dictera-test-")) / "phrase_fr.wav"
        synthesize(PHRASE, wav)
        print(f"   synthèse fr-FR locale : « {PHRASE} »")
    samples = read_wav(wav)
    print(f"   {wav} : {len(samples) / SAMPLE_RATE:.2f} s à {SAMPLE_RATE} Hz")

    print("\n3) Chargement du modèle (disque local uniquement) et préchauffage GPU")
    results: list[Transcript] = []
    errors: list[str] = []
    got = threading.Event()

    def on_result(t: Transcript) -> None:
        results.append(t)
        got.set()

    def on_error(msg: str) -> None:
        errors.append(msg)
        got.set()

    t0 = time.perf_counter()
    engine = DictationEngine("large-v3-turbo", "fr", on_result, on_error)
    engine.start()
    if not engine.wait_ready(300):
        print(f"   ÉCHEC\n{errors[0] if errors else 'délai dépassé'}")
        return 1
    print(f"   modèle {engine.transcriber.model_name} prêt en {time.perf_counter() - t0:.1f} s "
          f"(sonde + chargement + préchauffage)")
    print(f"   amorce : {engine.transcriber.vocabulary.initial_prompt()}")

    print(f"\n4) Transcription ({args.runs} passages, latence mesurée depuis le « relâchement »)")
    rec = Recording(samples, SAMPLE_RATE, startup_ms=0.0, truncated=False, xruns=0)
    for i in range(args.runs):
        got.clear()
        engine.submit(rec, released_at=time.perf_counter())
        got.wait(120)
        if errors:
            print(f"   ÉCHEC : {errors[-1]}")
            return 1
        t = results[-1]
        print(f"   passage {i + 1} : latence {t.latency_ms:6.0f} ms  |  parole {t.speech_s:.2f} s "
              f"sur {t.audio_s:.2f} s  |  RTF {t.latency_ms / 1000 / max(t.speech_s, 1e-6):.3f}")
    engine.stop()

    t = results[-1]
    print(f"\n   texte brut Whisper : {t.raw_text}")
    print(f"   texte final        : {t.text}")
    print(f"   corrections        : {', '.join(f'{a} → {b}' for a, b in t.corrections) or 'aucune'}")
    lat = sorted(r.latency_ms for r in results)
    print(f"\n   latence : min {lat[0]:.0f} ms, médiane {lat[len(lat) // 2]:.0f} ms, max {lat[-1]:.0f} ms")
    ok = bool(t.text) and t.model == "large-v3-turbo"
    print("SUCCÈS" if ok else "ÉCHEC : transcription vide ou mauvais modèle")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
