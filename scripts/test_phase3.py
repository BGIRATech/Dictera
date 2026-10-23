"""Test de la Phase 3 : reformulation -> insertion dans la fenêtre capturée -> restauration
du presse-papiers.

Déroulé :
  1. état de la reformulation (Ollama présent ou repli règles) ;
  2. ouverture de deux fenêtres de test (« Cible », « Autre fenêtre ») ;
  3. le presse-papiers reçoit un contenu « d'origine » multi-format (texte + format privé) ;
  4. « appui » : la fenêtre Cible est au premier plan et capturée ;
  5. l'utilisateur « change de fenêtre » : l'Autre fenêtre prend le focus ;
  6. la phrase est reformulée puis insérée par Inserter.insert ;
  7. vérifications : texte dans la Cible, rien dans l'Autre, presse-papiers d'origine
     restauré à l'identique.
Votre presse-papiers réel est sauvegardé au début et remis à la fin.

Option --audio : la phrase est d'abord synthétisée (voix fr-FR) puis transcrite par le
moteur de la Phase 2 : chaîne complète transcription -> reformulation -> insertion.
"""

import argparse
import json
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from dictera import clipboard, target as tgt  # noqa: E402
from dictera.config import Config  # noqa: E402
from dictera.inserter import PASTED, Inserter  # noqa: E402
from dictera.reformulate import Reformulator  # noqa: E402
from dictera.vocabulary import Vocabulary  # noqa: E402

PHRASE = ("euh bonjour, je teste euh l'insertion automatique de Dictera dans la bonne fenêtre "
          "hum même si le focus a changé pendant la dictée")
MARKER_FORMAT = "Dictera.Test.Marqueur"
MARKER_DATA = b"\x01\x02marqueur-binaire\x00\xff"


class TargetApp:
    def __init__(self):
        self.proc = subprocess.Popen(
            [sys.executable, str(ROOT / "scripts" / "_target_window.py")],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding="utf-8",
        )
        self.hwnds = json.loads(self.proc.stdout.readline())

    def dump(self) -> dict:
        self.proc.stdin.write("dump\n")
        self.proc.stdin.flush()
        return json.loads(self.proc.stdout.readline())

    def close(self) -> None:
        try:
            self.proc.stdin.write("quit\n")
            self.proc.stdin.flush()
            self.proc.wait(5)
        except (OSError, subprocess.TimeoutExpired):
            self.proc.kill()


def window_target(hwnd: int) -> tgt.Target:
    """Met la fenêtre au premier plan puis la capture exactement comme à l'appui de la touche."""
    tgt.focus(tgt.Target(hwnd, 0, 0, _thread_of(hwnd), "", "", False), timeout_s=2.0)
    time.sleep(0.15)
    return tgt.capture_foreground()


def _thread_of(hwnd: int) -> int:
    return tgt.u32.GetWindowThreadProcessId(hwnd, None)


def transcribe_audio(phrase: str) -> str:
    from dictera.audio import SAMPLE_RATE, Recording
    from dictera.engine import DictationEngine
    from test_phase2 import read_wav, synthesize

    wav = Path(tempfile.mkdtemp(prefix="dictera-test-")) / "phrase.wav"
    synthesize(phrase, wav)
    out: list = []
    done = threading.Event()
    engine = DictationEngine("large-v3-turbo", "fr", lambda t: (out.append(t), done.set()),
                             lambda m: (out.append(m), done.set()))
    engine.start()
    engine.wait_ready(300)
    engine.submit(Recording(read_wav(wav), SAMPLE_RATE, 0.0, False, 0), time.perf_counter())
    done.wait(120)
    engine.stop()
    if not out or isinstance(out[0], str):
        raise SystemExit(f"Transcription impossible : {out[0] if out else 'délai dépassé'}")
    t = out[0]
    print(f"   transcription Whisper ({t.model}, {t.latency_ms:.0f} ms) : {t.text}")
    return t.text


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio", action="store_true", help="passer par la transcription (Phase 2)")
    parser.add_argument("--phrase", default=PHRASE)
    parser.add_argument("--keys", choices=["ctrl+v", "shift+insert"], help="force la combinaison de collage")
    args = parser.parse_args()
    cfg = Config.load()
    if args.keys:
        cfg.paste_keys = args.keys

    print("1) Reformulation")
    vocab = Vocabulary()
    reform = Reformulator(cfg.reformulation, cfg.ollama_url, cfg.ollama_model, cfg.ollama_timeout_s,
                          keep_terms=vocab.words)
    print(f"   mode « {cfg.reformulation} » : {reform.status()}")

    real_clipboard = clipboard.snapshot()  # votre presse-papiers réel, remis à la fin
    app = TargetApp()
    try:
        print("\n2) Fenêtres de test ouvertes : Cible hwnd=0x%X, Autre hwnd=0x%X"
              % (app.hwnds["target"], app.hwnds["other"]))

        print("\n3) Presse-papiers « d'origine » (multi-format)")
        original_text = f"Presse-papiers d'origine ✓ {time.strftime('%H:%M:%S')}"
        marker_fmt = clipboard.u32.RegisterClipboardFormatW(MARKER_FORMAT)
        clipboard.restore(clipboard.Snapshot(formats=[
            (13, (original_text + "\0").encode("utf-16-le")),  # CF_UNICODETEXT
            (marker_fmt, MARKER_DATA),
        ]))
        before = clipboard.snapshot()
        print(f"   texte : « {clipboard.get_text()} » + format privé « {MARKER_FORMAT} » "
              f"({len(MARKER_DATA)} octets) — {len(before.formats)} formats au total")

        print("\n4) Appui : capture de la fenêtre au premier plan")
        target = window_target(app.hwnds["target"])
        print(f"   cible capturée : {target}")
        if target is None or target.hwnd != app.hwnds["target"]:
            print("   ÉCHEC : la fenêtre Cible n'a pas pu être mise au premier plan")
            return 1

        print("\n5) Pendant la dictée, l'utilisateur passe sur une autre fenêtre")
        other = window_target(app.hwnds["other"])
        print(f"   premier plan maintenant : {other}")

        print("\n6) Transcription -> reformulation -> insertion")
        raw = transcribe_audio(args.phrase) if args.audio else args.phrase
        if not args.audio:
            print(f"   phrase donnée : {raw}")
        final, engine_used, ms = reform.process(raw)
        print(f"   reformulée ({engine_used}, {ms:.1f} ms) : {final}")
        inserter = Inserter(cfg.paste_delay_ms, cfg.restore_delay_ms, cfg.paste_keys,
                            cfg.shift_insert_apps, cfg.restore_clipboard, cfg.clipboard_no_history)
        result = inserter.insert(final, target)
        print(f"   insertion : {result.status} via {result.keys}, presse-papiers restauré : {result.restored}")
        print(f"   chronologie (ms) : {result.timings_ms}  "
              f"[paste_delay_ms={cfg.paste_delay_ms}, restore_delay_ms={cfg.restore_delay_ms}]")
        time.sleep(0.2)

        print("\n7) Vérifications")
        texts = app.dump()
        after = clipboard.snapshot()
        checks = {
            "texte inséré dans la fenêtre Cible": texts["target"] == final,
            "rien dans l'Autre fenêtre": texts["other"] == "",
            "presse-papiers : texte d'origine restauré": clipboard.get_text() == original_text,
            "presse-papiers : format privé restauré à l'octet près":
                dict(after.formats).get(marker_fmt) == MARKER_DATA,
            "insertion signalée comme collée": result.status == PASTED,
        }
        print(f"   contenu de la Cible : « {texts['target']} »")
        print(f"   contenu de l'Autre  : « {texts['other']} »")
        print(f"   presse-papiers final : « {clipboard.get_text()} »")
        for label, ok in checks.items():
            print(f"   [{'OK' if ok else 'ÉCHEC'}] {label}")
        success = all(checks.values())
        print("SUCCÈS" if success else "ÉCHEC")
        return 0 if success else 1
    finally:
        app.close()
        clipboard.restore(real_clipboard)


if __name__ == "__main__":
    sys.exit(main())
