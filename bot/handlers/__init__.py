"""aiogram routers. Order matters: commands first, the catch-all link handler last."""

from __future__ import annotations

import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, Dispatcher, Router
from aiogram.types import CallbackQuery, Message, TelegramObject

from .. import texts
from ..config import access_set
from ..ratelimit import FloodMiddleware
from . import admin, callbacks, links, start


class AccessMiddleware(BaseMiddleware):
    """Private mode: only ALLOWED_USER_IDS (and ADMIN_IDS) reach any handler.

    With an empty allow-list the bot is in setup mode: it downloads nothing and only tells
    the person their Telegram ID so they can put it into .env. Strangers get a short notice
    (at most once per hour each) in private chats and silence in groups.
    """

    NOTICE_EVERY = 3600.0
    MAX_TRACKED = 10_000

    def __init__(self) -> None:
        self._notified: dict[int, float] = {}

    def _should_notify(self, user_id: int) -> bool:
        now = time.monotonic()
        last = self._notified.get(user_id)
        if last is not None and now - last < self.NOTICE_EVERY:
            return False
        if len(self._notified) >= self.MAX_TRACKED:
            self._notified = {k: v for k, v in self._notified.items() if now - v < self.NOTICE_EVERY}
            if len(self._notified) >= self.MAX_TRACKED:
                return False
        self._notified[user_id] = now
        return True

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        settings = data.get("settings")
        allowed = access_set(settings) if settings is not None else frozenset()
        user = getattr(event, "from_user", None)
        if allowed is None or (user is not None and user.id in allowed):
            return await handler(event, data)
        if user is None:
            return None
        setup = not allowed
        try:
            if isinstance(event, Message):
                if event.chat.type != "private":
                    return None
                if setup:
                    await event.answer(texts.SETUP_MODE.format(user_id=user.id), parse_mode="HTML")
                elif self._should_notify(user.id):
                    await event.answer(texts.PRIVATE_BOT, parse_mode=None)
            elif isinstance(event, CallbackQuery):
                await event.answer(texts.PRIVATE_BOT, show_alert=True)
        except Exception:  # pragma: no cover - never let a notice crash the update loop
            pass
        return None


class UserMiddleware(BaseMiddleware):
    """Records users who talk to the bot in private (broadcast targets)."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        db = data.get("db")
        user = getattr(event, "from_user", None)
        chat = event.chat if isinstance(event, Message) else (
            event.message.chat if isinstance(event, CallbackQuery) and event.message else None)
        if db is not None and user is not None and chat is not None and chat.type == "private":
            try:
                await db.upsert_user(user.id, user.first_name, user.username)
            except Exception:  # pragma: no cover
                pass
        return await handler(event, data)


def setup_dispatcher(dp: Dispatcher) -> None:
    access = AccessMiddleware()
    flood = FloodMiddleware()
    users = UserMiddleware()
    for observer in (dp.message, dp.callback_query):
        observer.outer_middleware(access)  # first: strangers never reach limits, DB or handlers
        observer.outer_middleware(flood)
        observer.outer_middleware(users)
    router = Router(name="mediabot")
    for module in (start, admin, callbacks, links):  # catch-all link handler last
        module.register(router)
    dp.include_router(router)
