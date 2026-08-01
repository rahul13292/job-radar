# Deploying Job Radar to Railway

One service, one bill. The daily scrape runs inside the web process on a background
thread rather than as a second Railway service, because Railway bills idle RAM and a
second always-on service would roughly double the cost of a board that mostly sits idle.

## 1. Create the service

```bash
cd job-radar
railway login                # already logged in as admin@arraitech.com
railway init                 # or: railway link  (to attach to an existing project)
```

## 2. Add a volume — do this before the first deploy

The SQLite file holds everything she has saved and applied to. Without a volume it is
wiped on every redeploy.

In the Railway dashboard: **service → Variables → Volumes → New Volume**, mount path `/data`.

## 3. Set variables

```bash
railway variables --set "DASHBOARD_PASSWORD=<pick a real one>" \
                  --set "SESSION_SECRET=$(openssl rand -hex 32)" \
                  --set "COOKIE_SECURE=1" \
                  --set "DB_PATH=/data/jobs.db" \
                  --set "PROFILE_PATH=/data/profile.json" \
                  --set "SCRAPE_HOUR_UTC=3"
```

| Variable | Purpose |
|---|---|
| `DASHBOARD_PASSWORD` | **Required in production.** Empty means no login at all. |
| `SESSION_SECRET` | Signs the session cookie. If unset, a random one is generated per boot, so every restart logs her out. |
| `COOKIE_SECURE` | Set to `1` — Railway serves HTTPS, so the cookie should be HTTPS-only. |
| `DB_PATH` / `PROFILE_PATH` | Point at the mounted volume. |
| `SCRAPE_HOUR_UTC` | Daily scrape hour. `3` = 08:30 IST. |
| `SCRAPE_ON_BOOT` | `1` (default) fills an empty database on first deploy. Set `0` later. |
| `RUN_SCHEDULER` | `0` disables the daily scrape entirely. |
| `SMTP_*`, `DIGEST_TO` | Optional. Set them and the scheduler emails a digest after each scrape. |
| `APIFY_TOKENS` | Optional, comma-separated. Only needed if `sources.apify.enabled` is on. |

## 4. Deploy

```bash
railway up
railway domain          # generates the public URL
```

Health check is `GET /healthz`, which returns row counts — Railway uses it to decide
the deploy succeeded.

## 5. Verify

```bash
curl -s https://<your-domain>/healthz          # {"ok":true,...}
curl -s -o /dev/null -w "%{http_code}\n" https://<your-domain>/    # 303 -> /login
```

Then open the URL, log in, and confirm the Roles tab has rows. First boot runs a scrape
about 20 seconds in and takes roughly 6-10 minutes to fill.

## Cost note

This is a small always-on container plus a volume. On the Hobby plan the bill is driven
by idle RAM, not by the scrape. Keeping it to one service and one replica is the whole
cost strategy — don't split the scheduler into its own service.

## Local Docker check

The image was built and run locally before this doc was written:

```bash
docker build -t jobradar .
docker run --rm -p 8099:8080 \
  -e DASHBOARD_PASSWORD=test123 -e SESSION_SECRET=xyz -e RUN_SCHEDULER=0 \
  -e DB_PATH=/data/jobs.db -e PROFILE_PATH=/data/profile.json \
  -v "$PWD/.localdata:/data" jobradar
```
