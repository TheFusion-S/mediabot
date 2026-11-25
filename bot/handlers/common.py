"""Helpers shared by handlers: starting a job with a live progress message."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot
from aiogram.types import ReplyParameters

from ..errors import AppError
from ..jobs import Job, JobManager
from ..platforms import Link
from ..progress import ProgressReporter
from .. import texts

log = logging.getLogger(__name__)

_background: set[asyncio.Task] = set()


def keep(task: asyncio.Task) -> asyncio.Task:
    _background.add(task)
    task.add_done_callback(_background.discard)
    return task


def reply_to(message_id: int | None) -> ReplyParameters | None:
    return ReplyParameters(message_id=message_id, allow_sending_without_reply=True) if message_id else None


async def start_job(
    *,
    bot: Bot,
    jobs: JobManager,
    chat_id: int,
    user_id: int,
    link: Link,
    fmt: str,
    reply_message_id: int | None = None,
    title: str | None = None,
    thumbnail: str | None = None,
) -> Job | None:
    try:
        job = await jobs.submit(user_id=user_id, chat_id=chat_id, link=link, fmt=fmt, origin="bot",
                                title=title, thumbnail=thumbnail, reply_to=reply_message_id)
    except AppError as exc:
        try:
            await bot.send_message(chat_id, "❌ " + exc.message, reply_parameters=reply_to(reply_message_id))
        except Exception as send_exc:  # blocked bot, RetryAfter, deleted chat...
            log.info("could not deliver error to chat %s: %s", chat_id, send_exc)
        return None
    try:
        msg = await bot.send_message(chat_id, texts.STATUS_QUEUED, reply_parameters=reply_to(reply_message_id))
    except Exception:
        log.warning("could not send progress message for job %s", job.id)
        return job
    keep(ProgressReporter(bot, chat_id, msg.message_id, job).start())
    return job
