"""Sending results to Telegram (video/audio/photo/media group) and re-sending by cached file_id."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aiogram import Bot
from aiogram.types import (
    FSInputFile,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    InputMediaVideo,
    Message,
    ReplyParameters,
)

log = logging.getLogger(__name__)

CAPTION_LIMIT = 1024
UPLOAD_TIMEOUT = 1800  # seconds; large files on slow links


@dataclass(slots=True)
class MediaItem:
    path: Path
    type: str  # "video" | "photo" | "audio"
    width: int | None = None
    height: int | None = None
    duration: int | None = None
    thumbnail: Path | None = None
    title: str | None = None
    performer: str | None = None


def _reply(reply_to: int | None) -> ReplyParameters | None:
    return ReplyParameters(message_id=reply_to, allow_sending_without_reply=True) if reply_to else None


def _caption(caption: str | None) -> str | None:
    """Trim to Telegram's limit without cutting an HTML entity such as ``&amp;`` in half."""
    if not caption:
        return None
    if len(caption) <= CAPTION_LIMIT:
        return caption
    cut = caption[: CAPTION_LIMIT - 1]
    amp = cut.rfind("&")
    if amp != -1 and ";" not in cut[amp:]:
        cut = cut[:amp]
    return cut + "…"


def _pm(plain: bool) -> Any:
    """parse_mode kwargs: plain=True disables HTML (fallback after a 'can't parse entities' error)."""
    return {"parse_mode": None} if plain else {}


def _file_id(msg: Message) -> tuple[str, str] | None:
    if msg.video:
        return "video", msg.video.file_id
    if msg.audio:
        return "audio", msg.audio.file_id
    if msg.photo:
        return "photo", msg.photo[-1].file_id
    if msg.document:
        return "document", msg.document.file_id
    return None


class Sender:
    def __init__(self, bot: Bot, upload_timeout: int = UPLOAD_TIMEOUT):
        self.bot = bot
        self.upload_timeout = upload_timeout

    async def send_video(
        self,
        chat_id: int,
        item: MediaItem,
        *,
        caption: str | None = None,
        reply_markup: InlineKeyboardMarkup | None = None,
        reply_to: int | None = None,
        plain: bool = False,
    ) -> dict[str, str]:
        msg = await self.bot.send_video(
            **_pm(plain),
            chat_id=chat_id,
            video=FSInputFile(item.path, filename=item.path.name),
            duration=item.duration,
            width=item.width,
            height=item.height,
            thumbnail=FSInputFile(item.thumbnail) if item.thumbnail else None,
            caption=_caption(caption),
            supports_streaming=True,
            reply_markup=reply_markup,
            reply_parameters=_reply(reply_to),
            request_timeout=self.upload_timeout,
        )
        return self._entry(msg)

    async def send_audio(
        self,
        chat_id: int,
        item: MediaItem,
        *,
        caption: str | None = None,
        reply_to: int | None = None,
        plain: bool = False,
    ) -> dict[str, str]:
        msg = await self.bot.send_audio(
            **_pm(plain),
            chat_id=chat_id,
            audio=FSInputFile(item.path, filename=item.path.name),
            duration=item.duration,
            title=(item.title or None) and item.title[:64],
            performer=(item.performer or None) and item.performer[:64],
            thumbnail=FSInputFile(item.thumbnail) if item.thumbnail else None,
            caption=_caption(caption),
            reply_parameters=_reply(reply_to),
            request_timeout=self.upload_timeout,
        )
        return self._entry(msg)

    async def send_photo(
        self, chat_id: int, item: MediaItem, *, caption: str | None = None, reply_to: int | None = None,
        plain: bool = False,
    ) -> dict[str, str]:
        msg = await self.bot.send_photo(
            **_pm(plain),
            chat_id=chat_id,
            photo=FSInputFile(item.path, filename=item.path.name),
            caption=_caption(caption),
            reply_parameters=_reply(reply_to),
            request_timeout=self.upload_timeout,
        )
        return self._entry(msg)

    async def send_media_group(
        self, chat_id: int, items: list[MediaItem], *, caption: str | None = None, reply_to: int | None = None,
        plain: bool = False,
    ) -> list[dict[str, str]]:
        """Instagram carousel: photos and videos mixed, max 10 per group."""
        out: list[dict[str, str]] = []
        for start in range(0, len(items), 10):
            chunk = items[start : start + 10]
            media: list[Any] = []
            for i, it in enumerate(chunk):
                cap = _caption(caption) if start == 0 and i == 0 else None
                if it.type == "video":
                    media.append(InputMediaVideo(
                        media=FSInputFile(it.path, filename=it.path.name),
                        thumbnail=FSInputFile(it.thumbnail) if it.thumbnail else None,
                        width=it.width, height=it.height, duration=it.duration,
                        supports_streaming=True, caption=cap, **_pm(plain),
                    ))
                else:
                    media.append(InputMediaPhoto(media=FSInputFile(it.path, filename=it.path.name), caption=cap,
                                                 **_pm(plain)))
            msgs = await self.bot.send_media_group(
                chat_id=chat_id, media=media, reply_parameters=_reply(reply_to), request_timeout=self.upload_timeout
            )
            out.extend(e for e in (self._entry(m) for m in msgs) if e)
        return out

    async def send_cached(
        self,
        chat_id: int,
        entries: list[dict[str, str]],
        *,
        caption: str | None = None,
        reply_markup: InlineKeyboardMarkup | None = None,
        reply_to: int | None = None,
        plain: bool = False,
    ) -> None:
        cap = _caption(caption)
        if len(entries) > 1:
            media: list[Any] = []
            for i, e in enumerate(entries[:10]):
                c = cap if i == 0 else None
                if e["type"] == "video":
                    media.append(InputMediaVideo(media=e["file_id"], caption=c, supports_streaming=True, **_pm(plain)))
                else:
                    media.append(InputMediaPhoto(media=e["file_id"], caption=c, **_pm(plain)))
            await self.bot.send_media_group(chat_id=chat_id, media=media, reply_parameters=_reply(reply_to))
            return
        e = entries[0]
        kw: dict[str, Any] = {"chat_id": chat_id, "caption": cap, "reply_parameters": _reply(reply_to), **_pm(plain)}
        if e["type"] == "video":
            await self.bot.send_video(video=e["file_id"], supports_streaming=True, reply_markup=reply_markup, **kw)
        elif e["type"] == "audio":
            await self.bot.send_audio(audio=e["file_id"], **kw)
        elif e["type"] == "photo":
            await self.bot.send_photo(photo=e["file_id"], **kw)
        else:
            await self.bot.send_document(document=e["file_id"], reply_markup=reply_markup, **kw)

    @staticmethod
    def _entry(msg: Message) -> dict[str, str]:
        r = _file_id(msg)
        return {"type": r[0], "file_id": r[1]} if r else {}
