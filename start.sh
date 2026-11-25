#!/usr/bin/env bash
# MediaBot — Docker'siz ishga tushirish (Linux / macOS)
set -euo pipefail
cd "$(dirname "$0")"

need() { command -v "$1" >/dev/null 2>&1 || { echo "❌ '$1' topilmadi. $2"; exit 1; }; }
need python3 "Python 3.12+ o'rnating: https://www.python.org/downloads/"
need ffmpeg  "ffmpeg o'rnating: macOS: brew install ffmpeg | Ubuntu: sudo apt install ffmpeg"
need ffprobe "ffmpeg paketini o'rnating (ffprobe u bilan birga keladi)"
command -v deno >/dev/null 2>&1 || echo "⚠️  deno topilmadi — YouTube'dagi ba'zi formatlar chiqmasligi mumkin. O'rnatish: https://deno.com"

python3 - <<'PY' || { echo "❌ Python 3.12 yoki yangiroq kerak"; exit 1; }
import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)
PY

if [ ! -f .env ]; then
  cp .env.example .env
  chmod 600 .env
  echo "📝 .env fayli yaratildi. Uni oching, BOT_TOKEN ni yozing va skriptni qayta ishga tushiring."
  exit 0
fi

if [ ! -d .venv ]; then
  echo "📦 Virtual muhit yaratilmoqda..."
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
if [ ! -f .venv/.installed ] || [ requirements.txt -nt .venv/.installed ]; then
  echo "📦 Kutubxonalar o'rnatilmoqda (bir marta)..."
  pip install --upgrade pip >/dev/null
  pip install -r requirements.txt -c requirements.lock
  touch .venv/.installed
fi

mkdir -p data/downloads
echo "▶️  Bot ishga tushdi. To'xtatish: Ctrl+C"
exec python -m bot.main
