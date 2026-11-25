#!/bin/bash
# MediaBot boshqaruvi (macOS): mediabot status|logs|restart|stop|start|update|url|uninstall
set -uo pipefail
APP="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="uz.mediabot"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"
cd "$APP" || exit 1
ENVT=("$APP/.venv/bin/python" "$APP/scripts/envtool.py")

case "${1:-status}" in
  status)
    if launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
      state="$(launchctl print "$DOMAIN/$LABEL" | awk -F'= ' '/^\tstate/ {print $2; exit}')"
      [ -n "$state" ] || state="noma‘lum"
      echo "Holat: $state"
    else
      echo "Holat: o'chirilgan (yoqish: mediabot start)"
    fi
    echo "Mini App: $("${ENVT[@]}" get WEBAPP_URL)"
    echo "--- so'nggi loglar ---"
    tail -n 8 logs/bot.log 2>/dev/null || echo "(log yo'q)"
    ;;
  logs)    tail -n 50 -f logs/bot.log ;;
  restart) launchctl kickstart -k "$DOMAIN/$LABEL" && echo "Qayta ishga tushirildi." ;;
  stop)    launchctl bootout "$DOMAIN/$LABEL" && echo "To'xtatildi (Mac qayta yoqilsa ham ishlamaydi; yoqish: mediabot start)." ;;
  start)   launchctl bootstrap "$DOMAIN" "$PLIST" 2>/dev/null || launchctl kickstart "$DOMAIN/$LABEL"; echo "Yoqildi." ;;
  update)
    "$APP/.venv/bin/python" -m pip install -q --upgrade "yt-dlp[default]" && echo "yt-dlp yangilandi: $("$APP/.venv/bin/python" -m yt_dlp --version)"
    launchctl kickstart -k "$DOMAIN/$LABEL" && echo "Bot qayta ishga tushirildi."
    ;;
  url)     "${ENVT[@]}" get WEBAPP_URL ;;
  uninstall)
    launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null
    rm -f "$PLIST"
    echo "Avtomatik ishga tushish o'chirildi. Fayllar saqlandi: $APP (to'liq o'chirish: rm -rf \"$APP\")"
    ;;
  *) echo "Foydalanish: mediabot status|logs|restart|stop|start|update|url|uninstall"; exit 2 ;;
esac
