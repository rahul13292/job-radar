"""Probe an S/A/B-tier company universe for scrapable ATS boards.

Prints ready-to-paste config entries for every slug that returns real postings.
Anything that misses here is a candidate for the LinkedIn company feed instead
(tools/resolve_linkedin_companies.py).
"""
from __future__ import annotations

import concurrent.futures as cf
import sys

import requests

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
H = {"User-Agent": UA}

TIERS = {
"S": """
openai anthropic stripe databricks figma ramp anduril palantir snowflake datadog
cloudflare airbnb coinbase robinhood rippling deel notion linear vercel retool
scaleai perplexity anysphere cursor mistral cohere huggingface xai waymo
nvidia netflix rubrik discord reddit pinterest snap spotify shopify block square
""",
"A": """
twilio mongodb elastic confluent hashicorp gitlab github okta zscaler crowdstrike
paloaltonetworks sentinelone snyk wiz nutanix vmware splunk dropbox box asana miro
canva grammarly plaid brex chime affirm instacart flexport samsara verkada benchling
zapier amplitude mixpanel launchdarkly pagerduty sentry postman jfrog newrelic
dynatrace cohesity druva freshworks zoho browserstack chargebee hasura atlan
sourcegraph temporal cockroachlabs neon supabase clickhouse timescale grafana
airbyte dbtlabs fivetran census hightouch monte-carlo-data starburst dremio
""",
"B_india": """
flipkart swiggy zomato zeptonow blinkit meesho razorpay phonepe paytm cred groww
zerodha dream11 nykaa myntra urbancompany delhivery zetwerk lenskart policybazaar
ola rapido porter jupiter slice navi sharechat inmobi games24x7 mpl unacademy
physicswallah upgrad vedantu practo pharmeasy tata1mg licious countrydelight
bigbasket dunzo tekion innovaccer darwinbox whatfix zluri leadsquared mindtickle
juspay setu m2pfintech perfios signzy zeta yubi kreditbee moneyview epifi jar
uni onecard hevodata gushwork observeai bounce sprinto rilata atlan
""",
"quant_banks": """
janestreet optiver imc-trading jumptrading citadel millennium worldquant
squarepoint davinci-derivatives quadeye alphagrep graviton tower-research
deshaw hudson-river-trading drw akuna belvedere
""",
}


def probe(slug: str):
    out = []
    for kind, url, count in (
        ("greenhouse", f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
         lambda j: len(j.get("jobs", []))),
        ("ashby", f"https://api.ashbyhq.com/posting-api/job-board/{slug}",
         lambda j: len(j.get("jobs", []))),
        ("lever", f"https://api.lever.co/v0/postings/{slug}?mode=json",
         lambda j: len(j) if isinstance(j, list) else 0),
        ("smartrecruiters",
         f"https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=1",
         lambda j: j.get("totalFound", 0)),
    ):
        try:
            r = requests.get(url, headers=H, timeout=10)
            if r.status_code == 200:
                n = count(r.json())
                if n:
                    out.append((kind, slug, n))
                    break        # one board per company is enough
        except Exception:
            continue
    return out


def main():
    all_found, all_miss = [], []
    for tier, blob in TIERS.items():
        slugs = sorted(set(blob.split()))
        found, miss = [], []
        with cf.ThreadPoolExecutor(max_workers=14) as ex:
            for res in ex.map(probe, slugs):
                if res:
                    found.extend(res)
        got = {s for _, s, _ in found}
        miss = [s for s in slugs if s not in got]
        print(f"\n# ===== {tier}: {len(found)}/{len(slugs)} live =====", file=sys.stderr)
        for kind, slug, n in sorted(found, key=lambda x: -x[2]):
            print(f"  - {{ats: {kind}, slug: {slug}}}   # {tier}, {n} roles")
        print(f"# {tier} MISS ({len(miss)}): {' '.join(miss)}", file=sys.stderr)
        all_found.extend(found)
        all_miss.extend(miss)
    print(f"\n# TOTAL live boards: {len(all_found)}", file=sys.stderr)
    print(f"# no board (use LinkedIn feed): {' '.join(all_miss)}", file=sys.stderr)


if __name__ == "__main__":
    main()
