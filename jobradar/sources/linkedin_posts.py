"""LinkedIn *posts* — the 'we're hiring, DM me' feed, not the jobs board.

This is the one part of the system that needs your own logged-in session, because
LinkedIn does not expose post search to logged-out visitors. You paste your own
li_at + JSESSIONID cookies into .env and it queries as you.

Read this before turning it on:
  - It uses YOUR account. LinkedIn's ToS prohibits automated access; heavy use can
    get an account restricted. Keep `pages` at 1-2 and run it a few times a day, not
    every minute. The defaults here are deliberately gentle.
  - Voyager is a private API. LinkedIn changes it without notice, so treat a sudden
    zero-result run as "endpoint moved", not "no jobs today". Every other source in
    this project is public and stable; this one is best-effort by nature.
  - With no cookie configured it returns [] and says so. Nothing else breaks.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, List

from ..models import Post
from .base import _session, SourceError

NAME = "linkedin_posts"

VOYAGER = "https://www.linkedin.com/voyager/api/graphql"
BLENDED = "https://www.linkedin.com/voyager/api/search/dash/clusters"

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]{2,}")
LINK_RE = re.compile(r"https?://[^\s)\]]+")


def _headers() -> Dict[str, str]:
    li_at = os.getenv("LI_AT", "").strip()
    jsession = os.getenv("LI_JSESSIONID", "").strip().strip('"')
    if not li_at:
        raise SourceError("LI_AT not set — LinkedIn post search is off (see .env.example)")
    if not jsession:
        # LinkedIn will hand one out on first request, but csrf-token must match it.
        jsession = "ajax:0000000000000000000"
    _session.cookies.set("li_at", li_at, domain=".linkedin.com")
    _session.cookies.set("JSESSIONID", f'"{jsession}"', domain=".linkedin.com")
    return {
        "csrf-token": jsession,
        "x-restli-protocol-version": "2.0.0",
        "x-li-lang": "en_US",
        "accept": "application/vnd.linkedin.normalized+json+2.1",
        "referer": "https://www.linkedin.com/search/results/content/",
    }


def _walk_posts(obj, out: List[Dict]) -> None:
    """Voyager's shape shifts between releases, so pull anything that looks like an update."""
    if isinstance(obj, dict):
        urn = obj.get("entityUrn") or obj.get("*entityUrn") or ""
        if isinstance(urn, str) and ("activity" in urn or "ugcPost" in urn):
            out.append(obj)
        for v in obj.values():
            _walk_posts(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _walk_posts(v, out)


def _text_of(node: Dict) -> str:
    for key in ("commentary", "summary", "text"):
        v = node.get(key)
        if isinstance(v, dict):
            t = v.get("text")
            if isinstance(t, dict):
                t = t.get("text")
            if isinstance(t, str) and t.strip():
                return t
        if isinstance(v, str) and v.strip():
            return v
    return ""


def _actor_of(node: Dict) -> tuple:
    actor = node.get("actor") or {}
    name = ((actor.get("name") or {}).get("text")) or ""
    sub = ((actor.get("description") or {}).get("text")) or ""
    return name, sub


def _search(keyword: str, headers: Dict, date_posted: str, start: int) -> List[Dict]:
    params = {
        "decorationId": "com.linkedin.voyager.dash.deco.search.SearchClusterCollection-186",
        "origin": "SWITCH_SEARCH_VERTICAL",
        "q": "all",
        "query": (f"(keywords:{keyword},flagshipSearchIntent:SEARCH_SRP,"
                  f"queryParameters:(datePosted:List({date_posted}),resultType:List(CONTENT)),"
                  f"includeFiltersInResponse:false)"),
        "start": start,
    }
    r = _session.get(BLENDED, params=params, headers=headers, timeout=25)
    if r.status_code in (401, 403):
        raise SourceError(f"LinkedIn rejected the session ({r.status_code}) — cookie expired?")
    if r.status_code == 429:
        raise SourceError("LinkedIn rate-limited the post search; back off and retry later")
    if r.status_code != 200:
        raise SourceError(f"LinkedIn post search HTTP {r.status_code}")
    try:
        data = r.json()
    except ValueError:
        raise SourceError("LinkedIn returned non-JSON (endpoint likely moved)")
    found: List[Dict] = []
    _walk_posts(data, found)
    return found


def run(cfg: Dict) -> List[Post]:
    conf = cfg.get("sources", {}).get(NAME, {})
    if not conf.get("enabled"):
        return []
    keywords = conf.get("keywords", ["hiring software engineer"])
    pages = int(conf.get("pages", 1))
    date_posted = conf.get("date_posted", "past-week")

    headers = _headers()   # raises with a clear message if no cookie
    out: List[Post] = []
    seen = set()
    for kw in keywords:
        for page in range(pages):
            nodes = _search(kw, headers, date_posted, page * 10)
            for n in nodes:
                text = _text_of(n)
                if len(text) < 40:
                    continue
                author, headline = _actor_of(n)
                urn = str(n.get("entityUrn") or "")
                m = re.search(r"(\d{15,})", urn)
                aid = m.group(1) if m else urn
                emails = EMAIL_RE.findall(text)
                links = [l for l in LINK_RE.findall(text) if "linkedin.com/in/" not in l]
                p = Post(
                    source=NAME,
                    external_id=aid,
                    author=author,
                    author_headline=headline,
                    text=text,
                    url=f"https://www.linkedin.com/feed/update/urn:li:activity:{aid}/" if aid.isdigit() else "",
                    posted_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    apply_hint=(emails[0] if emails else (links[0] if links else "")),
                    raw_meta={"query": kw},
                )
                if p.fingerprint in seen:
                    continue
                seen.add(p.fingerprint)
                out.append(p)
    return out
