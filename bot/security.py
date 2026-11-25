"""Telegram Mini App ``initData`` validation.

https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
secret_key = HMAC_SHA256(key="WebAppData", msg=bot_token)
hash       = hex(HMAC_SHA256(key=secret_key, msg=data_check_string))
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl

MAX_AGE_SEC = 24 * 3600
MAX_INIT_DATA_LEN = 8192
FUTURE_SKEW_SEC = 300


class InitDataError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class WebAppUser:
    id: int
    first_name: str
    username: str | None
    last_name: str | None = None
    language_code: str | None = None

    def to_api(self) -> dict:
        return {"id": self.id, "first_name": self.first_name, "username": self.username}


def secret_key(bot_token: str) -> bytes:
    return hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()


def data_check_string(fields: dict[str, str]) -> str:
    return "\n".join(f"{k}={fields[k]}" for k in sorted(fields))


def sign(fields: dict[str, str], bot_token: str) -> str:
    """Compute the ``hash`` for ``fields`` (used by tests and dev tooling)."""
    return hmac.new(secret_key(bot_token), data_check_string(fields).encode(), hashlib.sha256).hexdigest()


def validate_init_data(
    init_data: str, bot_token: str, *, max_age: int = MAX_AGE_SEC, now: float | None = None
) -> WebAppUser:
    if not init_data or len(init_data) > MAX_INIT_DATA_LEN:
        raise InitDataError("empty or oversized initData")
    try:
        pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=True)
    except ValueError as exc:
        raise InitDataError("malformed initData") from exc
    fields: dict[str, str] = {}
    for k, v in pairs:
        if k in fields:
            raise InitDataError("duplicate key")
        fields[k] = v
    received = fields.pop("hash", None)
    if not received:
        raise InitDataError("missing hash")
    expected = sign(fields, bot_token)
    if not hmac.compare_digest(expected.encode(), received.lower().encode()):
        raise InitDataError("bad signature")

    try:
        auth_date = int(fields.get("auth_date", ""))
    except ValueError as exc:
        raise InitDataError("bad auth_date") from exc
    now = time.time() if now is None else now
    if now - auth_date > max_age:
        raise InitDataError("initData expired")
    if auth_date - now > FUTURE_SKEW_SEC:
        raise InitDataError("auth_date in the future")

    try:
        user = json.loads(fields.get("user", ""))
        uid = int(user["id"])
    except (ValueError, KeyError, TypeError) as exc:
        raise InitDataError("bad user") from exc
    if not isinstance(user, dict) or uid <= 0:
        raise InitDataError("bad user")
    return WebAppUser(
        id=uid,
        first_name=str(user.get("first_name") or "")[:128],
        username=(str(user["username"])[:64] if user.get("username") else None),
        last_name=(str(user["last_name"])[:128] if user.get("last_name") else None),
        language_code=(str(user["language_code"])[:16] if user.get("language_code") else None),
    )
