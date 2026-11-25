"""Bot progress message: edited at most every 1.5 s, only when the text changes."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter

from . import texts
from .jobs import Job

log = logging.getLogger(__name__)

MIN_EDIT_INTERVAL = 1.5


def render_status(job: Job) -> str:
    if job.status == "queued":
        return texts.STATUS_QUEUED
    if job.status == "downloading":
        return texts.fmt(texts.STATUS_DOWNLOADING, progress=job.progress)
    if job.status == "processing":
        return texts.STATUS_PROCESSING
    if job.status == "uploading":
        return texts.STATUS_UPLOADING
    if job.status == "done":
        return texts.STATUS_DONE
    return "❌ " + ((job.error or {}).get("message") or texts.error_text("internal"))


class ProgressReporter:
    def __init__(self, bot: Bot, chat_id: int, message_id: int, job: Job,
                 interval: float = MIN_EDIT_INTERVAL, clock=time.monotonic):
        self.bot = bot
        self.chat_id = chat_id
        self.message_id = message_id
        self.job = job
        self.interval = interval
        self._clock = clock
        self._last_text = texts.STATUS_QUEUED
        self._last_edit = clock()
        self.edits = 0

    def start(self) -> asyncio.Task:
        return asyncio.create_task(self.run(), name=f"progress-{self.job.id}")

    async def _edit(self, text: str) -> None:
        if text == self._last_text:
            return
        wait = self.interval - (self._clock() - self._last_edit)
        if wait > 0:
            await asyncio.sleep(wait)
        try:
            await self.bot.edit_message_text(text=text, chat_id=self.chat_id, message_id=self.message_id)
        except TelegramRetryAfter as exc:
            await asyncio.sleep(exc.retry_after)
        except TelegramBadRequest:  # "message is not modified" / deleted
            pass
        self._last_text = text
        self._last_edit = self._clock()
        self.edits += 1

    async def run(self) -> None:
        try:
            while not self.job.finished:
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(self.job.done_event.wait(), self.interval)
                if not self.job.finished:
                    await self._edit(render_status(self.job))
            if self.job.status == "done":
                with contextlib.suppress(Exception):
                    await self.bot.delete_message(chat_id=self.chat_id, message_id=self.message_id)
            else:
                await self._edit(render_status(self.job))
        except asyncio.CancelledError:
            raise
        except Exception:  # never let UI updates crash anything
            log.exception("progress reporter failed")
