"""Test de la Phase 1 : touche push-to-talk -> capture micro -> durée et niveau.

Modes :
  auto   (défaut) simule l'appui puis le relâchement de la touche via SendInput.
         Le hook bas niveau voit ces événements comme de vrais appuis (drapeau « injecté »).
  manuel (--manual) attend que vous mainteniez puis relâchiez la touche vous-même.

Usage : .venv\\Scripts\\python scripts\\test_phase1.py [--manual] [--hold 2.0] [--key RCTRL]
"""

import argparse
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sounddevice as sd  # noqa: E402

from dictera.audio import Recorder, Recording  # noqa: E402
from dictera.config import HOTKEYS  # noqa: E402
from dictera.hotkey import PushToTalkHook  # noqa: E402
from dictera.sounds import SoundPlayer  # noqa: E402
from dictera.win32 import send_key  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manual", action="store_true", help="appuyer soi-même sur la touche")
    parser.add_argument("--hold", type=float, default=2.0, help="durée du maintien simulé (s)")
    parser.add_argument("--key", default="RCTRL", choices=sorted(HOTKEYS))
    parser.add_argument("--no-sound", action="store_true")
    args = parser.parse_args()

    label, vk = HOTKEYS[args.key]
    dev = sd.query_devices(kind="input")
    print(f"Micro : {dev['name']}  |  touche : {label} (vk=0x{vk:02X})")

    t0 = time.perf_counter()
    stamp = lambda: f"[{time.perf_counter() - t0:6.3f} s]"  # noqa: E731
    recorder = Recorder()
    sounds = SoundPlayer(not args.no_sound)
    result: dict[str, object] = {}
    done = threading.Event()

    def on_press(injected: bool) -> None:
        result["press_at"] = time.perf_counter()
        print(f"{stamp()} hook : appui {label}{' (injecté par SendInput)' if injected else ' (physique)'}")
        recorder.start()
        sounds.start()
        print(f"{stamp()} capture DÉMARRÉE (flux démarré en {recorder._startup_ms:.0f} ms)")

    def on_release() -> None:
        result["release_at"] = time.perf_counter()
        print(f"{stamp()} hook : relâchement {label}")
        rec = recorder.stop()
        sounds.stop()
        print(f"{stamp()} capture ARRÊTÉE")
        result["rec"] = rec
        done.set()

    def on_cancel() -> None:
        recorder.cancel()
        print(f"{stamp()} hook : autre touche pressée -> capture ANNULÉE")
        result["cancelled"] = True
        done.set()

    recorder.open()
    sounds.open()
    print(f"{stamp()} micro et sortie audio ouverts (non démarrés)")
    hook = PushToTalkHook(vk, on_press, on_release, on_cancel)
    hook.start()
    print(f"{stamp()} hook WH_KEYBOARD_LL installé")
    try:
        if args.manual:
            print(f"Maintenez {label}, parlez, puis relâchez (60 s max)…")
            done.wait(60)
        else:
            time.sleep(0.3)
            print(f"{stamp()} SendInput : {label} enfoncée")
            send_key(vk, up=False)
            time.sleep(args.hold)
            print(f"{stamp()} SendInput : {label} relâchée")
            send_key(vk, up=True)
            done.wait(5)
        time.sleep(0.3)  # laisser finir le son de fin
    finally:
        hook.stop()
        recorder.cancel()
        recorder.close()
        sounds.close()

    rec: Recording | None = result.get("rec")  # type: ignore[assignment]
    if result.get("cancelled") or rec is None:
        print("ÉCHEC : aucun enregistrement complet (touche non détectée ou dictée annulée).")
        return 1

    held = result["release_at"] - result["press_at"]  # type: ignore[operator]
    print()
    print("Résultat")
    print(f"  maintien de la touche : {held:.3f} s")
    print(f"  durée capturée        : {rec.duration_s:.3f} s ({len(rec.samples)} échantillons à {rec.sample_rate} Hz, mono)")
    print(f"  niveau RMS            : {rec.rms_dbfs:.1f} dBFS")
    print(f"  niveau crête          : {rec.peak_dbfs:.1f} dBFS")
    print(f"  démarrage du flux     : {rec.startup_ms:.0f} ms  |  dépassements : {rec.xruns}")
    print(f"  écart maintien/capture: {1000 * (held - rec.duration_s):.0f} ms")

    # Tolérance de 100 ms : latence du pilote et granularité des blocs de 20 ms.
    ok = rec.sample_rate == 16_000 and rec.duration_s > 0 and abs(rec.duration_s - held) < 0.10
    print("SUCCÈS" if ok else "ÉCHEC : durée capturée incohérente avec le maintien.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
