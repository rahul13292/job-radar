"""Probe candidate company slugs against Greenhouse/Lever/Ashby and print the ones
that actually return jobs. Used to build the companies: block in config.yaml so we
ship verified boards instead of guesses. Re-run it any time to prune dead boards.

    ./.venv/bin/python tools/probe_boards.py > /tmp/boards.yaml
"""
from __future__ import annotations

import concurrent.futures as cf
import sys

import requests

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
S = requests.Session()
S.headers.update({"User-Agent": UA})

CANDIDATES = """
stripe databricks cloudflare atlassian dropbox coinbase robinhood airbnb doordash gitlab
hashicorp twilio mongodb elastic snyk crowdstrike sentinelone okta datadog confluent
samsara plaid razorpay zeta postman browserstack hasura freshworks chargebee meesho
swiggy zomato cred groww phonepe sprinto zscaler paloaltonetworks tenable rapid7
hackerone bugcrowd arcticwolf netskope wiz orcasecurity lacework jumpcloud 1password
canva figma notion linear vercel netlify supabase retool ramp brex deel remotecom gusto
checkr verkada scaleai anthropic openai harness chainguard semgrep socketdev sourcegraph
nutanix rubrik cohesity druva postmanlabs zscalerinc uber lyft instacart affirm chime
flexport benchling grammarly discord reddit pinterest squarespace udemy unity
salesforce servicenow workato zluri whatfix darwinbox innovaccer clevertap moengage
razorpaysoftware juspay setu m2p signzy perfios turtlemint acko digit navi jupiter
slice khatabook dukaan zepto blinkit licious rebel urbancompany porter delhivery
shiprocket unacademy vedantu physicswallah scaler newtonschool codingninjas
apnamart shipsy locus fareye hevodata atlan sarvam krutrim glean cursor perplexity
harvey sierra decagon abridge openevidence mercor clay attentive rippling gong
"""

ASHBY_EXTRA = "ramp deel notion linear vercel openai anthropic clay mercor sierra harvey"


def check(slug: str):
    out = []
    try:
        r = S.get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs", timeout=12)
        if r.status_code == 200 and r.json().get("jobs"):
            out.append(("greenhouse", slug, len(r.json()["jobs"])))
    except Exception:
        pass
    try:
        r = S.get(f"https://api.lever.co/v0/postings/{slug}?mode=json", timeout=12)
        if r.status_code == 200 and isinstance(r.json(), list) and r.json():
            out.append(("lever", slug, len(r.json())))
    except Exception:
        pass
    try:
        r = S.get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}", timeout=12)
        if r.status_code == 200 and r.json().get("jobs"):
            out.append(("ashby", slug, len(r.json()["jobs"])))
    except Exception:
        pass
    return out


def main():
    slugs = sorted(set(CANDIDATES.split() + ASHBY_EXTRA.split()))
    live = []
    with cf.ThreadPoolExecutor(max_workers=12) as ex:
        for res in ex.map(check, slugs):
            live.extend(res)
    live.sort(key=lambda x: (-x[2], x[1]))
    print(f"# {len(live)} live boards out of {len(slugs)} candidate slugs", file=sys.stderr)
    for ats, slug, n in live:
        print(f"  - {{ats: {ats}, slug: {slug}}}   # {n} open roles")


if __name__ == "__main__":
    main()
