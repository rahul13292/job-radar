"""Company ATS boards: Greenhouse, Lever, Ashby, SmartRecruiters, Workday.

These are the boards companies publish themselves — public JSON, no auth, no scraping
grey area, and they carry the full job description. They're the highest-signal source
in this whole system; LinkedIn is the discovery layer, this is the apply layer.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Dict, List

from ..models import Job
from .base import get, post_json, is_remote, strip_html, SourceError
from .names import display

NAME = "ats"


def _iso(ts) -> str:
    if not ts:
        return ""
    if isinstance(ts, (int, float)):
        # Ashby/Workday sometimes give epoch millis
        v = ts / 1000 if ts > 1e11 else ts
        return datetime.fromtimestamp(v, tz=timezone.utc).isoformat(timespec="seconds")
    s = str(ts).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s).astimezone(timezone.utc).isoformat(timespec="seconds")
    except Exception:
        return str(ts)


# --------------------------------------------------------------------------- greenhouse

def greenhouse(slug: str, company_label: str = "") -> List[Job]:
    r = get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
            params={"content": "true"}, pace=0.4)
    if r.status_code != 200:
        raise SourceError(f"greenhouse {slug}: HTTP {r.status_code}")
    jobs = []
    for j in r.json().get("jobs", []):
        loc = (j.get("location") or {}).get("name", "")
        desc = strip_html(j.get("content", ""))
        jobs.append(Job(
            source="greenhouse",
            external_id=str(j.get("id")),
            title=j.get("title", ""),
            company=company_label or display(slug),
            location=loc,
            url=j.get("absolute_url", ""),
            description=desc[:12000],
            posted_at=_iso(j.get("updated_at") or j.get("first_published")),
            remote=is_remote(f"{loc} {j.get('title','')}"),
            raw_meta={"board": slug},
        ))
    return jobs


# --------------------------------------------------------------------------- lever

def lever(slug: str, company_label: str = "") -> List[Job]:
    r = get(f"https://api.lever.co/v0/postings/{slug}", params={"mode": "json"}, pace=0.4)
    if r.status_code != 200:
        raise SourceError(f"lever {slug}: HTTP {r.status_code}")
    jobs = []
    for j in r.json():
        cat = j.get("categories") or {}
        desc = strip_html(j.get("descriptionPlain") or j.get("description", ""))
        lists = " ".join(strip_html(l.get("content", "")) for l in (j.get("lists") or []))
        jobs.append(Job(
            source="lever",
            external_id=str(j.get("id")),
            title=j.get("text", ""),
            company=company_label or display(slug),
            location=cat.get("location", "") or "",
            url=j.get("hostedUrl", ""),
            description=f"{desc}\n{lists}"[:12000],
            posted_at=_iso(j.get("createdAt")),
            remote=is_remote(f"{cat.get('location','')} {cat.get('commitment','')}"),
            raw_meta={"board": slug, "team": cat.get("team", "")},
        ))
    return jobs


# --------------------------------------------------------------------------- ashby

def ashby(slug: str, company_label: str = "") -> List[Job]:
    r = get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}",
            params={"includeCompensation": "true"}, pace=0.4)
    if r.status_code != 200:
        raise SourceError(f"ashby {slug}: HTTP {r.status_code}")
    jobs = []
    for j in r.json().get("jobs", []):
        jobs.append(Job(
            source="ashby",
            external_id=str(j.get("id")),
            title=j.get("title", ""),
            company=company_label or display(slug),
            location=j.get("location", "") or "",
            url=j.get("jobUrl", "") or j.get("applyUrl", ""),
            description=strip_html(j.get("descriptionHtml") or j.get("descriptionPlain", ""))[:12000],
            posted_at=_iso(j.get("publishedAt") or j.get("updatedAt")),
            remote=bool(j.get("isRemote")) or is_remote(j.get("location", "")),
            raw_meta={"board": slug, "team": j.get("team", "")},
        ))
    return jobs


# --------------------------------------------------------------------------- smartrecruiters

def smartrecruiters(slug: str, company_label: str = "") -> List[Job]:
    jobs, offset = [], 0
    while offset < 400:
        r = get(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings",
                params={"limit": 100, "offset": offset}, pace=0.4)
        if r.status_code != 200:
            raise SourceError(f"smartrecruiters {slug}: HTTP {r.status_code}")
        data = r.json()
        content = data.get("content", [])
        for j in content:
            loc = j.get("location") or {}
            loc_s = ", ".join(x for x in [loc.get("city"), loc.get("region"), loc.get("country")] if x)
            jobs.append(Job(
                source="smartrecruiters",
                external_id=str(j.get("id")),
                title=j.get("name", ""),
                company=company_label or display(slug),
                location=loc_s,
                url=f"https://jobs.smartrecruiters.com/{slug}/{j.get('id')}",
                description="",   # summary endpoint has no body; title+location still scores
                posted_at=_iso(j.get("releasedDate")),
                remote=bool(loc.get("remote")),
                raw_meta={"board": slug},
            ))
        offset += 100
        if len(content) < 100:
            break
    return jobs


# --------------------------------------------------------------------------- workday

def workday(entry: Dict) -> List[Job]:
    """entry: {host, tenant, site, label} e.g.
       {host: 'salesforce.wd12', tenant: 'salesforce', site: 'External_Career_Site'}"""
    host, tenant, site = entry["host"], entry["tenant"], entry["site"]
    label = entry.get("label") or display(tenant)
    url = f"https://{host}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"
    jobs, offset = [], 0
    while offset < 200:
        r = post_json(url, {"limit": 20, "offset": offset,
                            "searchText": entry.get("search", "engineer"),
                            "appliedFacets": {}})
        if r.status_code != 200:
            raise SourceError(f"workday {tenant}: HTTP {r.status_code}")
        data = r.json()
        posts = data.get("jobPostings", [])
        for j in posts:
            path = j.get("externalPath", "")
            jobs.append(Job(
                source="workday",
                external_id=j.get("bulletFields", [""])[0] or path,
                title=j.get("title", ""),
                company=label,
                location=j.get("locationsText", "") or "",
                url=f"https://{host}.myworkdayjobs.com/en-US/{site}{path}",
                description="",
                posted_at="",
                remote=is_remote(j.get("locationsText", "")),
                raw_meta={"posted_on": j.get("postedOn", "")},
            ))
        offset += 20
        if len(posts) < 20 or offset >= data.get("total", 0):
            break
    return jobs


HANDLERS = {
    "greenhouse": lambda e: greenhouse(e["slug"], e.get("label", "")),
    "lever": lambda e: lever(e["slug"], e.get("label", "")),
    "ashby": lambda e: ashby(e["slug"], e.get("label", "")),
    "smartrecruiters": lambda e: smartrecruiters(e["slug"], e.get("label", "")),
    "workday": workday,
}


def run(cfg: Dict) -> List[Job]:
    """cfg['companies'] is a list of {ats, slug|host/tenant/site, label}.

    Fetched concurrently. Sequentially, ~200 boards took over ten minutes and the whole
    daily run was dominated by waiting on sockets — these are independent hosts, so
    there is no reason to queue behind each other. Each board still gets the shared
    client's retry/backoff, and one dead board can't kill the run.
    """
    entries = [e for e in cfg.get("companies", []) if HANDLERS.get(e.get("ats"))]
    workers = int(cfg.get("fetch_workers", 12))

    def one(entry: Dict):
        kind = entry["ats"]
        try:
            return HANDLERS[kind](entry), None
        except Exception as e:
            return [], f"{kind}:{entry.get('slug') or entry.get('tenant')}: {e}"

    out: List[Job] = []
    errors: List[str] = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for jobs, err in ex.map(one, entries):
            out.extend(jobs)
            if err:
                errors.append(err)

    if errors:
        print(f"  [ats] {len(errors)}/{len(entries)} board(s) failed: {'; '.join(errors[:4])}")
    return out
