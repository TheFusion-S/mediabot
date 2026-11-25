"""All user-facing texts (Uzbek, Latin script)."""

from __future__ import annotations

from typing import Any


class _SafeDict(dict):
    def __missing__(self, key: str) -> str:  # pragma: no cover - trivial
        return "?"


def _fmt(template: str, **params: Any) -> str:
    return template.format_map(_SafeDict(params))


START = (
    "👋 Assalomu alaykum, <b>{name}</b>!\n\n"
    "Men Instagram va YouTube'dan videolarni <b>yuqori sifatda</b> yuklab beraman — "
    "asl formatida: Shorts/Reels vertikal, oddiy videolar gorizontal holda.\n\n"
    "📎 Shunchaki havolani yuboring:\n"
    "• Instagram Reels / post\n"
    "• YouTube Shorts\n"
    "• YouTube video (sifatni o'zingiz tanlaysiz)\n\n"
    "Yordam: /help"
)
START_WEBAPP_HINT = "\n\n📱 Qulay interfeys uchun Mini App'ni oching."

HELP = (
    "ℹ️ <b>Qanday foydalaniladi</b>\n\n"
    "1. Instagram yoki YouTube havolasini nusxalang.\n"
    "2. Uni shu chatga yuboring.\n"
    "3. Instagram va Shorts darhol yuklanadi; YouTube video uchun sifatni tanlang.\n\n"
    "🎵 Har bir video ostidagi tugma orqali MP3 ham olishingiz mumkin.\n\n"
    "<b>Cheklovlar</b>\n"
    "• Maksimal hajm: {max_upload_mb} MB\n"
    "• Maksimal davomiylik: {max_duration_min} daqiqa\n"
    "• Soatiga {hourly_limit} ta yuklash\n\n"
    "Buyruqlar: /start, /help, /history\n\n"
    "⚖️ Faqat o'zingizga tegishli yoki ruxsat berilgan kontentni yuklang, mualliflik huquqi "
    "va platformalar qoidalariga rioya qiling."
)

MINIAPP_BUTTON = "📱 Mini App"
MENU_BUTTON = "Mini App"

COMMANDS = {
    "start": "Botni ishga tushirish",
    "help": "Yordam",
    "history": "Oxirgi yuklamalar",
    "id": "Telegram ID'im",
}

# progress
STATUS_QUEUED = "⏳ Navbatda..."
STATUS_DOWNLOADING = "⬇️ Yuklanmoqda {progress}%"
STATUS_PROCESSING = "⚙️ Ishlanmoqda..."
STATUS_UPLOADING = "📤 Yuborilmoqda..."
STATUS_DONE = "✅ Tayyor!"

PROBING = "🔎 Havola tekshirilmoqda..."
CHOOSE_QUALITY = "Sifatni tanlang:"
DOWNGRADED_NOTE = "ℹ️ Hajm limiti sababli {quality} sifatda yuborildi."
SKIPPED_ITEMS_NOTE = "ℹ️ {count} ta element hajmi katta bo'lgani uchun o'tkazib yuborildi."
NO_LINK = (
    "🤔 Havola topilmadi.\n\nInstagram yoki YouTube havolasini yuboring, masalan:\n"
    "<code>https://www.youtube.com/shorts/...</code>"
)
LINK_EXPIRED = "⌛ Bu tugmaning muddati o'tgan. Havolani qayta yuboring."
TOO_MANY_MESSAGES = "🐢 Juda tez yozyapsiz. Bir oz kuting."

MP3_BUTTON = "🎵 MP3 qilib olish"
MP3_KEY_BUTTON = "🎵 MP3"
OVER_LIMIT_MARK = "⛔"

HISTORY_PRIVATE_ONLY = "🔒 Tarix faqat bot bilan shaxsiy chatda ko'rsatiladi."
HISTORY_EMPTY = "📭 Hozircha yuklamalar yo'q."
HISTORY_TITLE = "🕘 <b>Oxirgi yuklamalar</b>\n"
HISTORY_LINE = "{icon} <a href=\"{url}\">{title}</a> — {format}"

SECTION_ICONS = {"instagram": "📸", "shorts": "⚡", "videos": "▶️"}
STATUS_ICONS = {"done": "✅", "error": "❌"}

# formats
FORMAT_LABELS = {
    "auto": "Avto (asl sifat)",
    "1080": "1080p",
    "720": "720p",
    "480": "480p",
    "360": "360p",
    "audio": "MP3 (192 kbps)",
}
DEFAULT_TITLE = "Nomsiz"

# preview
PREVIEW = "🎬 <b>{title}</b>\n👤 {author}\n⏱ {duration}"

# admin
ADMIN_ONLY = "⛔ Bu buyruq faqat adminlar uchun."
STATS = (
    "📊 <b>Statistika</b>\n\n"
    "👥 Foydalanuvchilar: {users}\n"
    "🟢 Faol (24 soat): {active_24h}\n"
    "🚫 Botni bloklaganlar: {blocked}\n\n"
    "⬇️ Jami yuklamalar: {downloads}\n"
    "📅 Bugun (24 soat): {downloads_24h}\n"
    "📸 Instagram: {instagram}\n⚡ Shorts: {shorts}\n▶️ Videos: {videos}\n"
    "❌ Xatolar: {errors}\n\n"
    "⚙️ Faol joblar: {active_jobs}"
)
BROADCAST_USAGE = (
    "Foydalanish: <code>/broadcast matn</code> yoki biror xabarga javob tariqasida <code>/broadcast</code>."
)
BROADCAST_STARTED = "📣 Tarqatish boshlandi: {total} ta foydalanuvchi."
BROADCAST_RUNNING = "⏳ Tarqatish allaqachon davom etmoqda."
BROADCAST_DONE = "✅ Tarqatish tugadi.\nYuborildi: {sent}\nBloklagan: {blocked}\nXato: {failed}"

ERRORS = {
    "unauthorized": "Avtorizatsiya xatosi. Mini App'ni bot orqali qayta oching.",
    "forbidden": "Bot hozir yopiq. Botga /start yozib, egasidan ruxsat so'rang.",
    "bad_request": "Noto'g'ri so'rov.",
    "invalid_url": "Havola yaroqsiz. Faqat Instagram va YouTube havolalari qabul qilinadi.",
    "unsupported": "Bu turdagi havola qo'llab-quvvatlanmaydi. Reels, post, Shorts yoki video havolasini yuboring.",
    "private": "Bu kontent yopiq (shaxsiy akkaunt yoki kirish talab qilinadi).",
    "not_found": "Kontent topilmadi yoki o'chirilgan.",
    "too_long": "Video juda uzun. Maksimal davomiylik: {max_duration_min} daqiqa.",
    "too_large": "Fayl juda katta: hatto 360p sifatda ham {max_upload_mb} MB dan oshadi.",
    "rate_limited": "Limitga yetdingiz: soatiga {hourly_limit} ta so'rov. Birozdan keyin urinib ko'ring.",
    "busy": "Sizda faol yuklash bor. U tugashini kuting.",
    "internal": "Ichki xatolik yuz berdi. Keyinroq qayta urinib ko'ring.",
}
IG_SHARE_LINK = (
    "Bu Instagram \"share\" havolasi. Uni brauzer yoki Instagram ilovasida oching va manzil satridagi "
    "to'liq havolani (…/reel/KOD/ yoki …/p/KOD/) yuboring."
)
PROBE_RATE_LIMITED = "Juda ko'p tekshiruv so'rovi. Bir necha daqiqadan so'ng qayta urinib ko'ring."
SERVER_BUSY = "Server hozir band. Bir ozdan keyin qayta urinib ko'ring."
NO_DISK_SPACE = "Serverda vaqtincha joy yetarli emas. Keyinroq qayta urinib ko'ring."
LIVE_NOT_SUPPORTED = "Jonli efirlarni yuklab bo'lmaydi."
NOT_STARTED = "Botga avval /start yuboring, shundan so'ng fayl chatga yuboriladi."
REQUEST_TOO_LARGE = "So'rov hajmi juda katta."
YT_BLOCKED = (
    "YouTube bu serverdan so'rovlarni vaqtincha cheklab qo'ydi (\"bot emasligingizni tasdiqlang\"). "
    "Birozdan keyin qayta urinib ko'ring. Takrorlansa — YouTube cookies faylini ulang (README → cookies)."
)
# --- access control -------------------------------------------------------------------
SETUP_MODE = (
    "⚙️ <b>Bot sozlash rejimida.</b>\n\n"
    "Sizning Telegram ID'ingiz: <code>{user_id}</code>\n\n"
    "Bot egasi bo'lish uchun sozlamalarga (<code>.env</code> yoki serverdagi Environment variables) yozing:\n"
    "<code>ADMIN_IDS={user_id}</code>\n"
    "va botni qayta ishga tushiring."
)
MY_ID = "🆔 Sizning Telegram ID'ingiz: <code>{user_id}</code>"
OWNER_HINT = (
    "\n\nℹ️ Bot egasi hali belgilanmagan. Egasi bo'lish uchun sozlamalarga "
    "<code>ADMIN_IDS={user_id}</code> yozing va botni qayta ishga tushiring."
)
PRIVATE_BOT = "🔒 Bu bot hozir yopiq — undan faqat egasi ruxsat bergan foydalanuvchilar foydalana oladi."
REQUEST_BUTTON = "🔑 Ruxsat so'rash"
REQUEST_SENT = "✅ So'rovingiz bot egasiga yuborildi. Ruxsat berilganda sizga xabar keladi."
REQUEST_PENDING = "⏳ So'rovingiz bot egasida ko'rib chiqilmoqda. Javobni kuting."
OWNER_REQUEST = (
    "🔑 <b>Ruxsat so'rovi</b>\n\n"
    "{who}\nID: <code>{user_id}</code>\n\n"
    "Botdan foydalanishga ruxsat berasizmi?"
)
BTN_APPROVE = "✅ Ruxsat berish"
BTN_REJECT = "❌ Rad etish"
BTN_BLOCK = "🚫 Bloklash"
BTN_REVOKE = "↩️ Ruxsatni olish"
BTN_UNBLOCK = "♻️ Blokdan chiqarish"
OWNER_DECIDED = "{who} — {result}"
RESULT_APPROVED = "✅ ruxsat berildi"
RESULT_REJECTED = "❌ rad etildi"
RESULT_BLOCKED = "🚫 bloklandi"
RESULT_REVOKED = "↩️ ruxsat olib qo'yildi"
RESULT_UNBLOCKED = "♻️ blokdan chiqarildi"
USER_APPROVED = "🎉 Bot egasi sizga ruxsat berdi! Endi Instagram yoki YouTube havolasini yuboring."
USER_REJECTED = "😔 Bot egasi so'rovingizni rad etdi."
USER_REVOKED = "ℹ️ Bot egasi botdan foydalanish ruxsatingizni olib qo'ydi."
OWNER_ONLY = "⛔ Bu buyruq faqat bot egasi uchun."
MODE_STATUS = (
    "⚙️ <b>Kirish rejimi:</b> {mode}\n\n"
    "🌐 <b>Ochiq</b> — botdan hamma foydalana oladi (bloklanganlardan tashqari).\n"
    "🔒 <b>Yopiq</b> — faqat siz va siz ruxsat berganlar. Boshqalar \"Ruxsat so'rash\" tugmasini ko'radi,\n"
    "so'rov sizga keladi."
)
MODE_OPEN = "🌐 Ochiq"
MODE_PRIVATE = "🔒 Yopiq"
MODE_CHANGED = "Rejim o'zgartirildi: {mode}"
USERS_TITLE = "👥 <b>Foydalanuvchilar</b> (rejim: {mode})"
USERS_APPROVED = "\n\n✅ <b>Ruxsat berilganlar:</b> {count}"
USERS_PENDING = "\n⏳ <b>Kutayotgan so'rovlar:</b> {count}"
USERS_BLOCKED = "\n🚫 <b>Bloklanganlar:</b> {count}"
USERS_EMPTY = "\n\nHozircha ro'yxat bo'sh."
USERS_HELP = (
    "\n\nBuyruqlar: <code>/allow ID</code> — ruxsat berish, <code>/revoke ID</code> — ruxsatni olish, "
    "<code>/block ID</code> — bloklash, <code>/unblock ID</code> — blokdan chiqarish."
)
USER_CMD_USAGE = "Foydalanish: <code>/{cmd} 123456789</code> (foydalanuvchi ID'si)"
USER_CMD_DONE = "Bajarildi: <code>{user_id}</code> — {result}"
CANNOT_TARGET_OWNER = "Bot egasiga bu amalni qo'llab bo'lmaydi."
OWNER_COMMANDS = {
    "mode": "Kirish rejimi: ochiq / yopiq",
    "users": "Foydalanuvchilar va so'rovlar",
    "stats": "Statistika",
}


def error_text(code: str, **params: Any) -> str:
    return _fmt(ERRORS.get(code, ERRORS["internal"]), **params)


def fmt(template: str, **params: Any) -> str:
    return _fmt(template, **params)


def format_duration(seconds: int | float | None) -> str:
    if not seconds:
        return "—"
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def format_size(size: int | None) -> str:
    if not size:
        return ""
    mb = size / (1024 * 1024)
    return f"{mb:.0f} MB" if mb >= 10 else f"{mb:.1f} MB"

# Bot profili (ishga tushganda avtomatik qo'yiladi; BotFather'da qo'lda yozish shart emas)
BOT_DESCRIPTION = (
    "🎬 Instagram va YouTube'dan videolarni yuqori sifatda yuklab beraman.\n\n"
    "• Reels va Shorts — vertikal 9:16\n"
    "• YouTube video — 16:9, sifatni o'zingiz tanlaysiz\n"
    "• Karusel — albom, MP3 — audio\n\n"
    "Havolani yuboring yoki 📱 Mini App'ni oching."
)
BOT_SHORT_DESCRIPTION = "Instagram va YouTube videolarini asl formatda yuklab beruvchi shaxsiy bot."
