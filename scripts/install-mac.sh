#!/bin/bash
# =====================================================================
#  MediaBot — macOS uchun bir martalik o'rnatuvchi
#  Ishga tushirish: Terminal'da  bash <shu fayl yo'li>
#  Nima qiladi:
#   1. Homebrew va kerakli dasturlarni o'rnatadi (python@3.12, ffmpeg, deno, cloudflared)
#   2. Loyihani ~/MediaBot ga ko'chiradi va Python kutubxonalarini o'rnatadi
#   3. Bot tokenini so'raydi (ekranda ko'rinmaydi) va tekshiradi
#   4. Telegram ID'ingizni o'zi aniqlaydi va sizni bot egasi qiladi (/mode, /users)
#   5. Botni + Mini App tunnelini Mac yoqilganda o'zi ishga tushadigan qiladi (launchd)
#  Qayta ishga tushirish xavfsiz: bor narsalarni qayta o'rnatmaydi, .env saqlanadi.
# =====================================================================
set -euo pipefail

SRC="$(cd "$(dirname "$0")/.." && pwd)"
APP="$HOME/MediaBot"
LABEL="uz.mediabot"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
UIDN="$(id -u)"

step() { printf "\n\033[1;35m▶ %s\033[0m\n" "$*"; }
ok()   { printf "  \033[32m✓\033[0m %s\n" "$*"; }
warn() { printf "  \033[33m!\033[0m %s\n" "$*"; }
die()  { printf "\n\033[31m✗ %s\033[0m\n" "$*" >&2; exit 1; }

[ "$(uname)" = "Darwin" ] || die "Bu skript faqat macOS uchun."

# ---------------------------------------------------------------- 1. Homebrew
step "1/7  Homebrew"
load_brew() { for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do [ -x "$b" ] && eval "$("$b" shellenv)" && return 0; done; return 1; }
command -v brew >/dev/null 2>&1 || load_brew || true
if ! command -v brew >/dev/null 2>&1; then
  echo "  Homebrew o'rnatilmoqda — Mac parolingiz so'ralishi mumkin (yozganda ko'rinmaydi, bu normal)."
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  load_brew || die "Homebrew o'rnatilmadi. Terminal'ni qayta ochib, skriptni yana ishga tushiring."
fi
BREW_PREFIX="$(brew --prefix)"
ok "Homebrew: $BREW_PREFIX"

# ---------------------------------------------------------------- 2. Dasturlar
step "2/7  Kerakli dasturlar (birinchi marta bir necha daqiqa olishi mumkin)"
for pkg in python@3.12 ffmpeg deno cloudflared; do
  if brew list --formula "$pkg" >/dev/null 2>&1; then
    ok "$pkg allaqachon bor"
  else
    echo "  $pkg o'rnatilmoqda..."
    brew install "$pkg" >/dev/null || die "$pkg o'rnatilmadi"
    ok "$pkg o'rnatildi"
  fi
done
PY="$(brew --prefix python@3.12)/bin/python3.12"
[ -x "$PY" ] || die "python3.12 topilmadi: $PY"

# ---------------------------------------------------------------- 3. Loyiha
step "3/7  Loyiha: $APP"
# ~/MediaBot: Desktop/Documents/Downloads emas — macOS fon xizmatlarga u papkalarni bermaydi.
if [ "$SRC" != "$APP" ]; then
  mkdir -p "$APP"
  rsync -a --delete \
    --exclude '.venv/' --exclude 'data/' --exclude 'logs/' --exclude '.env' --exclude '*.zip' --exclude 'cookies.txt' \
    "$SRC"/ "$APP"/
  if [ -f "$SRC/.env" ] && [ ! -f "$APP/.env" ]; then cp "$SRC/.env" "$APP/.env"; fi
fi
cd "$APP"
mkdir -p logs data/downloads
if [ ! -x .venv/bin/python ]; then "$PY" -m venv .venv; fi
echo "  Python kutubxonalari o'rnatilmoqda..."
.venv/bin/python -m pip install -q --upgrade pip
.venv/bin/python -m pip install -q -r requirements.txt -c requirements.lock || die "Kutubxonalar o'rnatilmadi"
ok "kutubxonalar tayyor"
ENVT=(.venv/bin/python scripts/envtool.py)

[ -f .env ] || cp .env.example .env
chmod 600 .env
# Mac uchun standart qiymatlar
"${ENVT[@]}" set WEB_HOST 127.0.0.1
"${ENVT[@]}" set DOWNLOAD_DIR "$APP/data/downloads"
"${ENVT[@]}" set DB_PATH "$APP/data/mediabot.db"
"${ENVT[@]}" set DEV_MODE false
case "$("${ENVT[@]}" get WEBAPP_URL)" in *example.com*) "${ENVT[@]}" set WEBAPP_URL "" ;; esac

# ---------------------------------------------------------------- 4. Token
step "4/7  Bot tokeni"
tg() { curl -fsS --max-time 20 "https://api.telegram.org/bot${TOKEN}/$1"; }
json() { .venv/bin/python -c "import json,sys; d=json.load(sys.stdin); $1"; }
TOKEN="$("${ENVT[@]}" get BOT_TOKEN)"
BOTNAME=""
while :; do
  if [[ "$TOKEN" =~ ^[0-9]{3,15}:[A-Za-z0-9_-]{20,}$ ]]; then
    BOTNAME="$(tg getMe 2>/dev/null | json 'print(d["result"]["username"] if d.get("ok") else "")' 2>/dev/null || true)"
    [ -n "$BOTNAME" ] && break
    warn "Telegram bu tokenni qabul qilmadi (yoki internet yo'q)."
  fi
  echo "  @BotFather bergan tokenni joylang (Cmd+V) va Enter bosing. Token ekranda KO'RINMAYDI — bu normal."
  read -r -s -p "  Token: " TOKEN; echo
  TOKEN="$(printf '%s' "$TOKEN" | tr -d '[:space:]')"
done
"${ENVT[@]}" set BOT_TOKEN "$TOKEN"
ok "bot: @$BOTNAME"

# ---------------------------------------------------------------- 5. Telegram ID
step "5/7  Bot egasini belgilash"
IDS="$("${ENVT[@]}" get ADMIN_IDS)"
[ -n "$IDS" ] || IDS="$("${ENVT[@]}" get ALLOWED_USER_IDS)"   # eski o'rnatishlar
if [ -n "$IDS" ]; then
  ok "bot egasi: ADMIN_IDS=$IDS (o'zgartirish uchun $APP/.env ni tahrirlang)"
else
  launchctl bootout "gui/$UIDN/$LABEL" >/dev/null 2>&1 || true   # bot ishlab tursa getUpdates to'qnashadi
  tg "deleteWebhook" >/dev/null 2>&1 || true
  while [ -z "$IDS" ]; do
    echo "  Telegram'da  https://t.me/$BOTNAME  ni oching va botga /start yuboring."
    read -r -p "  Yuborgach shu yerda Enter bosing... " _
    FOUND="$(tg "getUpdates?timeout=0" 2>/dev/null | .venv/bin/python scripts/tg_last_sender.py 2>/dev/null || true)"
    if [ -z "$FOUND" ]; then warn "Xabar topilmadi. /start ni aynan @$BOTNAME ga yuborganingizni tekshiring."; continue; fi
    CID="${FOUND%%$'\t'*}"; WHO="${FOUND#*$'\t'}"
    read -r -p "  Topildi: $WHO (ID $CID). Bu sizmisiz? [H/y] " ans
    case "${ans:-h}" in [HhYy]*) IDS="$CID" ;; *) warn "Unda botga yana /start yuboring." ;; esac
  done
  "${ENVT[@]}" set ADMIN_IDS "$IDS"
  ok "bot egasi: ID $IDS (rejim: botda /mode — ochiq yoki yopiq)"
fi

# ---------------------------------------------------------------- 6. launchd
step "6/7  Avtomatik ishga tushish (Mac yoqilganda)"
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array><string>/bin/bash</string><string>$APP/scripts/run-mac.sh</string></array>
  <key>WorkingDirectory</key><string>$APP</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>15</integer>
  <key>StandardOutPath</key><string>$APP/logs/launchd.log</string>
  <key>StandardErrorPath</key><string>$APP/logs/launchd.log</string>
  <key>EnvironmentVariables</key>
  <dict><key>PATH</key><string>$BREW_PREFIX/bin:/usr/bin:/bin:/usr/sbin:/sbin</string></dict>
</dict>
</plist>
PLISTEOF
launchctl bootout "gui/$UIDN/$LABEL" >/dev/null 2>&1 || true
[ -f logs/bot.log ] && mv -f logs/bot.log logs/bot.prev.log   # yangi ishga tushishni eski logdan ajratish uchun
launchctl bootstrap "gui/$UIDN" "$PLIST" || die "launchd agentini yuklab bo'lmadi"
ok "launchd agent: $LABEL"

# boshqaruv buyrug'i: `mediabot status|logs|restart|stop|start|update|url|uninstall`
cat > "$BREW_PREFIX/bin/mediabot" <<CTLEOF
#!/bin/bash
exec /bin/bash "$APP/scripts/mediabot-ctl.sh" "\$@"
CTLEOF
chmod +x "$BREW_PREFIX/bin/mediabot"
ok "boshqaruv buyrug'i: mediabot"

# ---------------------------------------------------------------- 7. Tekshiruv
step "7/7  Bot ishga tushishini kutyapman"
STARTED=""
for _ in $(seq 1 90); do
  if grep -q "bot @" logs/bot.log 2>/dev/null; then STARTED=1; break; fi
  sleep 1
done
URL="$("${ENVT[@]}" get WEBAPP_URL)"
if [ -n "$STARTED" ]; then
  ok "bot ishlayapti: https://t.me/$BOTNAME"
  if [ -n "$URL" ]; then ok "Mini App: $URL (botdagi menyu tugmasi orqali oching)"; else warn "Mini App tunneli ulanmadi — bot havolalar bilan baribir ishlaydi. 'mediabot restart' qilib ko'ring."; fi
else
  warn "Bot hali ishga tushganini ko'rmadim. Loglar: mediabot logs"
fi

printf "\n\033[1;32m✅ Tayyor!\033[0m Botga Instagram yoki YouTube havolasini yuboring: https://t.me/%s\n" "$BOTNAME"
cat <<DONE

Boshqarish (Terminal'da):
  mediabot status     — holati
  mediabot logs       — jonli loglar (chiqish: Ctrl+C)
  mediabot restart    — qayta ishga tushirish
  mediabot stop/start — to'xtatish / yoqish
  mediabot update     — yt-dlp'ni yangilash (YouTube/Instagram ishlamay qolsa)
  mediabot url        — joriy Mini App manzili

Fayllar: $APP   (sozlamalar: $APP/.env)
Eslatma: Mac uxlasa (qopqoq yopilsa) bot ham to'xtaydi, uyg'onganda o'zi davom etadi.
DONE
