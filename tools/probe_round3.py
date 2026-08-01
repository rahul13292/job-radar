"""Round 3: the named companies that rounds 1-2 missed.

Google, Microsoft, Apple, Meta, the Indian unicorns, and the banks on Oracle
Recruiting Cloud. Each probe hits the backend the company's own careers page calls.
"""
from __future__ import annotations

import concurrent.futures as cf

import requests

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
H = {"User-Agent": UA, "Accept": "application/json, text/plain, */*",
     "Accept-Language": "en-US,en;q=0.9"}

GET_PROBES = [
    ("google_v3", "https://www.google.com/about/careers/applications/api/v3/search/",
     {"q": "software engineer", "location": "India", "page_size": 10}),
    ("google_v2", "https://careers.google.com/api/v2/jobs/search/",
     {"q": "software engineer", "location": "India"}),
    ("microsoft", "https://gcsservices.careers.microsoft.com/search/api/v1/search",
     {"q": "software engineer", "lc": "India", "l": "en_us", "pg": 1, "pgSz": 10}),
    ("apple_search", "https://jobs.apple.com/api/v1/search",
     {"query": "software engineer", "locationId": "IND"}),
    ("meta_api", "https://www.metacareers.com/api/jobs", {"q": "software engineer"}),
    ("netflix", "https://explore.jobs.netflix.net/api/apply/v2/jobs",
     {"domain": "netflix.com", "query": "software engineer", "num": 10}),
    ("zepto", "https://zepto.freshteam.com/jobs", None),
    ("razorpay", "https://razorpay.com/api/careers/jobs/", None),
    ("razorpay_kula", "https://jobs.razorpay.com/api/jobs", None),
    ("zomato", "https://www.zomato.com/careers/api/v1/jobs", None),
    ("swiggy_lever", "https://api.lever.co/v0/postings/swiggy?mode=json", None),
    ("blinkit_lever", "https://api.lever.co/v0/postings/blinkit?mode=json", None),
    ("flipkart_wd", "https://flipkart.wd3.myworkdayjobs.com/wday/cxs/flipkart/External/jobs", None),
    ("uber_api", "https://www.uber.com/api/loadSearchJobsResults", None),
    ("goldman_api", "https://higher.gs.com/services/analytics/roles/search", None),
]

# Oracle Recruiting Cloud — the pattern most large banks use.
ORC = [
    ("jpmorgan", "https://jpmc.fa.oraclecloud.com"),
    ("wellsfargo", "https://wellsfargojobs.fa.us2.oraclecloud.com"),
    ("hsbc", "https://mycareer.hsbc.com"),
    ("standardchartered", "https://scb.fa.em2.oraclecloud.com"),
    ("barclays", "https://search.jobs.barclays"),
]

ORC_PATH = ("/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
            "?onlyData=true&finder=findReqs;siteNumber=CX_1,limit=5")

# Workday site paths worth a second try with a wider candidate list.
WD_RETRY = [
    ("qualcomm", "qualcomm.wd5", "qualcomm",
     ["External", "External_Site", "Careers", "QCOM_External", "qualcomm"]),
    ("cisco", "cisco.wd1", "cisco", ["at_cisco", "External", "Careers", "jobs"]),
    ("uber", "uber.wd1", "uber", ["UberFulltime", "External", "Uber", "uber"]),
    ("nutanix", "nutanix.wd1", "nutanix", ["Nutanix", "External", "NutanixCareers", "careers"]),
    ("goldman", "gs.wd5", "gs", ["External", "GS_Careers", "Goldman", "careers"]),
    ("amex", "aexp.wd1", "aexp", ["GCS", "External", "AmericanExpress", "careers"]),
    ("visa", "visa.wd1", "visa", ["Job", "External", "VisaJobs", "careers"]),
    ("servicenow", "servicenow.wd1", "servicenow", ["careers", "External", "ServiceNow"]),
    ("walmart", "walmart.wd5", "walmart", ["WalmartExternal", "External", "walmart_careers"]),
    ("jpmc", "jpmc.wd5", "jpmc", ["External", "JPMC", "jpmc_external", "Careers"]),
]


def probe_get(item):
    label, url, params = item
    try:
        r = requests.get(url, params=params, headers=H, timeout=15)
        n = ""
        try:
            j = r.json()
            if isinstance(j, dict):
                for k in ("jobs", "hits", "results", "positions", "items", "data", "count"):
                    if k in j:
                        v = j[k]
                        n = f" {k}={len(v) if hasattr(v, '__len__') else v}"
                        break
            elif isinstance(j, list):
                n = f" items={len(j)}"
        except Exception:
            pass
        return f"{label:18} {r.status_code}{n}  {r.text[:80].replace(chr(10),' ')}"
    except Exception as e:
        return f"{label:18} ERR {type(e).__name__}: {str(e)[:60]}"


def probe_orc(item):
    label, base = item
    try:
        r = requests.get(base + ORC_PATH, headers=H, timeout=20)
        if r.status_code == 200:
            j = r.json()
            items = (j.get("items") or [{}])[0]
            n = items.get("TotalJobsCount", "?")
            return f"{label:18} 200 ORC total={n}  {base}"
        return f"{label:18} {r.status_code}  {base}"
    except Exception as e:
        return f"{label:18} ERR {type(e).__name__}  {base}"


def probe_wd(item):
    label, host, tenant, sites = item
    for s in sites:
        try:
            r = requests.post(
                f"https://{host}.myworkdayjobs.com/wday/cxs/{tenant}/{s}/jobs",
                json={"limit": 5, "offset": 0, "searchText": "software engineer",
                      "appliedFacets": {}},
                headers={**H, "Content-Type": "application/json"}, timeout=15)
            if r.status_code == 200:
                j = r.json()
                return (f"{label:18} OK  {{ats: workday, host: {host}, tenant: {tenant}, "
                        f"site: {s}}}  total={j.get('total')}")
        except Exception:
            continue
    return f"{label:18} --  none of {sites} worked"


if __name__ == "__main__":
    print("=== direct APIs ===")
    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        for line in ex.map(probe_get, GET_PROBES):
            print(line)
    print("\n=== oracle recruiting cloud (banks) ===")
    with cf.ThreadPoolExecutor(max_workers=5) as ex:
        for line in ex.map(probe_orc, ORC):
            print(line)
    print("\n=== workday retry ===")
    with cf.ThreadPoolExecutor(max_workers=6) as ex:
        for line in ex.map(probe_wd, WD_RETRY):
            print(line)
