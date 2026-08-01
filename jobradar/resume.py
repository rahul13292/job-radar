"""Turn a resume PDF into a matching profile: skills, titles, seniority band.

Deliberately dumb and inspectable — it writes profile.json, which you then hand-edit.
No LLM call, so it costs nothing and gives the same answer every run.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List

# Canonical vocabulary. If a term appears in the resume, it becomes a match keyword.
SKILL_VOCAB = [
    # languages
    "python", "c++", "java", "javascript", "typescript", "sql", "go", "golang", "rust", "bash",
    # backend
    "fastapi", "flask", "django", "rest api", "restful", "microservices", "graphql", "grpc",
    "backend", "distributed systems", "system design", "api design", "asyncio", "celery",
    # data / infra
    "postgres", "postgresql", "mysql", "redis", "kafka", "mongodb", "elasticsearch", "dynamodb",
    # cloud / devops
    "aws", "lambda", "ecs", "fargate", "ec2", "s3", "cloudwatch", "gcp", "azure", "oci",
    "docker", "kubernetes", "terraform", "github actions", "ci/cd", "jenkins", "cloud-native",
    "observability", "monitoring", "linux",
    # security
    "security", "appsec", "application security", "product security", "cloud security",
    "vulnerability", "mitre att&ck", "siem", "soc", "detection", "threat", "incident response",
    "penetration testing", "secure coding", "iam", "sso", "okta", "cognito", "semgrep",
    "sast", "dast", "gitleaks", "sentinelone", "cloudflare", "zero trust", "compliance",
    # ml / ai
    "machine learning", "random forest", "llm", "openai", "gemini", "tool calling", "rag",
    # practice
    "unit testing", "integration testing", "code review", "agile", "jira", "debugging",
]

TITLE_SEEDS = [
    "software engineer", "software development engineer", "sde", "backend engineer",
    "security engineer", "application security engineer", "product security engineer",
    "cloud security engineer", "platform engineer", "devops engineer", "site reliability",
]


def extract_text(pdf_path: str) -> str:
    import fitz  # pymupdf

    doc = fitz.open(pdf_path)
    return "\n".join(page.get_text() for page in doc)


def build_profile(pdf_path: str, out_path: str = "") -> Dict:
    from .matching import matched_terms

    text = extract_text(pdf_path)
    skills = sorted(set(matched_terms(SKILL_VOCAB, text)))

    emails = re.findall(r"[\w.+-]+@[\w-]+\.[\w.]+", text)
    phones = re.findall(r"\+?\d[\d\s\-]{8,}\d", text)
    name = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")

    # Graduation year drives the new-grad boost.
    grad_years = [int(y) for y in re.findall(r"20(\d{2})\s*[-–)]", text)]
    grad_years = [2000 + y for y in grad_years if 2000 + y >= 2020]
    grad_year = max(grad_years) if grad_years else None

    profile = {
        "name": name,
        "email": emails[0] if emails else "",
        "phone": phones[0].strip() if phones else "",
        "grad_year": grad_year,
        "years_experience": 1,          # internships only — hand-edit if that changes
        "skills": skills,
        "target_titles": TITLE_SEEDS,
        "source_pdf": str(Path(pdf_path).resolve()),
        "resume_chars": len(text),
    }
    if out_path:
        Path(out_path).write_text(json.dumps(profile, indent=2))
    return profile


def load_profile(path: str) -> Dict:
    return json.loads(Path(path).read_text())
