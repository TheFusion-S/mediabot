"""Application settings loaded from environment / .env (pydantic-settings)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated, Any

import ipaddress

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent

_TOKEN_RE = re.compile(r"\d{3,15}:[A-Za-z0-9_-]{20,}")


def _is_loopback(host: str) -> bool:
    host = host.strip().strip("[]").lower()
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    bot_token: SecretStr
    webapp_url: str = ""
    web_host: str = "0.0.0.0"
    web_port: int = Field(8080, ge=1, le=65535)
    admin_ids: Annotated[list[int], NoDecode] = Field(default_factory=list)
    # Shaxsiy rejim: faqat shu Telegram ID'lar botdan va Mini App'dan foydalana oladi.
    # Bo'sh bo'lsa bot "sozlash rejimi"da: hech narsa yuklamaydi, faqat /start'ga ID'ingizni aytadi.
    allowed_user_ids: Annotated[list[int], NoDecode] = Field(default_factory=list)
    # true = hamma uchun ochiq bot (tavsiya etilmaydi). Standart: false (shaxsiy).
    public_mode: bool = False

    max_upload_mb: int = Field(50, ge=1, le=2000)
    telegram_api_base: str | None = None
    max_duration_min: int = Field(120, ge=1)
    max_concurrent_downloads: int = Field(3, ge=1, le=32)
    user_hourly_limit: int = Field(30, ge=1)

    download_dir: Path = PROJECT_ROOT / "data" / "downloads"
    db_path: Path = PROJECT_ROOT / "data" / "mediabot.db"
    cookies_file: Path | None = None
    transcode_non_h264: bool = True
    dev_mode: bool = False
    # Max age of Mini App initData (auth_date). SPEC allows up to 24h; shorter is safer.
    init_data_max_age_hours: float = Field(6, gt=0, le=24)

    webapp_dir: Path = PROJECT_ROOT / "webapp"
    # Bot avatari (JPG). Bot uni o'zi qo'yadi — faqat rasm o'zgargandagina qayta yuklanadi.
    # O'chirish uchun bo'sh qoldiring: BOT_AVATAR_FILE=
    bot_avatar_file: Path | None = PROJECT_ROOT / "assets" / "bot-avatar.jpg"
    log_level: str = "INFO"

    @field_validator("bot_token")
    @classmethod
    def _check_token(cls, v: SecretStr) -> SecretStr:
        if not _TOKEN_RE.fullmatch(v.get_secret_value().strip()):
            raise ValueError("BOT_TOKEN formati noto'g'ri (kutilgan: 123456:ABC...)")
        return SecretStr(v.get_secret_value().strip())

    @field_validator("admin_ids", "allowed_user_ids", mode="before")
    @classmethod
    def _parse_admins(cls, v: Any) -> Any:
        if v is None or v == "":
            return []
        if isinstance(v, int):
            return [v]
        if isinstance(v, str):
            return [int(p) for p in re.split(r"[,\s;]+", v.strip()) if p]
        return v

    @field_validator("telegram_api_base", "cookies_file", "bot_avatar_file", mode="before")
    @classmethod
    def _empty_to_none(cls, v: Any) -> Any:
        return None if isinstance(v, str) and not v.strip() else v

    @field_validator("telegram_api_base")
    @classmethod
    def _check_api_base(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip().rstrip("/")
        if not re.match(r"^https?://[A-Za-z0-9.\-]+(:\d+)?$", v):
            raise ValueError("TELEGRAM_API_BASE masalan http://telegram-bot-api:8081 bo'lishi kerak")
        return v

    @field_validator("webapp_url")
    @classmethod
    def _strip_url(cls, v: str) -> str:
        return v.strip()

    @model_validator(mode="after")
    def _owner_is_admin(self) -> "Settings":
        """In private mode the owner(s) also get the admin commands unless ADMIN_IDS is set explicitly."""
        if not self.admin_ids and self.allowed_user_ids:
            self.admin_ids = list(self.allowed_user_ids)
        return self

    @model_validator(mode="after")
    def _dev_mode_guard(self) -> "Settings":
        """DEV_MODE disables Mini App auth: only allow it on a loopback-only, non-public setup."""
        if self.dev_mode:
            problems = []
            if self.webapp_url:
                problems.append("WEBAPP_URL o'rnatilgan (public Mini App)")
            if not _is_loopback(self.web_host):
                problems.append(f"WEB_HOST={self.web_host} loopback emas")
            if problems:
                raise ValueError(
                    "DEV_MODE=true faqat lokal ishlab chiqish uchun: " + "; ".join(problems)
                    + ". Productionda DEV_MODE=false qiling yoki WEBAPP_URL ni bo'shatib WEB_HOST=127.0.0.1 qiling. "
                    "(DEV_MODE disables Mini App authentication and is refused unless WEB_HOST is loopback "
                    "and WEBAPP_URL is empty.)"
                )
        return self

    # derived ---------------------------------------------------------------
    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def max_duration_sec(self) -> int:
        return self.max_duration_min * 60

    @property
    def webapp_enabled(self) -> bool:
        return self.webapp_url.lower().startswith("https://")

    @property
    def limits(self) -> dict[str, int]:
        """Parameters used to render limit-related error texts."""
        return {
            "max_upload_mb": self.max_upload_mb,
            "max_duration_min": self.max_duration_min,
            "hourly_limit": self.user_hourly_limit,
        }


def access_set(settings: "Settings") -> frozenset[int] | None:
    """Who may use the bot: None = everyone (public_mode), otherwise the allowed IDs (may be empty)."""
    if settings.public_mode:
        return None
    return frozenset(settings.allowed_user_ids) | frozenset(settings.admin_ids)
