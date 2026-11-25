"""aiogram routers. Order matters: commands first, the catch-all link handler last."""

from __future__ import annotations

import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, Dispatcher, Router
from aiogram.types import CallbackQuery, Message, TelegramObject

from .. import texts
from ..access import Access
from ..ratelimit import FloodMiddleware
from . import access as access_handlers, admin, callbacks, links, start
from .access import request_keyboard


class AccessMiddleware(BaseMiddleware):
    """Applies :class:`bot.access.Access` to every message / button press before any handler runs.

    Denied users in private chats get one explanation (with a "request access" button in private
    mode, at most once per hour each); in groups the bot stays silent. ``/id`` and the request
    button always pass through so people can find their ID and ask the owner for access.
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

    @staticmethod
    def _always_allowed(event: TelegramObject) -> bool:
        if isinstance(event, Message):
            cmd = (event.text or "").split(maxsplit=1)[0].split("@", 1)[0].lower() if event.text else ""
            return cmd == "/id"
        if isinstance(event, CallbackQuery):
            return event.data == "acc:req"
        return False

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        if user is None:
            return None
        access: Access | None = data.get("access")
        if access is None:
            settings, db = data.get("settings"), data.get("db")
            if settings is None or db is None:  # misconfigured dispatcher: fail closed
                return None
            access = data["access"] = Access(settings, db)
        decision = await access.check(user.id)
        if decision.allowed or self._always_allowed(event):
            return await handler(event, data)
        if decision.reason == "blocked":
            if isinstance(event, CallbackQuery):
                await _safe(event.answer())
            return None
        try:
            if isinstance(event, Message):
                if event.chat.type != "private":
                    return None
                if decision.reason == "setup":
                    await event.answer(texts.fmt(texts.SETUP_MODE, user_id=user.id), parse_mode="HTML")
                elif decision.reason == "pending":
                    if self._should_notify(user.id):
                        await event.answer(texts.REQUEST_PENDING, parse_mode=None)
                elif self._should_notify(user.id):
                    await event.answer(texts.PRIVATE_BOT, parse_mode=None, reply_markup=request_keyboard())
            elif isinstance(event, CallbackQuery):
                await event.answer(texts.PRIVATE_BOT, show_alert=True)
        except Exception:  # pragma: no cover - never let a notice crash the update loop
            pass
        return None


async def _safe(aw: Awaitable[Any]) -> None:
    try:
        await aw
    except Exception:  # pragma: no cover
        pass


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
    gate = AccessMiddleware()
    flood = FloodMiddleware()
    users = UserMiddleware()
    for observer in (dp.message, dp.callback_query):
        observer.outer_middleware(gate)  # first: strangers never reach limits, DB or handlers
        observer.outer_middleware(flood)
        observer.outer_middleware(users)
    router = Router(name="mediabot")
    for module in (start, admin, access_handlers, callbacks, links):  # catch-all link handler last
        module.register(router)
    dp.include_router(router)
