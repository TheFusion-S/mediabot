# MediaBot — Instagram va YouTube yuklovchi Telegram bot + Mini App

MediaBot Instagram (Reels, post, karusel) va YouTube (Shorts, oddiy video) havolalaridan videoni
**yuqori sifatda** yuklab, **asl formatini saqlagan holda** Telegram'ga video sifatida yuboradi:

- Shorts / Reels — vertikal **9:16**, oddiy YouTube video — gorizontal **16:9**, kvadrat — **1:1**.
  Video hech qachon kesilmaydi (crop) va qora chiziq qo'shilmaydi (pad).
- Haqiqiy `width/height/duration` ffprobe orqali aniqlanadi, thumbnail yaratiladi va
  `supports_streaming=True` bilan yuboriladi — shuning uchun Telegram videoni to'g'ri nisbatda ko'rsatadi.
- YouTube video uchun sifat tanlash (1080p/720p/480p/360p, hajmi bilan) va 🎵 MP3.
- Fayl limitdan katta bo'lsa — sifat avtomatik pasaytiriladi (1080 → 720 → 480 → 360).
- Instagram karusel — media group (rasm + video, 10 tagacha).
- Qayta so'ralgan kontent `file_id` keshidan darhol yuboriladi.
- Mini App (Telegram ichidagi veb-ilova): Instagram / YouTube (Shorts | Videos) bo'limlari, preview,
  progress, tarix va statistika.

> 🔒 **Shaxsiy bot.** Standart holatda bot va Mini App faqat `ALLOWED_USER_IDS` dagi foydalanuvchi(lar)
> uchun ishlaydi. Boshqalar "Bu shaxsiy bot" javobini oladi, Mini App esa ularga ochilmaydi.
> Tez boshlash uchun **[BOSHLASH.md](BOSHLASH.md)**, serverga (VPS) o'rnatish uchun **[SERVER.md](SERVER.md)** ni o'qing.

## Tuzilma

```
bot/            Python backend (aiogram 3, aiohttp, yt-dlp, ffmpeg, SQLite)
  main.py       kirish nuqtasi: polling + web server, graceful shutdown
  config.py     sozlamalar (.env)
  platforms.py  havolalarni qat'iy allowlist bo'yicha aniqlash, kanonik URL
  downloader.py yt-dlp (faqat Python API) — probe() va download()
  media.py      ffprobe / ffmpeg (thumbnail, faststart, kerak bo'lsa H.264 ga o'girish)
  pipeline.py   job ishi: kesh → probe → yuklash (auto-downgrade) → ffmpeg → yuborish
  jobs.py       JobManager: navbat, global semafor, 1 user = 1 faol job, soatlik limit
  sender.py     send_video / send_audio / send_media_group, file_id
  storage.py    SQLite: users, downloads, file_cache, tokens
  security.py   Mini App initData HMAC tekshiruvi
  webapp_api.py /api/* va statik fayllar, xavfsizlik headerlari
  handlers/     /start, /help, /history, havolalar, tugmalar, admin
webapp/         Mini App (vanilla HTML/CSS/JS)
tests/          pytest testlari
```

## Talablar

- Python **3.12+**
- **ffmpeg** va **ffprobe** (`apt install ffmpeg` / `brew install ffmpeg`)
- **deno** 2.x (YouTube uchun yt-dlp'ga JS runtime kerak: https://deno.com — Docker image'da allaqachon bor)
- Telegram bot tokeni (@BotFather)
- Mini App uchun **HTTPS** manzil (pastga qarang)

## 1. Botni yaratish (@BotFather)

1. @BotFather → `/newbot` → nom va username bering → **token**ni oling.
2. `/setprivacy` → **Enable** qoldirish mumkin: guruhlarda bot faqat buyruqlar va javoblarni ko'radi.
   Guruhda havolalarni avtomatik ushlashini istasangiz — **Disable** qiling (bot faqat havola bo'lsa javob beradi).

## 2. O'rnatish (lokal)

```bash
cd mediabot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -c requirements.lock
cp .env.example .env      # BOT_TOKEN, WEBAPP_URL, ALLOWED_USER_IDS ni to'ldiring
python -m bot.main
```

Bot polling rejimida ishlaydi va shu jarayonda `WEB_HOST:WEB_PORT` (standart `0.0.0.0:8080`) da
Mini App + API serveri ko'tariladi. `BOT_TOKEN` bo'lmasa, dastur tushunarli xabar bilan to'xtaydi.

## 3. Docker

```bash
cp .env.example .env   # to'ldiring
docker compose up -d --build
docker compose logs -f bot
```

- Image ichida **ffmpeg**, **deno** (YouTube JS challenge'lari uchun yt-dlp talab qiladigan JS runtime) va
  `yt-dlp[default]` bor. Base image va deno image **tag + digest** bilan pin qilingan (Dockerfile boshida).
- Ma'lumotlar (SQLite, vaqtinchalik fayllar) **`mediabot-data` named volume**'da saqlanadi. Docker uni
  konteyner foydalanuvchisi (uid **10001**) egaligida yaratadi, shuning uchun yozish huquqi muammosi bo'lmaydi.
- `./data:/app/data` kabi **bind mount** ishlatmoqchi bo'lsangiz, hostda egasini o'zgartiring:
  `sudo mkdir -p data && sudo chown -R 10001:10001 data`. Aks holda konteyner ishga tushishda
  tushunarli xato chiqaradi (`... papkasiga yozib bo'lmaydi`) va to'xtaydi.
- Konteyner qattiqlashtirilgan: root filesystem faqat o'qish uchun (`read_only`), `/tmp` tmpfs,
  `cap_drop: ALL`, `no-new-privileges`, xotira (2 GB) va jarayonlar soni limitlari. Port faqat
  `127.0.0.1:8080` da ochiladi — tashqariga HTTPS orqali chiqaring.
- Ishga tushishda `DOWNLOAD_DIR` dagi oldingi ishdan qolgan vaqtinchalik fayllar o'chiriladi.

### yt-dlp'ni yangilab turish

YouTube va Instagram tez-tez o'zgaradi, eski yt-dlp esa ishlamay qoladi. Bog'liqliklar barqarorlik uchun aniq
versiyalarga pin qilingan (`requirements.txt`, to'liq ro'yxat `requirements.lock`). Tavsiya:

- **Muntazam (masalan, haftada bir) image'ni qayta yig'ing.** Eng yangi yt-dlp bilan:
  `docker compose build --build-arg YTDLP_UPGRADE=1 && docker compose up -d`
  (yoki `.env` da `YTDLP_UPGRADE=1`).
- Pin qilingan versiyalarni yangilash: `requirements.txt` dagi `yt-dlp[default]==...` ni o'zgartiring,
  `pip install -r requirements.txt && pip freeze > requirements.lock` (dev paketlarsiz) qiling, testlarni ishga tushiring.
- Base image digest'ini yangilash: `docker buildx imagetools inspect python:3.12.12-slim-bookworm`.

## 4. HTTPS va Mini App

Telegram Mini App faqat **https://** manzilda ishlaydi. `WEBAPP_URL` shu manzil bo'lishi kerak
(masalan `https://mediabot.example.com`). Variantlar:

**a) Reverse proxy (domen bor bo'lsa)** — Caddy avtomatik sertifikat oladi:

```
# /etc/caddy/Caddyfile
mediabot.example.com {
    reverse_proxy 127.0.0.1:8080
}
```

nginx bilan: `proxy_pass http://127.0.0.1:8080;` + Let's Encrypt (certbot).

**b) Cloudflare Tunnel (domen/sertifikatsiz, test uchun):**

```bash
cloudflared tunnel --url http://localhost:8080
# yoki: docker compose --profile tunnel up -d && docker compose logs cloudflared
```

Chiqqan `https://....trycloudflare.com` manzilni `.env` dagi `WEBAPP_URL` ga yozing va botni qayta ishga tushiring.
(Quick tunnel manzili har safar o'zgaradi — doimiy ishlatish uchun nomlangan tunnel yarating.)

### BotFather'da Mini App sozlash

1. `/newapp` → botingizni tanlang → nom, tavsif, rasm (640×360) → **Web App URL** = `WEBAPP_URL`
   → qisqa nom (masalan `app`). Natijada `https://t.me/<bot>/app` havolasi paydo bo'ladi.
2. Menyu tugmasi: `/setmenubutton` → bot → URL = `WEBAPP_URL`, matn = `Mini App`.
   (Bot ishga tushganda `WEBAPP_URL` https bo'lsa menu tugmasini o'zi ham o'rnatadi.)
3. `/start` xabarida ham "📱 Mini App" tugmasi chiqadi.

Mini App backendga har so'rovda `X-Telegram-Init-Data` headerini yuboradi; server uni
HMAC-SHA256 bilan tekshiradi (standart: 6 soatdan eski bo'lmasligi kerak, `INIT_DATA_MAX_AGE_HOURS`). Natijalar bot orqali
foydalanuvchining **shaxsiy chatiga** yuboriladi — shuning uchun foydalanuvchi botga avval `/start` bosgan bo'lishi kerak.

Brauzerda dizaynni ko'rish uchun: `https://<manzil>/?mock=1` (backendsiz soxta ma'lumotlar).
Lokal ishlab chiqishda `DEV_MODE=true` qilsangiz, initData bo'lmagan so'rovlar dev user (id=1) nomidan
bajariladi. **Productionda `DEV_MODE` ni hech qachon yoqmang.** Himoya sifatida bot `DEV_MODE=true` bilan
faqat `WEB_HOST=127.0.0.1` (loopback) va bo'sh `WEBAPP_URL` bo'lganda ishga tushadi, aks holda xato beradi
(shu sababli Docker ichida DEV_MODE ishlamaydi).

## 5. 2 GB gacha fayllar: local Bot API server (ixtiyoriy)

Oddiy Bot API orqali bot **50 MB** gacha fayl yubora oladi. Katta fayllar uchun
[telegram-bot-api](https://github.com/tdlib/telegram-bot-api) serverini o'zingiz ishga tushiring:

1. https://my.telegram.org → API development tools → `api_id` va `api_hash` oling.
2. `.env` ga qo'shing:
   ```
   TELEGRAM_API_ID=...
   TELEGRAM_API_HASH=...
   TELEGRAM_API_BASE=http://telegram-bot-api:8081
   MAX_UPLOAD_MB=2000
   ```
3. Botni avval bulutli serverdan chiqaring (bir marta): `https://api.telegram.org/bot<TOKEN>/logOut`
4. `docker compose --profile local-api up -d`

## 6. Instagram cookies (tavsiya etiladi)

Instagram ko'pincha anonim so'rovlarni cheklaydi ("login required", "rate-limit"). Yechim:

1. Brauzerda (alohida, asosiy bo'lmagan akkaunt bilan) instagram.com ga kiring.
2. "Get cookies.txt LOCALLY" kabi kengaytma bilan **Netscape formatida** `cookies.txt` eksport qiling.
3. Faylni serverga qo'ying va `.env` da `COOKIES_FILE=/app/cookies.txt` (docker-compose.yml dagi volume
   qatorini oching) yoki lokal yo'lni ko'rsating. Fayl **read-only** (`:ro`) bo'lishi mumkin: bot uni har bir
   yuklash/tekshiruv uchun vaqtinchalik shaxsiy nusxaga ko'chiradi va asl faylga hech qachon yozmaydi.

Cookies — maxfiy ma'lumot: faylni hech kimga bermang, repoga qo'shmang (`.gitignore` da bor).
YouTube "Sign in to confirm you're not a bot" desa ham cookies yordam beradi.
`yt-dlp`ni muntazam yangilab turing: lokal `pip install -U "yt-dlp[default]"`, Docker'da `docker compose build --build-arg YTDLP_UPGRADE=1` (3-bo'lim).

## Sozlamalar (.env)

| O'zgaruvchi | Standart | Izoh |
|---|---|---|
| `BOT_TOKEN` | — | Majburiy |
| `WEBAPP_URL` | bo'sh | Mini App https manzili |
| `WEB_HOST` / `WEB_PORT` | `0.0.0.0` / `8080` | Ichki web server |
| `ADMIN_IDS` | bo'sh | `/stats`, `/broadcast` uchun ID'lar (vergul bilan) |
| `MAX_UPLOAD_MB` | `50` | Local Bot API bilan 2000 gacha |
| `TELEGRAM_API_BASE` | bo'sh | Local Bot API server manzili |
| `MAX_DURATION_MIN` | `120` | Undan uzun videolar rad etiladi |
| `MAX_CONCURRENT_DOWNLOADS` | `3` | Bir vaqtda nechta yuklash |
| `USER_HOURLY_LIMIT` | `30` | Foydalanuvchiga soatiga yuklashlar |
| `DOWNLOAD_DIR` / `DB_PATH` | `./data/...` | Vaqtinchalik fayllar / SQLite |
| `COOKIES_FILE` | bo'sh | Netscape cookies.txt |
| `TRANSCODE_NON_H264` | `true` | VP9/AV1 → H.264/AAC (aspect ratio o'zgarmaydi) |
| `INIT_DATA_MAX_AGE_HOURS` | `6` | Mini App initData amal qilish muddati (1–24 soat) |
| `DEV_MODE` | `false` | Faqat lokal test uchun (faqat loopback `WEB_HOST` va bo'sh `WEBAPP_URL` bilan) |
| `LOG_LEVEL` | `INFO` | |

## Bot buyruqlari

- `/start` — salomlashish, Mini App tugmasi
- `/help` — yo'riqnoma va limitlar
- `/history` — oxirgi 10 ta yuklama (faqat shaxsiy chatda)
- `/stats` — umumiy statistika (faqat admin)
- `/broadcast matn` yoki xabarga javoban `/broadcast` — barcha foydalanuvchilarga tarqatish (faqat admin;
  ~20 xabar/s tezlikda, `RetryAfter` va bloklaganlar hisobga olinadi)

## Mini App API (qisqacha)

Barcha so'rovlar `X-Telegram-Init-Data` headeri bilan. Javob: `{"ok": true, ...}` yoki
`{"ok": false, "error": {"code", "message"}}`.

- `POST /api/probe` `{"url", "section"}` → `{"media": {...}}`
- `POST /api/download` `{"url", "format": "auto|1080|720|480|360|audio"}` → `{"job": {...}}`
- `GET /api/jobs/{id}` → `{"job": {...}}`
- `GET /api/history?section=instagram|shorts|videos|all&limit=20`
- `GET /api/me`

To'liq shartnoma: `SPEC.md`.

## Testlar

```bash
pip install -r requirements-dev.txt
python -m pytest -q
python -m pyflakes bot tests
```

Testlar tarmoqsiz ishlaydi: yt-dlp va Telegram chaqiruvlari soxta (mock) obyektlar bilan almashtiriladi,
media testlari esa ffmpeg yordamida yaratilgan kichik vertikal/gorizontal videolardan foydalanadi.

## Xavfsizlik

- yt-dlp'da faqat `youtube` va `instagram` extractorlari yoqilgan (`allowed_extractors`), generic extractor yo'q.
- Probe so'rovlari alohida cheklangan thread pool'da (yuklashlarni band qila olmaydi), muvaffaqiyatsiz probe'lar
  qisqa muddat keshlanadi; foydalanuvchiga probe limiti (bot va Mini App uchun umumiy).
- Yuklash hajmi `MAX_UPLOAD_MB` dan ~10% oshsa (Content-Length yo'q HLS/DASH ham), yuklash to'xtatiladi; bo'sh disk tekshiriladi.
- Faqat allowlistdagi hostlar (youtube.com, youtu.be, instagram.com va ularning rasmiy subdomenlari);
  IP, port, `user@host`, boshqa sxemalar rad etiladi. yt-dlp'ga faqat qayta qurilgan **kanonik URL** beriladi.
- yt-dlp faqat Python API orqali; ffmpeg/ffprobe `create_subprocess_exec` bilan (shell yo'q).
- Inline tugmalarda URL emas, server tomonida saqlanadigan qisqa token ishlatiladi.
- initData HMAC (`hmac.compare_digest`), 24 soatlik muddat; JSON body ≤ 4 KB; CSP va boshqa headerlar; CORS yo'q.
- Har bir job uchun alohida vaqtinchalik papka, ish tugagach doim o'chiriladi.
- Loglarda bot tokeni yashiriladi.

## ⚖️ Huquqiy eslatma

Ushbu dastur faqat shaxsiy va qonuniy foydalanish uchun mo'ljallangan. Foydalanuvchilar faqat o'zlariga
tegishli yoki muallifi ruxsat bergan kontentni yuklab olishlari, **mualliflik huquqi** qonunlariga hamda
YouTube va Instagram **foydalanish shartlari (ToS)** ga rioya qilishlari shart. Bot egasi o'z serverida
qanday kontent qayta ishlanishi uchun javobgar. Mualliflik huquqi egasining murojaati bo'lsa, tegishli
kontentni tarqatishni to'xtating.

## Muammolar

- **"Telegram API unreachable"** — server api.telegram.org ga ulana olmayapti (tarmoq/proksi). Bot qayta urinadi.
- **Mini App ochilmaydi** — `WEBAPP_URL` https emas yoki BotFather'dagi URL bilan mos emas.
- **401 unauthorized** — Mini App bot orqali ochilmagan yoki initData eskirgan (qayta oching).
- **Instagram: yopiq/login** — cookies qo'shing; yopiq akkauntlar yuklanmaydi.
- **Instagram `/share/...` havolasi** — bu vaqtinchalik yo'naltirish havolasi; uni ochib, to'liq
  `/reel/KOD/` yoki `/p/KOD/` havolasini yuboring.
- **YouTube "Ichki xatolik" / formatlar topilmadi** — yt-dlp eskirgan yoki deno yo'q: image'ni
  `YTDLP_UPGRADE=1` bilan qayta yig'ing.
- **Konteyner "papkasiga yozib bo'lmaydi" deb to'xtaydi** — 3-bo'limga qarang (named volume yoki `chown 10001:10001`).
- **Fayl juda katta** — 360p ham limitdan oshsa yuborilmaydi; local Bot API server bilan limitni oshiring.
