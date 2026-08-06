"""Cold email + LinkedIn DM drafts for the roles worth chasing directly.

Applying through a portal puts her in a stack of 800. A short, specific note to the
person who owns the team is a different conversation, and for a startup that just
raised, it often lands before the role is even posted.

Design notes:

- **No LLM.** Same reason as the scorer: free, deterministic, reviewable. What makes a
  cold message work here isn't fluent prose, it's the *specific true detail* — the
  overlapping tech pulled from the actual job description, the funding round from the
  actual news feed, the proof that matches what they're building. Those come from data
  we already hold, so a template with real variables beats generated filler.
- **Every claim is drawn from her resume.** Nothing here invents experience. If a proof
  point doesn't apply to the role, it isn't used.
- Drafts are drafts. She reads and edits before anything sends; nothing here sends.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Optional

from .matching import matched_terms

# --------------------------------------------------------------------------- her USPs
#
# Ordered by strength. Each carries the tech it speaks to, so the generator can pick the
# proof that actually overlaps the role instead of leading with the same line every time.

USPS = [
    {
        "id": "rippling_security",
        "tech": ["security", "application security", "appsec", "mitre att&ck", "siem",
                 "detection", "vulnerability", "threat", "soc", "incident response",
                 "sentinelone", "cloudflare", "secure coding"],
        "one_line": "spent six months as a security engineer at Rippling",
        "proof": ("At Rippling I built a cloud-native security platform in FastAPI on AWS "
                  "Lambda, ingesting SentinelOne, Cloudflare and GitHub Security into a "
                  "real-time MITRE ATT&CK dashboard covering 300-450 techniques per domain."),
        "short": "security engineering at Rippling (MITRE ATT&CK dashboard, 300-450 techniques)",
    },
    {
        "id": "llm_tooling",
        "tech": ["llm", "openai", "gemini", "rag", "agent", "tool calling", "ai",
                 "machine learning", "genai"],
        "one_line": "built an LLM tool-calling assistant that cut a 2-hour analysis to seconds",
        "proof": ("I built an LLM tool-calling assistant at Rippling that compressed a "
                  "2+ hour manual analysis into seconds, and shipped Sentinel AI, a "
                  "provider-agnostic agentic code reviewer with sandboxed execution, "
                  "live on Render and Vercel."),
        "short": "LLM tool-calling assistant, 2+ hours of manual analysis down to seconds",
    },
    {
        "id": "cloud_infra",
        "tech": ["aws", "docker", "terraform", "ci/cd", "kubernetes", "ecs", "lambda",
                 "github actions", "devops", "platform", "infrastructure", "sre",
                 "observability", "monitoring"],
        "one_line": "automated CI/CD and containerised deploys across 800+ repositories",
        "proof": ("I automated CI/CD and containerised deployments across 800+ repositories "
                  "at Rippling using GitHub Actions, Docker and Terraform, and instrumented "
                  "the logging and metrics behind them."),
        "short": "CI/CD + Terraform across 800+ repos",
    },
    {
        "id": "backend",
        "tech": ["python", "fastapi", "backend", "microservices", "rest api", "restful",
                 "distributed systems", "api design", "flask", "system design", "scalability"],
        "one_line": "builds Python backends and microservices that ship",
        "proof": ("I build Python backends end to end. At Rippling that meant FastAPI "
                  "microservices on ECS Fargate with Cognito SSO; on my own projects it "
                  "means shipping them live, not leaving them in a repo."),
        "short": "Python/FastAPI microservices on AWS",
    },
    {
        "id": "shipped_side",
        "tech": ["next.js", "react", "full stack", "fullstack", "typescript", "product"],
        "one_line": "ships side projects all the way to production",
        "proof": ("Sentinel AI is mine end to end: FastAPI plus Next.js, a multi-turn "
                  "agentic tool-calling loop with sandboxed execution and JSON repair, "
                  "Dockerised on Render with the frontend on Vercel and CI auto-deploy."),
        "short": "Sentinel AI, shipped live end to end",
    },
]

CREDS = [
    "final-year Software Engineering at Delhi Technological University, 8.31 CGPA",
    "top 1.5% in JEE Mains out of a million+ candidates",
    "Millennium Fellow, 4% acceptance from 60,000+ applicants",
]

LINKS = {
    "github": "https://github.com/diya1827",
    "linkedin": "https://www.linkedin.com/in/diya-singh-478988269/",
    "sentinel": "https://github.com/diya1827/Sentinel-AI",
}


# --------------------------------------------------------------------------- helpers

def _funding_hook(company: str, news: List[Dict]) -> Optional[Dict]:
    """Match a company against the funding feed so the opener can cite the round."""
    c = re.sub(r"[^a-z0-9]", "", (company or "").lower())
    if len(c) < 4:
        return None
    for e in news:
        for cand in e.get("candidates", []):
            n = re.sub(r"[^a-z0-9]", "", cand.lower())
            if n and (n == c or (len(n) > 5 and n in c) or (len(c) > 5 and c in n)):
                return e
    return None


def load_funding_news(root: str) -> List[Dict]:
    p = Path(root) / "data" / "funding_news.json"
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text())
    except Exception:
        return []


def pick_usps(job_text: str, limit: int = 2) -> List[Dict]:
    """Rank her proof points by overlap with this specific role."""
    scored = []
    for u in USPS:
        hits = matched_terms(u["tech"], job_text)
        if hits:
            scored.append((len(hits), USPS.index(u), u, hits))
    scored.sort(key=lambda x: (-x[0], x[1]))
    if not scored:                     # nothing overlapped — lead with backend
        return [USPS[3]]
    return [u for _, _, u, _ in scored[:limit]]


def overlap_terms(job_text: str, profile: Dict, limit: int = 4) -> List[str]:
    """The concrete tech both she and the role have, for the 'why me' line."""
    hits = matched_terms(profile.get("skills", []), job_text)
    priority = ["python", "fastapi", "aws", "terraform", "docker", "kubernetes",
                "security", "application security", "microservices", "ci/cd", "linux"]
    ranked = [t for t in priority if t in hits] + [t for t in hits if t not in priority]
    return ranked[:limit]


# --------------------------------------------------------------------------- drafts

def email_draft(job: Dict, profile: Dict, news: List[Dict]) -> Dict:
    company = job.get("company") or "your team"
    title = (job.get("title") or "the engineering role").strip()
    blob = f"{title}\n{job.get('description') or ''}"
    usps = pick_usps(blob)
    overlap = overlap_terms(blob, profile)
    hook = _funding_hook(company, news)

    if hook:
        amount = hook.get("amount") or "a new round"
        rnd = f" {hook['round']}" if hook.get("round") else ""
        opener = (f"Congrats on the {amount}{rnd}. Teams usually start hiring engineers "
                  f"right after that, which is why I'm writing before the roles go up.")
    else:
        opener = (f"I saw {company} is hiring for {title} and wanted to reach you directly "
                  f"rather than add one more application to the pile.")

    tech_line = ""
    if overlap:
        listed = ", ".join(overlap[:3])
        tech_line = f"The stack lines up: {listed}. "

    body = usps[0]["proof"]
    # Second proof gets its own paragraph. Run together they read as a wall and the
    # strongest line stops landing.
    second = f"\n\n{usps[1]['proof']}" if len(usps) > 1 else ""

    # No em dashes anywhere in these drafts: they are the clearest tell that a message
    # was machine-written, which is exactly the impression a cold note cannot afford.
    subject = (f"{title}: {usps[0]['short']}" if not hook
               else f"{company} post-raise hiring: {usps[0]['short']}")
    subject = subject[:78]

    text = f"""Hi,

{opener}

{tech_line}I'm Diya, {CREDS[0]}.

{body}{second}

Code: {LINKS['sentinel']}
GitHub: {LINKS['github']}

Would a 15-minute call this week be useful? Happy to send my resume either way.

Diya Singh
{LINKS['linkedin']}"""

    return {"channel": "email", "subject": subject, "body": text,
            "company": company, "title": title,
            "hook": (hook or {}).get("headline", ""), "overlap": overlap,
            "usps": [u["id"] for u in usps], "url": job.get("url", "")}


def dm_draft(job: Dict, profile: Dict, news: List[Dict]) -> Dict:
    """LinkedIn caps connection notes at 300 characters, so this is a different shape,
    not a trimmed email."""
    company = job.get("company") or "your team"
    title = (job.get("title") or "the role").strip()
    blob = f"{title}\n{job.get('description') or ''}"
    usps = pick_usps(blob, limit=1)
    hook = _funding_hook(company, news)

    if hook and hook.get("amount"):
        first = f"Congrats on the {hook['amount']}."
    else:
        first = f"Saw {company} is hiring {title}."

    text = (f"{first} I'm a 2026 DTU grad who did {usps[0]['short']}. "
            f"Would love to be considered, happy to send my resume or a short Loom. "
            f"Portfolio: github.com/diya1827")

    if len(text) > 300:                # hard LinkedIn limit on connection notes
        text = (f"{first} 2026 DTU grad, {usps[0]['short']}. "
                f"Would love to be considered. github.com/diya1827")
    return {"channel": "linkedin_dm", "body": text[:300], "company": company,
            "title": title, "chars": len(text[:300]), "url": job.get("url", "")}


def build(jobs: List[Dict], profile: Dict, root: str) -> List[Dict]:
    news = load_funding_news(root)
    out = []
    for j in jobs:
        out.append({
            "company": j.get("company"),
            "title": j.get("title"),
            "score": j.get("score"),
            "url": j.get("url"),
            "email": email_draft(j, profile, news),
            "dm": dm_draft(j, profile, news),
        })
    return out
