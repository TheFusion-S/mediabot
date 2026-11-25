#!/bin/sh
# Checks that the data directories are writable by the (non-root) container user before
# starting the bot, and explains how to fix it instead of crash-looping with a traceback.
set -eu

# PaaS (Back4App, Render, Koyeb...) o'z portini PORT orqali beradi — bot o'sha portda tinglasin.
if [ -n "${PORT:-}" ]; then
    WEB_PORT="$PORT"
    export WEB_PORT
fi

uid="$(id -u)"
gid="$(id -g)"
db_dir="$(dirname "${DB_PATH:-/app/data/mediabot.db}")"
dl_dir="${DOWNLOAD_DIR:-/app/data/downloads}"

for d in "$db_dir" "$dl_dir"; do
    mkdir -p "$d" 2>/dev/null || true
    probe="$d/.write-test.$$"
    if [ -d "$d" ] && (: > "$probe") 2>/dev/null; then
        rm -f "$probe"
    else
        echo "XATO: '$d' papkasiga yozib bo'lmaydi (konteyner foydalanuvchisi uid=$uid)." >&2
        echo "  Yechim: docker-compose.yml dagi named volume (mediabot-data) dan foydalaning yoki" >&2
        echo "  bind mount uchun hostda: sudo chown -R $uid:$gid ./data" >&2
        echo "ERROR: '$d' is not writable by uid $uid. Use the named volume or chown the host directory." >&2
        exit 78
    fi
done

if [ -n "${COOKIES_FILE:-}" ] && [ ! -r "$COOKIES_FILE" ]; then
    echo "OGOHLANTIRISH: COOKIES_FILE=$COOKIES_FILE o'qib bo'lmaydi; cookies'siz davom etiladi." >&2
fi

exec "$@"
