"""ATS slugs are lowercase ('mongodb', 'phonepe'), which looks wrong in a digest.
Map the ones whose casing you cannot derive; title-case everything else."""
from __future__ import annotations

OVERRIDES = {
    "mongodb": "MongoDB", "phonepe": "PhonePe", "gitlab": "GitLab", "openai": "OpenAI",
    "1password": "1Password", "hackerone": "HackerOne", "scaleai": "Scale AI",
    "remotecom": "Remote.com", "orcasecurity": "Orca Security", "netskope": "Netskope",
    "jumpcloud": "JumpCloud", "hevodata": "Hevo Data", "openevidence": "OpenEvidence",
    "zscaler": "Zscaler", "datadog": "Datadog", "cloudflare": "Cloudflare",
    "databricks": "Databricks", "bugcrowd": "Bugcrowd", "chainguard": "Chainguard",
    "smartrecruiters": "SmartRecruiters", "paloaltonetworks": "Palo Alto Networks",
    "sentinelone": "SentinelOne", "crowdstrike": "CrowdStrike", "servicenow": "ServiceNow",
    "atlan": "Atlan", "sarvam": "Sarvam AI", "cred": "CRED", "zeta": "Zeta",
}


def display(slug: str) -> str:
    if not slug:
        return ""
    return OVERRIDES.get(slug.lower(), slug.replace("-", " ").replace("_", " ").title())
