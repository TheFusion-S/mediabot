"""Who may use the bot — one place for the Telegram handlers and the Mini App API.

Rules (first match wins):
  owner (ADMIN_IDS)                      -> allowed
  blocked by the owner                   -> denied ("blocked")
  mode "open"                            -> allowed
  mode "private", no owner configured    -> denied ("setup": the bot only tells people their ID)
  mode "private", pre-approved/approved  -> allowed
  mode "private", otherwise              -> denied ("pending" if a request is waiting, else "none")

The mode starts from ACCESS_MODE and the owner changes it at runtime with /mode (stored in the DB).
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import Settings
from .storage import Storage

MODES = ("open", "private")
MODE_KEY = "access_mode"


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str  # owner | open | approved | blocked | setup | pending | none


class Access:
    def __init__(self, settings: Settings, storage: Storage) -> None:
        self.settings = settings
        self.db = storage

    @property
    def owners(self) -> frozenset[int]:
        return frozenset(self.settings.admin_ids)

    def is_owner(self, user_id: int) -> bool:
        return user_id in self.owners

    async def mode(self) -> str:
        stored = await self.db.get_setting(MODE_KEY)
        return stored if stored in MODES else self.settings.access_mode

    async def set_mode(self, mode: str) -> None:
        if mode not in MODES:
            raise ValueError(mode)
        await self.db.set_setting(MODE_KEY, mode)

    async def check(self, user_id: int) -> Decision:
        if self.is_owner(user_id):
            return Decision(True, "owner")
        status = await self.db.get_access(user_id)
        if status == "blocked":
            return Decision(False, "blocked")
        if await self.mode() == "open":
            return Decision(True, "open")
        if not self.owners:
            return Decision(False, "setup")
        if status == "approved" or user_id in self.settings.allowed_user_ids:
            return Decision(True, "approved")
        return Decision(False, "pending" if status == "pending" else "none")
