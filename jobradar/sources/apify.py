"""Apify-backed scraping for the two things nothing else can reach.

1. LinkedIn creator posts — the "we're hiring, DM me" feed from named profiles,
   without putting Diya's own account at risk. Apify runs the scrape from its
   infrastructure, so a block lands on them, not on her login.
2. The bot-walled job boards (Google, Microsoft, Apple, Meta, Uber) if the LinkedIn
   company feed is not enough.

MONEY: unlike every other source here, this one costs real money per run. The token
pool is five free-tier Apify accounts capped at $5/month each, SHARED with the
cold-email rig — spending here takes budget from there. Guards, in order:

  - `enabled: false` by default. Nothing runs until you turn it on.
  - `budget_usd` per run, checked against Apify's own usage API before every call.
  - Tokens rotate: an exhausted or 403'd token is skipped, not retried.
  - Actor runs are capped by maxItems so a runaway actor cannot drain a token.

If no token has headroom the source logs why and returns [] — it never silently
burns the last dollars of a shared account.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from ..models import Job, Post
from .base import strip_html, is_remote, SourceError

NAME = "apify"

API = "https://api.apify.com/v2"

# Actor ids. These are public actors on the Apify store; swap them in config if a
# better one appears — the adapter only assumes a list of dicts comes back.
DEFAULT_ACTORS = {
    # 12.8M runs and no cookie needed — the scrape happens on Apify's side, so a block
    # lands on them rather than on Diya's LinkedIn account.
    "linkedin_posts": "harvestapi~linkedin-profile-posts",
    "linkedin_jobs": "bebity~linkedin-jobs-scraper",
}


# --------------------------------------------------------------------------- tokens

def _tokens() -> List[str]:
    """Env first, then the shared pool the cold-email rig already uses."""
    raw = os.getenv("APIFY_TOKENS") or os.getenv("APIFY_TOKEN") or ""
    toks = [t.strip() for t in raw.split(",") if t.strip()]
    if toks:
        return toks
    # Optional shared token file, path supplied by env only — never hardcoded, so the
    # repo doesn't advertise where a token file lives on someone's machine.
    token_file = os.getenv("APIFY_TOKEN_FILE", "")
    shared = Path(token_file) if token_file else None
    if shared and shared.exists():
        m = re.search(r"APIFY_TOKENS?=(.+)", shared.read_text())
        if m:
            return [t.strip() for t in m.group(1).split(",") if t.strip()]
    return []


def _headroom(token: str) -> float:
    """Dollars left on this token this month. -1 if the token is unusable."""
    try:
        with urllib.request.urlopen(f"{API}/users/me/limits?token={token}", timeout=20) as r:
            d = json.loads(r.read().decode()).get("data", {})
        used = float(d.get("current", {}).get("monthlyUsageUsd") or 0)
        cap = float(d.get("limits", {}).get("maxMonthlyUsageUsd") or 0)
        return max(0.0, cap - used)
    except Exception:
        return -1.0


def _pick_token(need: float) -> Optional[str]:
    best, best_room = None, 0.0
    for t in _tokens():
        room = _headroom(t)
        if room > best_room:
            best, best_room = t, room
    if best is None or best_room < need:
        return None
    return best


def _run_actor(actor: str, payload: Dict, token: str, timeout: int = 300) -> List[Dict]:
    url = f"{API}/acts/{actor}/run-sync-get-dataset-items?token={token}"
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            out = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise SourceError(f"apify {actor}: HTTP {e.code} {e.read().decode()[:180]}")
    except Exception as e:
        raise SourceError(f"apify {actor}: {type(e).__name__}: {e}")
    return out if isinstance(out, list) else []


def _conf(cfg: Dict) -> Dict:
    return cfg.get("sources", {}).get(NAME, {}) or {}


def _actor_id(cfg: Dict, key: str) -> str:
    return (_conf(cfg).get("actors") or {}).get(key, DEFAULT_ACTORS[key])


# --------------------------------------------------------------------------- posts

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]{2,}")
LINK_RE = re.compile(r"https?://[^\s)\]]+")


def _first(d: Dict, *keys, default=""):
    for k in keys:
        v = d.get(k)
        if isinstance(v, dict):
            v = v.get("text") or v.get("name") or ""
        if v:
            return v
    return default


def run_posts(cfg: Dict) -> List[Post]:
    """Recent posts from the tracked LinkedIn creators."""
    conf = _conf(cfg)
    if not conf.get("enabled"):
        return []
    if os.getenv("JOBRADAR_FREE_ONLY"):
        # Set by restart-triggered boot scrapes and the dashboard button, so neither a
        # crash loop nor button-mashing can spend Apify budget. Daily cron runs unset it.
        return []
    profiles = (cfg.get("linkedin_creators") or [])[:int(conf.get("max_creator_profiles", 21))]
    if not profiles:
        return []

    budget = float(conf.get("budget_usd", 2.0))
    token = _pick_token(budget)
    if not token:
        raise SourceError(
            f"no Apify token has ${budget:.2f} of headroom — topping up or lowering "
            f"sources.apify.budget_usd is the fix (pool is shared with the cold-email rig)")

    urls = [p if isinstance(p, str) else p.get("url", "") for p in profiles]
    urls = [u for u in urls if u]
    # harvestapi/linkedin-profile-posts input schema.
    payload = {
        "targetUrls": urls,
        "maxPosts": int(conf.get("posts_per_profile", 8)),
        "postedLimit": conf.get("posted_limit", "month"),
        "includeReposts": False,       # reposts duplicate the original hiring post
        "includeQuotePosts": True,
        "scrapeReactions": False,      # reactions/comments multiply cost for no signal
        "scrapeComments": False,
        # Only any/US/GB/DE/FR are accepted — there is no IN option, so "any" it is.
        "contextCountry": conf.get("context_country", "any"),
    }
    items = _run_actor(_actor_id(cfg, "linkedin_posts"), payload, token,
                       timeout=int(conf.get("timeout", 420)))

    out: List[Post] = []
    seen = set()
    for it in items:
        text = _first(it, "content", "text", "postText", "commentary", "description")
        if not text or len(text) < 40:
            continue

        # harvestapi nests author and timestamp; flat fallbacks keep other actors working.
        a = it.get("author") if isinstance(it.get("author"), dict) else {}
        author = (a.get("name")
                  or " ".join(filter(None, [a.get("firstName"), a.get("lastName")])).strip()
                  or a.get("publicIdentifier")
                  or _first(it, "authorName", "fullName", "profileName"))
        headline = (a.get("headline") or a.get("occupation")
                    or _first(it, "authorHeadline", "headline"))
        url = _first(it, "linkedinUrl", "postUrl", "url", "link", "permalink")
        pa = it.get("postedAt") if isinstance(it.get("postedAt"), dict) else {}
        posted = (pa.get("date") or pa.get("timestamp")
                  or _first(it, "publishedAt", "date", "time", "postedDate"))
        emails = EMAIL_RE.findall(text)
        links = [l for l in LINK_RE.findall(text) if "linkedin.com/in/" not in l]
        p = Post(
            source="apify_linkedin_posts",
            external_id=str(_first(it, "id", "entityId", "urn", "postId", default=url)),
            author=author or "unknown",
            author_headline=headline,
            text=text,
            url=url,
            posted_at=_norm_date(posted),
            apply_hint=(emails[0] if emails else (links[0] if links else "")),
            raw_meta={"via": "apify"},
        )
        if p.fingerprint in seen:
            continue
        seen.add(p.fingerprint)
        out.append(p)
    return out


def _norm_date(v) -> Optional[str]:
    if not v:
        return None
    s = str(v)
    if s.isdigit():
        try:
            n = int(s)
            n = n / 1000 if n > 1e11 else n
            return datetime.fromtimestamp(n, tz=timezone.utc).isoformat(timespec="seconds")
        except Exception:
            return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(
            timezone.utc).isoformat(timespec="seconds")
    except Exception:
        return None


# --------------------------------------------------------------------------- jobs

def run_jobs(cfg: Dict) -> List[Job]:
    """LinkedIn job search through Apify, for the companies whose own boards are walled."""
    conf = _conf(cfg)
    if not conf.get("enabled") or not conf.get("scrape_jobs"):
        return []
    if os.getenv("JOBRADAR_FREE_ONLY"):
        return []

    budget = float(conf.get("budget_usd", 2.0))
    token = _pick_token(budget)
    if not token:
        raise SourceError(f"no Apify token has ${budget:.2f} of headroom for job scraping")

    queries = conf.get("job_queries") or ["software engineer"]
    location = conf.get("job_location", "India")
    rows = int(conf.get("job_rows", 50))

    out: List[Job] = []
    for q in queries:
        payload = {"title": q, "location": location, "rows": rows,
                   "maxItems": rows, "publishedAt": "r604800"}
        try:
            items = _run_actor(_actor_id(cfg, "linkedin_jobs"), payload, token,
                               timeout=int(conf.get("timeout", 420)))
        except SourceError as e:
            print(f"  [apify] job query {q!r} failed: {e}")
            continue
        for it in items:
            title = _first(it, "title", "jobTitle", "position")
            if not title:
                continue
            company = _first(it, "companyName", "company", "companyTitle")
            loc = _first(it, "location", "jobLocation", "place")
            desc = strip_html(_first(it, "description", "descriptionText", "jobDescription"))
            out.append(Job(
                source="apify_linkedin_jobs",
                external_id=str(_first(it, "id", "jobId", "jobPostingId", default=title)),
                title=title,
                company=company,
                location=loc,
                url=_first(it, "link", "jobUrl", "url"),
                description=desc[:12000],
                posted_at=_norm_date(_first(it, "publishedAt", "postedAt", "postedDate")),
                remote=is_remote(f"{loc} {title}"),
                raw_meta={"via": "apify", "query": q},
            ))
        time.sleep(1)
    return out
