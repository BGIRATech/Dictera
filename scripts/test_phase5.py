"""Test de la Phase 5 : les 4 pages de l'interface, sur une base et une config TEMPORAIRES.

  1. remplit une base temporaire avec des dictées réalistes sur 16 jours ;
  2. construit la vraie fenêtre (MainWindow) et capture chaque page en PNG ;
  3. exerce les actions de l'interface : recherche, filtres, ajout/suppression de mot et
     de correction (avec rechargement du vocabulaire), suppression d'une dictée,
     « Tout effacer », réglages enregistrés et appliqués.
Votre historique et votre config.json réels ne sont pas touchés.

Usage : .venv\\Scripts\\python scripts\\test_phase5.py [--out DOSSIER] [--show]
"""

import argparse
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from dictera import stats  # noqa: E402
from dictera.app import create_qt_app  # noqa: E402
from dictera.config import Config  # noqa: E402
from dictera.storage import Database  # noqa: E402
from dictera.ui.context import EngineInfo, UiContext  # noqa: E402
from dictera.ui.window import MainWindow  # noqa: E402
from dictera.vocabulary import Vocabulary  # noqa: E402

SAMPLES = [
    ("Slack", "slack.exe", "Je regarde ça dans l'après-midi et je te fais un retour avant la réunion de seize heures."),
    ("Outlook", "olk.exe", "Bonjour Claire, merci pour votre retour. Je vous propose de décaler le point "
                           "à jeudi matin, dix heures, si cela vous convient."),
    ("VS Code", "code.exe", "Ajoute un test qui vérifie que la restauration du presse-papiers ne se fait pas "
                            "si le contenu a changé entre-temps."),
    ("Claude", "claude.exe", "Écris un skill qui résume chaque matin mes to-do et les classe par priorité, "
                             "puis propose un plan pour la journée."),
    ("Chrome", "chrome.exe", "Meilleurs restaurants italiens près de la gare de Lyon ouverts le dimanche soir."),
    ("Bloc-notes", "notepad.exe", "Idées pour l'atelier : démo en direct, retour des utilisateurs, feuille de route "
                                  "du trimestre et questions ouvertes."),
    ("Word", "winword.exe", "Le projet a atteint ses objectifs principaux ce trimestre. Les délais ont été tenus "
                            "et le budget respecté, à l'exception du module de synchronisation."),
]


def fill(db: Database, today: date) -> int:
    n = 0
    plan = [0, 0, 0, 0, 1, 1, 2, 2, 2, 3, 5, 6, 6, 8, 9, 11, 13, 15]  # jours avant aujourd'hui
    for i, ago in enumerate(plan):
        app, exe, text = SAMPLES[i % len(SAMPLES)]
        day = today - timedelta(days=ago)
        ts = datetime(day.year, day.month, day.day, 8 + (i * 3) % 11, (i * 17) % 60).timestamp()
        words = len(text.split())
        speech = words / 2.6  # ≈156 mots/min
        raw = "euh " + text[0].lower() + text[1:].replace(",", " euh,", 1)
        db.add_dictation(raw_text=raw, final_text=text, app_exe=exe, app_name=app, audio_s=speech + 0.8,
                         speech_s=speech, corrections=i % 3 == 0, latency_ms=150 + i * 3,
                         model="large-v3-turbo", reformulation="rules", insertion="pasted", ts=ts)
        n += 1
    return n


results: list[tuple[str, bool]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok))
    print(f"   [{'OK' if ok else 'ÉCHEC'}] {name}{f' — {detail}' if detail else ''}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, help="dossier des captures (défaut : dossier temporaire)")
    parser.add_argument("--show", action="store_true", help="laisser la fenêtre ouverte à la fin")
    args = parser.parse_args()
    tmp = Path(tempfile.mkdtemp(prefix="dictera-ui-"))
    out = args.out or tmp
    out.mkdir(parents=True, exist_ok=True)

    qt = create_qt_app()
    db = Database(tmp / "dictera.db")
    n = fill(db, date.today())
    cfg = Config(first_name="Alex")
    cfg.save = lambda path=None: Config.save(cfg, tmp / "config.json")  # jamais la vraie config
    vocab = Vocabulary()
    vocab.reload(db.words(), db.corrections())
    applied: list[str] = []
    ctx = UiContext(db, cfg, vocab,
                    engine_info=lambda: EngineInfo("large-v3-turbo", "CUDA · RTX 4070 Ti", "",
                                                   "Ollama absent → repli : règles"),
                    on_setting_changed=applied.append,
                    on_vocabulary_changed=lambda: vocab.reload(db.words(), db.corrections()))
    win = MainWindow(ctx)
    win.set_status("Moteur prêt · large-v3-turbo\nCtrl droit pour dicter")
    win.resize(1240, 900)
    win.show()
    QTest.qWait(300)
    print(f"1) Base temporaire : {n} dictées sur 16 jours — {tmp}")
    check("Tableau de bord affiché au lancement", win.stack.currentIndex() == 0
          and win.sidebar.buttons[0].isChecked())

    print("\n2) Captures des 4 pages (fenêtre telle qu'affichée + page entière)")
    names = ["1-tableau-de-bord", "2-historique", "3-dictionnaire", "4-reglages"]
    for i, name in enumerate(names):
        win.sidebar.buttons[i].click()
        QTest.qWait(250)
        win.grab().save(str(out / f"{name}.png"))
        win.pages[i].widget().grab().save(str(out / f"{name}-page-entiere.png"))
        print(f"   {out / name}.png (+ -page-entiere.png)")

    print("\n3) Actions de l'interface")
    dash = win.pages[0]
    win.show_page(0)
    s = stats.dashboard(db, cfg.typing_wpm)
    check("cartes = statistiques de la base", dash.c_today.value.text().replace(" ", "") == str(s.words_today)
          and dash.c_total.sub.text().startswith(str(s.total_dictations)),
          f"aujourd'hui {dash.c_today.value.text()} mots, {dash.c_total.sub.text()}")
    check("5 dernières dictées listées", dash.recent.count() == 5)
    check("histogramme sur 14 jours", len(dash.bars.data) == 14 and dash.bars.data[-1][1] == s.words_today)

    hist = win.pages[1]
    win.show_page(1)
    QTest.keyClicks(hist.search, "reunion")
    QTest.qWait(400)
    found = sum(hist.results.itemAt(i).widget().body.count() - 1 for i in range(hist.results.count())
                if hasattr(hist.results.itemAt(i).widget(), "body"))
    check("recherche sans accents (« reunion »)", found == len(db.query_dictations(search="réunion")) > 0,
          f"{found} dictée(s)")
    hist.search.clear()
    hist.period.button(0).click()
    QTest.qWait(50)
    today_groups = stats.history(db, "today")
    check("filtre « Aujourd'hui »", hist.results.count() == 1 and len(today_groups) == 1)
    hist.period.button(2).click()
    hist.app_filter.setCurrentIndex(hist.app_filter.findData("Slack"))
    QTest.qWait(50)
    check("filtre par appli", all(d.app_name == "Slack" for _, items in stats.history(db, "all", app="Slack")
                                  for d in items) and hist.app_filter.currentData() == "Slack")
    hist.app_filter.setCurrentIndex(0)
    first = db.query_dictations(limit=1)[0]
    hist.delete(first.id)
    check("supprimer une dictée", db.get_dictation(first.id) is None and dash is not None)

    dico = win.pages[2]
    win.show_page(2)
    dico.word_input.setText("Dictera")
    dico.add_word()
    check("ajout d'un mot -> base et amorce Whisper", "Dictera" in db.words()
          and "Dictera" in (vocab.initial_prompt() or ""))
    dico.heard.setText("clode code")
    dico.written.setText("Claude Code")
    dico.add_correction()
    check("ajout d'une correction -> appliquée", vocab.apply_corrections("j'ouvre clode code")[0] == "j'ouvre Claude Code")
    dico.remove_word("Dictera")
    check("retrait d'un mot", "Dictera" not in db.words() and "Dictera" not in (vocab.initial_prompt() or ""))

    sett = win.pages[3]
    win.show_page(3)
    sett.wpm.setValue(55)
    sett.sounds.click()
    saved = Config.load(tmp / "config.json")
    check("réglages enregistrés et transmis à l'appli", saved.typing_wpm == 55
          and saved.sounds_enabled is False and {"typing_wpm", "sounds_enabled"} <= set(applied))
    check("badges Moteur & vie privée", "large-v3-turbo" in sett.b_asr.text() and "règles" in sett.b_reform.text())

    sett.llm_url.setText("http://192.168.1.20:1234/v1/chat/completions")
    sett._url_edited()
    check("URL de LLM non locale refusée", cfg.llm_url.startswith("http://localhost") and "refusée" in
          sett.llm_state.text())
    model = cfg.llm_model
    sett.llm_url.setText("http://127.0.0.1:9/v1/chat/completions")  # port fermé : serveur hors ligne
    sett._url_edited()
    for _ in range(50):
        QTest.qWait(100)
        if "hors ligne" in sett.llm_state.text():
            break
    check("LM Studio hors ligne : message, modèle actuel gardé, sans planter",
          "hors ligne" in sett.llm_state.text() and sett.llm_model.currentData() == model == cfg.llm_model,
          sett.llm_state.text())
    sett.llm_on.setChecked(True)
    on = cfg.reformulation
    sett.llm_on.setChecked(False)
    check("interrupteur LLM : auto <-> règles, champs LLM grisés", on == "auto" and cfg.reformulation == "rules"
          and not sett.llm_model.isEnabled())
    sett.llm_timeout.setValue(5.0)
    sett._set_number("llm_timeout_s", sett.llm_timeout)
    sett.lang.setCurrentIndex(sett.lang.findData("en"))
    saved = Config.load(tmp / "config.json")
    check("délai LLM et langue enregistrés", saved.llm_timeout_s == 5.0 and saved.language == "en"
          and {"llm_timeout_s", "language", "llm_url"} <= set(applied))

    win.show_page(1)
    hist.clear_all()
    check("« Tout effacer »", stats.dashboard(db, 40).total_dictations == 0 and hist.results.count() == 1)

    failed = [name for name, ok in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} vérifications OK")
    print("SUCCÈS" if not failed else "ÉCHEC : " + "; ".join(failed))
    if args.show:
        fill(db, date.today())
        win.show_page(0)
        qt.exec()
    win.quitting = True
    win.close()
    db.close()
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
