#!/bin/bash
# MediaBot boshqaruvi (server): mediabot status|logs|restart|stop|start|update|url
set -uo pipefail
APP=/opt/mediabot
SVC=mediabot
SUDO=""; [ "$(id -u)" = 0 ] || SUDO="sudo"
cd "$APP" || exit 1

case "${1:-status}" in
  status)
    echo "Holat: $(systemctl is-active "$SVC")"
    echo "Mini App: $($SUDO "$APP/.venv/bin/python" "$APP/scripts/envtool.py" get WEBAPP_URL)"
    echo "--- so'nggi loglar ---"
    $SUDO journalctl -u "$SVC" -n 12 -o cat --no-pager
    ;;
  logs)    $SUDO journalctl -u "$SVC" -f -o cat ;;
  restart) $SUDO systemctl restart "$SVC" && echo "Qayta ishga tushirildi." ;;
  stop)    $SUDO systemctl stop "$SVC" && echo "To'xtatildi (yoqish: mediabot start)." ;;
  start)   $SUDO systemctl start "$SVC" && echo "Yoqildi." ;;
  update)
    $SUDO "$APP/.venv/bin/python" -m pip install -q --upgrade "yt-dlp[default]" \
      && echo "yt-dlp: $("$APP/.venv/bin/python" -m yt_dlp --version)"
    $SUDO systemctl restart "$SVC" && echo "Bot qayta ishga tushirildi."
    ;;
  url)     $SUDO "$APP/.venv/bin/python" "$APP/scripts/envtool.py" get WEBAPP_URL ;;
  *) echo "Foydalanish: mediabot status|logs|restart|stop|start|update|url"; exit 2 ;;
esac
