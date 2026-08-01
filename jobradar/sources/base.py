"""Shared HTTP client: one session, real UA, retry with backoff, polite pacing."""
from __future__ import annotations

import html
import random
import re
import time
from typing import Optional

import requests

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

_session = requests.Session()
_session.headers.update({
    "User-Agent": UA,
    "Accept-Language": "en-US,en;q=0.9",
})


class SourceError(RuntimeError):
    pass


def get(url: str, *, params: dict = None, headers: dict = None, timeout: int = 25,
        retries: int = 3, pace: float = 0.8) -> requests.Response:
    last = None
    for attempt in range(retries):
        try:
            r = _session.get(url, params=params, headers=headers, timeout=timeout)
            if r.status_code == 429:
                wait = 4 * (attempt + 1) + random.random() * 2
                time.sleep(wait)
                last = SourceError(f"429 rate limited: {url}")
                continue
            if r.status_code >= 500:
                time.sleep(1.5 * (attempt + 1))
                last = SourceError(f"{r.status_code} from {url}")
                continue
            time.sleep(pace + random.random() * 0.4)
            return r
        except requests.RequestException as e:
            last = e
            time.sleep(1.5 * (attempt + 1))
    raise SourceError(str(last) if last else f"failed: {url}")


def post_json(url: str, payload: dict, *, headers: dict = None, timeout: int = 25,
              retries: int = 2, pace: float = 0.6) -> requests.Response:
    last = None
    h = {"Content-Type": "application/json", "Accept": "application/json"}
    h.update(headers or {})
    for attempt in range(retries):
        try:
            r = _session.post(url, json=payload, headers=h, timeout=timeout)
            if r.status_code >= 500 or r.status_code == 429:
                time.sleep(2 * (attempt + 1))
                last = SourceError(f"{r.status_code} from {url}")
                continue
            time.sleep(pace)
            return r
        except requests.RequestException as e:
            last = e
            time.sleep(1.5 * (attempt + 1))
    raise SourceError(str(last) if last else f"failed: {url}")


TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


def strip_html(s: str) -> str:
    if not s:
        return ""
    s = s.replace("</p>", "\n").replace("<br>", "\n").replace("<br/>", "\n").replace("</li>", "\n")
    s = TAG_RE.sub(" ", s)
    # html.unescape handles the numeric forms too — HN comments are full of &#x2F;
    # and &#x27;, which a hand-rolled replace table silently leaves in place.
    s = html.unescape(s)
    return WS_RE.sub(" ", s).strip()


def is_remote(text: str) -> bool:
    return bool(re.search(r"\b(remote|work from home|anywhere|distributed)\b", text or "", re.I))
