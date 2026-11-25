from __future__ import annotations

import html

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from ..config import Settings
from ..keyboards import webapp_keyboard
from ..storage import Storage
from .. import texts as T



async def cmd_start(message: Message, settings: Settings) -> None:
    name = html.escape(message.from_user.first_name if message.from_user else "")
    text = T.fmt(T.START, name=name)
    kb = webapp_keyboard(settings.webapp_url)
    if kb is not None:
        text += T.START_WEBAPP_HINT
    await message.answer(text, reply_markup=kb)


async def cmd_help(message: Message, settings: Settings) -> None:
    await message.answer(T.fmt(T.HELP, **settings.limits), reply_markup=webapp_keyboard(settings.webapp_url))


async def cmd_history(message: Message, db: Storage) -> None:
    if message.from_user is None:
        return
    if message.chat.type != "private":  # personal data: never list it in a group
        await message.reply(T.HISTORY_PRIVATE_ONLY)
        return
    rows = await db.history(message.from_user.id, "all", 10)
    if not rows:
        await message.answer(T.HISTORY_EMPTY)
        return
    lines = [T.HISTORY_TITLE]
    for r in rows:
        icon = T.STATUS_ICONS.get(r["status"]) or T.SECTION_ICONS.get(r["section"], "•")
        fmt = T.FORMAT_LABELS.get(r["format"], r["format"])
        lines.append(T.fmt(T.HISTORY_LINE, icon=icon, url=html.escape(r["url"], quote=True),
                           title=html.escape((r["title"] or T.DEFAULT_TITLE)[:60]), format=fmt))
    await message.answer("\n".join(lines), disable_web_page_preview=True)


def register(router: Router) -> None:
    router.message.register(cmd_start, CommandStart())
    router.message.register(cmd_help, Command("help"))
    router.message.register(cmd_history, Command("history"))
