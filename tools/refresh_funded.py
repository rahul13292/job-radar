"""Find recently-funded startups and resolve the ones with a scrapable job board.

Why this source exists: a company that just closed a round is about to hire, the roles
often aren't posted anywhere yet, and a cold email lands with a founder who is actively
thinking about headcount. That is the highest-leverage moment to reach them, and no job
board captures it.

Pipeline: funding-news RSS -> company name -> guess ATS slug -> VERIFY the board
answers -> write data/funded_boards.yaml (which config.yaml includes).

Name extraction from headlines is deliberately loose. It doesn't need to be precise
because every candidate is verified against a live board — a bad guess just fails to
resolve and is dropped. Same safety net as the YC prober.

    ./.venv/bin/python tools/refresh_funded.py --out data/funded_boards.yaml
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import re
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

import requests
import yaml

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
H = {"User-Agent": UA}

# RSS only exposes a shallow window (~20-50 recent items each), so breadth of feeds
# matters more than depth of any one. India feeds carry the most relevant rounds since
# those companies hire in her metros.
# Probed and rejected: finsmes and crunchbase news 403 any client, vccircle 500s.
FEEDS = {
    "techcrunch_vc": "https://techcrunch.com/category/venture/feed/",
    "techcrunch_startups": "https://techcrunch.com/category/startups/feed/",
    "techcrunch": "https://techcrunch.com/feed/",
    "tech_eu": "https://tech.eu/feed/",
    "inc42": "https://inc42.com/feed/",                  # India
    "yourstory": "https://yourstory.com/feed",           # India
    "entrackr": "https://entrackr.com/rss",              # India, funding-heavy
    "et_tech": "https://economictimes.indiatimes.com/tech/rssfeeds/13357270.cms",
}

RAISE = re.compile(
    r"^(.{2,60}?)\s+(?:raises|raised|bags|secures|snags|lands|nets|closes|"
    r"picks up|mops up|scores)\b", re.I)

# Headlines lead with a descriptor far more often than with the bare name:
# "Edtech platform raises…", "Quick commerce startup Homerun raises…".
DESCRIPTOR = re.compile(
    r"^(?:[\w\-.]+\s+)*(?:startup|platform|firm|company|app|maker|giant|unicorn|"
    r"provider|player|venture|brand|marketplace|lab|labs)\s+", re.I)
LEAD_JUNK = re.compile(
    r"^(?:repeat\s+founder|serial\s+entrepreneur|ex-\w+|former\s+\w+)\s+", re.I)
GENERIC = {"edtech", "fintech", "healthtech", "startup", "platform", "company", "firm",
           "the", "this", "new", "indian", "us", "ai", "saas", "b2b", "d2c"}

ROUND = re.compile(r"\b(pre-seed|seed|series\s+[a-f]\+?|bridge)\b", re.I)
AMOUNT = re.compile(r"([₹$€£]\s?[\d.,]+\s?(?:crore|cr|million|billion|mn|bn|M|B)\b)", re.I)


def company_candidates(title: str) -> list:
    m = RAISE.match(title.strip())
    if not m:
        return []
    raw = m.group(1).strip(" ,–—-")
    cleaned = LEAD_JUNK.sub("", raw)
    cleaned = DESCRIPTOR.sub("", cleaned).strip()
    out = []
    for name in (cleaned, raw):
        name = name.strip(" ,.'\"")
        if not name or name.lower() in GENERIC or len(name) < 3:
            continue
        if name not in out:
            out.append(name)
    return out


# Slugs that are ordinary English words match somebody else's board and look like a
# real hit: "Healthcare AI startup X" resolved to lever/healthcare, "Lighthouse Canton"
# to greenhouse/lighthouse. Neither was the funded company.
COMMON_WORD = {
    "healthcare", "lighthouse", "health", "energy", "finance", "capital", "labs",
    "technology", "tech", "digital", "systems", "solutions", "global", "group",
    "partners", "ventures", "growth", "impact", "future", "smart", "data", "cloud",
    "secure", "security", "mobility", "logistics", "retail", "media", "care", "bank",
    "insurance", "space", "power", "water", "green", "climate", "leap", "spark",
}


def slug_variants(name: str) -> list:
    base = re.sub(r"[^a-z0-9 ]", "", name.lower()).strip()
    if not base:
        return []
    words = base.split()
    # Only whole-name forms. Taking the first word of a multi-word name is what produced
    # every false positive, so a multi-word company never falls back to one token.
    cands = [base.replace(" ", ""), base.replace(" ", "-")]
    if len(words) == 1:
        cands = [words[0]]
    seen, out = set(), []
    for c in cands:
        if not c or len(c) < 4 or c in seen or c in GENERIC or c in COMMON_WORD:
            continue
        seen.add(c)
        out.append(c)
    return out[:2]


def probe_board(slug: str):
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
                    return kind, slug, n
        except Exception:
            continue
    return None


def fetch_feed(item):
    name, url = item
    out = []
    try:
        r = requests.get(url, headers=H, timeout=25)
        root = ET.fromstring(r.content)
    except Exception as e:
        print(f"  {name}: {type(e).__name__}", file=sys.stderr)
        return out
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        date = (it.findtext("pubDate") or "").strip()
        if not title:
            continue
        cands = company_candidates(title)
        if not cands:
            continue
        out.append({"headline": title, "url": link, "date": date, "source": name,
                    "candidates": cands,
                    "round": (ROUND.search(title).group(0) if ROUND.search(title) else ""),
                    "amount": (AMOUNT.search(title).group(1) if AMOUNT.search(title) else "")})
    return out


def resolve(entry):
    for name in entry["candidates"]:
        for slug in slug_variants(name):
            hit = probe_board(slug)
            if hit:
                kind, slug, n = hit
                return {"ats": kind, "slug": slug, "label": name,
                        "_n": n, "_headline": entry["headline"],
                        "_round": entry["round"], "_amount": entry["amount"],
                        "_news": entry["url"], "_source": entry["source"]}
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/funded_boards.yaml")
    ap.add_argument("--news-out", default="data/funding_news.json",
                    help="raw funding events, used by the outreach generator for hooks")
    args = ap.parse_args()

    events = []
    with cf.ThreadPoolExecutor(max_workers=4) as ex:
        for res in ex.map(fetch_feed, FEEDS.items()):
            events.extend(res)
    print(f"{len(events)} funding headlines parsed", file=sys.stderr)

    found = []
    with cf.ThreadPoolExecutor(max_workers=10) as ex:
        for res in ex.map(resolve, events):
            if res:
                found.append(res)
                print(f"  OK {res['label'][:26]:28} {res['ats']}/{res['slug']} "
                      f"({res['_n']} roles) {res['_amount']}", file=sys.stderr)

    Path(args.out).write_text(
        "# Recently-funded companies with a live job board. Regenerated by\n"
        "# tools/refresh_funded.py — do not hand-edit.\n"
        + yaml.safe_dump({"companies": [{"ats": f["ats"], "slug": f["slug"],
                                         "label": f["label"]} for f in found]},
                         sort_keys=False, default_flow_style=True))

    # Keep every event, resolved or not — the outreach generator uses the headline as a
    # personalisation hook even when the company has no scrapable board.
    Path(args.news_out).write_text(json.dumps(events, indent=1))
    print(f"\n{len(found)} funded boards -> {args.out}", file=sys.stderr)
    print(f"{len(events)} funding events -> {args.news_out}", file=sys.stderr)


if __name__ == "__main__":
    main()
