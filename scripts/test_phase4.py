"""Test de la Phase 4 : historique SQLite, statistiques, dictionnaire persistant.

Tout se passe dans une base TEMPORAIRE : votre historique réel n'est pas touché.
  A. création du schéma et dictionnaire pré-rempli (une seule fois) ;
  B. dictionnaire et corrections : ajout/suppression, rechargement dans Vocabulary ;
  C. jeu de dictées sur 20 jours -> statistiques du tableau de bord, comparées à des
     valeurs attendues recalculées indépendamment (en Python, sans SQL) ;
  D. historique : regroupement par jour, filtres période/appli, recherche sans accents ;
  E. corrections de la semaine ; suppression d'une dictée ; « Tout effacer » ;
  F. chaîne réelle : audio fr-FR -> Whisper -> règles -> enregistrement dans la base
     (option --no-audio pour sauter cette étape).
"""

import argparse
import math
import sys
import tempfile
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from dictera import stats  # noqa: E402
from dictera.app_names import display_name  # noqa: E402
from dictera.storage import Database, record_transcript  # noqa: E402
from dictera.vocabulary import DEFAULT_CORRECTIONS, DEFAULT_WORDS, Vocabulary  # noqa: E402

TYPING_WPM = 40
FILLER = ("je prépare le compte rendu de la réunion pour toute l'équipe et je relis les points "
          "importants avant de l'envoyer ce soir sans faute").split()

results: list[tuple[str, bool]] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    results.append((label, ok))
    print(f"   [{'OK' if ok else 'ÉCHEC'}] {label}{f' — {detail}' if detail else ''}")


def text_of(n: int, prefix: str = "") -> str:
    words = (prefix.split() + FILLER * 10)[:n]
    return " ".join(words)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-audio", action="store_true", help="sauter la chaîne réelle (F)")
    args = parser.parse_args()
    today = date.today()
    tmp = Path(tempfile.mkdtemp(prefix="dictera-test-"))
    path = tmp / "dictera.db"

    print(f"A) Schéma et pré-remplissage — base temporaire {path}")
    db = Database(path)
    check("mots pré-remplis (spec § 9)", db.words() == DEFAULT_WORDS, ", ".join(db.words()))
    check("correction pré-remplie ski → skill", db.corrections() == DEFAULT_CORRECTIONS)
    db.remove_word("to-do")
    db.close()
    db = Database(path)
    check("un mot supprimé n'est pas recréé au lancement suivant", "to-do" not in db.words())
    db.add_word("to-do")

    print("\nB) Dictionnaire -> amorce Whisper et corrections")
    vocab = Vocabulary()
    shared_terms = vocab.words  # même liste que celle donnée à la reformulation
    db.add_word("Dictera")
    db.add_word("  dictera ")  # doublon (casse, espaces) : ignoré
    db.set_correction("clode code", "Claude Code")
    vocab.reload(db.words(), db.corrections())
    check("doublon ignoré (sans tenir compte de la casse)", db.words().count("Dictera") == 1)
    check("nouveau mot dans l'amorce", "Dictera" in (vocab.initial_prompt() or ""), vocab.initial_prompt())
    check("liste partagée mise à jour en place", shared_terms is vocab.words and "Dictera" in shared_terms)
    fixed, applied = vocab.apply_corrections("J'utilise clode code et un ski.")
    check("corrections appliquées", fixed == "J'utilise Claude Code et un skill.", fixed)

    print("\nC) Statistiques du tableau de bord")
    # (jours avant aujourd'hui, appli, mots, maintien s, parole s, corrections)
    dataset = [
        (0, "Bloc-notes", 30, 12.0, 10.0, 1), (0, "Slack", 20, 8.0, 6.0, 0), (0, "Chrome", 10, 5.0, 4.0, 1),
        (1, "VS Code", 40, 15.0, 12.0, 2),
        (2, "Slack", 25, 10.0, 9.0, 0),
        (10, "Word", 50, 20.0, 18.0, 1),
        (20, "Chrome", 100, 40.0, 36.0, 3),
    ]
    exe_of = {"Bloc-notes": "notepad.exe", "Slack": "slack.exe", "Chrome": "chrome.exe",
              "VS Code": "code.exe", "Word": "winword.exe"}
    for i, (ago, app, n, held, speech, corr) in enumerate(dataset):
        day = today - timedelta(days=ago)
        ts = datetime(day.year, day.month, day.day, 9 + i, 15).timestamp()
        prefix = "Réunion d'équipe :" if i == 3 else ""
        db.add_dictation(raw_text=text_of(n, prefix).lower(), final_text=text_of(n, prefix), app_exe=exe_of[app],
                         app_name=app, audio_s=held, speech_s=speech, corrections=corr, ts=ts)

    # Valeurs attendues, recalculées sans SQL.
    exp_today = sum(d[2] for d in dataset if d[0] == 0)
    exp_yday = sum(d[2] for d in dataset if d[0] == 1)
    exp_total = sum(d[2] for d in dataset)
    exp_wpm = exp_total / (sum(d[4] for d in dataset) / 60)
    exp_saved = exp_total / TYPING_WPM * 60 - sum(d[3] for d in dataset)
    by_app: dict[str, int] = {}
    for d in dataset:
        by_app[d[1]] = by_app.get(d[1], 0) + d[2]
    exp_top = sorted(by_app.items(), key=lambda kv: (-kv[1], kv[0]))[:5]

    s = stats.dashboard(db, TYPING_WPM, today)
    print(f"   aujourd'hui {s.words_today} mots (hier {s.words_yesterday}, écart {s.delta_pct:+.1f} %) | "
          f"total {s.total_words} mots en {s.total_dictations} dictées | {s.avg_wpm} mots/min | "
          f"temps gagné {s.time_saved_label} | série {s.streak_days} j")
    print("   14 jours : " + " ".join(str(w) for _, w in s.daily))
    print("   où je dicte : " + ", ".join(f"{a.app_name} {a.pct} %" for a in s.top_apps))
    check("mots aujourd'hui", s.words_today == exp_today, str(exp_today))
    check("écart vs hier en %", s.delta_pct == round((exp_today - exp_yday) / exp_yday * 100, 1))
    check("total des mots et des dictées", (s.total_words, s.total_dictations) == (exp_total, len(dataset)))
    check("vitesse moyenne pondérée", math.isclose(s.avg_wpm, round(exp_wpm, 1)), f"{exp_wpm:.1f}")
    check("temps gagné vs 40 mots/min au clavier", math.isclose(s.time_saved_s, exp_saved), f"{exp_saved:.0f} s")
    check("histogramme sur 14 jours (la dictée à J-20 en est exclue)",
          len(s.daily) == 14 and sum(w for _, w in s.daily) == exp_total - 100 and s.daily[-1][1] == exp_today)
    check("série de jours d'affilée", s.streak_days == 3, "aujourd'hui, J-1, J-2 ; J-3 vide")
    check("top 5 des applis, % des mots",
          [(a.app_name, a.words) for a in s.top_apps] == exp_top
          and math.isclose(sum(a.pct for a in s.top_apps), 100.0, abs_tol=0.2))
    check("5 dernières dictées, la plus récente d'abord",
          len(s.recent) == 5 and s.recent[0].app_name == "Chrome" and s.recent[0].day == today.isoformat())

    print("\nD) Historique")
    groups = stats.history(db, "7d", today=today)
    print("   7 jours : " + " | ".join(f"{label} ({len(items)})" for label, items in groups))
    check("regroupement Aujourd'hui / Hier / date",
          [g[0] for g in groups][:2] == ["Aujourd'hui", "Hier"] and len(groups) == 3
          and groups[2][0] == stats.day_label(today - timedelta(days=2), today))
    check("filtre « aujourd'hui »", sum(len(g[1]) for g in stats.history(db, "today", today=today)) == 3)
    check("filtre par appli", sum(len(g[1]) for g in stats.history(db, "all", app="Slack", today=today)) == 2)
    found = [d for _, items in stats.history(db, "all", search="REUNION D'EQUIPE", today=today) for d in items]
    check("recherche sans casse ni accents", len(found) == 1 and found[0].final_text.startswith("Réunion"),
          "« REUNION D'EQUIPE » trouve « Réunion d'équipe »")
    check("liste des applis pour le filtre", db.apps()[0] == "Chrome" and len(db.apps()) == 5, ", ".join(db.apps()))
    check("vitesse par dictée enregistrée", math.isclose(found[0].wpm, round(40 / (12.0 / 60), 1)),
          f"{found[0].wpm} mots/min")

    print("\nE) Dictionnaire, suppression, « Tout effacer »")
    monday = today - timedelta(days=today.weekday())
    exp_week = sum(d[5] for d in dataset if today - timedelta(days=d[0]) >= monday)
    ds = stats.dictionary(db, today)
    check("carte Dictionnaire : mots et corrections de la semaine",
          ds.words == len(db.words()) and ds.corrections_this_week == exp_week,
          f"{ds.words} mots, {ds.corrections_this_week} corrections depuis lundi")
    victim = s.recent[0]
    check("suppression d'une dictée", db.delete_dictation(victim.id) and db.get_dictation(victim.id) is None)
    n = db.clear_history()
    s = stats.dashboard(db, TYPING_WPM, today)
    check("« Tout effacer » vide l'historique", n == len(dataset) - 1 and s.total_dictations == 0 and not db.apps())
    raw = path.read_bytes()
    wal = path.with_name(path.name + "-wal")
    raw += wal.read_bytes() if wal.exists() else b""
    check("texte effacé absent du fichier et du journal WAL",
          "Réunion".encode() not in raw and b"compte rendu" not in raw)
    check("le dictionnaire survit à « Tout effacer »", "Dictera" in db.words())

    if not args.no_audio:
        print("\nF) Chaîne réelle : audio -> Whisper -> règles -> historique")
        from dictera.audio import SAMPLE_RATE, Recording
        from dictera.engine import DictationEngine
        from dictera.reformulate import Reformulator
        from test_phase2 import read_wav, synthesize

        wav = tmp / "phrase.wav"
        synthesize("Euh, j'ai ajouté un nouveau ski à Claude Code pour euh gagner du temps.", wav)
        out: list = []
        done = threading.Event()
        vocab.reload(db.words(), db.corrections())
        engine = DictationEngine("large-v3-turbo", "fr", lambda t: (out.append(t), done.set()),
                                 lambda m: (out.append(m), done.set()), vocabulary=vocab,
                                 reformulator=Reformulator("rules"))
        engine.start()
        engine.wait_ready(300)
        target = type("T", (), {"exe": "notepad.exe", "exe_path": ""})()  # fenêtre cible simulée
        engine.submit(Recording(read_wav(wav), SAMPLE_RATE, 0.0, False, 0), time.perf_counter(), context=target)
        done.wait(120)
        engine.stop()
        if not out or isinstance(out[0], str):
            check("transcription", False, str(out[0]) if out else "délai dépassé")
        else:
            t = out[0]
            row = db.get_dictation(record_transcript(db, t, t.context, "pasted"))
            print(f"   brut   : {row.raw_text}")
            print(f"   final  : {row.final_text}")
            print(f"   appli « {row.app_name} » | {row.words} mots | {row.wpm} mots/min | "
                  f"{row.corrections} correction(s) | {row.reformulation} | {row.latency_ms:.0f} ms | {row.model}")
            check("dictée réelle enregistrée avec ses métadonnées",
                  row.app_name == "Bloc-notes" and row.words > 0 and row.wpm > 0 and row.corrections >= 1
                  and row.reformulation == "rules" and row.model == "large-v3-turbo")
            check("hésitations retirées par les règles", row.final_text.startswith("J'ai")
                  and "euh" not in row.final_text.lower(), row.final_text)
            check("pas d'audio dans la base (aucune colonne binaire)",
                  all(r["type"] != "BLOB" for r in db.execute("PRAGMA table_info(dictations)")))

    print(f"\n   nom lisible via les ressources de l'exécutable : python.exe -> « "
          f"{display_name('python.exe', sys.executable)} »")
    db.close()
    failed = [label for label, ok in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} vérifications OK")
    print("SUCCÈS" if not failed else "ÉCHEC : " + "; ".join(failed))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
