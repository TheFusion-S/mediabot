"""Owner-managed access: /id, /mode, /users, /allow, /revoke, /block, /unblock and the request buttons.

Callback data (<= 64 bytes): acc:req | acc:ok:<uid> | acc:no:<uid> | acc:ban:<uid> | acc:rev:<uid> |
acc:unb:<uid> | acc:mode:<open|private>
"""

from __future__ import annotations

import html
import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, User

from .. import texts as T
from ..access import Access
from ..storage import Storage

log = logging.getLogger(__name__)

# action -> (stored status or None to forget, owner-facing result, message to the user or None)
ACTIONS = {
    "ok": ("approved", T.RESULT_APPROVED, T.USER_APPROVED),
    "no": (None, T.RESULT_REJECTED, T.USER_REJECTED),
    "ban": ("blocked", T.RESULT_BLOCKED, None),
    "rev": (None, T.RESULT_REVOKED, T.USER_REVOKED),
    "unb": (None, T.RESULT_UNBLOCKED, None),
}
COMMAND_ACTIONS = {"allow": "ok", "revoke": "rev", "block": "ban", "unblock": "unb"}


def who(user_id: int, first_name: str | None, username: str | None) -> str:
    name = html.escape(first_name or "") or "Foydalanuvchi"
    return f"{name} (@{html.escape(username)})" if username else name


def mode_label(mode: str) -> str:
    return T.MODE_OPEN if mode == "open" else T.MODE_PRIVATE


def request_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=T.REQUEST_BUTTON, callback_data="acc:req")]])


def decision_keyboard(uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=T.BTN_APPROVE, callback_data=f"acc:ok:{uid}"),
         InlineKeyboardButton(text=T.BTN_REJECT, callback_data=f"acc:no:{uid}")],
        [InlineKeyboardButton(text=T.BTN_BLOCK, callback_data=f"acc:ban:{uid}")],
    ])


def mode_keyboard(mode: str) -> InlineKeyboardMarkup:
    def b(m: str) -> InlineKeyboardButton:
        mark = "• " if m == mode else ""
        return InlineKeyboardButton(text=mark + mode_label(m), callback_data=f"acc:mode:{m}")
    return InlineKeyboardMarkup(inline_keyboard=[[b("open"), b("private")]])


# ------------------------------------------------------------------ everyone
async def cmd_id(message: Message, access: Access) -> None:
    if message.from_user is None:
        return
    text = T.fmt(T.MY_ID, user_id=message.from_user.id)
    if not access.owners and message.chat.type == "private":
        text += T.fmt(T.OWNER_HINT, user_id=message.from_user.id)
    await message.answer(text)


async def send_request(bot: Bot, access: Access, user: User) -> str:
    """Store a pending request and notify every owner. Returns the text to show the requester."""
    status = await access.db.get_access(user.id)
    if status == "pending":
        return T.REQUEST_PENDING
    await access.db.set_access(user.id, "pending", user.first_name, user.username)
    text = T.fmt(T.OWNER_REQUEST, who=who(user.id, user.first_name, user.username), user_id=user.id)
    for owner in access.owners:
        try:
            await bot.send_message(owner, text, reply_markup=decision_keyboard(user.id))
        except Exception as exc:  # owner never started the bot, blocked it, ...
            log.warning("could not notify owner %s about access request: %s", owner, exc)
    return T.REQUEST_SENT


async def cb_request(call: CallbackQuery, bot: Bot, access: Access) -> None:
    decision = await access.check(call.from_user.id)
    if decision.allowed:
        await call.answer()
        return
    if decision.reason in ("blocked", "setup"):
        await call.answer(T.PRIVATE_BOT, show_alert=True)
        return
    await call.answer(await send_request(bot, access, call.from_user), show_alert=True)


# ------------------------------------------------------------------ owner
async def apply_action(bot: Bot, access: Access, action: str, uid: int) -> str:
    status, result, notice = ACTIONS[action]
    await access.db.set_access(uid, status)
    if notice:
        try:
            await bot.send_message(uid, notice)
        except Exception as exc:
            log.info("could not notify user %s: %s", uid, exc)
    return result


async def cb_owner(call: CallbackQuery, bot: Bot, access: Access, db: Storage) -> None:
    if not access.is_owner(call.from_user.id):
        await call.answer(T.OWNER_ONLY, show_alert=True)
        return
    parts = (call.data or "").split(":")
    if len(parts) == 3 and parts[1] == "mode" and parts[2] in ("open", "private"):
        await access.set_mode(parts[2])
        await call.answer(T.fmt(T.MODE_CHANGED, mode=mode_label(parts[2])))
        if call.message is not None:
            await call.message.edit_text(T.fmt(T.MODE_STATUS, mode=mode_label(parts[2])),
                                         reply_markup=mode_keyboard(parts[2]))
        return
    if len(parts) != 3 or parts[1] not in ACTIONS or not parts[2].isdigit():
        await call.answer()
        return
    action, uid = parts[1], int(parts[2])
    if access.is_owner(uid):
        await call.answer(T.CANNOT_TARGET_OWNER, show_alert=True)
        return
    result = await apply_action(bot, access, action, uid)
    await call.answer(result)
    if call.message is not None:
        rows = await _user_label(db, uid)
        await call.message.edit_text(T.fmt(T.OWNER_DECIDED, who=rows, result=result))


async def _user_label(db: Storage, uid: int) -> str:
    async with db.db.execute("SELECT first_name, username FROM users WHERE id=?", (uid,)) as cur:
        row = await cur.fetchone()
    first, username = (row if row else (None, None))
    if not first:
        async with db.db.execute("SELECT first_name, username FROM access WHERE user_id=?", (uid,)) as cur:
            row = await cur.fetchone()
        first, username = (row if row else (None, None))
    return f"{who(uid, first, username)} (<code>{uid}</code>)"


async def cmd_mode(message: Message, access: Access) -> None:
    if message.from_user is None or not access.is_owner(message.from_user.id):
        await message.answer(T.OWNER_ONLY)
        return
    mode = await access.mode()
    await message.answer(T.fmt(T.MODE_STATUS, mode=mode_label(mode)), reply_markup=mode_keyboard(mode))


async def cmd_users(message: Message, access: Access, db: Storage) -> None:
    if message.from_user is None or not access.is_owner(message.from_user.id):
        await message.answer(T.OWNER_ONLY)
        return
    mode = await access.mode()
    approved = await db.list_access("approved")
    pending = await db.list_access("pending")
    blocked = await db.list_access("blocked")
    text = T.fmt(T.USERS_TITLE, mode=mode_label(mode))
    rows: list[list[InlineKeyboardButton]] = []
    if not (approved or pending or blocked):
        text += T.USERS_EMPTY
    for title, items, btn_text, act in (
        (T.USERS_APPROVED, approved, T.BTN_REVOKE, "rev"),
        (T.USERS_PENDING, pending, T.BTN_APPROVE, "ok"),
        (T.USERS_BLOCKED, blocked, T.BTN_UNBLOCK, "unb"),
    ):
        if not items:
            continue
        text += T.fmt(title, count=len(items))
        for r in items[:15]:
            label = who(r["user_id"], r["first_name"], r["username"])
            text += f"\n• {label} — <code>{r['user_id']}</code>"
            rows.append([InlineKeyboardButton(text=f"{btn_text}: {r['first_name'] or r['user_id']}"[:60],
                                              callback_data=f"acc:{act}:{r['user_id']}")])
    text += T.USERS_HELP
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows) if rows else None)


async def cmd_user_action(message: Message, command: CommandObject, bot: Bot, access: Access) -> None:
    if message.from_user is None or not access.is_owner(message.from_user.id):
        await message.answer(T.OWNER_ONLY)
        return
    arg = (command.args or "").strip()
    if not arg.isdigit() or len(arg) > 15:
        await message.answer(T.fmt(T.USER_CMD_USAGE, cmd=command.command))
        return
    uid = int(arg)
    if access.is_owner(uid):
        await message.answer(T.CANNOT_TARGET_OWNER)
        return
    result = await apply_action(bot, access, COMMAND_ACTIONS[command.command], uid)
    await message.answer(T.fmt(T.USER_CMD_DONE, user_id=uid, result=result))


def register(router: Router) -> None:
    router.message.register(cmd_id, Command("id"))
    router.message.register(cmd_mode, Command("mode"))
    router.message.register(cmd_users, Command("users"))
    router.message.register(cmd_user_action, Command(*COMMAND_ACTIONS))
    router.callback_query.register(cb_request, F.data == "acc:req")
    router.callback_query.register(cb_owner, F.data.startswith("acc:"))
