# QA / Integratsiya hisoboti (QA agent)

Testlash: haqiqiy create_app + JobManager + Pipeline + yt-dlp (lokal stub extractor orqali), soxta Telegram Bot; Playwright bilan mock'siz Mini App.

## High
1. Rasm bor Instagram karusel (va bitta rasmli post) probe'da `not_found` bo'ladi (yt-dlp "No video formats found"). Fix: `ignore_no_formats_error=True` yoki process=False bilan probe.
2. Faqat o'qiladigan cookies.txt hamma probe/download'ni buzadi (yt-dlp cookie'ni qayta yozadi).
3. `./data` bind mount konteyner foydalanuvchisi (uid 10001) uchun yozib bo'lmaydigan -> crash-loop.

## Medium
4. "Avto" 1080p hajmini ko'rsatadi; muvaffaqiyat matni noto'g'ri sifatni aytadi. Fix: auto hajmi = birinchi sig'adigan daraja; Job'ga `used_format`, `note`.
5. Docker image'da yt-dlp uchun JS runtime yo'q (YouTube formatlari yo'qolishi mumkin). Fix: deno + yt-dlp[default].
6. Bitta faylli yuklamalarda progress 45% dan oshmaydi.

## Low
7. Caption qisqartirish HTML entity'ni bo'lib yuborishi mumkin.
8. Kesh: downgrade izohi yo'qoladi; limit oshirilsa eski past sifat beriladi.
9. Instagram `/share/reel/<token>/` noto'g'ri talqin qilinadi.
10. Frontend va backend havola qoidalari farq qiladi.
11. Instagram reel'larda Mini App'da MP3 varianti yo'q (acodec None).

## Ishlashi tasdiqlangan
API shartnomasi to'liq mos; vertikal /watch -> Shorts; aspect ratio (rotate=90, SAR ham) to'g'ri, crop/pad yo'q; thumbnail JPEG ≤320px; VP9/HEVC -> H.264 +faststart; MP3 send_audio; karusel media group; file_id kesh; caption escaping; callback_data ≤20 bayt; guruhlarda jim; tmp tozalanadi; local Bot API is_local.
