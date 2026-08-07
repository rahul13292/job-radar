"""Core record types shared by every source."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


@dataclass
class Job:
    source: str
    external_id: str
    title: str
    company: str
    location: str = ""
    url: str = ""
    description: str = ""
    posted_at: Optional[str] = None      # ISO8601
    remote: bool = False
    years_req: Optional[int] = None      # lowest stated experience bar; None = unstated
    raw_meta: dict = field(default_factory=dict)

    # filled in by the scorer
    score: float = 0.0
    score_reasons: list = field(default_factory=list)

    @property
    def fingerprint(self) -> str:
        """Same role at the same company from two boards collapses to one row."""
        key = f"{_norm(self.company)}|{_norm(self.title)}|{_norm(self.location)[:24]}"
        return hashlib.sha1(key.encode()).hexdigest()

    def as_row(self) -> dict:
        d = asdict(self)
        d.pop("score_reasons", None)
        d.pop("raw_meta", None)
        return d


@dataclass
class Post:
    """A LinkedIn (or other social) hiring post — a person saying 'we're hiring'."""
    source: str
    external_id: str
    author: str
    author_headline: str = ""
    text: str = ""
    url: str = ""
    posted_at: Optional[str] = None
    company_guess: str = ""
    apply_hint: str = ""          # email / link pulled out of the post body
    raw_meta: dict = field(default_factory=dict)

    score: float = 0.0
    score_reasons: list = field(default_factory=list)

    @property
    def fingerprint(self) -> str:
        return hashlib.sha1(f"{_norm(self.author)}|{_norm(self.text)[:180]}".encode()).hexdigest()

    def as_row(self) -> dict:
        d = asdict(self)
        d.pop("score_reasons", None)
        d.pop("raw_meta", None)
        return d


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
