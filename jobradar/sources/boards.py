"""Aggregator boards that are public and stable: RemoteOK and HN 'Who is hiring'."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Dict, List

from ..models import Job, Post
from .base import get, strip_html, is_remote, SourceError

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]{2,}")
LINK_RE = re.compile(r"https?://[^\s<>\"]+")


# --------------------------------------------------------------------------- remoteok

def remoteok(cfg: Dict) -> List[Job]:
    r = get("https://remoteok.com/api", pace=0.5)
    if r.status_code != 200:
        raise SourceError(f"remoteok: HTTP {r.status_code}")
    data = r.json()
    jobs = []
    for j in data:
        if not isinstance(j, dict) or not j.get("position"):
            continue
        desc = strip_html(j.get("description", ""))
        tags = " ".join(j.get("tags") or [])
        jobs.append(Job(
            source="remoteok",
            external_id=str(j.get("id")),
            title=j.get("position", ""),
            company=j.get("company", ""),
            location=j.get("location") or "Remote",
            url=j.get("url", ""),
            description=f"{desc}\nTags: {tags}"[:12000],
            posted_at=j.get("date", ""),
            remote=True,
            raw_meta={"tags": tags},
        ))
    return jobs


# --------------------------------------------------------------------------- hn who is hiring

def _latest_whoishiring_story() -> Dict:
    """Newest monthly thread from the whoishiring account.

    Must be search_by_date, not search: relevance ranking happily returns a 2020
    thread ahead of this month's, and stale threads look like live jobs. Also has
    to exclude "Who wants to be hired?", which the same account posts minutes apart.
    """
    r = get("https://hn.algolia.com/api/v1/search_by_date",
            params={"tags": "story,author_whoishiring", "hitsPerPage": 12}, pace=0.4)
    if r.status_code != 200:
        raise SourceError(f"hn: HTTP {r.status_code}")
    hits = [h for h in r.json().get("hits", [])
            if "who is hiring" in (h.get("title") or "").lower()
            and "wants to be hired" not in (h.get("title") or "").lower()]
    if not hits:
        raise SourceError("hn: no Who-is-hiring thread found")
    hits.sort(key=lambda h: h.get("created_at_i", 0), reverse=True)
    return hits[0]


def hackernews(cfg: Dict) -> List[Post]:
    """Top-level comments in the monthly thread are individual job posts."""
    story = _latest_whoishiring_story()
    sid = story["objectID"]
    out: List[Post] = []
    page = 0
    while page < 6:
        r = get("https://hn.algolia.com/api/v1/search",
                params={"tags": f"comment,story_{sid}", "hitsPerPage": 100, "page": page}, pace=0.4)
        if r.status_code != 200:
            break
        data = r.json()
        for h in data.get("hits", []):
            text = strip_html(h.get("comment_text") or "")
            if len(text) < 60:
                continue
            emails = EMAIL_RE.findall(text)
            links = LINK_RE.findall(text)
            first_line = text.split("|")[0][:120]
            out.append(Post(
                source="hn_whoishiring",
                external_id=str(h.get("objectID")),
                author=h.get("author", ""),
                author_headline=story.get("title", ""),
                text=text,
                url=f"https://news.ycombinator.com/item?id={h.get('objectID')}",
                posted_at=h.get("created_at", ""),
                company_guess=first_line,
                apply_hint=(emails[0] if emails else (links[0] if links else "")),
                raw_meta={"thread": story.get("title", "")},
            ))
        page += 1
        if page >= data.get("nbPages", 1):
            break
    return out
