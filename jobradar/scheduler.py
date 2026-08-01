"""Daily scrape, run inside the web process.

Deliberately not a separate Railway cron service. Railway bills for idle RAM, so a
second always-on service would roughly double the cost of a board that spends most of
its life doing nothing. One process, one bill, one place to read logs.

Set SCRAPE_HOUR_UTC (default 03:00 UTC = 08:30 IST, so results are waiting when she
wakes up). RUN_SCHEDULER=0 disables it for local use.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone


def _db_empty() -> bool:
    import sqlite3
    path = os.getenv("DB_PATH", "")
    if not path or not os.path.exists(path):
        return True
    try:
        conn = sqlite3.connect(path)
        n = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        conn.close()
        return n == 0
    except Exception:
        return True


def _next_run(hour: int) -> datetime:
    now = datetime.now(timezone.utc)
    target = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target


def _run_once(root: str, include_paid: bool = True) -> None:
    started = datetime.now(timezone.utc)
    mode = "full" if include_paid else "free-only"
    print(f"[scheduler] {mode} scrape starting {started.isoformat(timespec='seconds')}", flush=True)
    env = dict(os.environ)
    if not include_paid:
        env["JOBRADAR_FREE_ONLY"] = "1"
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "jobradar.cli", "run"],
            cwd=root, env=env, capture_output=True, text=True, timeout=60 * 50)
        tail = (proc.stdout or "").strip().splitlines()[-6:]
        for line in tail:
            print(f"[scheduler] {line}", flush=True)
        if proc.returncode != 0:
            print(f"[scheduler] exit {proc.returncode}: {(proc.stderr or '')[-400:]}", flush=True)
    except subprocess.TimeoutExpired:
        print("[scheduler] scrape timed out after 50min", flush=True)
    except Exception as e:
        print(f"[scheduler] {type(e).__name__}: {e}", flush=True)

    # Email digest, but only if SMTP is actually configured — otherwise this is noise.
    if os.getenv("SMTP_HOST") and os.getenv("DIGEST_TO"):
        try:
            subprocess.run([sys.executable, "-m", "jobradar.cli", "digest", "--send"],
                           cwd=root, capture_output=True, text=True, timeout=300)
            print("[scheduler] digest sent", flush=True)
        except Exception as e:
            print(f"[scheduler] digest failed: {e}", flush=True)


def start(root: str) -> None:
    if os.getenv("RUN_SCHEDULER", "1") == "0":
        return
    hour = int(os.getenv("SCRAPE_HOUR_UTC", "3"))

    def loop():
        # On a cold deploy with an empty database, fill it once rather than showing
        # her an empty board until tomorrow morning. Paid sources (Apify) only join the
        # boot scrape when the DB is truly empty — a redeploy or crash-loop restart
        # re-scrapes free sources only, so restarts can never drain the Apify budget.
        if os.getenv("SCRAPE_ON_BOOT", "1") == "1":
            time.sleep(20)
            _run_once(root, include_paid=_db_empty())
        while True:
            nxt = _next_run(hour)
            sleep_for = (nxt - datetime.now(timezone.utc)).total_seconds()
            print(f"[scheduler] next scrape at {nxt.isoformat(timespec='seconds')} "
                  f"({sleep_for/3600:.1f}h)", flush=True)
            time.sleep(max(60, sleep_for))
            _run_once(root)

    threading.Thread(target=loop, name="jobradar-scheduler", daemon=True).start()
    print(f"[scheduler] daily scrape armed for {hour:02d}:00 UTC", flush=True)
