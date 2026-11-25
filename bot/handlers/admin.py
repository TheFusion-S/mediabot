"""Admin commands (ADMIN_IDS only): /stats, /broadcast."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from .. import texts as T
from ..config import Settings
from ..jobs import JobManager
from ..storage import Storage
from .common import keep

log = logging.getLogger(__name__)

BROADCAST_DELAY = 0.05  # ~20 msg/s, below Telegram's ~30 msg/s global limit
_broadcast_lock = asyncio.Lock()


def is_admin(message: Message, settings: Settings) -> bool:
    return message.from_user is not None and message.from_user.id in settings.admin_ids


async def cmd_stats(message: Message, settings: Settings, db: Storage, jobs: JobManager) -> None:
    if not is_admin(message, settings):
        await message.answer(T.ADMIN_ONLY)
        return
    stats = await db.global_stats()
    await message.answer(T.fmt(T.STATS, active_jobs=jobs.active_count, **stats))


async def broadcast(
    bot: Bot, db: Storage, user_ids: list[int], *, text: str | None = None,
    from_chat_id: int | None = None, message_id: int | None = None, delay: float = BROADCAST_DELAY,
) -> dict[str, int]:
    result = {"sent": 0, "blocked": 0, "failed": 0}

    async def send(uid: int) -> None:
        if from_chat_id is not None and message_id is not None:
            await bot.copy_message(chat_id=uid, from_chat_id=from_chat_id, message_id=message_id)
        else:
            await bot.send_message(uid, text or "", parse_mode=None)

    for uid in user_ids:
        for attempt in range(3):
            try:
                await send(uid)
                result["sent"] += 1
                break
            except TelegramRetryAfter as exc:
                await asyncio.sleep(exc.retry_after + 1)
            except TelegramForbiddenError:
                result["blocked"] += 1
                await db.set_blocked(uid, True)
                break
            except TelegramBadRequest:
                result["failed"] += 1
                break
            except Exception:
                log.exception("broadcast to %s failed", uid)
                result["failed"] += 1
                break
        else:
            result["failed"] += 1
        await asyncio.sleep(delay)
    return result


async def cmd_broadcast(message: Message, command: CommandObject, bot: Bot, settings: Settings,
                        db: Storage) -> None:
    if not is_admin(message, settings):
        await message.answer(T.ADMIN_ONLY)
        return
    src = message.reply_to_message
    text = (command.args or "").strip()
    if src is None and not text:
        await message.answer(T.BROADCAST_USAGE)
        return
    if _broadcast_lock.locked():
        await message.answer(T.BROADCAST_RUNNING)
        return
    user_ids = await db.active_user_ids()
    await message.answer(T.fmt(T.BROADCAST_STARTED, total=len(user_ids)))

    async def run() -> None:
        async with _broadcast_lock:
            res = await broadcast(bot, db, user_ids, text=text or None,
                                  from_chat_id=src.chat.id if src else None,
                                  message_id=src.message_id if src else None)
        await message.answer(T.fmt(T.BROADCAST_DONE, **res))

    keep(asyncio.create_task(run(), name="broadcast"))


def register(router: Router) -> None:
    router.message.register(cmd_stats, Command("stats"))
    router.message.register(cmd_broadcast, Command("broadcast"))
