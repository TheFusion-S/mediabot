# 🆓 MediaBot'ni Render'ga bepul joylash (karta kerak emas, kun-u tun)

Render bepul tarifi: 512 MB RAM, doimiy `https://...onrender.com` manzil (Mini App ishlaydi), karta so'ralmaydi.
Render 15 daqiqa so'rov bo'lmasa xizmatni uxlatadi — bot buni o'zi hal qiladi: har 10 daqiqada o'z manziliga
murojaat qiladi. Oyiga 750 bepul soat bitta xizmatni to'xtovsiz ishlatishga yetadi.

## 1. Ro'yxatdan o'ting
https://render.com → **Get Started** → **GitHub** bilan kiring (TheFusion-S). Ruxsat so'ralsa —
`mediabot` repozitoriyasiga ruxsat bering.

## 2. Blueprint orqali yarating (eng oson)
1. Dashboard → **New +** → **Blueprint**.
2. `TheFusion-S/mediabot` repozitoriyasini tanlang → **Connect**.
3. Render `render.yaml` faylini o'qiydi va **BOT_TOKEN** qiymatini so'raydi — @BotFather bergan tokenni joylang.
4. **Apply** / **Deploy Blueprint** ni bosing. Birinchi yig'ish 5–10 daqiqa.

> Blueprint ko'rinmasa: **New +** → **Web Service** → repozitoriyni tanlang → *Language*: **Docker**,
> *Instance type*: **Free**, *Environment Variables*: `BOT_TOKEN` = token → **Create Web Service**.

## 3. O'zingizni bot egasi qiling
1. Log'da `bot @... started` chiqqach, Telegram'da botga `/id` yuboring.
2. Render → `mediabot` → **Environment** → **Add Environment Variable**: `ADMIN_IDS` = bot aytgan ID → **Save**
   (Render xizmatni o'zi qayta ishga tushiradi).
3. Endi sizda `/mode`, `/users`, `/stats` buyruqlari bor. Mini App manzili avtomatik qo'yiladi.

## Bilish kerak
- Bepul tarifda disk doimiy emas: qayta ishga tushganda tarix, kesh, ruxsatlar ro'yxati va `/mode` tanlovi
  tozalanadi. Doimiy yopiq qilish uchun `ACCESS_MODE=private`, doimiy ruxsatlar uchun `ALLOWED_USER_IDS=ID1,ID2`.
- Kod GitHub'ga yuklanganda Render avtomatik qayta deploy qiladi.
- YouTube/Instagram server IP'larini bloklasa, bot shu haqda xabar beradi — `cookies.txt` kerak (SERVER.md).
