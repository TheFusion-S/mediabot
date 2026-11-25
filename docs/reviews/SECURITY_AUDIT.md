# Xavfsizlik auditi (Security auditor agent)

Umumiy xavf: LOW–MEDIUM. Critical/High topilmadi.

## Medium
- M1. Probe so'rovlari yt-dlp thread pool'ini band qiladi (umumiy executor, global probe limiti yo'q, bot preview'da probe_limiter yo'q). PoC: 10 ta sekin probe -> download 3s kutdi. Fix: alohida probe executor/semafor, preview()'da probe_limiter, negativ kesh.
- M2. yt-dlp har chaqiruvda cookies faylini qayta yozadi (`:ro` mount -> hammasi `internal`; parallel yozish faylni buzadi). Fix: cookie faylni bir marta o'qib, har job uchun nusxa berish, asl faylga yozmaslik.
- M3. DEV_MODE uchun production himoyasi yo'q (autentifikatsiyasiz = user 1). Fix: DEV_MODE + WEBAPP_URL yoki loopback bo'lmagan WEB_HOST bo'lsa ishga tushmaslik.

## Low
- L1. YT ID regex `$` oxiridagi `\n`ni o'tkazadi (`%0a`) -> keshni chetlab o'tish. Fix: re.fullmatch.
- L2. Rate limiter dict'lari tozalanmaydi (xotira o'sadi). Fix: bo'sh/eskirgan kalitlarni tozalash.
- L3. max_filesize faqat Content-Length ma'lum bo'lganda ishlaydi (HLS/DASH). Fix: progress hook'da hajm limitini tekshirish + bo'sh disk tekshiruvi.
- L4. token_for'da poyga holati (SELECT keyin INSERT UNIQUE). Fix: INSERT OR IGNORE.
- L5. Timeout/cancel'da worker ishlashda davom etadi; ishga tushishda download_dir tozalanmaydi.
- L6. Bog'liqliklar va image pin qilinmagan; aiohttp>=3.12.14 kerak.
- L7. Yakuniy yuklashda TelegramRetryAfter qayta urinilmaydi; start_job'dagi xato xabari himoyalanmagan.

## Info
CSP'ga `base-uri 'none'; form-action 'none'; object-src 'none'`; yt-dlp `allowed_extractors`; initData muddatini qisqartirish; guruhlarda /history; compose hardening (read_only, cap_drop, no-new-privileges, limitlar).

## Tekshirildi va mustahkam
URL allowlist (userinfo, homoglif, punycode, port, sxema, ReDoS yo'q), initData HMAC, IDOR yo'q, admin tekshiruvlari, subprocess in'ektsiyasi yo'q, yt-dlp opsiyalari, xavfsizlik headerlari barcha javoblarda, statik traversal yo'q, frontendda XSS sink yo'q, token loglarda yashirilgan, non-root konteyner.
