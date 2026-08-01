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
COPY data/tier_boards.yaml data/yc_boards.yaml ./data/

# The SQLite file lives on a Railway volume mounted at /data so saved/applied state
# survives redeploys. DB_PATH and PROFILE_PATH point there.
ENV DB_PATH=/data/jobs.db \
    PROFILE_PATH=/data/profile.json \
    RESUME_PATH=/app/data/resume.pdf \
    PORT=8080

# From assets/, NOT data/ — data/*.pdf is gitignored, and the Railway CLI respects
# .gitignore when uploading the build context. With the PDF under data/ the file never
# reached the builder, this COPY failed before the first log line, and the deploy died
# as "scheduling build" with empty logs. Three deploys failed exactly that way.
COPY assets/resume.pdf /app/data/resume.pdf

# Build the match profile only if the volume doesn't already have one — otherwise a
# redeploy would silently discard any hand-tuning she did to profile.json.
CMD ["sh", "-c", "[ -f \"$PROFILE_PATH\" ] || python -m jobradar.cli init --resume \"$RESUME_PATH\"; exec python -m jobradar.cli web --host 0.0.0.0 --port ${PORT}"]
