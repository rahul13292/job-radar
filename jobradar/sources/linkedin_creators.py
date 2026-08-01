"""Track hiring posts from specific LinkedIn people.

These are the accounts that reliably post "we're hiring / DM me / referral open"
content for Indian SDE and security roles. Following ~20 named profiles is far higher
signal than keyword-searching all of LinkedIn, because the noise is already filtered
by who is posting.

Same constraint as linkedin_posts.py: LinkedIn does not serve member activity to
logged-out visitors, so this needs her own li_at cookie and queries as her account.
Read the header of linkedin_posts.py before enabling — the ToS and rate limits apply
here too, and the defaults are deliberately gentle (one page per profile, meant to run
a few times a day).

With no cookie configured this returns [] and says so; nothing else in the run breaks.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, List

from ..models import Post
from .base import _session, SourceError
from .linkedin_posts import _headers, _walk_posts, _text_of, _actor_of, EMAIL_RE, LINK_RE

NAME = "linkedin_creators"

PROFILE_URL = "https://www.linkedin.com/voyager/api/identity/profiles/{pid}/posts"
FEED_URL = "https://www.linkedin.com/voyager/api/graphql"


def profile_id(url: str) -> str:
    """https://www.linkedin.com/in/debugwithshubham/ -> debugwithshubham"""
    m = re.search(r"/in/([^/?#]+)", url or "")
    return m.group(1) if m else ""


def _fetch_profile_posts(pid: str, headers: Dict, count: int) -> List[Dict]:
    """Voyager's member-activity endpoint. Shape shifts between LinkedIn releases, so
    the response is walked for anything update-shaped rather than indexed by key."""
    urls = [
        (f"https://www.linkedin.com/voyager/api/identity/profileUpdatesV2"
         f"?profileUrn=urn%3Ali%3Afsd_profile%3A{pid}&q=memberShareFeed&count={count}"),
        (f"https://www.linkedin.com/voyager/api/feed/updates"
         f"?count={count}&profileId={pid}&q=memberShareFeed"),
    ]
    for u in urls:
        try:
            r = _session.get(u, headers=headers, timeout=25)
        except Exception:
            continue
        if r.status_code in (401, 403):
            raise SourceError(f"LinkedIn rejected the session ({r.status_code}) — cookie expired?")
        if r.status_code == 429:
            raise SourceError("LinkedIn rate-limited creator fetch; back off and retry later")
        if r.status_code != 200:
            continue
        try:
            data = r.json()
        except ValueError:
            continue
        found: List[Dict] = []
        _walk_posts(data, found)
        if found:
            return found
    return []


def run(cfg: Dict) -> List[Post]:
    conf = cfg.get("sources", {}).get(NAME, {})
    if not conf.get("enabled"):
        return []

    profiles = cfg.get("linkedin_creators", [])
    if not profiles:
        return []

    headers = _headers()          # raises a clear SourceError when no cookie is set
    per_profile = int(conf.get("posts_per_profile", 10))
    max_age = timedelta(days=int(conf.get("max_age_days", 14)))
    now = datetime.now(timezone.utc)

    out: List[Post] = []
    seen = set()
    for entry in profiles:
        url = entry if isinstance(entry, str) else entry.get("url", "")
        pid = profile_id(url)
        if not pid:
            continue
        try:
            nodes = _fetch_profile_posts(pid, headers, per_profile)
        except SourceError:
            raise                 # auth/rate-limit problems should stop the whole source
        except Exception:
            continue              # one dead profile must not kill the rest

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
                author=author or pid,
                author_headline=headline,
                text=text,
                url=(f"https://www.linkedin.com/feed/update/urn:li:activity:{aid}/"
                     if aid.isdigit() else url),
                posted_at=(now - max_age / 2).isoformat(timespec="seconds"),
                company_guess="",
                apply_hint=(emails[0] if emails else (links[0] if links else "")),
                raw_meta={"profile": pid},
            )
            if p.fingerprint in seen:
                continue
            seen.add(p.fingerprint)
            out.append(p)
    return out
