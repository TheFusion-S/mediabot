"""Per-user sliding-window limits and a light flood guard middleware."""

from __future__ import annotations

import time
from collections import deque
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from . import texts


class RateLimiter:
    """Sliding window: at most ``limit`` hits per ``window`` seconds per key.

    Keys with no hits inside the window are dropped (on access and by a periodic sweep),
    so memory stays proportional to *recently active* users.
    """

    PRUNE_EVERY = 1024  # operations between full sweeps

    def __init__(self, limit: int, window: float = 3600.0, clock: Callable[[], float] = time.monotonic):
        self.limit = limit
        self.window = window
        self._clock = clock
        self._hits: dict[int, deque[float]] = {}
        self._ops = 0
        self._last_prune = clock()

    def _trim(self, key: int) -> deque[float]:
        q = self._hits.get(key)
        if q is None:
            return deque()
        cutoff = self._clock() - self.window
        while q and q[0] <= cutoff:
            q.popleft()
        if not q:
            del self._hits[key]
        return q

    def _tick(self) -> None:
        """Full sweep every PRUNE_EVERY hits, or when a whole window has passed since the last sweep."""
        self._ops += 1
        now = self._clock()
        if self._ops >= self.PRUNE_EVERY or now - self._last_prune >= min(self.window, 60.0):
            self._ops = 0
            self._last_prune = now
            self.prune()

    def prune(self) -> None:
        for key in list(self._hits):
            self._trim(key)

    def __len__(self) -> int:
        return len(self._hits)

    def used(self, key: int) -> int:
        return len(self._trim(key))

    def allowed(self, key: int) -> bool:
        return self.used(key) < self.limit

    def hit(self, key: int) -> bool:
        """Record a hit if allowed. Returns False (and records nothing) when over limit."""
        self._tick()
        q = self._trim(key)
        if len(q) >= self.limit:
            return False
        if key not in self._hits:
            self._hits[key] = q
        q.append(self._clock())
        return True

    def retry_after(self, key: int) -> float:
        q = self._trim(key)
        if len(q) < self.limit or not q:
            return 0.0
        return max(0.0, q[0] + self.window - self._clock())


class FloodMiddleware(BaseMiddleware):
    """Drops messages from users sending more than ``limit`` messages per ``window`` seconds."""

    def __init__(self, limit: int = 8, window: float = 10.0):
        self.limiter = RateLimiter(limit, window)
        self._warned: dict[int, float] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        if user is None:
            return await handler(event, data)
        if self.limiter.hit(user.id):
            return await handler(event, data)
        now = time.monotonic()
        if len(self._warned) > 10_000:  # bounded memory
            self._warned = {k: v for k, v in self._warned.items() if now - v <= 30}
        if isinstance(event, Message) and event.chat.type == "private" and now - self._warned.get(user.id, 0) > 30:
            self._warned[user.id] = now
            try:
                await event.answer(texts.TOO_MANY_MESSAGES)
            except Exception:  # pragma: no cover - network
                pass
        return None
