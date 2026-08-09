"""Score a job 0-100 against the resume profile, and say why.

Every point is attributable. If a job scores 71 the dashboard shows the six clauses
that produced 71, so you can tune config.yaml instead of guessing at a black box.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from .matching import matched_terms
from .models import Job, Post

# --- title patterns -------------------------------------------------------

CORE_TITLE = re.compile(
    r"\b(software (development )?engineer|sde\b|swe\b|software developer|backend|back-end|"
    r"full[ -]?stack|platform engineer|infrastructure engineer|site reliability|sre\b|"
    r"security engineer|application security|product security|cloud security|infrastructure security|"
    r"appsec|security analyst|detection engineer|security operations|devsecops|devops)\b", re.I)

SECURITY_TITLE = re.compile(
    r"\b(security|appsec|infosec|devsecops|threat|vulnerabilit|detection|soc\b|siem)\b", re.I)

TOO_SENIOR = re.compile(
    r"\b(senior|sr\.?|staff|principal|lead\b|manager|director|head of|vp\b|architect|"
    r"distinguished|fellow|expert|"
    # Ladder titles that don't contain "senior" but sit well above a fresher. Salesforce
    # posts "Software Engineering LMTS - Backend", which scored 87 in her fresher view
    # until these were added. MTS/SMTS/LMTS = (Lead/Senior) Member of Technical Staff.
    r"lmts|smts|pmts|mts\b|member of technical staff|"
    # In Indian services firms these are experienced-hire bands, not entry roles.
    r"specialist|consultant|"
    # Levelled titles. She is a 2026 grad with internships only, so "Engineer II" and
    # "SDE-2" are already a rung above her — those get rejected, not merely penalised.
    r"ii+\b|iv\b|l[2-9]\b|level [2-9]\b|[- ][2-9]\b|grade [b-z]\b)\b", re.I)

JUNIOR_SIGNAL = re.compile(
    r"\b(new grad|new-grad|graduate|entry[- ]level|early career|campus hire|university hire|"
    r"associate|junior|jr\.?|trainee|fresher|0-2 years|1-2 years|1-3 years|apprentice)\b", re.I)

INTERN_TITLE = re.compile(r"\b(intern|internship|co-?op)\b", re.I)

WRONG_FIELD = re.compile(
    r"\b(sales|account executive|recruit|marketing|physician|nurse|driver|teacher|"
    r"mechanical|civil engineer|electrical engineer|hvac|welder|technician|guard|"
    r"customer success|business development|hr\b|accountant|designer|copywriter|"
    # QA / test-automation track — explicitly out of scope. She is a product-engineering
    # candidate; these titles pattern-match on "engineer" and would otherwise flood the list.
    r"\bqa\b|quality assurance|test engineer|testing engineer|sdet|automation tester|"
    r"manual test|tester|quality engineer|test analyst|"
    # Support / services tiers that also read as "engineer"
    r"technical support|support engineer|service desk|help ?desk|field engineer)\b", re.I)

YEARS_REQ = re.compile(r"(\d+)\s*\+?\s*(?:-\s*\d+\s*)?year", re.I)

# --- experience extraction -------------------------------------------------
# A bare "N years" match is not an experience requirement: JDs say "60+ years of
# heritage", "100 years old company", "2 years of runway". A number only counts when
# the surrounding text is talking about the candidate's experience.
YEARS_TOKEN = re.compile(
    r"(\d{1,2})\s*(?:\+|\s*(?:-|–|to)\s*(\d{1,2}))?\s*\+?\s*y(?:ea)?rs?\b", re.I)
EXP_CONTEXT = re.compile(
    r"experience|exp\b|professional|industry|relevant|hands[- ]on|"
    r"work(?:ing)?\s+(?:in|with|as|on)|minimum|at\s?least|track record|"
    r"background in|proficien|expertise", re.I)


def extract_years_req(text: str) -> Optional[int]:
    """The lowest credible years-of-experience bar stated in a JD, or None.

    Lowest, not highest: a JD listing "2+ years" for one duty and "5+ years preferred"
    still admits candidates at the 2-year bar, and the entry bar is what decides
    whether a fresher can apply at all.
    """
    if not text:
        return None
    reqs = []
    for m in YEARS_TOKEN.finditer(text):
        lo = int(m.group(1))
        if lo > 15:      # "60+ years old", "25 years in business" — company age, not a bar
            continue
        ctx = text[max(0, m.start() - 60): m.end() + 60]
        if EXP_CONTEXT.search(ctx):
            reqs.append(lo)
    return min(reqs) if reqs else None

# Google and NVIDIA run separate "Software Engineer, PhD, Early Career" tracks. They
# read as perfect new-grad matches on every other signal and are closed to her — she
# holds a BTech. Title match is a hard reject; JD wording is only rejected when the
# doctorate is stated as required, since plenty of JDs list "PhD a plus".
PHD_TITLE = re.compile(r"\b(ph\.?d|doctoral|doctorate)\b", re.I)
PHD_REQUIRED = re.compile(
    r"(ph\.?d|doctorate)[^.]{0,40}\b(required|degree required|is required)\b|"
    r"\b(must (?:have|hold)|requires?)\b[^.]{0,40}(ph\.?d|doctorate)", re.I)
MASTERS_REQUIRED = re.compile(
    r"\b(master'?s?|m\.?s\.?|m\.?tech)\b[^.]{0,30}\b(required|is required)\b|"
    r"\b(must (?:have|hold)|requires?)\b[^.]{0,30}\bmaster'?s?\b", re.I)

REMOTE_HINT = re.compile(r"\b(remote|work from home|wfh|anywhere|distributed)\b", re.I)

# "Remote - USA" is not remote if you live in Delhi. Geo-locked remote gets treated
# as an off-profile location, not as a remote win.
# Two tiers, because "in India" and "in a city she'd actually take" are different questions.
# PREFERRED are the metros worth applying to; INDIA_GEO is everything else in-country,
# which scores lower rather than being dropped (Chennai/Kolkata/Ahmedabad/Jaipur/Kochi/
# Trivandrum land here — visible if you go looking, never at the top of the list).
PREFERRED_GEO = re.compile(
    r"\b(bengaluru|bangalore|blr\b|delhi|ncr\b|gurgaon|gurugram|noida|"
    r"hyderabad|pune|mumbai|navi mumbai|thane)\b", re.I)
INDIA_GEO = re.compile(
    r"\b(india|bengaluru|bangalore|delhi|ncr|gurgaon|gurugram|noida|hyderabad|pune|"
    r"mumbai|chennai|kolkata|ahmedabad|jaipur|kochi|trivandrum|coimbatore|indore|"
    r"chandigarh|bhubaneswar|nagpur|vadodara|mysuru|mysore)\b", re.I)
NON_INDIA_GEO = re.compile(
    # A bare "us" can't be listed — job copy is full of "join us" / "about us" — so the
    # US forms are matched only next to a work-arrangement word: "Remote (US)", "US-based".
    r"(?:\b(?:remote|hybrid|onsite|on-site)\b[^a-z0-9]{0,4}(?:only[^a-z0-9]{0,4})?(?:us|u\.s\.)\b)|"
    r"\bus[- ]based\b|"
    # \b fails after a trailing period, so "U.S." needs its own branch.
    r"(?<![a-z0-9])u\.s\.|\b(?:us|u\.s\.)\s+(?:work authorization|citizen|person)|"
    r"\b(usa|u\.s\.a?|united states|us only|canada|uk|united kingdom|ireland|germany|"
    r"france|netherlands|poland|portugal|spain|romania|brazil|mexico|argentina|colombia|"
    r"italy|sweden|norway|denmark|finland|switzerland|austria|belgium|czech|hungary|"
    r"greece|turkey|uae|dubai|australia|new zealand|singapore|japan|korea|israel|"
    r"emea|latam|apac|amer|europe|americas|north america|south america|"
    r"new york|san francisco|bay area|seattle|austin|chicago|boston|denver|"
    r"london|berlin|munich|amsterdam|dublin|toronto|vancouver|sydney|tel aviv)\b", re.I)


def _fresh_days(posted_at: str) -> float:
    if not posted_at:
        return 99.0
    try:
        dt = datetime.fromisoformat(posted_at.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0
    except Exception:
        return 99.0


def score_job(job: Job, profile: Dict, cfg: Dict) -> Tuple[float, List[str]]:
    w = cfg.get("weights", {})
    reasons: List[str] = []
    score = 0.0

    title = job.title or ""
    blob = f"{title}\n{job.description or ''}"
    loc = (job.location or "").lower()

    # --- hard gates -------------------------------------------------------
    blocked = [c.lower() for c in cfg.get("blocked_companies", [])]
    if any(b in (job.company or "").lower() for b in blocked):
        return 0.0, [f"rejected: blocked company ({job.company})"]

    if WRONG_FIELD.search(title):
        return 0.0, ["rejected: title is outside software/security"]

    if not CORE_TITLE.search(title):
        # Not an obvious match by title; allow through only if the body is heavily on-profile.
        hits = matched_terms(profile["skills"], blob)
        if len(hits) < cfg.get("offtitle_skill_floor", 6):
            return 0.0, ["rejected: title not a target role"]
        reasons.append(f"off-title but {len(hits)} resume skills in the body")
        score += 8

    if INTERN_TITLE.search(title) and not cfg.get("include_internships", False):
        return 0.0, ["rejected: internship (include_internships is off)"]

    if TOO_SENIOR.search(title) and not cfg.get("include_senior", False):
        return 0.0, [f"rejected: seniority in title ({title.strip()})"]

    if not cfg.get("allow_advanced_degree_roles", False):
        if PHD_TITLE.search(title):
            return 0.0, ["rejected: PhD track (she holds a BTech)"]
        if PHD_REQUIRED.search(job.description or ""):
            return 0.0, ["rejected: JD requires a PhD"]
        if MASTERS_REQUIRED.search(job.description or ""):
            return 0.0, ["rejected: JD requires a Master's"]

    # Years-of-experience wall. Sharp on purpose: a stated bar above the max with no
    # fresher signal anywhere is a reject, not a penalty — Diya's exact complaint was
    # high-scoring roles she opened and couldn't apply to ("sabmei exp rehta hai").
    max_years = cfg.get("max_years_required", 1)
    yreq = extract_years_req(job.description or "")
    job.years_req = yreq
    if yreq is not None and yreq > max_years and not JUNIOR_SIGNAL.search(blob):
        return 0.0, [f"rejected: JD asks for {yreq}+ years experience"]

    # --- title fit --------------------------------------------------------
    if CORE_TITLE.search(title):
        score += w.get("title_match", 25)
        reasons.append(f"target title: {title.strip()}")

    if SECURITY_TITLE.search(title):
        score += w.get("security_bonus", 12)
        reasons.append("security-track role (matches her Rippling experience)")

    if JUNIOR_SIGNAL.search(title) or JUNIOR_SIGNAL.search(job.description or ""):
        score += w.get("junior_bonus", 15)
        reasons.append("new-grad / entry-level signal")

    # --- skill overlap ----------------------------------------------------
    hits = matched_terms(profile["skills"], blob)
    priority = matched_terms(cfg.get("priority_skills", []), blob)
    skill_pts = min(w.get("skill_cap", 30), len(hits) * w.get("per_skill", 2.0)
                    + len(priority) * w.get("per_priority_skill", 2.0))
    if skill_pts:
        score += skill_pts
        top = ", ".join(hits[:8])
        reasons.append(f"{len(hits)} resume skills matched ({top}{'…' if len(hits) > 8 else ''})")

    # --- location ---------------------------------------------------------
    is_remote = job.remote or bool(REMOTE_HINT.search(loc)) or bool(REMOTE_HINT.search(title))
    india = bool(INDIA_GEO.search(loc))
    preferred = bool(PREFERRED_GEO.search(loc))
    offshore_locked = bool(NON_INDIA_GEO.search(loc)) and not india

    if preferred:
        score += w.get("location_match", 12)
        reasons.append(f"preferred metro: {job.location}")
    elif india:
        score -= w.get("india_offmetro", 6)
        reasons.append(f"India but off-metro: {job.location}")
    elif is_remote and not offshore_locked:
        score += w.get("remote_bonus", 8)
        reasons.append("remote, no geo lock")
    elif is_remote and offshore_locked and cfg.get("penalize_offshore", True):
        # e.g. "Remote - USA" — remote in name only if you're applying from India.
        score -= w.get("geo_locked_remote", 12)
        reasons.append(f"remote but geo-locked: {job.location}")
    elif loc and cfg.get("penalize_offshore", True):
        score -= w.get("location_miss", 15)
        reasons.append(f"location off-profile: {job.location}")

    # --- freshness --------------------------------------------------------
    age = _fresh_days(job.posted_at or "")
    if age <= 1:
        score += w.get("fresh_24h", 10)
        reasons.append("posted in the last 24h")
    elif age <= 7:
        score += w.get("fresh_7d", 5)
        reasons.append(f"posted {int(age)}d ago")
    elif age > cfg.get("stale_days", 30):
        score -= w.get("stale_penalty", 8)
        reasons.append(f"stale ({int(age)}d old)")

    # --- company allowlist ------------------------------------------------
    dream = [c.lower() for c in cfg.get("dream_companies", [])]
    if any(d in (job.company or "").lower() for d in dream):
        score += w.get("dream_company", 10)
        reasons.append(f"target company: {job.company}")

    return max(0.0, min(100.0, round(score, 1))), reasons


HIRING_POST = re.compile(
    r"\b(we(?:'re| are) hiring|hiring for|now hiring|is hiring|hiring alert|open role|"
    r"open position|join (?:our|the) team|apply (?:here|now|at|link)|dm me|"
    r"drop your (?:cv|resume)|referral|refer you|looking for a|vacanc|"
    r"opening[s]? (?:for|at)|off[- ]campus|freshers?|"
    # The dominant Indian format is a structured listing, not a sentence: a company,
    # a role, "Batch: 2026", "Apply: <link>". Requiring "we're hiring" threw away the
    # best posts in the whole feed — a Rubrik 2026-batch Bengaluru role scored 0.
    r"apply\s*[:\-]|batch\s*[:\-]\s*20\d\d|for\s+20\d\d\s*(?:,|and|&|\/)?\s*20?\d*\s*grads?|"
    r"stipend\s*[:\-]|role\s*[:\-]|eligibility\s*[:\-]|last date)\b|"
    r"lnkd\.in/", re.I)

POST_NEGATIVE = re.compile(
    r"\b(course|cohort|bootcamp|webinar|masterclass|enroll|my ebook|dm for collab|"
    r"follow me for|like and share|giveaway)\b", re.I)

# These posts stay up and keep scoring well after the role is gone — a "Hiring is
# Closed" slice post scored 87 on its first run.
POST_CLOSED = re.compile(
    r"\b(hiring is closed|applications? (?:are )?closed|position (?:is )?(?:now )?filled|"
    r"role (?:is )?filled|no longer (?:hiring|accepting)|closed for applications|"
    r"link (?:is )?(?:now )?(?:down|closed|expired)|form (?:is )?closed)\b", re.I)


def score_post(post: Post, profile: Dict, cfg: Dict) -> Tuple[float, List[str]]:
    """Posts are noisier than job boards, so the bar to survive is higher."""
    w = cfg.get("weights", {})
    text = post.text or ""
    low = text.lower()
    reasons: List[str] = []
    score = 0.0

    if not HIRING_POST.search(text):
        return 0.0, ["rejected: no hiring intent detected"]
    if POST_CLOSED.search(text[:400]):
        return 0.0, ["rejected: the post says the role is already closed"]
    score += 20
    reasons.append("hiring intent in post text")

    if POST_NEGATIVE.search(text):
        score -= 25
        reasons.append("looks like course/engagement bait")

    if CORE_TITLE.search(text):
        score += w.get("title_match", 25)
        reasons.append("target role named in the post")
    else:
        score -= 10
        reasons.append("no target role named")

    if SECURITY_TITLE.search(text):
        score += w.get("security_bonus", 12)
        reasons.append("security role")

    if JUNIOR_SIGNAL.search(text):
        score += w.get("junior_bonus", 15)
        reasons.append("entry-level / new-grad friendly")

    if TOO_SENIOR.search(text) and not JUNIOR_SIGNAL.search(text):
        score -= 15
        reasons.append("reads senior-only")

    hits = matched_terms(profile["skills"], text)
    if hits:
        score += min(20, len(hits) * 2.5)
        reasons.append(f"{len(hits)} resume skills mentioned ({', '.join(hits[:6])})")

    # Geography matters more here than on job boards: an HN comment reading
    # "London | Onsite" is a hard no from Delhi, but every other signal in it looks great.
    head = text[:300]        # HN posts put "Company | Location | Type" on the first line
    if INDIA_GEO.search(head) or INDIA_GEO.search(text):
        score += w.get("location_match", 12)
        reasons.append("India location mentioned")
    elif REMOTE_HINT.search(head) and not NON_INDIA_GEO.search(head):
        score += w.get("remote_bonus", 8)
        reasons.append("remote, no geo lock")
    elif NON_INDIA_GEO.search(head):
        onsite = re.search(r"\bonsite\b", head, re.I) and not REMOTE_HINT.search(head)
        score -= w.get("location_miss", 15) if onsite else w.get("geo_locked_remote", 12)
        reasons.append(f"{'onsite ' if onsite else ''}outside India")

    if post.apply_hint:
        score += 8
        reasons.append(f"direct apply path: {post.apply_hint}")

    age = _fresh_days(post.posted_at or "")
    if age <= 2:
        score += 10
        reasons.append("posted in the last 48h")

    return max(0.0, min(100.0, round(score, 1))), reasons
