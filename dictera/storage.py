"""Base SQLite locale : historique des dictées, dictionnaire personnel, corrections.

Fichier : %LOCALAPPDATA%\\Dictera\\dictera.db. Jamais d'audio (spec § 8) ; pas non plus
le titre des fenêtres (il peut contenir un sujet de mail, un nom de fichier…) : une
dictée est étiquetée par l'appli seulement.

Une connexion partagée protégée par un verrou : le thread du moteur écrit, l'interface
(Phase 5) lit. Mode WAL pour que les lectures ne bloquent pas les écritures.
"""

import logging
import os
import sqlite3
import threading
import time
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from .vocabulary import DEFAULT_CORRECTIONS, DEFAULT_WORDS

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1
_SCHEMA = """
CREATE TABLE dictations (
    id            INTEGER PRIMARY KEY,
    ts            REAL    NOT NULL,          -- horodatage Unix (s)
    day           TEXT    NOT NULL,          -- date locale AAAA-MM-JJ, pour les regroupements
    raw_text      TEXT    NOT NULL,          -- sortie brute de Whisper
    final_text    TEXT    NOT NULL,          -- après corrections et reformulation
    app_exe       TEXT    NOT NULL DEFAULT '',
    app_name      TEXT    NOT NULL DEFAULT '',
    words         INTEGER NOT NULL,
    audio_s       REAL    NOT NULL,          -- durée de maintien de la touche
    speech_s      REAL    NOT NULL,          -- parole après rognage des silences
    wpm           REAL    NOT NULL,          -- mots par minute de parole
    corrections   INTEGER NOT NULL DEFAULT 0,-- corrections automatiques appliquées
    latency_ms    REAL    NOT NULL DEFAULT 0,
    model         TEXT    NOT NULL DEFAULT '',
    reformulation TEXT    NOT NULL DEFAULT 'off',
    insertion     TEXT    NOT NULL DEFAULT ''-- pasted | clipboard_only | skipped
);
CREATE INDEX dictations_day ON dictations(day);
CREATE INDEX dictations_ts ON dictations(ts);
CREATE TABLE dictionary_words (
    id         INTEGER PRIMARY KEY,
    word       TEXT NOT NULL UNIQUE COLLATE NOCASE,
    created_at REAL NOT NULL
);
CREATE TABLE corrections (
    id         INTEGER PRIMARY KEY,
    heard      TEXT NOT NULL UNIQUE COLLATE NOCASE,
    written    TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def db_path() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Dictera" / "dictera.db"


def fold(text: str | None) -> str:
    """Forme de comparaison : minuscules et sans accents (« Été » == « ete »)."""
    if not text:
        return ""
    nfkd = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def count_words(text: str) -> int:
    return len(text.split())


@dataclass(frozen=True)
class Dictation:
    id: int
    ts: float
    day: str
    raw_text: str
    final_text: str
    app_exe: str
    app_name: str
    words: int
    audio_s: float
    speech_s: float
    wpm: float
    corrections: int
    latency_ms: float
    model: str
    reformulation: str
    insertion: str

    @property
    def time_hhmm(self) -> str:
        return datetime.fromtimestamp(self.ts).strftime("%H:%M")


class Database:
    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path else db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.create_function("fold", 1, fold, deterministic=True)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        # Une dictée supprimée est écrasée par des zéros, pas seulement marquée libre.
        self._conn.execute("PRAGMA secure_delete=ON")
        self._migrate()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # -- schéma -------------------------------------------------------------------------

    def _migrate(self) -> None:
        with self._lock:
            version = self._conn.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                raise RuntimeError(f"Base créée par une version plus récente de Dictera ({version})")
            if version == 0:
                # executescript valide d'office toute transaction ouverte : il porte la sienne.
                self._conn.executescript(f"BEGIN;{_SCHEMA}PRAGMA user_version={SCHEMA_VERSION};COMMIT;")
                log.info("Base créée : %s", self.path)
            self._prefill()

    def _prefill(self) -> None:
        """Dictionnaire pré-rempli (spec § 9), une seule fois : une suppression par
        l'utilisateur ne doit pas être annulée au lancement suivant."""
        if self._meta("prefilled"):
            return
        with self._tx():
            now = time.time()
            self._conn.executemany("INSERT OR IGNORE INTO dictionary_words(word, created_at) VALUES (?, ?)",
                                   [(w, now) for w in DEFAULT_WORDS])
            self._conn.executemany("INSERT OR IGNORE INTO corrections(heard, written, created_at) VALUES (?, ?, ?)",
                                   [(h, w, now) for h, w in DEFAULT_CORRECTIONS.items()])
            self._conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('prefilled', '1')")

    def _meta(self, key: str) -> str | None:
        row = self._conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def _tx(self):
        return _Transaction(self._conn)

    # -- dictées ------------------------------------------------------------------------

    def add_dictation(self, *, raw_text: str, final_text: str, app_exe: str = "", app_name: str = "",
                      audio_s: float, speech_s: float, corrections: int = 0, latency_ms: float = 0.0,
                      model: str = "", reformulation: str = "off", insertion: str = "",
                      ts: float | None = None) -> int:
        ts = time.time() if ts is None else ts
        words = count_words(final_text)
        minutes = (speech_s or audio_s) / 60
        wpm = words / minutes if minutes > 0 else 0.0
        with self._lock, self._tx():
            cur = self._conn.execute(
                "INSERT INTO dictations(ts, day, raw_text, final_text, app_exe, app_name, words, audio_s,"
                " speech_s, wpm, corrections, latency_ms, model, reformulation, insertion)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (ts, _day(ts), raw_text, final_text, app_exe, app_name, words, audio_s, speech_s,
                 round(wpm, 1), corrections, latency_ms, model, reformulation, insertion),
            )
            return cur.lastrowid

    def get_dictation(self, dictation_id: int) -> Dictation | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM dictations WHERE id = ?", (dictation_id,)).fetchone()
        return Dictation(**row) if row else None

    def delete_dictation(self, dictation_id: int) -> bool:
        with self._lock, self._tx():
            return self._conn.execute("DELETE FROM dictations WHERE id = ?", (dictation_id,)).rowcount > 0

    def clear_history(self) -> int:
        """« Tout effacer » : supprime les dictées, puis compacte le fichier pour que le
        texte effacé ne subsiste pas dans les pages libres de la base."""
        with self._lock:
            with self._tx():
                n = self._conn.execute("DELETE FROM dictations").rowcount
            self._conn.execute("VACUUM")  # en mode WAL, le résultat passe d'abord par le journal…
            self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")  # … qu'on reporte puis vide
        log.info("Historique effacé (%d dictées)", n)
        return n

    def query_dictations(self, *, since_day: str | None = None, app: str | None = None,
                         search: str | None = None, limit: int | None = None) -> list[Dictation]:
        """Dictées les plus récentes d'abord. `app` filtre sur app_name ; `search` cherche
        dans le texte final et le texte brut, sans tenir compte de la casse ni des accents."""
        sql, args = "SELECT * FROM dictations WHERE 1=1", []
        if since_day:
            sql += " AND day >= ?"
            args.append(since_day)
        if app:
            sql += " AND app_name = ?"
            args.append(app)
        if search and search.strip():
            pattern = "%" + fold(search.strip()).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            sql += r" AND (fold(final_text) LIKE ? ESCAPE '\' OR fold(raw_text) LIKE ? ESCAPE '\')"
            args += [pattern, pattern]
        sql += " ORDER BY ts DESC, id DESC"
        if limit:
            sql += " LIMIT ?"
            args.append(limit)
        with self._lock:
            return [Dictation(**r) for r in self._conn.execute(sql, args)]

    def apps(self) -> list[str]:
        """Applis présentes dans l'historique (filtre « par appli »), les plus utilisées d'abord."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT app_name FROM dictations WHERE app_name != '' GROUP BY app_name ORDER BY SUM(words) DESC"
            ).fetchall()
        return [r[0] for r in rows]

    def execute(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        """Lecture brute pour les statistiques (stats.py)."""
        with self._lock:
            return self._conn.execute(sql, args).fetchall()

    # -- dictionnaire et corrections ----------------------------------------------------

    def words(self) -> list[str]:
        with self._lock:
            return [r[0] for r in self._conn.execute("SELECT word FROM dictionary_words ORDER BY created_at, id")]

    def add_word(self, word: str) -> bool:
        word = " ".join(word.split())
        if not word:
            return False
        with self._lock, self._tx():
            return self._conn.execute("INSERT OR IGNORE INTO dictionary_words(word, created_at) VALUES (?, ?)",
                                      (word, time.time())).rowcount > 0

    def remove_word(self, word: str) -> bool:
        with self._lock, self._tx():
            return self._conn.execute("DELETE FROM dictionary_words WHERE word = ?", (word,)).rowcount > 0

    def corrections(self) -> dict[str, str]:
        with self._lock:
            rows = self._conn.execute("SELECT heard, written FROM corrections ORDER BY created_at, id")
            return {r[0]: r[1] for r in rows}

    def set_correction(self, heard: str, written: str) -> None:
        heard, written = " ".join(heard.split()), written.strip()
        if not heard or not written:
            raise ValueError("« entendu » et « à écrire » sont tous deux requis")
        with self._lock, self._tx():
            self._conn.execute(
                "INSERT INTO corrections(heard, written, created_at) VALUES (?, ?, ?)"
                " ON CONFLICT(heard) DO UPDATE SET written = excluded.written",
                (heard, written, time.time()),
            )

    def remove_correction(self, heard: str) -> bool:
        with self._lock, self._tx():
            return self._conn.execute("DELETE FROM corrections WHERE heard = ?", (heard,)).rowcount > 0


def record_transcript(db: Database, transcript, target=None, insertion: str = "") -> int:
    """Enregistre une dictée terminée (Transcript de la Phase 2/3, Target de la Phase 3)."""
    from .app_names import display_name, site_name

    exe = getattr(target, "exe", "") or ""
    return db.add_dictation(
        raw_text=transcript.raw_text,
        final_text=transcript.final_text or transcript.text,
        app_exe=exe,
        app_name=site_name(exe, getattr(target, "title", "") or "")
        or display_name(exe, getattr(target, "exe_path", "") or ""),
        audio_s=transcript.audio_s,
        speech_s=transcript.speech_s,
        corrections=len(transcript.corrections),
        latency_ms=transcript.latency_ms,
        model=transcript.model,
        reformulation=transcript.reformulation,
        insertion=insertion,
    )


class _Transaction:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def __enter__(self):
        self.conn.execute("BEGIN")

    def __exit__(self, exc_type, *_):
        self.conn.execute("ROLLBACK" if exc_type else "COMMIT")


def _day(ts: float) -> str:
    return date.fromtimestamp(ts).isoformat()
