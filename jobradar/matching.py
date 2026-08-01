"""Boundary-aware term matching.

Plain `"go" in text` matches "alGOrithms", and `"soc" in text` matches "asSOCiate".
Both fire constantly on job descriptions and quietly inflate every score, so every
skill lookup in this project goes through here instead.
"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Iterable, List


@lru_cache(maxsize=2048)
def term_re(term: str) -> re.Pattern:
    # Not \b — that breaks on terms ending in punctuation like "c++" or "ci/cd".
    # Trailing (?:s|es)? so "code review" still matches "code reviews".
    return re.compile(
        r"(?<![a-z0-9])" + re.escape(term.lower()) + r"(?:es|s)?(?![a-z0-9])", re.I)


def has_term(term: str, text: str) -> bool:
    return bool(term_re(term).search(text or ""))


def matched_terms(terms: Iterable[str], text: str) -> List[str]:
    low = (text or "").lower()
    return [t for t in terms if term_re(t).search(low)]
