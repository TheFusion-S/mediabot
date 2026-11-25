# 🚀 Tez boshlash — shaxsiy MediaBot

Bu bot **faqat siz uchun** ishlaydi. Boshqa odamlar botga yozsa "🔒 Bu shaxsiy bot" javobini oladi,
Mini App esa ularga ochilmaydi. Hech narsa hech qayerga yuklanmaydi: bot sizning kompyuteringiz
yoki serveringizda ishlaydi.

---

## ☁️ Kun-u tun ishlashi uchun: serverga o'rnatish

Bot kompyuteringiz o'chiq bo'lganda ham ishlashi kerak bo'lsa — **[SERVER.md](SERVER.md)** ga qarang
(VPS + Mac Terminal'dan bitta buyruq).

## 🍎 Mac uchun eng oson yo'l (bitta buyruq)

1. @BotFather'da bot yarating va tokenni nusxalang (pastdagi 1-qadam).
2. Bu arxivni **Downloads** papkasida oching (ikki marta bosing) — `MediaBot` papkasi paydo bo'ladi.
3. **Terminal**ni oching (Cmd + Probel → "Terminal" → Enter) va quyidagini joylab Enter bosing:

   ```
   bash ~/Downloads/MediaBot/scripts/install-mac.sh
   ```

4. Skript so'raganlarini bajaring: tokenni joylang (ekranda ko'rinmaydi), botga `/start` yuboring.
   Qolganini — dasturlarni o'rnatish, botni faqat sizga qulflash, Mini App tunneli, Mac yoqilganda
   avtomatik ishga tushish — skript o'zi qiladi. Keyin `mediabot status` / `mediabot logs` buyruqlari ishlaydi.

Quyidagi qadamlar — skriptsiz (qo'lda) o'rnatish uchun.

## 1-qadam. Bot yarating (2 daqiqa)

1. Telegram'da **@BotFather** ni oching → `/newbot`.
2. Botga nom va username bering (masalan `mening_yuklovchim_bot`).
3. BotFather bergan **tokenni** nusxalang (`123456789:AAH...` ko'rinishida). Uni hech kimga bermang!

> 🖼 Avatar, bot tavsifi va buyruqlar menyusini qo'yish **shart emas** — bot birinchi ishga tushganda
> ularni o'zi qo'yadi (avatar: `assets/bot-avatar.jpg`, uni o'z rasmingizga almashtirishingiz mumkin).

## 2-qadam. Sozlamalar fayli

Papka ichida `.env.example` faylidan nusxa oling va nomini `.env` qiling, keyin oching:

```
BOT_TOKEN=bu_yerga_tokeningiz
ALLOWED_USER_IDS=          ← hozircha bo'sh qoldiring (3-qadamda to'ldirasiz)
WEBAPP_URL=                ← Mini App uchun (5-qadam), hozircha bo'sh bo'lishi mumkin
```

## 3-qadam. Ishga tushiring va ID'ingizni oling

**Variant A — Docker (tavsiya etiladi, hammasi tayyor ichida: ffmpeg, deno):**

```bash
docker compose up -d --build
```

**Variant B — Docker'siz:**
- Linux / macOS: `./start.sh`
- Windows: `start.bat` ni ikki marta bosing

(Docker'siz variant uchun kompyuteringizda **Python 3.12+**, **ffmpeg** va **deno** o'rnatilgan bo'lishi kerak.)

Endi botingizga Telegram'da `/start` yuboring. Bot shunday javob beradi:

> ⚙️ Bot sozlash rejimida. Sizning Telegram ID'ingiz: `123456789`

## 4-qadam. Botni o'zingizga qulflang

`.env` fayliga ID'ingizni yozing:

```
ALLOWED_USER_IDS=123456789
```

va botni qayta ishga tushiring (`docker compose restart` yoki skriptni qayta ishga tushiring).
✅ Tayyor — endi bot faqat sizga ishlaydi. Unga Instagram yoki YouTube havolasini tashlang.

## 5-qadam. Mini App (ixtiyoriy)

Telegram Mini App faqat **https://** manzilda ochiladi. Eng oson yo'l — Cloudflare tunnel:

```bash
docker compose --profile tunnel up -d
docker compose logs cloudflared | grep trycloudflare
```

Chiqqan `https://....trycloudflare.com` manzilni `.env` dagi `WEBAPP_URL=` ga yozing va botni qayta
ishga tushiring. Bot `/start` da "📱 Mini App" tugmasini ko'rsatadi.
(Bu tezkor manzil har qayta ishga tushganda o'zgaradi. Doimiy manzil uchun README'dagi 4-bo'limga qarang.)

---

## Foydalanish

| Siz yuborasiz | Bot qaytaradi |
|---|---|
| YouTube **Shorts** havolasi | Darhol vertikal **9:16** video (1080×1920 gacha) |
| Instagram **Reels** havolasi | Darhol vertikal **9:16** video |
| Instagram **post / karusel** | Rasm va videolar albom bo'lib |
| Oddiy **YouTube video** | Sifat tanlash: 1080p / 720p / 480p / 360p yoki 🎵 MP3 → **16:9** video |

- Oddiy bot 50 MB gacha fayl yubora oladi. Katta bo'lsa bot sifatni o'zi pasaytiradi va buni aytadi.
  2 GB gacha kerak bo'lsa — README'dagi "local Bot API server" bo'limi.
- Instagram ba'zi postlarni kirishsiz bermaydi — README'dagi "Instagram cookies" bo'limiga qarang.
- `/history` — so'nggi yuklamalar, `/stats` — statistika.

## Muammo bo'lsa

- Bot javob bermayapti → `docker compose logs -f bot` (yoki skript oynasidagi xabarlar).
- "BOT_TOKEN formati noto'g'ri" → `.env` dagi tokenni tekshiring (bo'sh joy yoki qo'shtirnoqsiz).
- YouTube videolari yuklanmay qoldi → yt-dlp eskirgan: `docker compose build --build-arg YTDLP_UPGRADE=1 && docker compose up -d`.

⚖️ Faqat o'zingizga ruxsat berilgan kontentni yuklab oling va platformalar qoidalariga rioya qiling.
