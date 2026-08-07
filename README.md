# Job Radar 🧸

A job + hiring-post scraper tuned to one resume. Built for Diya Singh — DTU Software
Engineering 2026, security-SWE intern at Rippling, Python/FastAPI/AWS/Docker/Terraform —
targeting **fresher** SDE and security-engineering roles in Indian metros.

It pulls ~17,000 postings per run from a dozen sources, scores every one against her
actual resume, dedupes across boards, and serves the survivors on a password-protected
dashboard with an Excel application tracker.

A full run takes ~14 minutes and yields roughly 865 on-profile roles and 170 hiring posts.

No OpenAI key, no LLM calls. Scoring is regex + keyword overlap against the resume, so
it costs nothing, runs the same way twice, and shows its reasoning on every card.

## Quick start

```bash
cd job-radar
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt

./.venv/bin/python -m jobradar.cli init --resume data/Diya_Singh_SWE.pdf
./.venv/bin/python -m jobradar.cli run
./.venv/bin/python -m jobradar.cli web        # http://127.0.0.1:8765
```

For hosting, see **[DEPLOY.md](DEPLOY.md)** (Railway, one service, daily scrape built in).

## Who it's for — the fresher gate

She is a 2026 grad with internships only, so the filter is deliberately strict:

| Rejected outright | Why |
|---|---|
| `Senior`, `Staff`, `Lead`, `Principal`, `Manager`, `Architect` | above her level |
| `Engineer II`, `SDE-2`, `L3`, `Level 2` | levelled titles are already a rung up |
| JD demanding **2+ years** | `max_years_required: 1` |
| `PhD` / `Doctorate` in the title, or a JD requiring a PhD or Master's | she holds a BTech |
| QA, SDET, Test Engineer, Manual Testing | not a product-engineering track |
| Support Engineer, Service Desk, Field Engineer | pattern-match on "engineer", aren't the job |
| Staffing marketplaces (Alignerr, hackajob, Turing, Crossover) | thousands of fake "Software Engineer" listings |

The PhD rule earned its place: Google's *"Software Engineer, PhD, Early Career, 2026"*
scored **91** — perfect on every other signal, and closed to her.

## Geography

| Tier | Places | Effect |
|---|---|---|
| Preferred | Bengaluru, Delhi/NCR, Gurgaon, Noida, Hyderabad, Pune, Mumbai | **+12** |
| India, off-metro | Chennai, Kolkata, Ahmedabad, Jaipur, Kochi, Trivandrum, … | **−6** — visible if she looks, never at the top |
| Global remote, no geo lock | "Remote (Global)" | +8 |
| Geo-locked remote | "Remote — USA", "Remote (Italy)", "US-based" | **−12** — not remote from Delhi |
| Elsewhere onsite | | −15 |

## Sources

| Source | Auth | Covers |
|---|---|---|
| **LinkedIn jobs** | none | Guest search, widest net across India |
| **LinkedIn company feeds** | none | **78 verified company IDs** — the *only* route to Google, Microsoft, Apple, Meta, Uber, Rippling, Flipkart, Swiggy, Zepto, CrowdStrike, Palo Alto |
| **Greenhouse / Lever / Ashby / SmartRecruiters** | none | **170 company boards** — S-tier (OpenAI, Anthropic, Stripe, Databricks, Snowflake, Palantir, xAI, Figma, Waymo, Cursor, Perplexity, Cohere), A-tier (MongoDB, Okta, Zscaler, Datadog, Cloudflare, Canva, Samsara), India (Rubrik, PhonePe, Meesho, Paytm, Groww, CRED, Zeta, Tekion) |
| **Amazon** | none | `amazon.jobs`, India-filtered (319 SDE roles) |
| **JPMorgan Chase** | none | Oracle Recruiting Cloud (7,279 roles; 122 India SWE) |
| **Workday** | none | NVIDIA, Salesforce, Adobe, Morgan Stanley, Citi, Deutsche Bank, BlackRock, PayPal |
| **Netflix** | none | Eightfold-hosted careers API |
| **YC startups** | none | **185 boards** auto-discovered across every batch W23-W27 (683 hiring companies probed), refreshed weekly |
| **Recently funded** | none | Funding RSS (TechCrunch, Inc42, YourStory, Entrackr, ET Tech) -> company -> verified board; the funding events themselves become outreach hooks |
| **Quant / trading** | none | IMC, WorldQuant, Tower Research via LinkedIn feed |
| **RemoteOK** | none | global remote |
| **HN "Who is hiring"** | none | current month's thread |
| **LinkedIn creator posts** | Apify | the 20 tracked "we're hiring / batch 2026 / apply here" accounts — **on by default** |

### What is NOT scraped directly, and why

These were each probed and refuse a programmatic client. Rather than ship scrapers that
silently return zero, they're covered through the LinkedIn company feed instead:

| Company | Result |
|---|---|
| Google, Microsoft | careers API 404 / host no longer resolves |
| Apple | `401 User Unauthorized` |
| Meta, Uber | GraphQL 400 / `403 Forbidden` at the edge |
| Goldman Sachs | JS app, no JSON endpoint |
| Zomato, Swiggy, Blinkit, Zepto | client-rendered SPAs, no jobs API |
| **Naukri** | `406 recaptcha required` — its own email alerts are the honest answer |
| **Wellfound** | 403 to any non-browser request |

Every one of those *except* Naukri and Wellfound is still collected, via
`linkedin_companies`. That feed is keyword-scoped: without a keyword, `f_C` returns a
company's entire job board — on the first run 256 of 323 cards were procurement and
sales roles that the title gate then threw away.

## Scoring

0–100, with every point attributable. The dashboard prints the clauses that produced
the number, so you tune `config.yaml` instead of guessing.

**Points**: target title +25 · security-track role +12 · new-grad signal +15 · resume-skill
overlap up to +30 · preferred metro +12 · global remote +8 · posted in last 24h +10 ·
target company +10.

Change any weight, then re-grade everything already stored without re-scraping:

```bash
./.venv/bin/python -m jobradar.cli rescore
```

## Dashboard

Three tabs — **Roles**, **Hiring posts**, **Tracker** — in a soft pastel theme, with
CSS-drawn bear and panda mascots (original shapes, not the copyrighted characters).

- Filter by score, status, source, free text; sort by match / newly found / newest posted
- 💛 Save, ✅ Applied, Hide on every card
- **Tracker** tab: what she applied to, when, with an editable note per row
- **⬇︎ Excel**: 4-sheet `.xlsx` — Applied, Saved, All matches, About — with clickable links
- **✨ Find jobs** runs a scrape in the background
- Login required whenever `DASHBOARD_PASSWORD` is set (HMAC-signed cookie, 30-day expiry)

## Commands

```bash
jobradar init --resume FILE.pdf     # resume PDF -> profile.json (hand-editable)
jobradar run [--only SOURCE]        # scrape, score, store
jobradar rescore                    # re-grade stored rows after a config change
jobradar list --min-score 65 -v     # top matches in the terminal, with reasons
jobradar posts --min-score 50 -v    # top hiring posts
jobradar digest [--send]            # new-since-last digest, printed or emailed
jobradar export --out jobs.csv      # CSV (the dashboard's Excel export is richer)
jobradar web --port 8765            # dashboard
```

Prefix with `./.venv/bin/python -m jobradar.cli`.

## Tools

```bash
tools/probe_boards.py               # re-probe company ATS boards, prune dead ones
tools/resolve_linkedin_companies.py # resolve + VERIFY LinkedIn company IDs
tools/refresh_yc.py                 # rediscover hiring YC startups (run weekly)
tools/resume_gap.py                 # what the collected JDs ask for that her resume lacks
tools/probe_bigco.py                # re-probe the direct career APIs
tools/refresh_funded.py             # recently-funded startups + outreach hooks (run weekly)
```

`resolve_linkedin_companies.py` verifies every ID by running a real search and checking
the company name that comes back. Never hand-write an ID into config — a wrong number
returns a different company's jobs and looks perfectly valid.

## Apify — LinkedIn creator posts (ON, costs money)

Scrapes the 20 tracked profiles via `harvestapi/linkedin-profile-posts`. No cookie
needed, so **her own LinkedIn account is never used and never at risk** — the scrape
runs on Apify's infrastructure.

This is the highest-signal source in the whole system for a fresher. Real output from
the first live run: Amazon SDE-I mass hiring (97), Adobe SDE (95), Barclays SWE (92),
Red Hat SRE internship (85), Amazon for 2025/26 grads (80).

Two scoring rules exist only because of this feed:
- Indian hiring posts are **structured listings**, not sentences — "Rubrik Industrial
  Trainee | Bengaluru | Batch: 2026/2027 | Apply: lnkd.in/…". Requiring "we're hiring"
  scored the best posts in the feed a flat 0.
- Posts stay up after the role closes. A slice post reading "Hiring is Closed" scored
  87 before the closed-role filter was added.

Guards: `budget_usd` per-run ceiling checked against Apify's usage API before every
call; token rotation that skips exhausted accounts; `maxItems` caps on actor runs.

The fallback token pool is **shared with the cold-email rig** ($5/month cap per account),
so spending here takes budget from there. Set `APIFY_TOKENS` in `.env` to use separate ones.

## Known limits

- SmartRecruiters and Workday list responses carry no description text, so those roles
  score on title + location alone and rank lower than they deserve.
- LinkedIn rate-limits the guest endpoint; on a 429 the client backs off and moves on,
  so a run can come back thin. The next run picks up what it missed.
- Post scoring reads the first 300 characters for location, which is where HN comments
  put it. A post burying "Charleston SC" further down can score higher than it should.
- Zomato, Blinkit, Nykaa, Dream11 and Zetwerk have no verified LinkedIn company ID yet,
  so they're only caught by the general keyword search. Re-run the resolver to retry.
