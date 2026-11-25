# 🆓 MediaBot'ni Back4App'ga bepul joylash (karta kerak emas)

Kod GitHub'dagi **yopiq** `mediabot` repozitoriyasida turadi. Back4App uni o'zi oladi, Dockerfile bo'yicha yig'adi
va ishga tushiradi. Bot tokeni faqat Back4App sozlamalariga yoziladi — kodda ham, GitHub'da ham bo'lmaydi.

> Bepul tarif kuchsiz (taxminan 0.25 CPU / 256 MB RAM). Bot shunga moslab sozlangan (bir vaqtda 1 ta yuklash),
> lekin juda katta videolarda xotira yetmasligi mumkin. YouTube/Instagram server IP'larini bloklasa — `cookies.txt`
> kerak bo'ladi (SERVER.md oxiriga qarang).

## 1. Back4App'da ro'yxatdan o'ting
https://www.back4app.com → **Sign up** → **Continue with GitHub** (TheFusion-S akkaunti bilan).

## 2. Konteyner yarating
1. Bosh sahifada **Containers** (Container as a Service) bo'limini tanlang → **New container** / **Create new app**.
2. GitHub'ga ruxsat so'ralsa — **mediabot** repozitoriyasiga ruxsat bering va uni tanlang.
3. Sozlamalar:
   - **Branch**: `main`
   - **Root directory**: `./` (o'zgartirmang)
   - **Port**: `8080`
4. **Environment variables** bo'limiga qo'shing:

| Nom | Qiymat |
|---|---|
| `BOT_TOKEN` | @BotFather bergan token |

5. **Create App** / **Deploy** ni bosing. Birinchi yig'ish 5–10 daqiqa oladi.

## 3. Bot egasini belgilang (siz)
1. Deploy tugagach, Telegram'da botingizga `/id` yuboring — bot ID'ingizni aytadi (masalan `123456789`).
2. Back4App → ilovangiz → **Settings / Environment variables** ga qo'shing:

| Nom | Qiymat |
|---|---|
| `ADMIN_IDS` | bot aytgan ID |
| `WEBAPP_URL` | ilova sahifasida ko'rsatilgan manzil, masalan `https://mediabot-xxxx.b4a.run` |

3. Saqlang va **Redeploy** qiling. Endi `/start` da 📱 Mini App tugmasi chiqadi, sizda esa egasi
   buyruqlari paydo bo'ladi.

## Kim foydalana oladi — buni o'zingiz boshqarasiz

| Buyruq (faqat egasi) | Nima qiladi |
|---|---|
| `/mode` | 🌐 **Ochiq** (hamma foydalanadi) yoki 🔒 **Yopiq** (faqat siz ruxsat berganlar) — tugma bilan |
| `/users` | ruxsat berilganlar, kutayotgan so'rovlar, bloklanganlar ro'yxati |
| `/allow ID`, `/revoke ID` | ruxsat berish / olib qo'yish |
| `/block ID`, `/unblock ID` | bloklash / blokdan chiqarish |
| `/stats` | statistika |

Standart holatda bot **ochiq**. Yopiq rejimda begona odam botga yozsa, **🔑 Ruxsat so'rash** tugmasini
ko'radi; so'rov sizga **✅ Ruxsat berish / ❌ Rad etish / 🚫 Bloklash** tugmalari bilan keladi.
Rejim va ruxsatlar qayta deploy qilmasdan darhol ishlaydi.

## 4. Uxlab qolmasligi uchun (tavsiya)
https://uptimerobot.com (bepul, karta kerak emas) → **New monitor** → turi **HTTP(s)** →
URL: `https://mediabot-xxxx.b4a.run/healthz` → interval **5 minutes** → **Create**.
Bu har 5 daqiqada botni "uyg'otib" turadi.

## Yangilash
Kodda o'zgarish bo'lsa, u GitHub'ga yuklanadi va Back4App avtomatik qayta yig'adi
(yoki ilova sahifasida **Redeploy** ni bosing).

⚠️ Bepul tarifda disk doimiy emas: qayta deploy qilinganda tarix, kesh, **ruxsatlar ro'yxati va /mode tanlovi**
tozalanadi (rejim `ACCESS_MODE` qiymatiga qaytadi). Doimiy yopiq qilmoqchi bo'lsangiz `ACCESS_MODE=private`,
doimiy ruxsat berilganlar uchun `ALLOWED_USER_IDS=ID1,ID2` o'zgaruvchilarini qo'shing.
