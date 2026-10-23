"""Statistiques du tableau de bord et regroupement de l'historique (spec § 4 et § 5).

Calculées à la demande depuis SQLite : rien n'est mis en cache, les chiffres sont
donc toujours cohérents avec l'historique (y compris après un « Tout effacer »).

Définitions :
  vitesse moyenne = total des mots / total des minutes de parole (moyenne pondérée,
                    une dictée de 3 mots ne pèse pas autant qu'une de 300) ;
  temps gagné     = temps qu'il aurait fallu pour taper ces mots à la vitesse clavier
                    déclarée, moins le temps passé à dicter (touche maintenue) ;
  série           = jours consécutifs avec au moins une dictée, jusqu'à aujourd'hui
                    (ou hier : la série n'est pas perdue tant que la journée n'est pas finie).
"""

from dataclasses import dataclass, field
from datetime import date, timedelta

from .storage import Database, Dictation

_WEEKDAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
_MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
           "septembre", "octobre", "novembre", "décembre"]
PERIODS = ("today", "7d", "all")


@dataclass
class AppShare:
    app_name: str
    words: int
    pct: float


@dataclass
class DashboardStats:
    words_today: int = 0
    words_yesterday: int = 0
    delta_pct: float | None = None  # None si hier = 0 (écart non défini)
    total_words: int = 0
    total_dictations: int = 0
    avg_wpm: float = 0.0
    time_saved_s: float = 0.0
    daily: list[tuple[str, int]] = field(default_factory=list)  # 14 jours, du plus ancien à aujourd'hui
    streak_days: int = 0
    top_apps: list[AppShare] = field(default_factory=list)
    recent: list[Dictation] = field(default_factory=list)

    @property
    def time_saved_label(self) -> str:
        minutes = int(self.time_saved_s // 60)
        return f"{minutes // 60} h {minutes % 60:02d} min" if minutes >= 60 else f"{minutes} min"


@dataclass
class DictionaryStats:
    words: int
    corrections_this_week: int  # corrections automatiques appliquées depuis lundi


def dashboard(db: Database, typing_wpm: float, today: date | None = None, days: int = 14) -> DashboardStats:
    today = today or date.today()
    s = DashboardStats()
    per_day = {r["day"]: r["w"] for r in db.execute(
        "SELECT day, SUM(words) AS w FROM dictations WHERE day >= ? GROUP BY day",
        ((today - timedelta(days=days - 1)).isoformat(),))}
    s.daily = [((today - timedelta(days=i)).isoformat(), per_day.get((today - timedelta(days=i)).isoformat(), 0))
               for i in range(days - 1, -1, -1)]
    s.words_today = per_day.get(today.isoformat(), 0)
    s.words_yesterday = per_day.get((today - timedelta(days=1)).isoformat(), 0)
    if s.words_yesterday:
        s.delta_pct = round((s.words_today - s.words_yesterday) / s.words_yesterday * 100, 1)

    row = db.execute("SELECT COUNT(*) AS n, COALESCE(SUM(words), 0) AS w,"
                     " COALESCE(SUM(CASE WHEN speech_s > 0 THEN speech_s ELSE audio_s END), 0) AS speech,"
                     " COALESCE(SUM(audio_s), 0) AS held FROM dictations")[0]
    s.total_dictations, s.total_words = row["n"], row["w"]
    s.avg_wpm = round(row["w"] / (row["speech"] / 60), 1) if row["speech"] > 0 else 0.0
    if typing_wpm > 0:
        s.time_saved_s = max(0.0, row["w"] / typing_wpm * 60 - row["held"])

    s.streak_days = _streak(db, today)
    rows = db.execute("SELECT app_name, SUM(words) AS w FROM dictations WHERE app_name != ''"
                      " GROUP BY app_name ORDER BY w DESC, app_name LIMIT 5")
    s.top_apps = [AppShare(r["app_name"], r["w"], round(r["w"] / s.total_words * 100, 1) if s.total_words else 0.0)
                  for r in rows]
    s.recent = db.query_dictations(limit=5)
    return s


def _streak(db: Database, today: date) -> int:
    days = {date.fromisoformat(r["day"]) for r in db.execute(
        "SELECT DISTINCT day FROM dictations WHERE day <= ?", (today.isoformat(),))}
    cursor = today if today in days else today - timedelta(days=1)
    n = 0
    while cursor in days:
        n += 1
        cursor -= timedelta(days=1)
    return n


def dictionary(db: Database, today: date | None = None) -> DictionaryStats:
    today = today or date.today()
    monday = today - timedelta(days=today.weekday())
    row = db.execute("SELECT COALESCE(SUM(corrections), 0) AS c FROM dictations WHERE day >= ?",
                     (monday.isoformat(),))[0]
    return DictionaryStats(words=len(db.words()), corrections_this_week=row["c"])


def history(db: Database, period: str = "all", app: str | None = None, search: str | None = None,
            today: date | None = None) -> list[tuple[str, list[Dictation]]]:
    """Dictées filtrées, regroupées par jour : [(« Aujourd'hui », [...]), (« Hier », [...]),
    (« lundi 20 octobre 2026 », [...]), …], du plus récent au plus ancien."""
    today = today or date.today()
    if period not in PERIODS:
        raise ValueError(f"période inconnue : {period}")
    since = {"today": today, "7d": today - timedelta(days=6), "all": None}[period]
    groups: list[tuple[str, list[Dictation]]] = []
    for d in db.query_dictations(since_day=since.isoformat() if since else None, app=app, search=search):
        label = day_label(date.fromisoformat(d.day), today)
        if not groups or groups[-1][0] != label:
            groups.append((label, []))
        groups[-1][1].append(d)
    return groups


def day_label(day: date, today: date | None = None) -> str:
    today = today or date.today()
    if day == today:
        return "Aujourd'hui"
    if day == today - timedelta(days=1):
        return "Hier"
    label = f"{_WEEKDAYS[day.weekday()]} {day.day} {_MONTHS[day.month - 1]}"
    return label if day.year == today.year else f"{label} {day.year}"
