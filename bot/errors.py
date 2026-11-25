"""Application error type with stable error codes shared by the bot and the HTTP API."""

from __future__ import annotations

from typing import Any

from . import texts

# code -> HTTP status (see SPEC "Xato kodlari")
HTTP_STATUS: dict[str, int] = {
    "unauthorized": 401,
    "bad_request": 400,
    "invalid_url": 400,
    "unsupported": 400,
    "private": 403,
    "forbidden": 403,
    "not_found": 404,
    "too_long": 413,
    "too_large": 413,
    "rate_limited": 429,
    "busy": 409,
    "internal": 500,
}


class AppError(Exception):
    """An expected, user-presentable error.

    ``code`` is one of :data:`HTTP_STATUS` keys. ``message`` is the Uzbek user-facing
    text; when omitted it is rendered from :data:`texts.ERRORS` with ``params``.
    """

    def __init__(self, code: str, message: str | None = None, *, status: int | None = None, **params: Any):
        if code not in HTTP_STATUS:
            code = "internal"
        self.code = code
        self.params = params
        self.message = message or texts.error_text(code, **params)
        self.status = status or HTTP_STATUS[code]
        super().__init__(f"{code}: {self.message}")

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


class SizeExceeded(AppError):
    """The produced file (or yt-dlp's selected format) is bigger than the upload limit."""

    def __init__(self, **params: Any):
        super().__init__("too_large", **params)
