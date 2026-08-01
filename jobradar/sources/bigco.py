"""Direct career-site adapters for large employers that don't use a public ATS.

Each of these hits the same backend the company's own careers page calls.

What is NOT here, and why — these were probed and refused a programmatic client:
  Google          careers API returns 404 to anything but its own SPA
  Microsoft       gcsservices.careers.microsoft.com no longer resolves
  Apple           /api/v1/search returns 401 User Unauthorized
  Meta            metacareers GraphQL rejects unauthenticated POSTs (400)
  Uber            403 Forbidden at the edge
  Goldman Sachs   higher.gs.com is a JS app with no JSON endpoint
  Zomato/Swiggy/  careers pages are client-rendered SPAs with no jobs API
  Blinkit/Zepto
All of them are covered instead through LinkedIn's per-company feed
(see linkedin_jobs.company_feeds), which needs no login and returns their real
postings. That is the honest substitute, not a workaround that silently returns zero.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Dict, List

from ..models import Job
from .base import get, strip_html, is_remote, SourceError

NAME = "bigco"


# --------------------------------------------------------------------------- amazon

def amazon(cfg_entry: Dict) -> List[Job]:
    """amazon.jobs search.json.

    The country filter is `normalized_country_code[]`, not `country[]` — the latter is
    accepted and silently ignored, which returns the worldwide list looking like a
    successful India query. Responses also contain raw control characters, so the JSON
    needs strict=False.
    """
    queries = cfg_entry.get("queries", ["software development engineer"])
    country = cfg_entry.get("country", "IND")
    out: List[Job] = []
    for q in queries:
        offset = 0
        while offset < cfg_entry.get("max_per_query", 200):
            r = get("https://www.amazon.jobs/en/search.json",
                    params={"base_query": q, "normalized_country_code[]": country,
                            "result_limit": 100, "offset": offset, "sort": "recent"},
                    pace=0.8)
            if r.status_code != 200:
                raise SourceError(f"amazon: HTTP {r.status_code}")
            data = json.loads(r.text, strict=False)
            jobs = data.get("jobs", [])
            for j in jobs:
                desc = strip_html(" ".join(filter(None, [
                    j.get("description", ""), j.get("basic_qualifications", ""),
                    j.get("preferred_qualifications", "")])))
                posted = ""
                try:
                    posted = datetime.strptime(
                        j.get("posted_date", ""), "%B %d, %Y").replace(
                        tzinfo=timezone.utc).isoformat(timespec="seconds")
                except Exception:
                    pass
                loc = j.get("normalized_location", "") or j.get("location", "")
                out.append(Job(
                    source="amazon",
                    external_id=str(j.get("id_icims") or j.get("id")),
                    title=j.get("title", ""),
                    company="Amazon",
                    location=loc.replace(", IND", ", India"),
                    url="https://www.amazon.jobs" + (j.get("job_path") or ""),
                    description=desc[:12000],
                    posted_at=posted or None,
                    remote=is_remote(loc),
                    raw_meta={"team": j.get("company_name", ""), "query": q},
                ))
            offset += 100
            if len(jobs) < 100:
                break
    return out


# --------------------------------------------------------------------------- oracle recruiting cloud

def oracle_orc(entry: Dict) -> List[Job]:
    """Oracle Recruiting Cloud — what most large banks run.

    entry: {base, site, label, location}
    Needs expand=requisitionList or the response comes back as facets with no jobs.
    """
    base = entry["base"].rstrip("/")
    site = entry.get("site", "CX_1")
    label = entry.get("label", "")
    location = entry.get("location", "India")
    out: List[Job] = []
    for kw in entry.get("queries", ["software engineer"]):
        offset = 0
        while offset < entry.get("max_per_query", 200):
            finder = (f"findReqs;siteNumber={site},limit=100,offset={offset},"
                      f"keyword={kw},location={location}")
            r = get(f"{base}/hcmRestApi/resources/latest/recruitingCEJobRequisitions",
                    params={"onlyData": "true", "expand": "requisitionList.secondaryLocations",
                            "finder": finder},
                    headers={"Accept": "application/json"}, timeout=35, pace=0.8)
            if r.status_code != 200:
                raise SourceError(f"orc {label}: HTTP {r.status_code}")
            items = r.json().get("items", [])
            reqs = items[0].get("requisitionList", []) if items else []
            for j in reqs:
                loc = j.get("PrimaryLocation", "") or ""
                out.append(Job(
                    source="oracle_orc",
                    external_id=str(j.get("Id")),
                    title=j.get("Title", ""),
                    company=label,
                    location=loc,
                    url=f"{base}/hcmUI/CandidateExperience/en/sites/{site}/job/{j.get('Id')}",
                    description=strip_html(j.get("ShortDescriptionStr") or "")[:12000],
                    posted_at=j.get("PostedDate") or None,
                    remote=is_remote(loc + " " + (j.get("WorkplaceType") or "")),
                    raw_meta={"query": kw},
                ))
            offset += 100
            if len(reqs) < 100:
                break
    return out


# --------------------------------------------------------------------------- eightfold

def eightfold(entry: Dict) -> List[Job]:
    """Eightfold AI-hosted career sites (Netflix and others).

    entry: {base, domain, label}
    """
    base = entry["base"].rstrip("/")
    domain = entry["domain"]
    label = entry.get("label", domain)
    out: List[Job] = []
    for q in entry.get("queries", ["software engineer"]):
        start = 0
        while start < entry.get("max_per_query", 200):
            r = get(f"{base}/api/apply/v2/jobs",
                    params={"domain": domain, "query": q, "start": start, "num": 50,
                            "location": entry.get("location", "")},
                    pace=0.7)
            if r.status_code != 200:
                raise SourceError(f"eightfold {label}: HTTP {r.status_code}")
            positions = r.json().get("positions", [])
            for p in positions:
                loc = p.get("location", "") or ""
                ts = p.get("t_update") or p.get("t_create")
                posted = ""
                if ts:
                    try:
                        posted = datetime.fromtimestamp(
                            int(ts), tz=timezone.utc).isoformat(timespec="seconds")
                    except Exception:
                        pass
                out.append(Job(
                    source="eightfold",
                    external_id=str(p.get("id")),
                    title=p.get("name", ""),
                    company=label,
                    location=loc,
                    url=p.get("canonicalPositionUrl", ""),
                    description=strip_html(p.get("job_description", ""))[:12000],
                    posted_at=posted or None,
                    remote=is_remote(loc + " " + (p.get("work_location_option") or "")),
                    raw_meta={"dept": p.get("department", ""), "query": q},
                ))
            start += 50
            if len(positions) < 50:
                break
    return out


HANDLERS = {"amazon": amazon, "oracle_orc": oracle_orc, "eightfold": eightfold}


def run(cfg: Dict) -> List[Job]:
    out: List[Job] = []
    errors: List[str] = []
    for entry in cfg.get("bigco", []):
        fn = HANDLERS.get(entry.get("kind"))
        if not fn:
            continue
        try:
            out.extend(fn(entry))
        except Exception as e:
            errors.append(f"{entry.get('kind')}/{entry.get('label', '')}: {e}")
    if errors:
        print(f"  [bigco] {len(errors)} failed: {'; '.join(errors[:4])}")
    return out
