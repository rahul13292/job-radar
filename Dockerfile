FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# lxml needs a compiler toolchain only if no wheel matches; slim images have wheels
# for both arches, so this stays a plain pip install.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY jobradar/ ./jobradar/
COPY tools/ ./tools/
COPY config.yaml ./

# The probe-generated board lists. Without these the container silently loads only the
# hand-maintained boards (75 instead of 170) and nothing warns you — config.py skips
# include_company_files entries that don't exist.
#
# profile.template.json is the match profile with the PII stripped: the scorer only ever
# reads `skills` and `target_titles`, never the name/email/phone. The resume PDF is
# deliberately NOT in this image or the repo — it is a real person's contact details,
# and a container image is the wrong place for them.
COPY data/tier_boards.yaml data/yc_boards.yaml data/profile.template.json ./data/

# The SQLite file lives on a Railway volume mounted at /data so saved/applied state
# survives redeploys. DB_PATH and PROFILE_PATH point there.
ENV DB_PATH=/data/jobs.db \
    PROFILE_PATH=/data/profile.json \
    PORT=8080

# Seed the volume from the template only on a genuinely cold start. A redeploy keeps
# whatever profile is already on the volume, so hand-tuning survives. To use a real
# resume instead, run `jobradar init --resume <pdf>` locally and copy the generated
# profile.json onto the volume — the PDF never needs to reach the server.
CMD ["sh", "-c", "[ -f \"$PROFILE_PATH\" ] || cp /app/data/profile.template.json \"$PROFILE_PATH\"; exec python -m jobradar.cli web --host 0.0.0.0 --port ${PORT}"]
