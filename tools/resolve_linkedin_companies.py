"""Resolve LinkedIn numeric company IDs, then VERIFY each one.

Needed because Google, Microsoft, Apple, Meta, Flipkart, Swiggy, Zepto, Blinkit and
Zomato all block their own careers APIs, but they all post to LinkedIn. LinkedIn's
guest job search accepts f_C=<companyId>, which gives an exact per-company feed with
no login.

A company page can carry several organization URNs (parent org, showcase pages, ad
accounts), so scraping the first number is not enough. Every candidate is verified by
running a real f_C search and checking that the returned cards actually carry that
company's name. Unverified IDs are dropped rather than guessed.

    ./.venv/bin/python tools/resolve_linkedin_companies.py > /tmp/companies.yaml
"""
from __future__ import annotations

import re
import sys
import time

import requests

sys.path.insert(0, ".")
from jobradar.sources.linkedin_jobs import _parse_cards  # noqa: E402

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
H = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}
SEARCH = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"

# slug on linkedin.com/company/<slug>  ->  display name we expect back
TARGETS = {
    "google": "Google", "microsoft": "Microsoft", "apple": "Apple", "meta": "Meta",
    "amazon": "Amazon", "netflix": "Netflix", "nvidia": "NVIDIA", "uber-com": "Uber",
    "flipkart": "Flipkart", "swiggy": "Swiggy", "zomato": "Zomato",
    "zeptonow": "Zepto", "blinkit": "Blinkit", "myntra": "Myntra", "nykaa": "Nykaa",
    "razorpay": "Razorpay", "phonepe": "PhonePe", "paytm": "Paytm", "meesho": "Meesho",
    "groww-in": "Groww", "cred-club": "CRED", "dream11": "Dream11", "zetwerk": "Zetwerk",
    "goldman-sachs": "Goldman Sachs", "jpmorganchase": "JPMorgan", "morganstanley": "Morgan Stanley",
    "deutsche-bank": "Deutsche Bank", "barclays": "Barclays", "hsbc": "HSBC",
    "wells-fargo": "Wells Fargo", "citi": "Citi", "american-express": "American Express",
    "blackrock": "BlackRock", "ubs": "UBS", "standard-chartered-bank": "Standard Chartered",
    "rubrik-inc": "Rubrik", "atlassian": "Atlassian", "salesforce": "Salesforce",
    "adobe": "Adobe", "cisco": "Cisco", "qualcomm": "Qualcomm", "vmware": "VMware",
    "intuit": "Intuit", "servicenow": "ServiceNow", "walmart": "Walmart",
    "linkedin": "LinkedIn", "oracle": "Oracle", "sap": "SAP", "ibm": "IBM",
    "samsung-electronics": "Samsung", "de-shaw-india": "D. E. Shaw",
    "tower-research-capital": "Tower Research", "optiver": "Optiver",
    "jane-street": "Jane Street", "graviton-research-capital": "Graviton",
}


def candidate_ids(slug: str) -> list:
    try:
        r = requests.get(f"https://www.linkedin.com/company/{slug}/", headers=H, timeout=20)
        if r.status_code != 200:
            return []
    except Exception:
        return []
    ids = re.findall(r"urn:li:(?:organization|company|fsd_company):(\d+)", r.text)
    ids += re.findall(r'"companyId"\s*:\s*(\d+)', r.text)
    ids += re.findall(r"f_C=(\d+)", r.text)
    seen, out = set(), []
    for i in ids:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out[:6]


def verify(cid: str, expect: str) -> tuple:
    """Run a real search on this ID and check the company name that comes back."""
    try:
        r = requests.get(SEARCH, params={"f_C": cid, "location": "India", "start": 0},
                         headers=H, timeout=20)
        if r.status_code != 200 or not r.text.strip():
            return False, 0, ""
        jobs = list(_parse_cards(r.text))
        if not jobs:
            return False, 0, ""
        names = [j.company for j in jobs if j.company]
        if not names:
            return False, len(jobs), ""
        top = max(set(names), key=names.count)
        want = re.sub(r"[^a-z]", "", expect.lower())
        got = re.sub(r"[^a-z]", "", top.lower())
        ok = want in got or got in want
        return ok, len(jobs), top
    except Exception:
        return False, 0, ""


def main():
    good, bad = [], []
    for slug, name in TARGETS.items():
        hit = None
        for cid in candidate_ids(slug):
            ok, n, top = verify(cid, name)
            time.sleep(1.2)
            if ok:
                hit = (cid, n, top)
                break
        if hit:
            cid, n, top = hit
            good.append(f"  - {{name: {name}, company_id: {cid}}}   # verified, {n} India cards")
            print(f"OK   {name:22} id={cid:12} -> {top}", file=sys.stderr)
        else:
            bad.append(name)
            print(f"MISS {name:22} (no verifiable id)", file=sys.stderr)
        time.sleep(1.0)

    print(f"# {len(good)} verified, {len(bad)} unresolved: {', '.join(bad)}", file=sys.stderr)
    print("linkedin_companies:")
    for line in good:
        print(line)


if __name__ == "__main__":
    main()
