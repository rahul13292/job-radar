"""Digest output: markdown to stdout always, email if SMTP is configured."""
from __future__ import annotations

import json
import os
import smtplib
from email.message import EmailMessage
from typing import List

from .db import Store


def _reasons(row) -> str:
    try:
        return " · ".join(json.loads(row["reasons"] or "[]")[:3])
    except Exception:
        return ""


def build_digest(store: Store, min_score: float) -> tuple:
    jobs = store.undelivered("jobs", min_score)
    posts = store.undelivered("posts", min_score)
    if not jobs and not posts:
        return "", "", [], []

    lines = [f"# Job Radar — {len(jobs)} new roles, {len(posts)} new hiring posts", ""]
    html = ["<h2 style='font-family:system-ui'>Job Radar</h2>"]

    if jobs:
        lines.append("## Roles")
        html.append("<h3 style='font-family:system-ui'>Roles</h3><ol style='font-family:system-ui;line-height:1.5'>")
        for r in jobs:
            loc = r["location"] or ("Remote" if r["remote"] else "")
            lines.append(f"- **{int(r['score'])}** · [{r['title']}]({r['url']}) — {r['company']} · {loc}")
            lines.append(f"    - {_reasons(r)}")
            html.append(
                f"<li><b>{int(r['score'])}</b> · <a href=\"{r['url']}\">{r['title']}</a> — "
                f"{r['company']} · {loc}<br><span style='color:#666;font-size:13px'>{_reasons(r)}</span></li>")
        html.append("</ol>")

    if posts:
        lines.append("")
        lines.append("## Hiring posts")
        html.append("<h3 style='font-family:system-ui'>Hiring posts</h3><ol style='font-family:system-ui;line-height:1.5'>")
        for r in posts:
            snippet = (r["text"] or "")[:220].replace("\n", " ")
            lines.append(f"- **{int(r['score'])}** · {r['author']} — {r['url']}")
            lines.append(f"    - {snippet}…")
            if r["apply_hint"]:
                lines.append(f"    - apply: {r['apply_hint']}")
            html.append(
                f"<li><b>{int(r['score'])}</b> · {r['author']} "
                f"<a href=\"{r['url']}\">[post]</a><br>"
                f"<span style='color:#666;font-size:13px'>{snippet}…</span>"
                + (f"<br><b>apply:</b> {r['apply_hint']}" if r["apply_hint"] else "") + "</li>")
        html.append("</ol>")

    return "\n".join(lines), "".join(html), [r["fingerprint"] for r in jobs], [r["fingerprint"] for r in posts]


def send_email(subject: str, html_body: str, text_body: str) -> str:
    host = os.getenv("SMTP_HOST", "")
    user = os.getenv("SMTP_USER", "")
    pw = os.getenv("SMTP_PASS", "")
    to = os.getenv("DIGEST_TO", "")
    if not (host and user and pw and to):
        return "smtp not configured (SMTP_HOST/SMTP_USER/SMTP_PASS/DIGEST_TO) — printed only"

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = os.getenv("SMTP_FROM", user)
    msg["To"] = to
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")

    port = int(os.getenv("SMTP_PORT", "587"))
    if port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=30) as s:
            s.login(user, pw)
            s.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=30) as s:
            s.starttls()
            s.login(user, pw)
            s.send_message(msg)
    return f"emailed {to}"
