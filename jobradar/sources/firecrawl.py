"""Firecrawl adapter for the career sites that block every other approach.

Google, Microsoft, Apple, Meta, Uber, Zomato, Swiggy, Blinkit, Zepto and Naukri all
refuse a plain HTTP client (401/403/404/recaptcha) or render their listings entirely in
JavaScript. Firecrawl runs a real browser and returns rendered markdown, which gets
past both problems.

Budget reality: the free tier is 1,000 credits/month, recurring, no card, at 1 credit
per page. At ~15 target pages on a Mon/Wed/Fri cadence that's ~180 credits/month, so
this comfortably fits free. `max_pages_per_run` is a hard stop regardless.

Off unless FIRECRAWL_API_KEY is set. With no key the source logs why and returns [],
exactly like the other optional sources.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Dict, List

from ..models import Job
from .base import is_remote, SourceError

NAME = "firecrawl"
API = "https://api.firecrawl.dev/v1/scrape"

# Job rows in rendered markdown look like a link followed by location text. These are
# intentionally loose: every candidate still goes through the normal title/experience
# gates, so a bad parse is dropped downstream rather than reaching her board.
MD_LINK = re.compile(r"\[([^\]]{6,120})\]\((https?://[^)]+)\)")
LOCATION_HINT = re.compile(
    r"\b(bengaluru|bangalore|hyderabad|pune|mumbai|delhi|gurgaon|gurugram|noida|"
    r"chennai|india|remote)\b", re.I)
TITLEISH = re.compile(
    r"\b(engineer|developer|sde|swe|programmer|analyst|architect|scientist|intern)\b", re.I)


def _key() -> str:
    k = os.getenv("FIRECRAWL_API_KEY", "").strip()
    if not k:
        raise SourceError(
            "FIRECRAWL_API_KEY not set — Firecrawl source is off. Free tier is "
            "1,000 credits/month at firecrawl.dev; paste the key into .env or Railway.")
    return k


def _scrape(url: str, key: str, timeout: int = 90) -> str:
    payload = {
        "url": url,
        "formats": ["markdown"],
        "onlyMainContent": True,
        # Career pages hydrate their listings after first paint.
        "waitFor": 3500,
        "timeout": 45000,
    }
    req = urllib.request.Request(
        API, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:200]
        if e.code == 402:
            raise SourceError("Firecrawl credits exhausted for this month")
        if e.code == 401:
            raise SourceError("Firecrawl rejected the API key")
        raise SourceError(f"firecrawl HTTP {e.code}: {body}")
    except Exception as e:
        raise SourceError(f"firecrawl {type(e).__name__}: {e}")
    if not d.get("success"):
        raise SourceError(f"firecrawl returned success=false for {url}")
    return (d.get("data") or {}).get("markdown", "") or ""


def _parse(markdown: str, company: str, base_url: str) -> List[Job]:
    out, seen = [], set()
    lines = markdown.splitlines()
    for i, line in enumerate(lines):
        for m in MD_LINK.finditer(line):
            title, href = m.group(1).strip(), m.group(2).strip()
            if not TITLEISH.search(title) or len(title) > 120:
                continue
            if href in seen:
                continue
            seen.add(href)
            # Location usually sits on the same line or the next couple.
            ctx = " ".join(lines[i:i + 3])
            loc_m = LOCATION_HINT.search(ctx)
            loc = loc_m.group(0) if loc_m else ""
            out.append(Job(
                source="firecrawl",
                external_id=href,
                title=re.sub(r"\s+", " ", title),
                company=company,
                location=loc.title(),
                url=href,
                description="",     # listing pages carry no JD; enrichment can follow
                remote=is_remote(ctx),
                raw_meta={"via": "firecrawl", "page": base_url},
            ))
    return out


def run(cfg: Dict) -> List[Job]:
    conf = cfg.get("sources", {}).get(NAME, {}) or {}
    if not conf.get("enabled"):
        return []
    targets = cfg.get("firecrawl_targets") or []
    if not targets:
        return []
    key = _key()          # raises a clear SourceError when unset

    max_pages = int(conf.get("max_pages_per_run", 20))
    out: List[Job] = []
    used = 0
    for t in targets:
        if used >= max_pages:
            print(f"  [firecrawl] page cap {max_pages} reached, stopping")
            break
        url, company = t.get("url"), t.get("company", "")
        if not url:
            continue
        try:
            md = _scrape(url, key, timeout=int(conf.get("timeout", 90)))
        except SourceError as e:
            print(f"  [firecrawl] {company}: {e}")
            if "credits exhausted" in str(e) or "rejected the API key" in str(e):
                break          # no point burning the rest of the list
            continue
        used += 1
        jobs = _parse(md, company, url)
        out.extend(jobs)
        print(f"  [firecrawl] {company}: {len(jobs)} listings ({used}/{max_pages} credits)")
    return out
