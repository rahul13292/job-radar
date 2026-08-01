from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from ..db import Store
from . import auth

HERE = Path(__file__).resolve().parent

PUBLIC_PATHS = {"/login", "/healthz"}


def create_app(cfg: dict) -> FastAPI:
    app = FastAPI(title="Job Radar", docs_url=None, redoc_url=None)
    templates = Jinja2Templates(directory=str(HERE / "templates"))
    store = Store(cfg["db_path"])

    # ---------------------------------------------------------------- auth gate

    @app.middleware("http")
    async def gate(request: Request, call_next):
        if auth.auth_required() and request.url.path not in PUBLIC_PATHS:
            if not auth.valid_token(request.cookies.get(auth.COOKIE)):
                if request.method == "GET":
                    return RedirectResponse("/login", status_code=303)
                return Response("login required", status_code=401)
        return await call_next(request)

    def reasons(row) -> list:
        try:
            return json.loads(row["reasons"] or "[]")
        except Exception:
            return []

    def base_ctx(tab: str) -> dict:
        return {"counts": store.counts(), "runs": store.last_runs(8), "tab": tab,
                "locked": auth.auth_required()}

    # ---------------------------------------------------------------- login

    @app.get("/login", response_class=HTMLResponse)
    def login_form(request: Request, bad: int = 0):
        if not auth.auth_required():
            return RedirectResponse("/", status_code=303)
        return templates.TemplateResponse(request, "login.html", {"bad": bad})

    @app.post("/login")
    def login(password: str = Form(...)):
        if not auth.check_password(password):
            time.sleep(0.8)      # blunt but effective brute-force throttle
            return RedirectResponse("/login?bad=1", status_code=303)
        resp = RedirectResponse("/", status_code=303)
        resp.set_cookie(auth.COOKIE, auth.make_token(), max_age=auth.MAX_AGE,
                        httponly=True, samesite="lax",
                        secure=bool(os.getenv("COOKIE_SECURE", "")))
        return resp

    @app.get("/logout")
    def logout():
        resp = RedirectResponse("/login", status_code=303)
        resp.delete_cookie(auth.COOKIE)
        return resp

    @app.get("/healthz")
    def healthz():
        c = store.counts()
        return {"ok": True, "jobs": c["jobs"], "posts": c["posts"]}

    # ---------------------------------------------------------------- pages

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request, min_score: float = None, status: str = "new",
              source: str = "", q: str = "", sort: str = "score"):
        floor = cfg["min_score_dashboard"] if min_score is None else min_score
        rows = store.jobs(min_score=floor, status=status or "", limit=500, source=source)
        if q:
            ql = q.lower()
            rows = [r for r in rows
                    if ql in (r["title"] or "").lower()
                    or ql in (r["company"] or "").lower()
                    or ql in (r["description"] or "").lower()]
        if sort == "new":
            rows = sorted(rows, key=lambda r: r["first_seen"] or "", reverse=True)
        elif sort == "posted":
            rows = sorted(rows, key=lambda r: r["posted_at"] or "", reverse=True)

        sources = [r[0] for r in store.conn.execute(
            "SELECT DISTINCT source FROM jobs ORDER BY source").fetchall()]
        ctx = base_ctx("jobs")
        ctx.update({"rows": rows, "reasons": reasons, "floor": floor, "status": status,
                    "source": source, "q": q, "sources": sources, "sort": sort})
        return templates.TemplateResponse(request, "index.html", ctx)

    @app.get("/posts", response_class=HTMLResponse)
    def posts(request: Request, min_score: float = 35, status: str = "new"):
        rows = store.posts(min_score=min_score, status=status or "", limit=300)
        ctx = base_ctx("posts")
        ctx.update({"rows": rows, "reasons": reasons, "floor": min_score, "status": status})
        return templates.TemplateResponse(request, "posts.html", ctx)

    @app.get("/tracker", response_class=HTMLResponse)
    def tracker(request: Request):
        applied = store.conn.execute(
            "SELECT * FROM jobs WHERE status='applied' "
            "ORDER BY COALESCE(status_at,'') DESC").fetchall()
        saved = store.conn.execute(
            "SELECT * FROM jobs WHERE status='saved' ORDER BY score DESC").fetchall()
        ctx = base_ctx("tracker")
        ctx.update({"applied": applied, "saved": saved, "reasons": reasons})
        return templates.TemplateResponse(request, "tracker.html", ctx)

    # ---------------------------------------------------------------- actions

    @app.post("/mark")
    def mark(table: str = Form(...), fingerprint: str = Form(...),
             status: str = Form(...), back: str = Form("/")):
        store.set_status(table, fingerprint, status)
        return RedirectResponse(back or "/", status_code=303)

    @app.post("/note")
    def note(table: str = Form(...), fingerprint: str = Form(...),
             note: str = Form(""), back: str = Form("/tracker")):
        store.set_note(table, fingerprint, note)
        return RedirectResponse(back or "/tracker", status_code=303)

    @app.post("/refresh")
    def refresh(back: str = Form("/")):
        # Button clicks scrape free sources only — Apify costs money per run and
        # belongs to the daily scheduler, not to an unbounded UI action.
        env = {**os.environ, "JOBRADAR_FREE_ONLY": "1"}
        subprocess.Popen([sys.executable, "-m", "jobradar.cli", "run"],
                         cwd=cfg["_root"], env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return RedirectResponse(back or "/", status_code=303)

    @app.get("/export.xlsx")
    def export_xlsx():
        from ..export_xlsx import build
        data = build(store)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return Response(
            content=data,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition":
                     f'attachment; filename="job-radar-{stamp}.xlsx"'})

    return app
