"""Inline button presses: ``dl:<token>:<format>`` -> server-side URL lookup -> job."""

from __future__ import annotations

from aiogram import Bot, Router
from aiogram.types import CallbackQuery

from .. import texts as T
from ..downloader import FORMAT_IDS
from ..jobs import JobManager
from ..keyboards import DownloadCB
from ..platforms import classify
from ..storage import Storage
from .common import start_job



async def on_download(cb: CallbackQuery, callback_data: DownloadCB, bot: Bot, db: Storage,
                      jobs: JobManager) -> None:
    url = await db.url_for_token(callback_data.token)
    link = classify(url) if url else None  # re-validate even server-stored URLs
    if link is None or callback_data.fmt not in FORMAT_IDS:
        await cb.answer(T.LINK_EXPIRED, show_alert=True)
        return
    await cb.answer()
    chat_id = cb.message.chat.id if cb.message else cb.from_user.id
    reply_id = cb.message.message_id if cb.message else None
    await start_job(bot=bot, jobs=jobs, chat_id=chat_id, user_id=cb.from_user.id, link=link,
                    fmt=callback_data.fmt, reply_message_id=reply_id)


def register(router: Router) -> None:
    router.callback_query.register(on_download, DownloadCB.filter())
