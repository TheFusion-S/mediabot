# Base image pinned by tag AND digest (SEC-L6; multi-arch index digest from Docker Hub, 2026-02-25).
# To refresh: docker buildx imagetools inspect python:3.12.12-slim-bookworm
ARG PYTHON_IMAGE=python:3.12.12-slim-bookworm@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c
# Deno = JavaScript runtime yt-dlp needs for YouTube's JS challenges (QA-M5). Official binary image, pinned.
ARG DENO_IMAGE=denoland/deno:bin-2.5.4@sha256:1245e9856180be858aebeefdff2c3b98dc01e8ea667b48f4fb64647dc56bb61d

FROM ${DENO_IMAGE} AS deno

FROM ${PYTHON_IMAGE}

# 1 = upgrade yt-dlp to the newest release at build time (YouTube/Instagram change often):
#   docker compose build --build-arg YTDLP_UPGRADE=1
ARG YTDLP_UPGRADE=0

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=deno /deno /usr/local/bin/deno
RUN deno --version

WORKDIR /app
COPY requirements.txt requirements.lock ./
RUN pip install -r requirements.txt -c requirements.lock \
    && if [ "$YTDLP_UPGRADE" = "1" ]; then pip install --upgrade "yt-dlp[default]"; fi \
    && python -m yt_dlp --version

COPY bot ./bot
COPY webapp ./webapp
COPY assets ./assets
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

RUN chmod 0755 /usr/local/bin/docker-entrypoint.sh \
    && useradd --create-home --uid 10001 mediabot \
    && mkdir -p /app/data/downloads \
    && chown -R mediabot:mediabot /app/data
USER mediabot

# /app/data must be writable by uid 10001 (named volume does this automatically).
# Caches go to /tmp so the root filesystem can be mounted read-only.
ENV DOWNLOAD_DIR=/app/data/downloads \
    DB_PATH=/app/data/mediabot.db \
    WEB_HOST=0.0.0.0 \
    WEB_PORT=8080 \
    MAX_CONCURRENT_DOWNLOADS=1 \
    DENO_DIR=/tmp/deno \
    XDG_CACHE_HOME=/tmp/.cache

EXPOSE 8080
VOLUME ["/app/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,os; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"WEB_PORT\",\"8080\")}/healthz', timeout=4)" || exit 1

STOPSIGNAL SIGTERM
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["python", "-m", "bot.main"]
