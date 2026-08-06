# Job Radar — full project context

Everything a future session (or Diya) needs. Written 2026-08-05.
No secrets in this file by design — see "Where the secrets live" below.

---

## What this is

A job + hiring-post scraper tuned to **one** resume: Diya Singh, DTU Software
Engineering 2026, security-SWE intern at Rippling (Jan–Jun 2026), Oracle before that.
Targets **fresher** SDE + security-engineering roles in Indian metros.

It pulls ~17,000 postings per run from a dozen sources, scores each against her resume,
dedupes across boards, and serves survivors on a password-protected dashboard with an
Excel application tracker.

**Live:** https://job-radar-production-df24.up.railway.app
**Repo:** github.com/rahul13292/job-radar (**private** — see Security below)
**Schedule:** Mon / Wed / Fri, 03:00 UTC = 08:30 IST

---

## Status

| Piece | State |
|---|---|
| Scraping, scoring, dedupe | Done, verified live |
| Dashboard (Roles / Posts / Tracker) | Done, pastel theme, login-gated |
| Excel export | Done — Applied / Saved / All matches / About sheets |
| Railway deploy + `/data` volume | Live, survives redeploys |
| MWF scheduler | Live, confirmed in prod logs |
| Apify creator posts | Live, budget-guarded |
| Email digest | **Not configured** — needs SMTP creds |
| Repo access | Rahul owner; diya1827 collaborator (write). Transfer to her was initiated 8/3, pending her accept |

---

## Architecture in one pass

```
jobradar/
  cli.py          init | run | rescore | list | posts | digest | export | web
  config.py       loads config.yaml, merges include_company_files, env overrides
  resume.py       PDF -> data/profile.json (skills, titles, grad year)
  matching.py     boundary-aware term matching (see Trap #1)
  scoring.py      score_job / score_post -> (0-100, [reasons])
  db.py           SQLite, dedupe on fingerprint, WAL, thread-safe
  scheduler.py    in-process MWF cron (no second Railway service — cost)
  export_xlsx.py  the application tracker
  notify.py       markdown + SMTP digest
  sources/
    linkedin_jobs.py      guest search + company_feeds (f_C)
    linkedin_creators.py  cookie-based profile posts (off; Apify preferred)
    linkedin_posts.py     cookie-based post search (off)
    apify.py              harvestapi actor — creator posts (ON)
    ats.py                greenhouse/lever/ashby/smartrecruiters/workday, THREADED
    bigco.py              amazon.jobs, Oracle ORC (JPMorgan), Eightfold (Netflix)
    boards.py             RemoteOK, HN "Who is hiring"
    names.py              ATS slug -> display name
  web/
    app.py, auth.py, templates/
tools/            probe_* and resolve_* — regenerate the board/company lists
```

**Scoring is regex + resume-keyword overlap. No LLM, no OpenAI key.** Deliberate: it's
free, deterministic, and every card can show *why* it scored what it did. Adding a model
would cost money to produce the same ranking and lose the explanation.

---

## The gates (why results look the way they do)

**Fresher** — she's a 2026 grad with internships only:
- Rejected: `Senior`/`Staff`/`Lead`/`Principal`/`Manager`/`Architect`
- Rejected: levelled titles — `Engineer II`, `SDE-2`, `L3`
- Rejected: JD asking 2+ years (`max_years_required: 1`)
- Rejected: **PhD/Master's-required** — Google's "Software Engineer, PhD, Early Career
  2026" scored 91 and is closed to a BTech holder
- Rejected: QA / SDET / Test / support-tier titles
- Rejected: staffing marketplaces (Alignerr, hackajob, Turing, Crossover)

**Geography** — two tiers:
- Preferred (+12): Bengaluru, Delhi/NCR, Gurgaon, Noida, Hyderabad, Pune, Mumbai
- India off-metro (−6): Chennai, Kolkata, Ahmedabad, Jaipur, Kochi, Trivandrum — kept
  but pushed down, per Rahul's call
- Global remote, no geo lock: +8
- **Geo-locked remote (−12)**: "Remote — USA", "Remote (Italy)", "US-based" — not
  remote from Delhi. Without this rule US roles flooded the top of the list.

Change any weight in `config.yaml`, then `rescore` re-grades stored rows without
re-scraping.

---

## Traps already paid for — do not re-learn these

1. **Substring matching inflates every score.** `"go" in text` matches *alGOrithms*,
   `"soc"` matches *asSOCiate*. All skill lookups go through `matching.py`.
2. **LinkedIn `f_C` with no keyword returns the company's ENTIRE board** — 256 of 323
   cards were sales/procurement. Company feeds must be keyword-scoped.
3. **LinkedIn company IDs must be verified.** A wrong ID returns a different company's
   jobs and looks perfectly valid. `tools/resolve_linkedin_companies.py` runs a real
   search per ID and checks the returned company name.
4. **HN Algolia relevance search returns a 2020 thread above the current one.** Must use
   `search_by_date` + exclude "Who wants to be hired".
5. **Indian hiring posts are structured listings, not sentences** — "Rubrik Industrial
   Trainee | Bengaluru | Batch: 2026/2027 | Apply: lnkd.in/…". Requiring "we're hiring"
   scored the best posts in the whole feed a flat 0.
6. **Posts stay up after roles close.** A "Hiring is Closed" post scored 87 before the
   closed-role filter.
7. **Railway CLI respects `.gitignore` when uploading the build context.** `data/*.pdf`
   was gitignored, so `COPY data/…pdf` failed on the builder *before the first log
   line* — the deploy showed only "scheduling build on Metal builder" and FAILED. Cost
   5 builds. **Empty Railway build logs = a COPY of an ignored file, not a platform
   problem.** Resume now ships from `assets/`. Debug trick: deploy a trivial
   hello-world Dockerfile to the same project — if that succeeds, it's your image.

---

## Dead ends — probed, confirmed blocked, don't retry

| Target | Result |
|---|---|
| Naukri | `406 recaptcha required`, any headers. Use its own email alerts. |
| Wellfound | 403 to any non-browser client |
| Google, Microsoft | careers API 404 / host no longer resolves |
| Apple | `401 User Unauthorized` |
| Meta, Uber | GraphQL 400 / 403 at the edge |
| Goldman Sachs | JS app, no JSON endpoint |
| Zomato, Swiggy, Blinkit, Zepto | client-rendered SPAs, no jobs API |
| Workday site discovery | landing pages don't redirect; site paths must be probed |

Everything except Naukri and Wellfound is still covered via the **LinkedIn company
feed** (`f_C`), which needs no login. That's the workaround, and it works.

---

## Cost model

- Everything except Apify is **free** and needs no auth.
- **Apify** (`harvestapi~linkedin-profile-posts`) is the only paid source. No cookie
  needed, so Diya's own LinkedIn account is never used or at risk.
- Token pool falls back to `cold-email-rig/.env` — **5 free accounts, $5/mo cap each,
  SHARED with the cold-email rig**. Spending here takes budget from there.
- Guards: `budget_usd` per run checked against Apify's usage API *before* every call;
  token rotation skips exhausted accounts; `maxItems` caps runs.
- `JOBRADAR_FREE_ONLY=1` is set by container restarts and the dashboard "Find jobs"
  button, so a crash loop or button-mashing can never drain the pool. Only the MWF cron
  and a true cold start (empty DB) spend money.
- Railway: one service, one replica, in-process scheduler. A second cron service would
  roughly double the bill since idle RAM is what's charged.

---

## Where the secrets live (none are in this repo)

| Secret | Location |
|---|---|
| Dashboard password | Railway var `DASHBOARD_PASSWORD` |
| Session signing key | Railway var `SESSION_SECRET` |
| Apify tokens | Railway var `APIFY_TOKENS`; locally `cold-email-rig/.env` |
| SMTP creds | Not set yet |

Read the current values with `railway variables --service job-radar`.

---

## Security review + PII incident (2026-08-05/06)

**No keys, tokens, or passwords have ever been committed** — verified across every blob
in every commit. `.env`, `jobs.db`, `profile.json` are gitignored and clean.

**But the repo was accidentally PUBLIC for ~4 days** (Aug 1 18:06Z → Aug 5) with
`assets/resume.pdf` committed, exposing Diya's phone, email and city. `gh repo create
--private` did not take, and the visibility was never verified afterwards. GitHub
traffic recorded **17 unique cloners** against 0 stars/watchers — the signature of
automated firehose scrapers. 0 forks, so nothing persisted on GitHub itself.

**Always verify after creating a repo:**
```bash
gh repo view <owner>/<repo> --json visibility,isPrivate
```

Remediated Aug 6, verified from a fresh clone off GitHub — **0 PII, 0 PDFs, 0 secrets
in the entire history**:
- `git filter-repo --path assets/resume.pdf --invert-paths` — PDF gone from history
- `git filter-repo --replace-text` — her email/phone scrubbed from old `.env.example`
  blobs. Path-based filtering alone misses these, and `git gc --prune=now` is required
  or dangling pre-rewrite objects still hold the data.
- The container now seeds from `data/profile.template.json` — skills and target_titles
  only, since the scorer never reads name/email/phone. **The resume is no longer in the
  repo or the image.** The local copy lives at gitignored `data/Diya_Singh_SWE.pdf`.
- `apify.py` hardcoded path → `APIFY_TOKEN_FILE` env
- `*.pdf` and `assets/` blocked in `.dockerignore` / `.railwayignore`

**Keep it private anyway:** `config.yaml` names 20 real people's LinkedIn profiles.

---

## Operating it

```bash
cd ~/arrai-n8n-mcp/job-radar

# local
./.venv/bin/python -m jobradar.cli run          # full scrape
./.venv/bin/python -m jobradar.cli rescore      # re-grade after a config change
./.venv/bin/python -m jobradar.cli web          # dashboard on :8765

# production
railway variables --service job-radar                    # read config/secrets
railway logs --service job-radar                         # live logs
railway up --service job-radar                           # redeploy
railway ssh --service job-radar "cd /app && python -m jobradar.cli run --only apify_posts"
```

That last one is how to force an out-of-band scrape on the server without waiting for
the cron.

**Regenerating the target lists** (occasionally, not per-run):
```bash
./.venv/bin/python tools/probe_tiers.py             # S/A/B-tier ATS boards
./.venv/bin/python tools/refresh_yc.py              # hiring YC startups (weekly)
./.venv/bin/python tools/resolve_linkedin_companies.py   # verified company IDs
./.venv/bin/python tools/resume_gap.py              # resume gaps vs collected JDs
```

---

## Open items

1. **SMTP creds** — until set, `digest --send` prints instead of emailing. Gmail needs
   an App Password, not the account password.
2. **Repo transfer to diya1827** — initiated 2026-08-03, expires 24h after. If it
   lapsed, re-run `gh api -X POST repos/rahul13292/job-radar/transfer -f new_owner=diya1827`.
   She currently has collaborator/write, which is enough to use it.
3. **Password handover** to Diya.
4. Zomato, Blinkit, Nykaa, Dream11, Zetwerk have no verified LinkedIn company ID — only
   caught by general keyword search. Re-run the resolver to retry.

---

## Resume audit for Diya (2026-08-05 findings)

**Highest-impact fix: her LinkedIn and GitHub are invisible to ATS parsers.** The PDF
embeds 9 working hyperlinks, but the visible text uses icon-font glyphs — extraction
yields `ï Diya Singh` and `§ diya1827`, no URLs. Humans clicking are fine; a resume
parser reading text sees nothing. Fix: write both as plain text.

**Skill gaps**, counted against 29 JDs she actually scores ≥55 on:

| Missing | Share of her target JDs |
|---|---|
| Go | 41% |
| Azure | 38% |
| **Kubernetes** | 34% |
| GCP | 34% |
| Prometheus / Grafana | 21% each |
| Incident response | 17% |

**Kubernetes is the best investment** — she already has Docker, ECS Fargate and
Terraform, so it's a short step, and it unlocks a third of her targets.

Already strong and in demand, should lead every bullet: **AWS 66%, Python 59%,
Java 48%, CI/CD 38%**.

Smaller: CGPA written two ways (8.31 vs 8.307); "final-year student" is stale post-
graduation; the Oracle section has no metrics while Rippling is metric-rich;
"cutting review time by 40%" has no baseline.
