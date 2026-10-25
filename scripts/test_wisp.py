"""Test du lien Dictera -> Wisp (dictera/wisp.py).

  1. sans Wisp : avec un faux pipe, vérifie l'ordre des messages, le flux de niveaux
     pendant l'écoute, la reconnexion après un redémarrage de Wisp, l'absence de blocage
     quand Wisp est fermé ou figé, et l'interrupteur des Réglages ;
  2. --live : joue une vraie dictée simulée vers Wisp lancé (\\\\.\\pipe\\wisp-bus), avec
     une voix synthétique qui monte et descend, pour voir la flamme pulser.

Usage : .venv\\Scripts\\python scripts\\test_wisp.py [--live]
"""

import argparse
import json
import math
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dictera.wisp import WispLink  # noqa: E402


class FakeWisp:
    """Faux serveur : enregistre les lignes reçues ; peut être « fermé » ou « figé »."""

    def __init__(self):
        self.lines: list[dict] = []
        self.running = True
        self.frozen = threading.Event()
        self.opens = 0
        self.generation = 0

    def opener(self):
        if not self.running:
            raise OSError("pipe introuvable")
        self.opens += 1
        return _FakePipe(self, self.generation)

    def restart(self):
        self.generation += 1  # les anciennes connexions sont mortes


class _FakePipe:
    def __init__(self, server: FakeWisp, gen: int):
        self.server, self.gen = server, gen

    def write(self, data: bytes) -> None:
        if self.gen != self.server.generation or not self.server.running:
            raise OSError("pipe brisé")
        if self.server.frozen.is_set():
            time.sleep(5)  # Wisp figé : l'écriture bloque
        for line in data.decode("utf-8").splitlines():
            self.server.lines.append(json.loads(line))

    def close(self) -> None:
        pass


def wait_for(cond, timeout=2.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return cond()


def states(server: FakeWisp) -> list[str]:
    return [m.get("state") for m in server.lines]


def test_dictation_sequence():
    srv = FakeWisp()
    link = WispLink(opener=srv.opener)
    link.start()
    level = {"v": 0.0}
    link.listening(lambda: level["v"])
    for i in range(10):
        level["v"] = i / 10
        time.sleep(0.03)
    link.thinking()
    link.done(42)
    assert wait_for(lambda: "finished" in states(srv)), states(srv)
    link.stop()

    s = states(srv)
    n_listen = s.count("listening")
    assert n_listen >= 3, f"flux de niveaux trop pauvre : {s}"
    first_other = next(i for i, x in enumerate(s) if x != "listening")
    assert s[first_other:] == ["thinking", "finished"], f"un niveau est passé après la fin de l'écoute : {s}"
    levels = [m["level"] for m in srv.lines if m["state"] == "listening"]
    assert levels == sorted(levels) and all(0 <= x <= 1 for x in levels), levels
    fin = srv.lines[-1]
    assert fin["label"] == "+42 mots" and fin["emote"] == "wink" and fin["source"] == "dictera" and fin["v"] == 1
    assert all("text" not in m for m in srv.lines)
    print(f"  ok  séquence écoute ({n_listen} niveaux) -> transcription -> +42 mots")


def test_wisp_closed_never_blocks_and_retries_slowly():
    srv = FakeWisp()
    srv.running = False
    link = WispLink(opener=srv.opener)
    link.start()
    t0 = time.perf_counter()
    for _ in range(100):
        link.thinking()
        link.idle()
    took = (time.perf_counter() - t0) * 1000
    assert took < 50, f"send() a bloqué {took:.0f} ms"
    time.sleep(0.3)
    srv.running = True
    link.done(3)  # une tentative au plus toutes les 2 s : ce message-là est perdu
    time.sleep(0.2)
    assert srv.lines == [], "reconnexion trop agressive"
    link.stop()
    print(f"  ok  Wisp fermé : 200 envois en {took:.1f} ms, aucune connexion forcée")


def test_reconnects_after_wisp_restart():
    srv = FakeWisp()
    link = WispLink(opener=srv.opener)
    link.start()
    link.thinking()
    assert wait_for(lambda: len(srv.lines) == 1)
    srv.restart()  # Wisp relancé : l'ancienne connexion casse à la prochaine écriture
    link.done(5)
    assert wait_for(lambda: len(srv.lines) == 2), srv.lines
    link.stop()
    assert srv.opens == 2 and srv.lines[-1]["label"] == "+5 mots"
    print("  ok  Wisp redémarré : reconnexion et message renvoyé")


def test_frozen_wisp_drops_instead_of_blocking():
    srv = FakeWisp()
    link = WispLink(opener=srv.opener)
    link.start()
    link.thinking()
    assert wait_for(lambda: len(srv.lines) == 1)
    srv.frozen.set()
    link.idle()  # le thread du lien reste bloqué sur cette écriture
    time.sleep(0.05)
    t0 = time.perf_counter()
    for i in range(100):
        link.done(i)
    took = (time.perf_counter() - t0) * 1000
    assert took < 50 and link.dropped > 0, (took, link.dropped)
    print(f"  ok  Wisp figé : send() reste instantané ({took:.1f} ms), {link.dropped} messages jetés")


def test_setting_off_clears_then_stays_silent():
    srv = FakeWisp()
    link = WispLink(opener=srv.opener)
    link.start()
    link.listening(lambda: 0.5)
    time.sleep(0.1)
    link.set_enabled(False)
    n = len(srv.lines)
    link.thinking()
    link.listening(lambda: 0.5)
    time.sleep(0.2)
    link.stop()
    assert wait_for(lambda: srv.lines and srv.lines[-1]["state"] == "idle"), states(srv)
    assert len(srv.lines) <= n + 1, f"messages envoyés après désactivation : {states(srv)[n:]}"
    print("  ok  réglage désactivé : pastille effacée, puis plus rien")


def live() -> int:
    link = WispLink()
    link.start()
    print("Dictée simulée vers Wisp : écoute 3 s (voix synthétique), transcription, résultat.")
    t0 = time.monotonic()
    link.listening(lambda: 0.5 + 0.5 * math.sin((time.monotonic() - t0) * 6) * abs(math.sin((time.monotonic() - t0) * 1.3)))
    time.sleep(3)
    link.thinking()
    time.sleep(1.2)
    link.done(42)
    time.sleep(4)
    link.error("Micro introuvable (essai)")
    time.sleep(3)
    link.idle()
    link.stop()
    if link.sent == 0:
        print("Aucun message envoyé : Wisp est-il lancé ?")
        return 1
    print(f"{link.sent} messages envoyés.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="envoyer une dictée simulée au vrai Wisp")
    args = ap.parse_args()
    if args.live:
        return live()
    print("Lien Wisp (faux pipe) :")
    for test in (test_dictation_sequence, test_wisp_closed_never_blocks_and_retries_slowly,
                 test_reconnects_after_wisp_restart, test_frozen_wisp_drops_instead_of_blocking,
                 test_setting_off_clears_then_stays_silent):
        test()
    print("Tous les tests passent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
