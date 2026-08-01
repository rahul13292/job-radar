"""LinkedIn job search via the public guest endpoint (no login, no cookie).

This is the same endpoint the logged-out /jobs page calls for its infinite scroll.
It returns HTML job cards. LinkedIn rate-limits it hard, so keep the page count low
and let base.get() back off on 429.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from itertools import product
from typing import Dict, Iterator, List

from bs4 import BeautifulSoup

from ..models import Job
from .base import get, is_remote, strip_html, SourceError

SEARCH = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
DETAIL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{jid}"

NAME = "linkedin_jobs"

# f_TPR windows
TPR = {"24h": "r86400", "week": "r604800", "month": "r2592000"}

# f_E experience levels: 1 internship, 2 entry, 3 associate, 4 mid-senior
EXP = {"internship": "1", "entry": "2", "associate": "3", "mid": "4"}


def _rel_to_iso(text: str) -> str:
    """'3 days ago' / '2 hours ago' -> ISO timestamp."""
    if not text:
        return ""
    m = re.search(r"(\d+)\s+(minute|hour|day|week|month)", text, re.I)
    if not m:
        return ""
    n, unit = int(m.group(1)), m.group(2).lower()
    delta = {"minute": timedelta(minutes=n), "hour": timedelta(hours=n), "day": timedelta(days=n),
             "week": timedelta(weeks=n), "month": timedelta(days=30 * n)}[unit]
    return (datetime.now(timezone.utc) - delta).isoformat(timespec="seconds")


def _parse_cards(html: str) -> Iterator[Job]:
    soup = BeautifulSoup(html, "lxml")
    # Only <li> — each result is an <li> wrapping a div.base-card, so selecting both
    # yields every job twice. Dedupe hid it downstream, but it doubled the detail fetches.
    for card in soup.select("li"):
        a = card.select_one("a.base-card__full-link, a.base-search-card__title-link, a[href*='/jobs/view/']")
        title_el = card.select_one("h3.base-search-card__title, .base-search-card__title")
        comp_el = card.select_one("h4.base-search-card__subtitle a, h4.base-search-card__subtitle")
        loc_el = card.select_one(".job-search-card__location, .base-search-card__metadata span")
        time_el = card.select_one("time")
        if not (a and title_el):
            continue

        url = (a.get("href") or "").split("?")[0]
        jid = ""
        m = re.search(r"-(\d{6,})(?:\?|$)", url) or re.search(r"currentJobId=(\d+)", a.get("href") or "")
        if m:
            jid = m.group(1)
        if not jid:
            urn = card.select_one("[data-entity-urn]")
            if urn:
                jid = (urn.get("data-entity-urn") or "").split(":")[-1]

        posted = ""
        if time_el:
            posted = time_el.get("datetime") or _rel_to_iso(time_el.get_text(" ", strip=True))

        loc = loc_el.get_text(" ", strip=True) if loc_el else ""
        yield Job(
            source=NAME,
            external_id=jid or url,
            title=title_el.get_text(" ", strip=True),
            company=comp_el.get_text(" ", strip=True) if comp_el else "",
            location=loc,
            url=url,
            posted_at=posted or None,
            remote=is_remote(f"{loc} {title_el.get_text()}"),
        )


def fetch_detail(job: Job) -> None:
    """Pull the full JD so the scorer can read skills and the years-of-experience wall."""
    if not job.external_id.isdigit():
        return
    try:
        r = get(DETAIL.format(jid=job.external_id), pace=1.2, retries=2)
        if r.status_code != 200:
            return
        soup = BeautifulSoup(r.text, "lxml")
        body = soup.select_one(".show-more-less-html__markup, .description__text")
        if body:
            job.description = strip_html(str(body))[:12000]
        crit = soup.select(".description__job-criteria-item")
        for c in crit:
            k = c.select_one(".description__job-criteria-subheader")
            v = c.select_one(".description__job-criteria-text")
            if k and v:
                job.raw_meta[k.get_text(strip=True)] = v.get_text(strip=True)
    except SourceError:
        return


def company_feeds(cfg: Dict) -> List[Job]:
    """Per-company job feeds via f_C=<linkedin company id>.

    This is how Google, Microsoft, Apple, Meta, Uber, Flipkart, Swiggy and Zepto get
    covered at all — every one of them blocks its own careers API, but all of them
    publish here, and the guest endpoint accepts an exact company filter with no login.

    IDs come from tools/resolve_linkedin_companies.py, which verifies each one by
    running a real search and checking the company name that comes back. Never
    hand-write an ID into config: a wrong number returns a different company's jobs
    that look perfectly valid.
    """
    entries = cfg.get("linkedin_companies", [])
    conf = cfg.get("sources", {}).get("linkedin_companies", {})
    locations = conf.get("locations", ["India"])[:1]   # one location per company is plenty
    window = TPR.get(conf.get("window", "month"), TPR["month"])
    # Without a keyword, f_C returns EVERY open role at the company — procurement
    # managers, sales, trust & safety. On the first run 256 of 323 cards died on the
    # title gate, i.e. most of the requests were spent fetching jobs we then threw away.
    keywords = conf.get("keywords", ["software engineer", "security engineer"])
    exp_levels = [EXP[e] for e in conf.get("experience_levels", []) if e in EXP]

    out: List[Job] = []
    seen = set()
    for e in entries:
        cid, label = str(e.get("company_id", "")), e.get("name", "")
        if not cid.isdigit():
            continue
        pages = range(int(conf.get("company_pages", 1)))
        for loc, kw, page in product(locations, keywords, pages):
            params = {"f_C": cid, "keywords": kw, "location": loc, "f_TPR": window,
                      "start": page * 25, "sortBy": "DD"}
            if exp_levels:
                params["f_E"] = ",".join(exp_levels)
            try:
                r = get(SEARCH, params=params, pace=1.5)
            except SourceError:
                break
            if r.status_code != 200 or not r.text.strip():
                continue
            for job in _parse_cards(r.text):
                if job.fingerprint in seen:
                    continue
                seen.add(job.fingerprint)
                job.raw_meta["company_feed"] = label
                if not job.company:
                    job.company = label
                out.append(job)

    from ..scoring import CORE_TITLE
    for j in [j for j in out if CORE_TITLE.search(j.title)][:60]:
        fetch_detail(j)
    return out


def run(cfg: Dict, limit_detail: int = 40) -> List[Job]:
    conf = cfg.get("sources", {}).get(NAME, {})
    keywords = conf.get("keywords", ["software engineer"])
    locations = conf.get("locations", ["India"])
    pages = int(conf.get("pages", 2))
    window = TPR.get(conf.get("window", "week"), TPR["week"])
    exp_levels = [EXP[e] for e in conf.get("experience_levels", []) if e in EXP]

    out: List[Job] = []
    seen = set()
    for kw in keywords:
        for loc in locations:
            for page in range(pages):
                params = {
                    "keywords": kw,
                    "location": loc,
                    "f_TPR": window,
                    "start": page * 25,
                    "sortBy": "DD",
                }
                if exp_levels:
                    params["f_E"] = ",".join(exp_levels)
                if conf.get("remote_only"):
                    params["f_WT"] = "2"
                try:
                    r = get(SEARCH, params=params, pace=1.5)
                except SourceError:
                    break
                if r.status_code != 200 or not r.text.strip():
                    break
                got = 0
                for job in _parse_cards(r.text):
                    got += 1
                    if job.fingerprint in seen:
                        continue
                    seen.add(job.fingerprint)
                    job.raw_meta["query"] = f"{kw} @ {loc}"
                    out.append(job)
                if got == 0:
                    break

    # Detail fetch is the expensive part — only for the cards that look plausible by title.
    from ..scoring import CORE_TITLE
    shortlist = [j for j in out if CORE_TITLE.search(j.title)][:limit_detail]
    for j in shortlist:
        fetch_detail(j)
    return out
