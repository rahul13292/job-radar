"""Round 2: discover correct Workday site paths, and probe Indian-company ATS boards."""
from __future__ import annotations

import concurrent.futures as cf
import re

import requests

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
H = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}

# tenants whose site path we guessed wrong (422) — discover it from the landing redirect
UNKNOWN = [
    ("jpmorgan", "jpmc.wd5", "jpmc"), ("wellsfargo", "wellsfargojobs.wd12", "wellsfargojobs"),
    ("hsbc", "hsbc.wd3", "hsbc"), ("amex", "aexp.wd1", "aexp"),
    ("qualcomm", "qualcomm.wd5", "qualcomm"), ("visa", "visa.wd1", "visa"),
    ("cisco", "cisco.wd1", "cisco"), ("servicenow", "servicenow.wd1", "servicenow"),
    ("uber", "uber.wd1", "uber"), ("nutanix", "nutanix.wd1", "nutanix"),
    ("walmart", "walmart.wd5", "walmart"), ("goldman", "gs.wd5", "gs"),
    ("barclays", "barclays.wd3", "barclays"), ("ubs", "ubs.wd3", "ubs"),
    ("standardchartered", "scb.wd3", "scb"), ("macquarie", "macquarie.wd3", "macquarie"),
    ("nomura", "nomura.wd3", "nomura"), ("bnymellon", "bnymellon.wd1", "bnymellon"),
    ("statestreet", "statestreet.wd1", "statestreet"), ("fidelity", "fidelity.wd1", "fidelity"),
]


def discover_site(item):
    label, host, tenant = item
    base = f"https://{host}.myworkdayjobs.com"
    try:
        r = requests.get(base + "/", headers=H, timeout=15, allow_redirects=True)
        m = re.search(r"myworkdayjobs\.com/(?:[a-zA-Z-]+/)?([A-Za-z0-9_\-]+)/?", r.url)
        site = m.group(1) if m else None
        # the landing URL sometimes carries a locale segment first
        cands = [site] if site else []
        cands += ["External", "Careers", "External_Career_Site", "careers", "external"]
        for c in dict.fromkeys([c for c in cands if c]):
            rr = requests.post(f"{base}/wday/cxs/{tenant}/{c}/jobs",
                               json={"limit": 5, "offset": 0, "searchText": "software engineer",
                                     "appliedFacets": {}},
                               headers={**H, "Content-Type": "application/json"}, timeout=15)
            if rr.status_code == 200:
                j = rr.json()
                return (f"{label:20} OK site={c:26} total={j.get('total')}"
                        f"  {{ats: workday, host: {host}, tenant: {tenant}, site: {c}}}")
        return f"{label:20} -- landing={r.url[:80]} (no working site path found)"
    except Exception as e:
        return f"{label:20} ERR {type(e).__name__}: {str(e)[:60]}"


INDIA = """
zepto meesho groww razorpay phonepe zomato swiggy blinkit flipkart rubrik sprinto
zetwerk dream11 ola paytm myntra nykaa urbancompany physicswallah sharechat zoho
freshworks browserstack hasura chargebee innovaccer darwinbox zluri whatfix juspay
setu m2pfintech jupiter cars24 spinny lenskart licious rebelfoods zeptonow
dunzo pharmeasy healthkart practo curefit cult unacademy vedantu upgrad simplilearn
razorpaysoftware perfios signzy turtlemint acko digit navi khatabook oyo makemytrip
ixigo redbus delhivery shiprocket porter rapido bounce yulu ather ola-electric
tekion mindtickle leadsquared kissflow chargebeeinc exotel knowlarity gupshup
haptik yellowai verloop uniphore observeai gushwork atlan hevodata rilata
"""


def probe_ats(slug: str):
    out = []
    for kind, url, check in [
        ("greenhouse", f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
         lambda j: len(j.get("jobs", []))),
        ("lever", f"https://api.lever.co/v0/postings/{slug}?mode=json",
         lambda j: len(j) if isinstance(j, list) else 0),
        ("ashby", f"https://api.ashbyhq.com/posting-api/job-board/{slug}",
         lambda j: len(j.get("jobs", []))),
    ]:
        try:
            r = requests.get(url, headers=H, timeout=12)
            if r.status_code == 200:
                n = check(r.json())
                if n:
                    out.append(f"  - {{ats: {kind}, slug: {slug}}}   # {n} open roles")
        except Exception:
            pass
    return out


if __name__ == "__main__":
    print("=== workday site discovery ===")
    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        for line in ex.map(discover_site, UNKNOWN):
            print(line)

    print("\n=== india company boards ===")
    slugs = sorted(set(INDIA.split()))
    found = []
    with cf.ThreadPoolExecutor(max_workers=12) as ex:
        for res in ex.map(probe_ats, slugs):
            found.extend(res)
    for line in sorted(found):
        print(line)
    print(f"# {len(found)} live boards from {len(slugs)} Indian candidates")
