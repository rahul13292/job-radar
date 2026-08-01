#!/usr/bin/env bash
# One-shot: scrape everything, then email the digest if SMTP is configured.
# Wire this to cron/launchd for a daily 9am run:
#   crontab -e
#   0 9 * * * /Users/rahul/arrai-n8n-mcp/job-radar/run.sh >> /tmp/jobradar.log 2>&1
set -euo pipefail
cd "$(dirname "$0")"
./.venv/bin/python -m jobradar.cli run
./.venv/bin/python -m jobradar.cli digest --send
