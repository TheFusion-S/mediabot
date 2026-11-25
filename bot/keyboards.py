"""Inline keyboards. callback_data only carries short server-side tokens, never URLs."""

from __future__ import annotations

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from . import texts
from .downloader import MediaInfo


class DownloadCB(CallbackData, prefix="dl"):
    token: str
    fmt: str


def webapp_keyboard(webapp_url: str) -> InlineKeyboardMarkup | None:
    if not webapp_url.lower().startswith("https://"):
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=texts.MINIAPP_BUTTON, web_app=WebAppInfo(url=webapp_url))]]
    )


def quality_keyboard(token: str, media: MediaInfo) -> InlineKeyboardMarkup:
    buttons: list[InlineKeyboardButton] = []
    for f in media.formats:
        if f.id in ("auto", "audio"):
            continue
        label = f.label
        size = texts.format_size(f.size)
        if size:
            label += f" · {size}"
        if not f.fits:
            label = f"{texts.OVER_LIMIT_MARK} {label}"
        buttons.append(InlineKeyboardButton(text=label, callback_data=DownloadCB(token=token, fmt=f.id).pack()))
    if not buttons:  # no tier info -> offer auto
        buttons.append(InlineKeyboardButton(text=texts.FORMAT_LABELS["auto"],
                                             callback_data=DownloadCB(token=token, fmt="auto").pack()))
    rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
    if media.format("audio") is not None:
        rows.append([InlineKeyboardButton(text=texts.MP3_KEY_BUTTON,
                                          callback_data=DownloadCB(token=token, fmt="audio").pack())])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def mp3_keyboard(token: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=texts.MP3_BUTTON,
                                               callback_data=DownloadCB(token=token, fmt="audio").pack())]]
    )
