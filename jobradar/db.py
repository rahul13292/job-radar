"""SQLite store. Dedupes on fingerprint so a role seen on three boards is one row."""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Iterable, List, Optional

from .models import Job, Post, now_iso

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    fingerprint TEXT PRIMARY KEY,
    source      TEXT NOT NULL,
    external_id TEXT,
    title       TEXT NOT NULL,
    company     TEXT NOT NULL,
    location    TEXT,
    url         TEXT,
    description TEXT,
    posted_at   TEXT,
    remote      INTEGER DEFAULT 0,
    score       REAL DEFAULT 0,
    reasons     TEXT,
    first_seen  TEXT NOT NULL,
    last_seen   TEXT NOT NULL,
    status      TEXT DEFAULT 'new',      -- new | saved | applied | dismissed
    notes       TEXT DEFAULT '',
    notified    INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_jobs_score ON jobs(score DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_seen  ON jobs(first_seen DESC);

CREATE TABLE IF NOT EXISTS posts (
    fingerprint     TEXT PRIMARY KEY,
    source          TEXT NOT NULL,
    external_id     TEXT,
    author          TEXT,
    author_headline TEXT,
    text            TEXT,
    url             TEXT,
    posted_at       TEXT,
    company_guess   TEXT,
    apply_hint      TEXT,
    score           REAL DEFAULT 0,
    reasons         TEXT,
    first_seen      TEXT NOT NULL,
    last_seen       TEXT NOT NULL,
    status          TEXT DEFAULT 'new',
    notes           TEXT DEFAULT '',
    notified        INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_posts_seen ON posts(first_seen DESC);

CREATE TABLE IF NOT EXISTS runs (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    started   TEXT,
    finished  TEXT,
    source    TEXT,
    found     INTEGER,
    new       INTEGER,
    error     TEXT
);
"""


class Store:
    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: the dashboard serves sync endpoints from a thread
        # pool, so the connection is touched by more than one thread. WAL + a write
        # lock keeps that safe, and lets a background `run` write while the UI reads.
        self.conn = sqlite3.connect(self.path, check_same_thread=False, timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=15000")
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.commit()

    def _migrate(self) -> None:
        """Additive column adds, safe to run on every open."""
        for table, col, decl in (
            ("jobs", "status_at", "TEXT"),      # when she marked it applied/saved
            ("posts", "status_at", "TEXT"),
            ("jobs", "years_req", "INTEGER"),   # stated experience bar; NULL = unstated
            ("jobs", "gone", "INTEGER DEFAULT 0"),   # role taken down / closed
            ("jobs", "gone_reason", "TEXT"),
            ("jobs", "checked_at", "TEXT"),          # last liveness probe
        ):
            cols = {r["name"] for r in self.conn.execute(f"PRAGMA table_info({table})")}
            if col not in cols:
                self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")

    # ---------- writes ----------

    def upsert_jobs(self, jobs: Iterable[Job]) -> int:
        """Returns count of genuinely new rows."""
        new = 0
        ts = now_iso()
        with self.lock:
            for j in jobs:
                cur = self.conn.execute(
                    "SELECT fingerprint FROM jobs WHERE fingerprint=?", (j.fingerprint,))
                if cur.fetchone():
                    # Seeing it again means it's open again: clear any expiry so a role
                    # that was briefly pulled and reposted comes back to the board.
                    self.conn.execute(
                        "UPDATE jobs SET last_seen=?, score=?, reasons=?, years_req=?, "
                        "gone=0, gone_reason=NULL WHERE fingerprint=?",
                        (ts, j.score, json.dumps(j.score_reasons), j.years_req, j.fingerprint),
                    )
                    continue
                self.conn.execute(
                    """INSERT INTO jobs (fingerprint, source, external_id, title, company, location,
                                         url, description, posted_at, remote, years_req, score,
                                         reasons, first_seen, last_seen)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (j.fingerprint, j.source, j.external_id, j.title, j.company, j.location, j.url,
                     j.description[:20000], j.posted_at, int(j.remote), j.years_req, j.score,
                     json.dumps(j.score_reasons), ts, ts),
                )
                new += 1
            self.conn.commit()
        return new

    def upsert_posts(self, posts: Iterable[Post]) -> int:
        new = 0
        ts = now_iso()
        with self.lock:
            for p in posts:
                cur = self.conn.execute(
                    "SELECT fingerprint FROM posts WHERE fingerprint=?", (p.fingerprint,))
                if cur.fetchone():
                    self.conn.execute(
                        "UPDATE posts SET last_seen=? WHERE fingerprint=?", (ts, p.fingerprint))
                    continue
                self.conn.execute(
                    """INSERT INTO posts (fingerprint, source, external_id, author, author_headline,
                                          text, url, posted_at, company_guess, apply_hint, score,
                                          reasons, first_seen, last_seen)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (p.fingerprint, p.source, p.external_id, p.author, p.author_headline,
                     p.text[:8000], p.url, p.posted_at, p.company_guess, p.apply_hint, p.score,
                     json.dumps(p.score_reasons), ts, ts),
                )
                new += 1
            self.conn.commit()
        return new

    def log_run(self, source: str, started: str, found: int, new: int, error: str = "") -> None:
        with self.lock:
            self.conn.execute(
                "INSERT INTO runs (started, finished, source, found, new, error) VALUES (?,?,?,?,?,?)",
                (started, now_iso(), source, found, new, error),
            )
            self.conn.commit()

    def set_status(self, table: str, fingerprint: str, status: str, note: str = "") -> None:
        assert table in ("jobs", "posts")
        with self.lock:
            if note:
                self.conn.execute(
                    f"UPDATE {table} SET status=?, status_at=?, notes=? WHERE fingerprint=?",
                    (status, now_iso(), note, fingerprint))
            else:
                self.conn.execute(
                    f"UPDATE {table} SET status=?, status_at=? WHERE fingerprint=?",
                    (status, now_iso(), fingerprint))
            self.conn.commit()

    def set_note(self, table: str, fingerprint: str, note: str) -> None:
        assert table in ("jobs", "posts")
        with self.lock:
            self.conn.execute(f"UPDATE {table} SET notes=? WHERE fingerprint=?",
                              (note, fingerprint))
            self.conn.commit()

    def mark_notified(self, table: str, fingerprints: List[str]) -> None:
        assert table in ("jobs", "posts")
        with self.lock:
            self.conn.executemany(
                f"UPDATE {table} SET notified=1 WHERE fingerprint=?", [(f,) for f in fingerprints]
            )
            self.conn.commit()

    # ---------- reads ----------

    def jobs(self, min_score: float = 0, status: str = "", limit: int = 200,
             since: str = "", source: str = "", max_exp: Optional[int] = None,
             include_gone: bool = False) -> List[sqlite3.Row]:
        # Closed roles are hidden by default. They stay in the table so a later scrape
        # dedupes against them instead of resurfacing the same dead listing.
        q = "SELECT * FROM jobs WHERE score >= ?" + ("" if include_gone else " AND gone=0")
        args: list = [min_score]
        if status:
            q += " AND status = ?"
            args.append(status)
        if since:
            q += " AND first_seen >= ?"
            args.append(since)
        if source:
            q += " AND source = ?"
            args.append(source)
        if max_exp is not None:
            # NULL (unstated) stays visible but is labeled in the UI — a JD that names
            # no bar is usually open to freshers, and hiding those would empty the board.
            q += " AND (years_req IS NULL OR years_req <= ?)"
            args.append(max_exp)
        q += " ORDER BY score DESC, first_seen DESC LIMIT ?"
        args.append(limit)
        return self.conn.execute(q, args).fetchall()

    def posts(self, min_score: float = 0, status: str = "", limit: int = 200) -> List[sqlite3.Row]:
        q = "SELECT * FROM posts WHERE score >= ?"
        args: list = [min_score]
        if status:
            q += " AND status = ?"
            args.append(status)
        q += " ORDER BY score DESC, first_seen DESC LIMIT ?"
        args.append(limit)
        return self.conn.execute(q, args).fetchall()

    def undelivered(self, table: str, min_score: float) -> List[sqlite3.Row]:
        assert table in ("jobs", "posts")
        return self.conn.execute(
            f"SELECT * FROM {table} WHERE notified=0 AND status='new' AND score >= ? "
            f"ORDER BY score DESC LIMIT 60", (min_score,)
        ).fetchall()

    def counts(self) -> dict:
        # Live board excludes expired rows; saved/applied are counted regardless, since
        # those are her records and shouldn't shrink when a posting comes down.
        c = self.conn.execute(
            "SELECT SUM(gone=0) n, SUM(status='new' AND gone=0) new, "
            "SUM(status='saved') saved, SUM(status='applied') applied FROM jobs").fetchone()
        g = self.conn.execute(
            "SELECT COUNT(*) n FROM jobs WHERE gone=1 AND status='new'").fetchone()
        p = self.conn.execute("SELECT COUNT(*) n FROM posts").fetchone()
        return {"jobs": c["n"] or 0, "new": c["new"] or 0, "saved": c["saved"] or 0,
                "applied": c["applied"] or 0, "posts": p["n"] or 0, "gone": g["n"] or 0}

    def last_runs(self, limit: int = 20) -> List[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
