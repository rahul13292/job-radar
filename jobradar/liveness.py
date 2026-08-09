"""Detect jobs that are no longer open, so she stops applying to closed roles.

The board was showing dead listings for days. On 2026-08-09, 69% of what she saw had
not appeared in the most recent scrape, and a spot-check of her top rows found the
#1 result (EY Security Analyst, score 91) already closed and PhonePe SRE returning a
404. Applying to those is wasted effort and it makes the whole board feel stale.

Two mechanisms, because the sources differ in what absence means:

1. **Sweep (free, exact).** Greenhouse/Lever/Ashby/Amazon/Workday return their COMPLETE
   open-roles list every run. So a stored job from that source that is missing from a
   successful fetch has been taken down. That is a certainty, not a guess.

2. **Probe (costed, fuzzy).** LinkedIn guest search is keyword-scoped and paginated, so
   absence proves nothing — a job can be live and simply not returned. Those get an
   HTTP fetch of the posting itself, looking for the tombstone text boards use.

Both mark `gone=1` rather than deleting: an expired row still deduplicates future
scrapes, and keeping it means we never re-add and re-surface the same dead job.
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Iterable, List, Set

from .db import Store
from .models import now_iso
from .sources.base import get, SourceError

# Sources whose fetch returns the complete open list, so absence == removed.
COMPLETE_LIST_SOURCES = {"greenhouse", "lever", "ashby", "smartrecruiters",
                         "workday", "amazon", "oracle_orc", "eightfold", "remoteok"}

# Tombstone text used by the major boards when a posting is closed.
DEAD_TEXT = re.compile(
    r"no longer accepting applications|no longer available|no longer accepting|"
    r"position (?:has been )?(?:filled|closed)|this job (?:is|has been) closed|"
    r"job closed|posting (?:is )?(?:closed|expired)|applications (?:are )?closed|"
    r"we are no longer|this role (?:is|has been) (?:filled|closed)|"
    r"page not found|job not found", re.I)


def sweep_missing(store: Store, source: str, seen: Set[str]) -> int:
    """Mark stored jobs from `source` that a complete fetch didn't return.

    Only call after a fetch that actually succeeded — sweeping on a failed or
    rate-limited run would bury the entire board in one stroke.
    """
    if source not in COMPLETE_LIST_SOURCES or not seen:
        return 0
    # Never expire something she has engaged with. A saved or applied role leaving the
    # board is normal (it's often gone because they're interviewing), and her tracker
    # history must survive it.
    rows = store.conn.execute(
        "SELECT fingerprint FROM jobs WHERE source=? AND gone=0 AND status='new'",
        (source,)).fetchall()
    missing = [r["fingerprint"] for r in rows if r["fingerprint"] not in seen]
    if missing:
        ts = now_iso()
        with store.lock:
            store.conn.executemany(
                "UPDATE jobs SET gone=1, gone_reason='removed from board', checked_at=? "
                "WHERE fingerprint=?", [(ts, f) for f in missing])
            store.conn.commit()
    return len(missing)


def _probe_one(row) -> tuple:
    """(fingerprint, gone, reason). Network failure is never treated as death."""
    url = row["url"] or ""
    if not url:
        return row["fingerprint"], False, ""
    try:
        r = get(url, timeout=20, retries=1, pace=0.4)
    except SourceError:
        return row["fingerprint"], False, ""
    if r.status_code == 404 or r.status_code == 410:
        return row["fingerprint"], True, f"HTTP {r.status_code}"
    if r.status_code != 200:
        return row["fingerprint"], False, ""
    m = DEAD_TEXT.search(r.text[:80000])
    if m:
        return row["fingerprint"], True, m.group(0)[:40].lower()
    return row["fingerprint"], False, ""


def probe_surfaced(store: Store, cfg: Dict, limit: int = 60, workers: int = 8) -> tuple:
    """Check the highest-scoring live jobs she'd actually click, oldest-checked first."""
    floor = cfg.get("min_score_dashboard", 40)
    rows = store.conn.execute(
        """SELECT fingerprint, url, title, company FROM jobs
           WHERE gone=0 AND status='new' AND score >= ?
           ORDER BY COALESCE(checked_at,'') ASC, score DESC LIMIT ?""",
        (floor, limit)).fetchall()
    if not rows:
        return 0, 0

    results = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(_probe_one, rows))

    ts = now_iso()
    dead = [(ts, reason, fp) for fp, gone, reason in results if gone]
    alive = [(ts, fp) for fp, gone, _ in results if not gone]
    with store.lock:
        if dead:
            store.conn.executemany(
                "UPDATE jobs SET gone=1, gone_reason=?, checked_at=? WHERE fingerprint=?",
                [(reason, t, fp) for t, reason, fp in dead])
        if alive:
            store.conn.executemany(
                "UPDATE jobs SET checked_at=? WHERE fingerprint=?", alive)
        store.conn.commit()
    return len(rows), len(dead)
