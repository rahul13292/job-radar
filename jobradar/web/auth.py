"""Cookie-session login for the dashboard.

The board is going on the public internet (Railway), and it holds her whole job
search — what she's applied to, what she's saved. That should not be world-readable
just because someone guesses the URL.

Password lives in DASHBOARD_PASSWORD. The cookie is an HMAC of the username plus an
expiry, signed with SESSION_SECRET, so it cannot be forged without the secret and it
expires on its own. No password is ever stored in the cookie.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from typing import Optional

COOKIE = "jr_session"
MAX_AGE = 60 * 60 * 24 * 30      # 30 days


def _secret() -> bytes:
    s = os.getenv("SESSION_SECRET", "")
    if not s:
        # Ephemeral fallback: sessions die on restart, which is the safe failure mode.
        s = secrets.token_hex(32)
        os.environ["SESSION_SECRET"] = s
    return s.encode()


def password() -> str:
    return os.getenv("DASHBOARD_PASSWORD", "")


def auth_required() -> bool:
    """No password configured means local use — don't lock her out of her own laptop."""
    return bool(password())


def check_password(candidate: str) -> bool:
    return hmac.compare_digest(candidate or "", password())


def make_token(user: str = "diya") -> str:
    exp = int(time.time()) + MAX_AGE
    payload = f"{user}:{exp}"
    sig = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}:{sig}"


def valid_token(token: Optional[str]) -> bool:
    if not token:
        return False
    try:
        user, exp, sig = token.rsplit(":", 2)
    except ValueError:
        return False
    if not exp.isdigit() or int(exp) < time.time():
        return False
    expected = hmac.new(_secret(), f"{user}:{exp}".encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, expected)
