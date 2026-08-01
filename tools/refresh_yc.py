"""Discover YC companies that are hiring and have a scrapable job board.

Diya is ex-YC-adjacent by way of the YC Startup School selection on her resume, and
wants YC startups specifically. YC's public API lists ~6,000 companies with an
`isHiring` badge, but no jobs — Work at a Startup requires a login (406 to any client).

So: take the hiring YC companies, resolve each one's ATS board by slug, keep the ones
that answer. That resolution is slow (thousands of probes), which is exactly why it
lives in a tool run weekly rather than in the daily scrape. It appends verified boards
to a file the normal ATS source reads.

    ./.venv/bin/python tools/refresh_yc.py --batches F26,S26,W26,S25,W25 --out data/yc_boards.yaml
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import re
import sys
import time
from pathlib import Path

import requests
import yaml

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
H = {"User-Agent": UA}
API = "https://api.ycombinator.com/v0.1/companies"


def fetch_companies(max_pages: int) -> list:
    out, page = [], 1
    while page <= max_pages:
        try:
            r = requests.get(API, params={"page": page}, headers=H, timeout=30)
            if r.status_code != 200:
                break
            d = r.json()
            out.extend(d.get("companies", []))
            if not d.get("nextPage"):
                break
            page += 1
        except Exception as e:
            print(f"  page {page} failed: {e}", file=sys.stderr)
            break
        time.sleep(0.25)
    return out


def slug_variants(c: dict) -> list:
    """A YC slug is not always the ATS slug — try the obvious rewrites."""
    slug = (c.get("slug") or "").strip()
    name = re.sub(r"[^a-z0-9]", "", (c.get("name") or "").lower())
    cands = [slug, slug.replace("-", ""), name]
    site = c.get("website") or ""
    m = re.search(r"https?://(?:www\.)?([a-z0-9-]+)\.", site)
    if m:
        cands.append(m.group(1))
    seen, out = set(), []
    for s in cands:
        if s and s not in seen and len(s) > 2:
            seen.add(s)
            out.append(s)
    return out[:4]


def probe(company: dict):
    for slug in slug_variants(company):
        for kind, url, count in (
            ("greenhouse", f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
             lambda j: len(j.get("jobs", []))),
            ("ashby", f"https://api.ashbyhq.com/posting-api/job-board/{slug}",
             lambda j: len(j.get("jobs", []))),
            ("lever", f"https://api.lever.co/v0/postings/{slug}?mode=json",
             lambda j: len(j) if isinstance(j, list) else 0),
        ):
            try:
                r = requests.get(url, headers=H, timeout=10)
                if r.status_code == 200:
                    n = count(r.json())
                    if n:
                        return {"ats": kind, "slug": slug,
                                "label": company.get("name", slug),
                                "_n": n, "_batch": company.get("batch", "")}
            except Exception:
                continue
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batches", default="",
                    help="comma-separated YC batches to keep, e.g. F26,S26,W26. Empty = all")
    ap.add_argument("--max-pages", type=int, default=245)
    ap.add_argument("--out", default="data/yc_boards.yaml")
    ap.add_argument("--limit", type=int, default=400, help="max companies to probe")
    args = ap.parse_args()

    print("fetching YC company list…", file=sys.stderr)
    companies = fetch_companies(args.max_pages)
    print(f"  {len(companies)} companies", file=sys.stderr)

    batches = {b.strip().upper() for b in args.batches.split(",") if b.strip()}
    hiring = [c for c in companies
              if "isHiring" in str(c.get("badges", ""))
              and (not batches or (c.get("batch") or "").upper() in batches)]
    print(f"  {len(hiring)} hiring{' in ' + args.batches if batches else ''}", file=sys.stderr)
    hiring = hiring[:args.limit]

    found = []
    with cf.ThreadPoolExecutor(max_workers=12) as ex:
        for res in ex.map(probe, hiring):
            if res:
                found.append(res)
                print(f"  OK {res['label'][:28]:30} {res['ats']}/{res['slug']} "
                      f"({res['_n']} roles)", file=sys.stderr)

    entries = [{"ats": f["ats"], "slug": f["slug"], "label": f["label"]} for f in found]
    Path(args.out).write_text(yaml.safe_dump({"companies": entries}, sort_keys=False))
    print(f"\n{len(entries)} YC boards written to {args.out} "
          f"(probed {len(hiring)})", file=sys.stderr)


if __name__ == "__main__":
    main()
