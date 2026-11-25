#!/bin/bash
# =====================================================================
#  MediaBot — Linux server (VPS) uchun bir martalik o'rnatuvchi
#  Tizim: Ubuntu 22.04 / 24.04 yoki Debian 12. root sifatida ishga tushiriladi.
#  Nima qiladi:
#   1. Dasturlar: Python 3.12, ffmpeg, deno, Caddy (HTTPS), ufw (firewall)
#   2. Loyiha -> /opt/mediabot, alohida "mediabot" tizim foydalanuvchisi
#   3. Bot tokenini so'raydi (ko'rinmaydi) va tekshiradi
#   4. Telegram ID'ingizni o'zi aniqlaydi -> siz bot egasisiz (/mode, /users)
#   5. Mini App uchun doimiy HTTPS manzil: https://<IP>.sslip.io (domen sotib olish shart emas)
#   6. systemd xizmati: server yoqilganda o'zi ishga tushadi, yiqilsa qayta turadi
#  Qayta ishga tushirish xavfsiz (yangilash uchun ham shu skript).
# =====================================================================
set -euo pipefail

SRC="$(cd "$(dirname "$0")/.." && pwd)"
APP=/opt/mediabot
SVC=mediabot
RUN_USER=mediabot
PORT=8080

step() { printf "\n\033[1;35m▶ %s\033[0m\n" "$*"; }
ok()   { printf "  \033[32m✓\033[0m %s\n" "$*"; }
warn() { printf "  \033[33m!\033[0m %s\n" "$*"; }
die()  { printf "\n\033[31m✗ %s\033[0m\n" "$*" >&2; exit 1; }

[ "$(id -u)" = 0 ] || die "root sifatida ishga tushiring: sudo bash $0"
[ -f /etc/os-release ] && . /etc/os-release
case "${ID:-}" in ubuntu|debian) ;; *) die "Faqat Ubuntu/Debian qo'llab-quvvatlanadi (sizda: ${PRETTY_NAME:-noma‘lum})";; esac
export DEBIAN_FRONTEND=noninteractive

# ---------------------------------------------------------------- 1. Dasturlar
step "1/7  Dasturlar o'rnatilmoqda (2-5 daqiqa)"
apt-get update -qq
apt-get install -y -qq curl ca-certificates gnupg rsync unzip ffmpeg ufw python3 python3-venv >/dev/null
PY=""
for c in python3.13 python3.12 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)'; then PY="$(command -v "$c")"; break; fi
done
if [ -z "$PY" ]; then
  [ "${ID}" = ubuntu ] || die "Python 3.12+ topilmadi. Debian 12 o'rniga Ubuntu 24.04 o'rnating."
  echo "  Python 3.12 (deadsnakes PPA) o'rnatilmoqda..."
  apt-get install -y -qq software-properties-common >/dev/null
  add-apt-repository -y ppa:deadsnakes/ppa >/dev/null
  apt-get update -qq && apt-get install -y -qq python3.12 python3.12-venv >/dev/null
  PY="$(command -v python3.12)"
fi
"$PY" -m venv --help >/dev/null 2>&1 || apt-get install -y -qq "python3-venv" >/dev/null
ok "python: $("$PY" --version)"
ok "ffmpeg: $(ffmpeg -version | head -n1 | cut -d' ' -f1-3)"

if ! command -v deno >/dev/null 2>&1; then
  curl -fsSL https://deno.land/install.sh | DENO_INSTALL=/usr/local sh -s -- -y >/dev/null 2>&1 || warn "deno o'rnatilmadi"
fi
command -v deno >/dev/null 2>&1 && ok "deno: $(deno --version | head -n1)" || warn "deno yo'q — YouTube'da ba'zi formatlar chiqmasligi mumkin"

if ! command -v caddy >/dev/null 2>&1; then
  curl -fsSL 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -fsSL 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -qq && apt-get install -y -qq caddy >/dev/null
fi
ok "caddy: $(caddy version | cut -d' ' -f1)"

# ---------------------------------------------------------------- 2. Loyiha
step "2/7  Loyiha: $APP"
id "$RUN_USER" >/dev/null 2>&1 || useradd --system --home-dir "$APP" --shell /usr/sbin/nologin "$RUN_USER"
mkdir -p "$APP"
if [ "$SRC" != "$APP" ]; then
  rsync -a --delete \
    --exclude '.venv/' --exclude 'data/' --exclude 'logs/' --exclude '.env' --exclude '*.zip' --exclude 'cookies.txt' \
    "$SRC"/ "$APP"/
fi
if [ -f "$SRC/cookies.txt" ] && [ "$SRC" != "$APP" ]; then cp "$SRC/cookies.txt" "$APP/cookies.txt"; fi
cd "$APP"
chown -R root:root "$APP"
mkdir -p data/downloads data/cache logs
chown -R "$RUN_USER:$RUN_USER" data logs
[ -x .venv/bin/python ] || "$PY" -m venv .venv
echo "  Python kutubxonalari o'rnatilmoqda..."
.venv/bin/python -m pip install -q --upgrade pip
.venv/bin/python -m pip install -q -r requirements.txt -c requirements.lock || die "Kutubxonalar o'rnatilmadi"
ok "kutubxonalar tayyor"
ENVT=(.venv/bin/python scripts/envtool.py)

[ -f .env ] || cp .env.example .env
"${ENVT[@]}" set WEB_HOST 127.0.0.1
"${ENVT[@]}" set WEB_PORT "$PORT"
"${ENVT[@]}" set DOWNLOAD_DIR "$APP/data/downloads"
"${ENVT[@]}" set DB_PATH "$APP/data/mediabot.db"
"${ENVT[@]}" set DEV_MODE false
if [ -f "$APP/cookies.txt" ]; then "${ENVT[@]}" set COOKIES_FILE "$APP/cookies.txt"; fi

# ---------------------------------------------------------------- 3. Token
step "3/7  Bot tokeni"
systemctl stop "$SVC" >/dev/null 2>&1 || true   # getUpdates bilan to'qnashmasligi uchun
tg() { curl -fsS --max-time 20 "https://api.telegram.org/bot${TOKEN}/$1"; }
TOKEN="$("${ENVT[@]}" get BOT_TOKEN)"
BOTNAME=""
while :; do
  if [[ "$TOKEN" =~ ^[0-9]{3,15}:[A-Za-z0-9_-]{20,}$ ]]; then
    BOTNAME="$(tg getMe 2>/dev/null | .venv/bin/python -c 'import json,sys; d=json.load(sys.stdin); print(d["result"]["username"] if d.get("ok") else "")' 2>/dev/null || true)"
    [ -n "$BOTNAME" ] && break
    warn "Telegram bu tokenni qabul qilmadi."
  fi
  echo "  @BotFather bergan tokenni joylang va Enter bosing. Token ekranda KO'RINMAYDI — bu normal."
  read -r -s -p "  Token: " TOKEN; echo
  TOKEN="$(printf '%s' "$TOKEN" | tr -d '[:space:]')"
done
"${ENVT[@]}" set BOT_TOKEN "$TOKEN"
ok "bot: @$BOTNAME"

# ---------------------------------------------------------------- 4. Telegram ID
step "4/7  Bot egasini belgilash"
IDS="$("${ENVT[@]}" get ADMIN_IDS)"
[ -n "$IDS" ] || IDS="$("${ENVT[@]}" get ALLOWED_USER_IDS)"   # eski o'rnatishlar
if [ -n "$IDS" ]; then
  ok "bot egasi: ADMIN_IDS=$IDS"
else
  tg deleteWebhook >/dev/null 2>&1 || true
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
# ---------------------------------------------------------------- 5. HTTPS (Mini App)
step "5/7  Mini App uchun HTTPS"
PUBLIC_IP="$(curl -fsS -4 --max-time 10 https://api.ipify.org 2>/dev/null || true)"
URL=""
if [[ "$PUBLIC_IP" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  HOST="${PUBLIC_IP//./-}.sslip.io"
  cat > /etc/caddy/Caddyfile <<CADDYEOF
# MediaBot Mini App — Caddy avtomatik Let's Encrypt sertifikati oladi
$HOST {
    encode gzip
    reverse_proxy 127.0.0.1:$PORT
}
CADDYEOF
  ufw allow OpenSSH >/dev/null
  SSH_PORT="$(echo "${SSH_CONNECTION:-}" | awk '{print $4}')"   # SSH boshqa portda bo'lsa ham o'zingizni qulflamang
  [ -n "$SSH_PORT" ] && ufw allow "$SSH_PORT/tcp" >/dev/null
  ufw allow 80/tcp >/dev/null; ufw allow 443/tcp >/dev/null
  ufw --force enable >/dev/null
  # Oracle Cloud Ubuntu image'larida INPUT zanjirida o'zining REJECT qoidasi bor (faqat 22-port ochiq).
  # ufw qoidalari undan keyin keladi, shuning uchun 80/443 ni eng boshiga qo'shamiz.
  if command -v iptables >/dev/null 2>&1 && iptables -S INPUT 2>/dev/null | grep -q -- "-j REJECT"; then
    for p in 443 80; do
      iptables -C INPUT -p tcp --dport "$p" -j ACCEPT 2>/dev/null || iptables -I INPUT 1 -p tcp --dport "$p" -j ACCEPT
    done
    command -v netfilter-persistent >/dev/null 2>&1 && netfilter-persistent save >/dev/null 2>&1 || true
    ok "Oracle firewall: 80/443 ochildi (Oracle konsolidagi Security List'da ham ochilgan bo'lishi kerak — SERVER.md)"
  fi
  systemctl enable caddy >/dev/null 2>&1 || true
  systemctl restart caddy
  URL="https://$HOST"
  ok "Mini App manzili: $URL"
else
  warn "Serverning ochiq IPv4 manzilini aniqlab bo'lmadi — Mini App o'chiq, bot havolalar bilan ishlayveradi."
fi
"${ENVT[@]}" set WEBAPP_URL "$URL"
# .env oxirgi marta yozilgandan keyin: faqat root yozadi, bot foydalanuvchisi o'qiy oladi
chown root:"$RUN_USER" .env && chmod 640 .env
if [ -f cookies.txt ]; then chown root:"$RUN_USER" cookies.txt && chmod 640 cookies.txt; fi

# ---------------------------------------------------------------- 6. systemd
step "6/7  Doimiy ishlash (systemd)"
cat > /etc/systemd/system/$SVC.service <<UNITEOF
[Unit]
Description=MediaBot (Telegram Instagram/YouTube downloader)
After=network-online.target
Wants=network-online.target

[Service]
User=$RUN_USER
Group=$RUN_USER
WorkingDirectory=$APP
ExecStart=$APP/.venv/bin/python -m bot.main
Restart=always
RestartSec=5
Environment=PATH=/usr/local/bin:/usr/bin:/bin
Environment=HOME=$APP/data
Environment=XDG_CACHE_HOME=$APP/data/cache
Environment=DENO_DIR=$APP/data/cache/deno
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
PrivateDevices=yes
ProtectKernelTunables=yes
ProtectControlGroups=yes
RestrictSUIDSGID=yes
ReadWritePaths=$APP/data $APP/logs
MemoryMax=2G

[Install]
WantedBy=multi-user.target
UNITEOF
systemctl daemon-reload
systemctl enable "$SVC" >/dev/null 2>&1
systemctl restart "$SVC"
ok "xizmat: $SVC (server qayta yoqilganda ham o'zi ishga tushadi)"

install -m 755 scripts/server-ctl.sh /usr/local/bin/mediabot
ok "boshqaruv buyrug'i: mediabot"

# ---------------------------------------------------------------- 7. Tekshiruv
step "7/7  Bot ishga tushishini kutyapman"
STARTED=""
SINCE="$(date '+%Y-%m-%d %H:%M:%S')"
for _ in $(seq 1 60); do
  if journalctl -u "$SVC" --since "$SINCE" -o cat 2>/dev/null | grep -q "bot @"; then STARTED=1; break; fi
  sleep 1
done
if [ -n "$STARTED" ]; then ok "bot ishlayapti: https://t.me/$BOTNAME"; else warn "Hali ishga tushganini ko'rmadim. Loglar: mediabot logs"; fi

printf "\n\033[1;32m✅ Tayyor!\033[0m Bot serverda kun-u tun ishlaydi: https://t.me/%s\n" "$BOTNAME"
cat <<DONE

Boshqarish (serverda):
  mediabot status     — holati va so'nggi loglar
  mediabot logs       — jonli loglar (chiqish: Ctrl+C)
  mediabot restart    — qayta ishga tushirish
  mediabot update     — yt-dlp'ni yangilash (YouTube/Instagram ishlamay qolsa)
  mediabot url        — Mini App manzili

Fayllar: $APP   (sozlamalar: $APP/.env)
DONE
