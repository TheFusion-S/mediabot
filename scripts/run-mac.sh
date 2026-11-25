#!/bin/bash
# MediaBot runner (launchd chaqiradi): Cloudflare tunnel -> WEBAPP_URL ni .env ga yozadi -> botni ishga tushiradi.
# Bot to'xtasa skript ham tugaydi, launchd esa uni qayta ishga tushiradi (yangi tunnel manzili bilan).
set -uo pipefail

APP="$(cd "$(dirname "$0")/.." && pwd)"
cd "$APP" || exit 1
for b in /opt/homebrew/bin /usr/local/bin; do [ -d "$b" ] && PATH="$b:$PATH"; done
export PATH

mkdir -p logs data/downloads
PY="$APP/.venv/bin/python"
ENVT=("$PY" "$APP/scripts/envtool.py")
PORT="$("${ENVT[@]}" get WEB_PORT)"; PORT="${PORT:-8080}"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> logs/run.log; }

TUN_PID=""
cleanup() { [ -n "$TUN_PID" ] && kill "$TUN_PID" 2>/dev/null; }
trap cleanup EXIT

URL=""
if command -v cloudflared >/dev/null 2>&1; then
  : > logs/tunnel.log
  cloudflared tunnel --no-autoupdate --url "http://127.0.0.1:${PORT}" >> logs/tunnel.log 2>&1 &
  TUN_PID=$!
  for _ in $(seq 1 60); do
    URL="$(grep -Eo 'https://[a-z0-9-]+\.trycloudflare\.com' logs/tunnel.log | head -n 1 || true)"
    [ -n "$URL" ] && break
    kill -0 "$TUN_PID" 2>/dev/null || break
    sleep 1
  done
else
  log "cloudflared topilmadi — Mini App'siz ishga tushirilmoqda"
fi

"${ENVT[@]}" set WEBAPP_URL "$URL"
SHOWN="$URL"; [ -n "$SHOWN" ] || SHOWN="<yo‘q, Mini App o‘chiq>"
log "start: WEBAPP_URL=$SHOWN"

# caffeinate -i: bot ishlayotganda Mac "bo'sh turib" uyquga ketmasin (qopqoq yopilsa baribir uxlaydi)
if command -v caffeinate >/dev/null 2>&1; then
  caffeinate -i "$PY" -m bot.main >> logs/bot.log 2>&1
else
  "$PY" -m bot.main >> logs/bot.log 2>&1
fi
code=$?
log "bot to'xtadi (kod $code)"
exit "$code"
