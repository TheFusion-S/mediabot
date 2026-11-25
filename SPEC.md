# MediaBot — Texnik topshiriq (barcha agentlar uchun umumiy shartnoma)

Telegram bot + Mini App: Instagram va YouTube havolalaridan videoni yuqori sifatda yuklab,
asl formatini (vertikal Shorts/Reels 9:16, gorizontal YouTube 16:9, kvadrat) saqlagan holda
Telegram'ga video sifatida yuboradi. UI tili: o'zbek (lotin).

## Stack
- Python 3.12+, aiogram 3.x, aiohttp (aiogram bilan keladi), yt-dlp (python API, subprocess/shell YO'Q),
  ffmpeg/ffprobe, aiosqlite, pydantic-settings. Testlar: pytest + pytest-asyncio.
- Frontend: build bosqichisiz vanilla HTML/CSS/JS (`webapp/`), `https://telegram.org/js/telegram-web-app.js`.
- Bitta jarayon: bot polling + aiohttp web server (Mini App statik fayllari + `/api/*`).

## Katalog tuzilmasi
```
mediabot/
  bot/
    main.py         # kirish nuqtasi: polling + web server, graceful shutdown
    config.py       # Settings (env): BOT_TOKEN, WEBAPP_URL, WEB_HOST, WEB_PORT, ADMIN_IDS,
                    # MAX_UPLOAD_MB(50; local Bot API bilan 2000), TELEGRAM_API_BASE (ixtiyoriy local server),
                    # MAX_DURATION_MIN(120), MAX_CONCURRENT_DOWNLOADS(3), USER_HOURLY_LIMIT(30),
                    # DOWNLOAD_DIR, DB_PATH, COOKIES_FILE (ixtiyoriy), TRANSCODE_NON_H264(true), DEV_MODE(false)
    platforms.py    # havolani aniqlash va kanonik URL qurish (allowlist)
    downloader.py   # yt-dlp wrapper: probe() va download(); thread executor; progress callback
    media.py        # ffprobe (w/h/duration/codec), thumbnail (jpg, <=320px, <200KB), kerak bo'lsa transcode
    jobs.py         # JobManager: navbat, global semafor, foydalanuvchiga 1 ta faol job, holatlar
    sender.py       # Telegram'ga yuborish: send_video(width,height,duration,thumbnail,supports_streaming=True),
                    # audio -> send_audio, Instagram karusel -> send_media_group; file_id kesh
    storage.py      # SQLite: users, downloads (history), file_cache(media_key, format -> file_id)
    ratelimit.py    # per-user soatlik limit + flood himoyasi
    security.py     # Telegram WebApp initData HMAC tekshiruvi
    webapp_api.py   # aiohttp route'lar (pastdagi API), xavfsizlik headerlari, statik webapp
    keyboards.py, texts.py
    handlers/       # start.py, links.py, callbacks.py, admin.py
  webapp/           # index.html, app.css, app.js (+ ikonlar inline SVG)
  tests/
  Dockerfile, docker-compose.yml (bot + ixtiyoriy telegram-bot-api local server profili), .env.example,
  requirements.txt, README.md (o'zbekcha: o'rnatish, BotFather'da Mini App sozlash, HTTPS, deploy)
```

## Havolalarni aniqlash (platforms.py) — QAT'IY allowlist
`classify(text) -> Link | None`, `Link(platform, kind, id, canonical_url, section)`
- YouTube hostlar: youtube.com, www.youtube.com, m.youtube.com, music.youtube.com, youtu.be
  - `/shorts/{ID}` -> kind=short, section=shorts
  - `/watch?v={ID}`, `youtu.be/{ID}`, `/live/{ID}`, `/embed/{ID}` -> kind=video, section=videos
  - ID regex `^[A-Za-z0-9_-]{11}$`. Kanonik: `https://www.youtube.com/watch?v=ID` yoki `https://www.youtube.com/shorts/ID`
  - Probe natijasida video vertikal va <=180s bo'lsa `/watch` havolasi ham short deb qayta belgilanishi mumkin (section=shorts).
- Instagram hostlar: instagram.com, www.instagram.com, m.instagram.com
  - `/reel/{CODE}`, `/reels/{CODE}`, `/p/{CODE}`, `/tv/{CODE}` (ixtiyoriy `/{username}/reel/{CODE}`) -> kind=reel|post, section=instagram
  - CODE regex `^[A-Za-z0-9_-]{5,64}$`. Kanonik: `https://www.instagram.com/reel/CODE/` yoki `/p/CODE/`
- Boshqa har qanday host/sxema (http bo'lmagan, IP, userinfo `@`, port) — rad etiladi.
- yt-dlp'ga FAQAT kanonik URL beriladi (foydalanuvchi matni hech qachon to'g'ridan-to'g'ri emas).
- Xabar matnida birinchi mos havola olinadi.

## Yuklab olish va format (downloader.py)
- yt-dlp opsiyalari: `noplaylist=True`, `ignoreconfig`(ya'ni tashqi config o'qilmasin), `quiet`, `no_warnings`,
  `restrictfilenames`, `outtmpl` = job uchun alohida tmp katalog (uuid), `merge_output_format='mp4'`,
  `max_filesize`, `socket_timeout`, `retries`, live streamlar rad (`is_live`), `cookiefile` faqat sozlangan bo'lsa.
  `exec`, `external_downloader`, postprocessor orqali ixtiyoriy buyruqlar ishlatilmaydi.
- Sifat tanlovi `format_sort` orqali (res = eng kichik o'lcham, shuning uchun vertikal/gorizontal uchun bir xil ishlaydi):
  - `auto`  : `['res:1080','vcodec:h264','acodec:m4a','ext:mp4']` (Shorts/Reels uchun standart — asl vertikal o'lcham saqlanadi)
  - `1080|720|480|360`: `['res:<N>','vcodec:h264','acodec:m4a','ext:mp4']`
  - format: `bv*+ba/b`
  - `audio`: `ba/b` -> FFmpegExtractAudio mp3 192k
- Natija H.264 bo'lmasa va TRANSCODE_NON_H264=true bo'lsa -> ffmpeg libx264 (crf 20, preset veryfast, aac, `+faststart`),
  o'lcham (aspect ratio) O'ZGARMAYDI, hech qanday crop/pad yo'q.
- Har doim `-movflags +faststart`. ffprobe orqali haqiqiy width/height/duration olinadi va send_video'ga beriladi —
  shu sababli Telegram Shorts/Reels'ni vertikal, oddiy videoni gorizontal ko'rsatadi.
- Hajm > MAX_UPLOAD_MB bo'lsa: avtomatik pastroq sifatga tushiriladi (1080->720->480->360) va foydalanuvchiga aytiladi;
  360 ham sig'masa — `too_large` xatosi.
- Davomiylik > MAX_DURATION_MIN -> `too_long`.
- Job tugagach tmp katalog DOIM o'chiriladi (finally).
- probe() natijasi: `MediaInfo` (pastdagi API `media` obyekti bilan bir xil maydonlar). Formatlar ro'yxati
  mavjud balandliklardan quriladi, taxminiy hajm (filesize yoki filesize_approx, video+audio) bilan, `fits` = hajm <= limit.
  probe natijasi 10 daqiqa xotirada keshlanadi (kanonik URL bo'yicha).

## Bot xatti-harakati
- /start: salomlashish, qisqa yo'riqnoma, "📱 Mini App" WebApp tugmasi (WEBAPP_URL https bo'lsa), menu button ham o'rnatiladi.
- /help, /history (oxirgi 10 ta), /stats va /broadcast — faqat ADMIN_IDS.
- Havola yuborilganda:
  - Instagram reel/post, YouTube Shorts -> darhol `auto` sifatda yuklanadi.
  - YouTube video -> preview (thumbnail, nomi, muallif, davomiylik) + inline tugmalar: 1080p/720p/480p/360p (hajm bilan,
    sig'maganlari belgilangan) + "🎵 MP3". callback_data: `dl:<short_token>:<format>` (token -> server tomonda saqlangan kanonik URL,
    callback_data'ga URL qo'yilmaydi, 64 bayt limit).
  - Jarayon xabari tahrirlanadi (throttle >= 1.5s): ⏳ navbatda / ⬇️ yuklanmoqda 45% / ⚙️ ishlanmoqda / 📤 yuborilmoqda.
  - Yuborilgan video ostida tugma: "🎵 MP3 qilib olish" (video uchun).
  - Instagram karusel -> media group (rasm + video aralash), 10 tagacha.
  - file_id kesh: bir xil (media_key, format) qayta so'ralsa — darhol file_id bilan yuboriladi.
- Guruhlarda: faqat havola bo'lsa javob beradi (privacy mode hisobga olinadi), aks holda jim.
- Xatolar o'zbekcha, tushunarli: yaroqsiz havola, yopiq akkaunt, topilmadi, juda uzun, juda katta, limit, ichki xato.

## Mini App HTTP API (webapp_api.py)
Barcha `/api/*` so'rovlar header talab qiladi: `X-Telegram-Init-Data: <Telegram.WebApp.initData>`.
Server HMAC-SHA256 tekshiradi (secret = HMAC_SHA256(key="WebAppData", msg=BOT_TOKEN)), `hmac.compare_digest`,
`auth_date` 24 soatdan eski bo'lmasin. Yaroqsiz -> 401 `unauthorized`. DEV_MODE=true bo'lsa header bo'lmaganda dev user (id=1) ishlatiladi.
JSON body <= 4KB. Javob formati:
- Muvaffaqiyat: `{"ok": true, ...}`
- Xato: `{"ok": false, "error": {"code": "<code>", "message": "<o'zbekcha matn>"}}` (+ mos HTTP status)
- Xato kodlari: `unauthorized`(401), `bad_request`(400), `invalid_url`(400), `unsupported`(400), `private`(403), `not_found`(404),
  `too_long`(413), `too_large`(413), `rate_limited`(429), `busy`(409, faol job bor), `internal`(500)

### POST /api/probe
Body: `{"url": "<str>", "section": "instagram"|"shorts"|"videos"}`
Javob: `{"ok": true, "media": Media}`
```
Media = {
  "platform": "instagram"|"youtube",
  "kind": "reel"|"post"|"short"|"video",
  "section": "instagram"|"shorts"|"videos",   // HAQIQIY aniqlangan bo'lim (so'ralgandan farq qilishi mumkin)
  "id": "<str>", "url": "<kanonik url>",
  "title": "<str>", "author": "<str>|null", "thumbnail": "<https url>|null",
  "duration": <int sek>|null, "width": <int>|null, "height": <int>|null,
  "orientation": "vertical"|"horizontal"|"square",
  "items_count": <int>,                        // Instagram karusel uchun, aks holda 1
  "formats": [ {"id": "auto"|"1080"|"720"|"480"|"360"|"audio", "label": "<str>", "height": <int>|null,
                "size": <int bayt>|null, "fits": <bool>} ]
}
```
Agar `section` so'ralgandan farq qilsa, frontend foydalanuvchiga ko'rsatadi va mos tabga o'tkazadi.

### POST /api/download
Body: `{"url": "<str>", "format": "auto"|"1080"|"720"|"480"|"360"|"audio"}`
Javob: `{"ok": true, "job": Job}`. Natija fayl bot orqali foydalanuvchining shaxsiy chatiga yuboriladi.

### GET /api/jobs/{job_id}
Javob: `{"ok": true, "job": Job}` (faqat o'z joblari; boshqasiniki -> 404)
```
Job = { "id": "<str>", "status": "queued"|"downloading"|"processing"|"uploading"|"done"|"error",
        "progress": <0..100>, "format": "<str>",       // so'ralgan format
        "used_format": "<str>"|null,                     // haqiqatda yuborilgan sifat (masalan auto/1080 -> "720"), tugaguncha null
        "note": "<o'zbekcha izoh>"|null,                 // masalan "Hajm limiti sababli 720p sifatda yuborildi"
        "error": {"code","message"}|null,
        "media": {"title","thumbnail","kind","section"},
        "created_at": "<ISO8601>" }
```

### GET /api/history?section=instagram|shorts|videos|all&limit=20 (limit <= 50)
Javob: `{"ok": true, "items": [ {"id","section","kind","title","thumbnail","url","format","status","created_at"} ]}`

### GET /api/me
Javob: `{"ok": true, "user": {"id","first_name","username"}, "stats": {"total","instagram","shorts","videos"},
         "limits": {"max_upload_mb","max_duration_min","hourly_limit","hourly_used"}}`

### Statik
- `GET /` -> `webapp/index.html`, `/static/*` -> webapp fayllari (yoki to'g'ridan-to'g'ri `/app.js`, `/app.css`).
- Xavfsizlik headerlari: CSP (`default-src 'self'; script-src 'self' https://telegram.org; img-src 'self' https: data:;
  style-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors https://web.telegram.org https://*.telegram.org`),
  `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`. CORS ochilmaydi (same-origin).

## Mini App UI
- Ikki asosiy bo'lim (pastki yoki yuqori tab bar): **Instagram** va **YouTube**.
  YouTube ichida segment-control: **Shorts** | **Videos**.
- Har bo'limda: havola maydoni + "Joylash" (clipboard) tugmasi + "Tekshirish"; preview kartochka (thumbnail o'zining
  aspect ratio'sida: Shorts/Reels 9:16, Video 16:9), nom, muallif, davomiylik, sifat tanlash chiplari (hajm bilan,
  `fits=false` bo'lsa o'chirilgan), "Yuklab olish" (Telegram MainButton ham ishlatiladi), progress (job polling 1s),
  tugagach "✅ Chatga yuborildi" + "Chatga o'tish" (WebApp.close()).
- Bo'lim bo'yicha tarix ro'yxati (GET /api/history), bo'sh holat, skeleton loaderlar, xato holatlari.
- Profil/statistika qismi (GET /api/me): jami yuklamalar, limitlar.
- Telegram theme (themeParams CSS o'zgaruvchilari), light/dark, HapticFeedback, BackButton, safe-area, 360px kenglikda ham chiroyli.
- Masofaviy ma'lumotlar (title va h.k.) faqat `textContent` orqali — innerHTML'ga hech qachon.
- `?mock=1` rejimi: backendsiz, soxta ma'lumotlar bilan ishlaydi (dizayn baholash va demo uchun).
