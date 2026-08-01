"""Resume gap analysis against the JDs actually collected.

Instead of guessing what a resume is missing, this reads the descriptions of the
highest-scoring roles in the database and reports which terms show up often in those
JDs but never in her resume. That turns "you should add Kubernetes" from an opinion
into a count: how many of the roles she is competitive for ask for it.

    ./.venv/bin/python tools/resume_gap.py --min-score 55
"""
from __future__ import annotations

import argparse
import collections
import re
import sys

sys.path.insert(0, ".")
from jobradar.config import load_config          # noqa: E402
from jobradar.db import Store                    # noqa: E402
from jobradar.matching import matched_terms, has_term   # noqa: E402
from jobradar.resume import extract_text, load_profile  # noqa: E402

# Terms worth checking for in a backend / security JD. Not exhaustive — it's the
# vocabulary that actually gates ATS keyword filters.
CHECK = [
    "kubernetes", "k8s", "helm", "istio", "docker", "terraform", "ansible", "jenkins",
    "aws", "gcp", "azure", "lambda", "s3", "ec2", "eks", "cloudformation",
    "python", "java", "golang", "go", "c++", "typescript", "javascript", "rust", "scala",
    "spring boot", "django", "flask", "fastapi", "node.js", "react", "graphql", "grpc",
    "kafka", "rabbitmq", "redis", "postgresql", "mysql", "mongodb", "elasticsearch",
    "spark", "hadoop", "airflow", "snowflake",
    "microservices", "distributed systems", "system design", "scalability",
    "rest api", "api design", "ci/cd", "devops", "sre", "observability", "prometheus",
    "grafana", "datadog", "splunk", "linux", "git",
    "owasp", "threat modeling", "penetration testing", "vulnerability management",
    "sast", "dast", "siem", "soc 2", "iso 27001", "incident response", "cryptography",
    "iam", "oauth", "saml", "zero trust", "secure coding", "burp suite", "nmap",
    "mitre att&ck", "edr", "xdr", "cspm", "container security", "kubernetes security",
    "machine learning", "llm", "data structures", "algorithms", "unit testing",
    "agile", "scrum", "code review", "debugging",
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-score", type=float, default=55)
    ap.add_argument("--top", type=int, default=30)
    args = ap.parse_args()

    cfg = load_config()
    store = Store(cfg["db_path"])
    profile = load_profile(cfg["profile_path"])
    resume_text = extract_text(profile["source_pdf"])

    rows = [r for r in store.jobs(min_score=args.min_score, limit=2000)
            if (r["description"] or "").strip()]
    if not rows:
        print("No scored jobs with descriptions yet — run a scrape first.")
        return

    counts = collections.Counter()
    for r in rows:
        blob = f"{r['title']} {r['description']}"
        for t in set(matched_terms(CHECK, blob)):
            counts[t] += 1

    in_resume = set(matched_terms(CHECK, resume_text))
    n = len(rows)

    print(f"Analysed {n} job descriptions scoring >= {args.min_score:.0f}\n")

    print("MISSING FROM RESUME — asked for most often")
    print(f"{'term':26} {'JDs':>5}  {'share':>6}")
    gaps = [(t, c) for t, c in counts.most_common() if t not in in_resume]
    for t, c in gaps[:args.top]:
        print(f"{t:26} {c:5}  {c/n*100:5.1f}%")

    print("\nON THE RESUME AND IN DEMAND — lead with these")
    have = [(t, c) for t, c in counts.most_common() if t in in_resume]
    for t, c in have[:12]:
        print(f"{t:26} {c:5}  {c/n*100:5.1f}%")

    print("\nON THE RESUME, RARELY ASKED FOR — candidates for cutting")
    cold = sorted([t for t in in_resume if counts[t] <= max(1, int(n * 0.02))])
    print("  " + ", ".join(cold) if cold else "  (none)")


if __name__ == "__main__":
    main()
