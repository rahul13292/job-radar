from __future__ import annotations

import os
from pathlib import Path
from typing import Dict

import yaml

ROOT = Path(__file__).resolve().parent.parent


def load_env(path: str = "") -> None:
    """Tiny .env loader — avoids a dependency for six lines of parsing."""
    p = Path(path or ROOT / ".env")
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def load_config(path: str = "") -> Dict:
    p = Path(path or ROOT / "config.yaml")
    cfg = yaml.safe_load(p.read_text())
    cfg["_root"] = str(ROOT)
    # Env wins, so the container can point both at the mounted volume.
    cfg["db_path"] = os.getenv("DB_PATH") or cfg["db_path"]
    cfg["profile_path"] = os.getenv("PROFILE_PATH") or cfg["profile_path"]
    for key in ("db_path", "profile_path"):
        if not os.path.isabs(cfg[key]):
            cfg[key] = str(ROOT / cfg[key])

    # Workday tenants are declared separately for readability, but the ATS source
    # handles them, so fold them into the one list it iterates.
    cfg.setdefault("companies", [])
    cfg["companies"] = list(cfg["companies"]) + list(cfg.get("workday") or [])

    # Boards discovered by tools/refresh_yc.py live in their own file so a weekly
    # refresh never has to rewrite hand-maintained config.
    for rel in cfg.get("include_company_files") or []:
        f = Path(rel) if os.path.isabs(rel) else ROOT / rel
        if not f.exists():
            continue
        try:
            extra = yaml.safe_load(f.read_text()) or {}
        except Exception:
            continue
        cfg["companies"].extend(extra.get("companies") or [])

    # The tracked-creator list names real individuals, so it lives outside the repo.
    cf = cfg.get("creator_file")
    if cf and not cfg.get("linkedin_creators"):
        f = Path(cf) if os.path.isabs(cf) else ROOT / cf
        if f.exists():
            try:
                cfg["linkedin_creators"] = (yaml.safe_load(f.read_text()) or {}).get(
                    "linkedin_creators", [])
            except Exception:
                cfg["linkedin_creators"] = []

    # De-dupe: a company can legitimately appear in both the curated list and the
    # YC file, and scraping the same board twice just wastes a request.
    seen, merged = set(), []
    for c in cfg["companies"]:
        key = (c.get("ats"), c.get("slug") or c.get("tenant"))
        if key in seen:
            continue
        seen.add(key)
        merged.append(c)
    cfg["companies"] = merged
    return cfg
