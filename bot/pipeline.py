"""Per-job work: cache lookup -> probe -> download (auto-downgrade) -> ffmpeg -> send -> cache."""

from __future__ import annotations

import asyncio
import dataclasses
import html
import logging
import shutil
from pathlib import Path
from typing import Any, Awaitable, Callable

from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramEntityTooLarge,
    TelegramForbiddenError,
    TelegramRetryAfter,
)

from . import media as mtools
from . import texts
from .downloader import FORMAT_IDS, MEDIA_EXTS, Downloader, DownloadResult, MediaInfo, plan_attempts, tier_label
from .errors import AppError, SizeExceeded
from .jobs import Job
from .keyboards import mp3_keyboard
from .platforms import Link
from .sender import MediaItem, Sender
from .storage import Storage

log = logging.getLogger(__name__)

PHOTO_MAX_BYTES = 10 * 1024 * 1024  # Telegram send_photo limit
TITLE_CAPTION_CHARS = 800  # raw title chars in captions (truncated *before* HTML escaping)
MAX_RETRY_AFTER = 120.0


def file_type(path: Path) -> str | None:
    ext = path.suffix.lower().lstrip(".")
    for kind, exts in MEDIA_EXTS.items():
        if ext in exts:
            return kind
    return None


class Pipeline:
    def __init__(
        self,
        *,
        downloader: Downloader,
        sender: Sender,
        storage: Storage | None,
        max_upload_bytes: int,
        transcode_non_h264: bool = True,
        limits: dict[str, int] | None = None,
    ) -> None:
        self.downloader = downloader
        self.sender = sender
        self.storage = storage
        self.max_upload_bytes = max_upload_bytes
        self.transcode_non_h264 = transcode_non_h264
        self.limits = limits or {}

    def cache_key(self, fmt: str) -> str:
        """file_id cache key includes the upload limit: raising the limit must not serve old low tiers."""
        return f"{fmt}@{self.max_upload_bytes // (1024 * 1024)}"

    async def __call__(self, job: Job, workdir: Path) -> None:
        if await self._try_cache(job):
            return

        media = await self.downloader.probe(job.link)
        job.link = media.link  # may be re-classified (e.g. vertical /watch -> shorts)
        job.title = media.title
        job.thumbnail = media.thumbnail
        job.version += 1

        items: list[MediaItem] = []
        used_fmt = job.format
        skipped = 0
        for i, fmt in enumerate(plan_attempts(job.format, media)):
            attempt_dir = workdir / f"a{i}"
            job.set("downloading", 0)
            try:
                res = await self.downloader.download(
                    job.link, fmt, attempt_dir, on_progress=lambda f: job.set(progress=f * 90)
                )
                job.set("processing", 92)
                items, skipped = await self._process(res, media, attempt_dir)
            except SizeExceeded:
                log.info("job %s: %s too large, downgrading", job.id, fmt)
                shutil.rmtree(attempt_dir, ignore_errors=True)
                continue
            used_fmt = fmt
            break
        if not items:
            raise AppError("too_large", **self.limits)

        # quality actually delivered: "auto" resolves to the real tier of the produced video
        if len(items) == 1 and items[0].type == "video":
            job.used_format = tier_label(used_fmt, items[0].height, items[0].width)
        else:
            job.used_format = used_fmt
        notes: list[str] = []
        if used_fmt != job.format and used_fmt != "audio":
            notes.append(texts.fmt(texts.DOWNGRADED_NOTE, quality=f"{job.used_format}p"))
        if skipped:
            notes.append(texts.fmt(texts.SKIPPED_ITEMS_NOTE, count=skipped))
        job.note = "\n".join(notes) or None

        job.set("uploading", 96)
        entries = await self._send(job, items, used_fmt)
        await self._store_cache(job, used_fmt, entries)

    # -- captions ---------------------------------------------------------------
    def caption(self, job: Job, plain: bool = False) -> str:
        parts = []
        if job.title:
            title = job.title[:TITLE_CAPTION_CHARS]
            parts.append(f"🎬 {title if plain else html.escape(title)}")
        if job.note:
            parts.append(job.note)
        return "\n\n".join(parts)

    async def _mp3_markup(self, job: Job, fmt: str, single_video: bool) -> Any:
        if self.storage is None or fmt == "audio" or not single_video:
            return None
        return mp3_keyboard(await self.storage.token_for(job.link.canonical_url))

    # -- delivery with retries -------------------------------------------------------
    async def _deliver(self, call: Callable[[bool], Awaitable[Any]]) -> Any:
        """Run ``call(plain)``: retry once after RetryAfter; on BadRequest retry once in plain mode
        (no HTML parse_mode, no custom thumbnail)."""
        plain = False
        waited = False
        while True:
            try:
                return await call(plain)
            except TelegramRetryAfter as exc:
                if waited:
                    raise AppError("internal") from None
                waited = True
                await asyncio.sleep(min(float(exc.retry_after), MAX_RETRY_AFTER) + 0.5)
            except TelegramForbiddenError:
                raise AppError("bad_request", texts.NOT_STARTED) from None
            except TelegramEntityTooLarge:
                raise AppError("too_large", **self.limits) from None
            except TelegramBadRequest as exc:
                if plain:
                    raise
                log.warning("send rejected (%s); retrying in plain mode", exc.message)
                plain = True

    async def _try_cache(self, job: Job) -> bool:
        if self.storage is None:
            return False
        key = self.cache_key(job.format)
        entries = await self.storage.get_cached(job.link.media_key, key)
        if not entries:
            return False
        meta = entries[0]
        job.title = job.title or meta.get("title") or None
        job.thumbnail = job.thumbnail or meta.get("thumbnail") or None
        job.used_format = meta.get("used_format") or job.format
        job.note = meta.get("note") or None
        if meta.get("kind") and meta.get("section"):
            job.link = Link(job.link.platform, meta["kind"], job.link.id, job.link.canonical_url, meta["section"])
        job.set("uploading", 96)
        single_video = len(entries) == 1 and entries[0]["type"] == "video"
        markup = await self._mp3_markup(job, job.format, single_video)
        try:
            await self._deliver(lambda plain: self.sender.send_cached(
                job.chat_id, entries, caption=self.caption(job, plain), reply_markup=markup,
                reply_to=job.reply_to, plain=plain))
        except TelegramBadRequest as exc:  # stale file_id -> download again
            log.info("cached file_id rejected (%s), re-downloading", exc)
            await self.storage.drop_cached(job.link.media_key, key)
            job.used_format = job.note = None
            return False
        return True

    # -- processing ---------------------------------------------------------------
    async def _process(self, res: DownloadResult, media: MediaInfo, workdir: Path) -> tuple[list[MediaItem], int]:
        limit = self.max_upload_bytes
        items: list[MediaItem] = []
        skipped = 0
        multi = len(res.files) > 1
        for idx, path in enumerate(res.files):
            kind = file_type(path)
            if kind == "audio":
                item = await self._audio(path, res, media)
            elif kind == "video":
                item = await self._video(path, idx, workdir)
            elif kind == "photo":
                item = await self._photo(path)
            else:
                continue
            max_size = PHOTO_MAX_BYTES if item.type == "photo" else limit
            if item.path.stat().st_size > max_size:
                if multi:
                    skipped += 1
                    continue
                raise SizeExceeded(**self.limits)
            items.append(item)
        if not items:
            raise SizeExceeded(**self.limits) if skipped else AppError("not_found")
        return items[:10], skipped

    async def _audio(self, path: Path, res: DownloadResult, media: MediaInfo) -> MediaItem:
        duration = None
        try:
            duration = (await mtools.ffprobe(path)).duration_int
        except mtools.MediaToolError:
            pass
        return MediaItem(path=path, type="audio", duration=duration or media.duration,
                         title=media.title, performer=media.author)

    async def _video(self, path: Path, idx: int, workdir: Path) -> MediaItem:
        probe = await mtools.ffprobe(path)
        ready = await mtools.prepare_video(path, probe, self.transcode_non_h264)
        if ready != path:
            path.unlink(missing_ok=True)
        final = await mtools.ffprobe(ready)
        thumb = await mtools.make_thumbnail(ready, workdir / f"thumb_{idx}.jpg", final.duration)
        return MediaItem(path=ready, type="video", width=final.width, height=final.height,
                         duration=final.duration_int, thumbnail=thumb)

    async def _photo(self, path: Path) -> MediaItem:
        if path.suffix.lower() not in (".jpg", ".jpeg", ".png"):
            path = await mtools.to_jpeg(path)
        return MediaItem(path=path, type="photo")

    # -- sending ------------------------------------------------------------------
    async def _send(self, job: Job, items: list[MediaItem], fmt: str) -> list[dict[str, str]]:
        markup = await self._mp3_markup(job, fmt, len(items) == 1 and items[0].type == "video")

        def variant(plain: bool) -> list[MediaItem]:
            return [dataclasses.replace(i, thumbnail=None) for i in items] if plain else items

        async def call(plain: bool) -> list[dict[str, str]]:
            caption = self.caption(job, plain)
            its = variant(plain)
            if len(its) > 1:
                return await self.sender.send_media_group(job.chat_id, its, caption=caption,
                                                          reply_to=job.reply_to, plain=plain)
            item = its[0]
            if item.type == "video":
                return [await self.sender.send_video(job.chat_id, item, caption=caption, reply_markup=markup,
                                                     reply_to=job.reply_to, plain=plain)]
            if item.type == "audio":
                return [await self.sender.send_audio(job.chat_id, item, caption=caption, reply_to=job.reply_to,
                                                     plain=plain)]
            return [await self.sender.send_photo(job.chat_id, item, caption=caption, reply_to=job.reply_to,
                                                 plain=plain)]

        try:
            return await self._deliver(call)
        except TelegramBadRequest as exc:
            log.warning("send failed for job %s: %s", job.id, exc.message)
            raise AppError("internal") from None

    async def _store_cache(self, job: Job, fmt: str, entries: list[dict[str, str]]) -> None:
        if self.storage is None or not entries or not all(e.get("file_id") for e in entries):
            return
        base = {"title": job.title or "", "thumbnail": job.thumbnail or "",
                "kind": job.link.kind, "section": job.link.section, "used_format": job.used_format or fmt}
        try:
            # requested format (keeps the downgrade note) ...
            first = [dict(e) for e in entries]
            first[0].update(base, note=job.note or "")
            await self.storage.set_cached(job.link.media_key, self.cache_key(job.format), first)
            # ... and the tier actually delivered (asking for it directly is not a downgrade)
            used = job.used_format
            if used and used != job.format and used in FORMAT_IDS:
                direct = [dict(e) for e in entries]
                direct[0].update(base, note="")
                await self.storage.set_cached(job.link.media_key, self.cache_key(used), direct)
        except Exception:
            log.exception("file cache write failed")
