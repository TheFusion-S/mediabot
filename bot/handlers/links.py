"""Incoming links: Instagram/Shorts download immediately, YouTube videos get a quality picker."""

from __future__ import annotations

import html
import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message

from .. import texts as T
from ..downloader import Downloader
from ..errors import AppError
from ..jobs import JobManager
from ..keyboards import quality_keyboard
from ..platforms import Link, analyze_full, reject_message
from ..ratelimit import RateLimiter
from ..storage import Storage
from .common import reply_to, start_job

log = logging.getLogger(__name__)


def message_text(message: Message) -> str:
    """Visible text plus hidden text_link URLs (entities)."""
    text = message.text or message.caption or ""
    extra = [e.url for e in (message.entities or message.caption_entities or []) if e.type == "text_link" and e.url]
    return " ".join([text, *extra]).strip()


async def on_message(message: Message, bot: Bot, db: Storage, downloader: Downloader, jobs: JobManager,
                     probe_limiter: RateLimiter | None = None) -> None:
    if message.from_user is None or message.from_user.is_bot:
        return
    text = message_text(message)
    private = message.chat.type == "private"
    if text.startswith("/"):
        return
    link, err, reason = analyze_full(text)
    if link is None:
        if private:  # in groups stay silent unless there is a link
            if err == "unsupported":
                await message.reply(reject_message(err, reason) or T.error_text("unsupported"))
            else:
                await message.reply(T.NO_LINK)
        return
    if link.platform == "youtube" and link.kind == "video":
        await preview(message, bot, db, downloader, jobs, link, probe_limiter)
        return
    await start_job(bot=bot, jobs=jobs, chat_id=message.chat.id, user_id=message.from_user.id,
                    link=link, fmt="auto", reply_message_id=message.message_id)


async def preview(message: Message, bot: Bot, db: Storage, downloader: Downloader, jobs: JobManager,
                  link: Link, probe_limiter: RateLimiter | None = None) -> None:
    if probe_limiter is not None and not probe_limiter.hit(message.from_user.id):
        await message.reply("❌ " + T.PROBE_RATE_LIMITED)
        return
    status = await message.reply(T.PROBING)
    try:
        media = await downloader.probe(link)
    except AppError as exc:
        await _safe_edit(status, "❌ " + exc.message)
        return
    if media.section == "shorts":  # vertical <=180s /watch link -> treat as a Short
        await _safe_delete(status)
        await start_job(bot=bot, jobs=jobs, chat_id=message.chat.id, user_id=message.from_user.id,
                        link=media.link, fmt="auto", reply_message_id=message.message_id,
                        title=media.title, thumbnail=media.thumbnail)
        return
    token = await db.token_for(media.url)
    caption = T.fmt(T.PREVIEW, title=html.escape(media.title[:200]),  # truncate *then* escape author=html.escape(media.author or "—"),
                    duration=T.format_duration(media.duration)) + "\n\n" + T.CHOOSE_QUALITY
    kb = quality_keyboard(token, media)
    await _safe_delete(status)
    if media.thumbnail:
        try:
            await message.answer_photo(media.thumbnail, caption=caption, reply_markup=kb,
                                       reply_parameters=reply_to(message.message_id))
            return
        except TelegramBadRequest:
            log.info("thumbnail rejected by Telegram, falling back to text preview")
    await message.answer(caption, reply_markup=kb, reply_parameters=reply_to(message.message_id),
                         disable_web_page_preview=True)


async def _safe_edit(msg: Message, text: str) -> None:
    try:
        await msg.edit_text(text)
    except TelegramBadRequest:
        pass


async def _safe_delete(msg: Message) -> None:
    try:
        await msg.delete()
    except TelegramBadRequest:
        pass


def register(router: Router) -> None:
    router.message.register(on_message, F.text | F.caption)
