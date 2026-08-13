from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List

from .config import load_config, load_env
from .db import Store
from .models import Job, Post, now_iso
from .resume import build_profile, load_profile
from .scoring import score_job, score_post


def _profile(cfg) -> dict:
    p = Path(cfg["profile_path"])
    if not p.exists():
        sys.exit(f"No profile at {p}. Run:  jobradar init --resume /path/to/resume.pdf")
    return load_profile(str(p))


# --------------------------------------------------------------------------- init

def cmd_init(args, cfg) -> None:
    prof = build_profile(args.resume, cfg["profile_path"])
    print(f"Profile written to {cfg['profile_path']}")
    print(f"  name         : {prof['name']}")
    print(f"  email        : {prof['email']}")
    print(f"  grad year    : {prof['grad_year']}")
    print(f"  skills ({len(prof['skills'])}) : {', '.join(prof['skills'])}")
    print("\nEdit that file by hand if anything looks off — the scorer reads it directly.")


# --------------------------------------------------------------------------- run

def cmd_run(args, cfg) -> None:
    from .liveness import expire_stale, probe_surfaced, sweep_missing
    from .sources import ats, bigco, boards, linkedin_jobs, linkedin_posts
    from .sources import apify as apify_src
    from .sources import firecrawl as firecrawl_src
    from .sources import linkedin_creators
    from .sources.base import SourceError

    prof = _profile(cfg)
    store = Store(cfg["db_path"])
    src_cfg = cfg.get("sources", {})
    only = set(args.only.split(",")) if args.only else set()

    def want(name: str) -> bool:
        if only:
            return name in only
        return bool(src_cfg.get(name, {}).get("enabled", True))

    total_new = 0

    # ---- job sources
    job_runners = [
        ("linkedin_jobs", lambda: linkedin_jobs.run(cfg)),
        ("linkedin_companies", lambda: linkedin_jobs.company_feeds(cfg)),
        ("ats", lambda: ats.run(cfg)),
        ("bigco", lambda: bigco.run(cfg)),
        ("remoteok", lambda: boards.remoteok(cfg)),
        ("apify_jobs", lambda: apify_src.run_jobs(cfg)),
        ("firecrawl", lambda: firecrawl_src.run(cfg)),
    ]
    for name, fn in job_runners:
        if not want(name):
            continue
        started = now_iso()
        print(f"[{name}] fetching…", flush=True)
        try:
            found: List[Job] = fn()
        except SourceError as e:
            print(f"[{name}] FAILED: {e}")
            store.log_run(name, started, 0, 0, str(e))
            continue
        kept = []
        for j in found:
            j.score, j.score_reasons = score_job(j, prof, cfg)
            if j.score > 0:
                kept.append(j)
        new = store.upsert_jobs(kept)
        total_new += new
        store.log_run(name, started, len(found), new)
        print(f"[{name}] {len(found)} scraped → {len(kept)} on-profile → {new} new")

        # These sources return their COMPLETE open list, so anything stored from them
        # that didn't come back has been taken down. Sweep only after a fetch that
        # actually returned rows — sweeping a failed run would bury the whole board.
        if found:
            by_source = {}
            for j in found:
                by_source.setdefault(j.source, set()).add(j.fingerprint)
            swept = sum(sweep_missing(store, s, fps) for s, fps in by_source.items())
            if swept:
                print(f"[{name}] {swept} previously-stored role(s) no longer on the board")

    # ---- post sources
    post_runners = [
        ("hn_whoishiring", lambda: boards.hackernews(cfg)),
        ("linkedin_posts", lambda: linkedin_posts.run(cfg)),
        ("linkedin_creators", lambda: linkedin_creators.run(cfg)),
        ("apify_posts", lambda: apify_src.run_posts(cfg)),
    ]
    for name, fn in post_runners:
        if not want(name):
            continue
        started = now_iso()
        print(f"[{name}] fetching…", flush=True)
        try:
            found: List[Post] = fn()
        except SourceError as e:
            print(f"[{name}] skipped: {e}")
            store.log_run(name, started, 0, 0, str(e))
            continue
        kept = []
        for p in found:
            p.score, p.score_reasons = score_post(p, prof, cfg)
            if p.score > 0:
                kept.append(p)
        new = store.upsert_posts(kept)
        total_new += new
        store.log_run(name, started, len(found), new)
        print(f"[{name}] {len(found)} scraped → {len(kept)} on-profile → {new} new")

    # JD enrichment for LinkedIn rows that scored on title alone — this is what makes
    # the experience gate real for the jobs she actually sees.
    if not only or "linkedin_jobs" in only or "linkedin_companies" in only:
        print("[enrich] fetching missing JDs for surfaced LinkedIn jobs…", flush=True)
        tried, fetched, rejected = enrich_linkedin(store, prof, cfg)
        print(f"[enrich] {tried} candidates → {fetched} JDs fetched → "
              f"{rejected} rejected as experienced-only")

    # Liveness probe for the jobs she'd actually click. LinkedIn absence proves nothing
    # (keyword-scoped, paginated), so those can only be caught by fetching the posting.
    print("[liveness] checking surfaced roles are still open…", flush=True)
    checked, dead = probe_surfaced(store, cfg)
    unseen, old = expire_stale(store, cfg)
    print(f"[liveness] {checked} probed → {dead} closed; "
          f"{unseen} stale (source stopped returning them), {old} past max age")

    c = store.counts()
    print(f"\n{total_new} new this run. Library: {c['jobs']} live roles ({c['new']} unreviewed, "
          f"{c['saved']} saved, {c['applied']} applied), {c['posts']} posts, "
          f"{c['gone']} expired and hidden.")


# --------------------------------------------------------------------------- rescore

def rescore_all(store: Store, prof: dict, cfg: dict) -> tuple:
    """Re-grade every stored row against the current profile. Shared by the CLI and
    the dashboard's CV-upload flow, so a new CV changes the recs in one pass."""
    from .sources.names import display

    rows = store.conn.execute("SELECT * FROM jobs").fetchall()
    ats_sources = {"greenhouse", "lever", "ashby", "smartrecruiters", "workday"}
    changed = 0
    for r in rows:
        # Rows stored before the display-name map kept the raw ATS slug. Company is
        # case-normalised inside the fingerprint, so relabelling cannot orphan a row.
        if r["source"] in ats_sources and r["company"] == (r["company"] or "").lower():
            store.conn.execute("UPDATE jobs SET company=? WHERE fingerprint=?",
                               (display(r["company"]), r["fingerprint"]))
        j = Job(source=r["source"], external_id=r["external_id"] or "", title=r["title"],
                company=r["company"], location=r["location"] or "", url=r["url"] or "",
                description=r["description"] or "", posted_at=r["posted_at"],
                remote=bool(r["remote"]))
        s, reasons = score_job(j, prof, cfg)
        if abs(s - (r["score"] or 0)) > 0.05:
            changed += 1
        store.conn.execute(
            "UPDATE jobs SET score=?, reasons=?, years_req=? WHERE fingerprint=?",
            (s, json.dumps(reasons), j.years_req, r["fingerprint"]))

    prows = store.conn.execute("SELECT * FROM posts").fetchall()
    for r in prows:
        p = Post(source=r["source"], external_id=r["external_id"] or "", author=r["author"] or "",
                 author_headline=r["author_headline"] or "", text=r["text"] or "",
                 url=r["url"] or "", posted_at=r["posted_at"],
                 company_guess=r["company_guess"] or "", apply_hint=r["apply_hint"] or "")
        s, reasons = score_post(p, prof, cfg)
        store.conn.execute("UPDATE posts SET score=?, reasons=? WHERE fingerprint=?",
                           (s, json.dumps(reasons), r["fingerprint"]))
    store.conn.commit()
    return len(rows), changed, len(prows)


def cmd_rescore(args, cfg) -> None:
    """Re-run scoring over everything already stored, after a config tweak."""
    prof = _profile(cfg)
    store = Store(cfg["db_path"])
    n, changed, np = rescore_all(store, prof, cfg)
    print(f"rescored {n} roles ({changed} changed) and {np} posts")


# --------------------------------------------------------------------------- enrich

def enrich_linkedin(store: Store, prof: dict, cfg: dict, cap: int = 150) -> tuple:
    """Fetch full JDs for surfaced LinkedIn jobs that were scored on title alone.

    This is the fix for 'sabmei exp rehta hai': 80% of shown LinkedIn jobs had no
    description stored, so the years gate never fired on them. Only jobs above the
    dashboard floor get fetched — enriching all 17k scraped rows would be thousands of
    rate-limited requests for jobs nobody will ever see.
    """
    from .scoring import extract_years_req
    from .sources import linkedin_jobs

    rows = store.conn.execute(
        "SELECT * FROM jobs WHERE source='linkedin_jobs' AND status='new' "
        "AND score >= ? AND LENGTH(COALESCE(description,'')) < 100 "
        "ORDER BY score DESC LIMIT ?",
        (cfg.get("min_score_dashboard", 40), cap)).fetchall()

    fetched = rejected = 0
    for r in rows:
        j = Job(source=r["source"], external_id=r["external_id"] or "", title=r["title"],
                company=r["company"], location=r["location"] or "", url=r["url"] or "",
                posted_at=r["posted_at"], remote=bool(r["remote"]))
        linkedin_jobs.fetch_detail(j)
        if len(j.description) < 100:
            # LinkedIn wouldn't give the detail (rate limit / gone). Mark it tried so
            # the next run doesn't burn its budget on the same rows.
            store.conn.execute(
                "UPDATE jobs SET description='(detail unavailable)' WHERE fingerprint=?",
                (r["fingerprint"],))
            continue
        fetched += 1
        s, reasons = score_job(j, prof, cfg)
        if s == 0:
            rejected += 1
        store.conn.execute(
            "UPDATE jobs SET description=?, score=?, reasons=?, years_req=? WHERE fingerprint=?",
            (j.description[:20000], s, json.dumps(reasons), j.years_req, r["fingerprint"]))
    store.conn.commit()
    return len(rows), fetched, rejected


def cmd_expire(args, cfg) -> None:
    """Probe stored roles and hide the ones that have closed."""
    from .liveness import probe_surfaced

    from .liveness import expire_stale

    store = Store(cfg["db_path"])
    checked, dead = probe_surfaced(store, cfg, limit=args.limit)
    unseen, old = expire_stale(store, cfg)
    c = store.counts()
    print(f"probed {checked} → {dead} closed; {unseen} stale; {old} past max age. "
          f"{c['jobs']} live, {c['gone']} expired and hidden.")


def cmd_enrich(args, cfg) -> None:
    prof = _profile(cfg)
    store = Store(cfg["db_path"])
    tried, fetched, rejected = enrich_linkedin(store, prof, cfg, cap=args.cap)
    print(f"enrich: {tried} candidates, {fetched} JDs fetched, "
          f"{rejected} turned out to need experience and were rejected")


# --------------------------------------------------------------------------- list

def cmd_list(args, cfg) -> None:
    store = Store(cfg["db_path"])
    rows = store.jobs(min_score=args.min_score, status=args.status, limit=args.limit)
    if not rows:
        print("nothing matches — try --min-score 0")
        return
    for r in rows:
        loc = r["location"] or ("Remote" if r["remote"] else "—")
        print(f"{int(r['score']):>3}  {r['title'][:58]:<58} {r['company'][:22]:<22} {loc[:26]:<26} [{r['source']}]")
        if args.verbose:
            try:
                for reason in json.loads(r["reasons"] or "[]"):
                    print(f"       · {reason}")
            except Exception:
                pass
            print(f"       {r['url']}")


def cmd_posts(args, cfg) -> None:
    store = Store(cfg["db_path"])
    rows = store.posts(min_score=args.min_score, limit=args.limit)
    for r in rows:
        print(f"{int(r['score']):>3}  {r['author'][:30]:<30} {(r['text'] or '')[:110]}")
        if args.verbose:
            print(f"       {r['url']}   apply: {r['apply_hint']}")


# --------------------------------------------------------------------------- digest

def cmd_digest(args, cfg) -> None:
    from .notify import build_digest, send_email

    store = Store(cfg["db_path"])
    floor = args.min_score if args.min_score is not None else cfg["min_score_digest"]
    text, html, jfps, pfps = build_digest(store, floor)
    if not text:
        print("nothing new above the digest floor")
        return
    print(text)
    if args.send:
        status = send_email(f"Job Radar — {len(jfps)} new roles", html, text)
        print(f"\n[{status}]")
        if status.startswith("emailed"):
            store.mark_notified("jobs", jfps)
            store.mark_notified("posts", pfps)
    elif args.mark:
        store.mark_notified("jobs", jfps)
        store.mark_notified("posts", pfps)


# --------------------------------------------------------------------------- export / web

def cmd_export(args, cfg) -> None:
    import csv
    store = Store(cfg["db_path"])
    rows = store.jobs(min_score=args.min_score, limit=5000)
    out = Path(args.out)
    with out.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["score", "title", "company", "location", "source", "posted_at", "status", "url"])
        for r in rows:
            w.writerow([r["score"], r["title"], r["company"], r["location"], r["source"],
                        r["posted_at"], r["status"], r["url"]])
    print(f"wrote {len(rows)} rows to {out}")


def cmd_web(args, cfg) -> None:
    import uvicorn
    from .scheduler import start as start_scheduler
    from .web.app import create_app

    app = create_app(cfg)
    start_scheduler(cfg["_root"])      # no-op when RUN_SCHEDULER=0
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


# --------------------------------------------------------------------------- main

def main(argv=None) -> None:
    load_env()
    ap = argparse.ArgumentParser(prog="jobradar", description="Job + hiring-post radar")
    ap.add_argument("--config", default="")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="build the match profile from a resume PDF")
    p.add_argument("--resume", required=True)
    p.set_defaults(fn=cmd_init)

    p = sub.add_parser("run", help="scrape every enabled source, score, store")
    p.add_argument("--only", default="", help="comma-separated source names")
    p.set_defaults(fn=cmd_run)

    p = sub.add_parser("rescore", help="re-score stored rows after a config change")
    p.set_defaults(fn=cmd_rescore)

    p = sub.add_parser("enrich", help="fetch missing JDs for surfaced LinkedIn jobs")
    p.add_argument("--cap", type=int, default=150)
    p.set_defaults(fn=cmd_enrich)

    p = sub.add_parser("expire", help="probe surfaced roles and hide closed ones")
    p.add_argument("--limit", type=int, default=120)
    p.set_defaults(fn=cmd_expire)

    p = sub.add_parser("list", help="top matches in the terminal")
    p.add_argument("--min-score", type=float, default=50)
    p.add_argument("--status", default="")
    p.add_argument("--limit", type=int, default=40)
    p.add_argument("-v", "--verbose", action="store_true")
    p.set_defaults(fn=cmd_list)

    p = sub.add_parser("posts", help="top hiring posts")
    p.add_argument("--min-score", type=float, default=40)
    p.add_argument("--limit", type=int, default=30)
    p.add_argument("-v", "--verbose", action="store_true")
    p.set_defaults(fn=cmd_posts)

    p = sub.add_parser("digest", help="print (and optionally email) the new-since-last digest")
    p.add_argument("--min-score", type=float, default=None)
    p.add_argument("--send", action="store_true")
    p.add_argument("--mark", action="store_true", help="mark as delivered without sending")
    p.set_defaults(fn=cmd_digest)

    p = sub.add_parser("export", help="dump matches to CSV")
    p.add_argument("--out", default="jobs.csv")
    p.add_argument("--min-score", type=float, default=40)
    p.set_defaults(fn=cmd_export)

    p = sub.add_parser("web", help="run the dashboard")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.set_defaults(fn=cmd_web)

    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    args.fn(args, cfg)


if __name__ == "__main__":
    main()
