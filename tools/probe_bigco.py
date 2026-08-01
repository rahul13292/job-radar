"""Probe the direct career-site APIs of large employers.

Each entry is a real request against that company's own careers backend. Prints which
ones answer a programmatic client so we only build adapters for endpoints that work.
"""
from __future__ import annotations

import concurrent.futures as cf
import json

import requests

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
H = {"User-Agent": UA, "Accept": "application/json,text/html", "Accept-Language": "en-US,en;q=0.9"}

WD = "https://{host}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"

PROBES = [
    # (label, method, url, payload/params)
    ("amazon", "GET", "https://www.amazon.jobs/en/search.json",
     {"base_query": "software engineer", "loc_query": "India", "result_limit": 10}),
    ("amazon_v2", "GET", "https://www.amazon.jobs/api/jobs/search",
     {"base_query": "software development engineer", "loc_query": "India"}),
    ("google", "GET", "https://careers.google.com/api/v3/search/",
     {"q": "software engineer", "location": "India", "page_size": 10}),
    ("microsoft", "GET", "https://gcsservices.careers.microsoft.com/search/api/v1/search",
     {"q": "software engineer", "lc": "India", "l": "en_us", "pg": 1, "pgSz": 10}),
    ("apple", "GET", "https://jobs.apple.com/api/role/searches", None),
    ("meta", "GET", "https://www.metacareers.com/graphql", None),
    ("goldman", "GET", "https://higher.gs.com/services/analytics/roles", None),
    ("goldman_v2", "GET", "https://higher.gs.com/roles", None),
    ("zomato", "GET", "https://www.zomato.com/careers/api/jobs", None),
    ("swiggy", "GET", "https://careers.swiggy.com/api/jobs", None),
    ("flipkart_sr", "GET", "https://api.smartrecruiters.com/v1/companies/Flipkart/postings",
     {"limit": 5}),
    ("razorpay_sr", "GET", "https://api.smartrecruiters.com/v1/companies/Razorpay/postings",
     {"limit": 5}),
    ("yc_companies", "GET", "https://api.ycombinator.com/v0.1/companies", {"page": 1}),
    ("yc_jobs_algolia", "GET",
     "https://45bwzj1sgc-dsn.algolia.net/1/indexes/WaaSJobPublic_created_at_desc", None),
    ("workatastartup", "GET", "https://www.workatastartup.com/companies.json", None),
]

WORKDAYS = [
    ("nvidia", "nvidia.wd5", "nvidia", "NVIDIAExternalCareerSite"),
    ("salesforce", "salesforce.wd12", "salesforce", "External_Career_Site"),
    ("adobe", "adobe.wd5", "adobe", "external_experienced"),
    ("walmart", "walmart.wd5", "walmart", "WalmartExternal"),
    ("jpmorgan", "jpmc.wd5", "jpmc", "jpmc"),
    ("morganstanley", "ms.wd5", "ms", "External"),
    ("citi", "citi.wd5", "citi", "2"),
    ("wellsfargo", "wellsfargojobs.wd12", "wellsfargojobs", "WellsFargoJobs"),
    ("hsbc", "hsbc.wd3", "hsbc", "External"),
    ("deutschebank", "db.wd3", "db", "DBWebsite"),
    ("blackrock", "blackrock.wd1", "blackrock", "BlackRock_Professional"),
    ("amex", "aexp.wd1", "aexp", "GCS"),
    ("intuit", "intuit.wd1", "intuit", "IntuitExternalCareerSite"),
    ("qualcomm", "qualcomm.wd5", "qualcomm", "External"),
    ("paypal", "paypal.wd1", "paypal", "jobs"),
    ("visa", "visa.wd1", "visa", "Job"),
    ("cisco", "cisco.wd1", "cisco", "at_cisco"),
    ("servicenow", "servicenow.wd1", "servicenow", "careers"),
    ("uber", "uber.wd1", "uber", "UberFulltime"),
    ("nutanix", "nutanix.wd1", "nutanix", "Nutanix"),
]


def probe_simple(item):
    label, method, url, params = item
    try:
        r = requests.get(url, params=params, headers=H, timeout=15)
        body = r.text[:160].replace("\n", " ")
        n = ""
        try:
            j = r.json()
            if isinstance(j, dict):
                for k in ("jobs", "hits", "results", "content", "companies", "roles", "operation"):
                    if k in j:
                        v = j[k]
                        n = f" items={len(v) if hasattr(v, '__len__') else '?'}"
                        break
            elif isinstance(j, list):
                n = f" items={len(j)}"
        except Exception:
            pass
        return f"{label:20} {r.status_code}{n}  {body[:90]}"
    except Exception as e:
        return f"{label:20} ERR  {type(e).__name__}: {str(e)[:70]}"


def probe_workday(item):
    label, host, tenant, site = item
    url = WD.format(host=host, tenant=tenant, site=site)
    try:
        r = requests.post(url, json={"limit": 5, "offset": 0, "searchText": "software engineer",
                                     "appliedFacets": {}},
                          headers={**H, "Content-Type": "application/json"}, timeout=15)
        if r.status_code == 200:
            j = r.json()
            return f"{label:20} 200  total={j.get('total')} got={len(j.get('jobPostings', []))}  {url}"
        return f"{label:20} {r.status_code}  {url}"
    except Exception as e:
        return f"{label:20} ERR  {type(e).__name__}  {url}"


if __name__ == "__main__":
    print("=== direct career APIs ===")
    with cf.ThreadPoolExecutor(max_workers=10) as ex:
        for line in ex.map(probe_simple, PROBES):
            print(line)
    print("\n=== workday tenants ===")
    with cf.ThreadPoolExecutor(max_workers=10) as ex:
        for line in ex.map(probe_workday, WORKDAYS):
            print(line)
