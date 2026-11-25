"""SQLite persistence (aiosqlite): users, download history, file_id cache, callback tokens."""

from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    first_name TEXT,
    username TEXT,
    created_at TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    is_blocked INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS downloads (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    platform TEXT NOT NULL,
    kind TEXT NOT NULL,
    section TEXT NOT NULL,
    media_id TEXT NOT NULL,
    url TEXT NOT NULL,
    title TEXT,
    thumbnail TEXT,
    format TEXT NOT NULL,
    status TEXT NOT NULL,
    error_code TEXT,
    error_message TEXT,
    used_format TEXT,
    note TEXT,
    created_at TEXT NOT NULL,
    finished_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_downloads_user ON downloads(user_id, created_at DESC);
CREATE TABLE IF NOT EXISTS file_cache (
    media_key TEXT NOT NULL,
    format TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (media_key, format)
);
CREATE TABLE IF NOT EXISTS tokens (
    token TEXT PRIMARY KEY,
    url TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);
"""

SECTIONS = ("instagram", "shorts", "videos")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime | None = None) -> str:
    return (dt or utcnow()).isoformat(timespec="seconds")


class Storage:
    def __init__(self, path: Path | str):
        self.path = str(path)
        self._db: aiosqlite.Connection | None = None

    async def open(self) -> "Storage":
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self.path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA foreign_keys=ON")
        await self._db.executescript(SCHEMA)
        await self._migrate()
        await self._db.commit()
        return self

    async def _migrate(self) -> None:
        """Add columns introduced after the first release (idempotent)."""
        async with self.db.execute("PRAGMA table_info(downloads)") as cur:
            cols = {r[1] for r in await cur.fetchall()}
        for col in ("used_format", "note"):
            if col not in cols:
                await self.db.execute(f"ALTER TABLE downloads ADD COLUMN {col} TEXT")

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    @property
    def db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("storage is not open")
        return self._db

    # users ---------------------------------------------------------------
    async def upsert_user(self, user_id: int, first_name: str | None, username: str | None) -> None:
        now = iso()
        await self.db.execute(
            """INSERT INTO users(id, first_name, username, created_at, last_seen, is_blocked)
               VALUES (?, ?, ?, ?, ?, 0)
               ON CONFLICT(id) DO UPDATE SET first_name=excluded.first_name, username=excluded.username,
                   last_seen=excluded.last_seen, is_blocked=0""",
            (user_id, (first_name or "")[:128], (username or "")[:64] or None, now, now),
        )
        await self.db.commit()

    async def set_blocked(self, user_id: int, blocked: bool = True) -> None:
        await self.db.execute("UPDATE users SET is_blocked=? WHERE id=?", (int(blocked), user_id))
        await self.db.commit()

    async def active_user_ids(self) -> list[int]:
        async with self.db.execute("SELECT id FROM users WHERE is_blocked=0 ORDER BY id") as cur:
            return [r[0] for r in await cur.fetchall()]

    # downloads -----------------------------------------------------------
    async def add_download(self, row: dict[str, Any]) -> None:
        await self.db.execute(
            """INSERT OR REPLACE INTO downloads(id, user_id, platform, kind, section, media_id, url, title,
                   thumbnail, format, status, error_code, error_message, used_format, note, created_at, finished_at)
               VALUES (:id, :user_id, :platform, :kind, :section, :media_id, :url, :title, :thumbnail,
                   :format, :status, :error_code, :error_message, :used_format, :note, :created_at, :finished_at)""",
            {"error_code": None, "error_message": None, "used_format": None, "note": None, "finished_at": None,
             **row},
        )
        await self.db.commit()

    async def update_download(self, job_id: str, **fields: Any) -> None:
        allowed = {"status", "error_code", "error_message", "finished_at", "title", "thumbnail",
                   "kind", "section", "format", "used_format", "note"}
        sets = {k: v for k, v in fields.items() if k in allowed}
        if not sets:
            return
        cols = ", ".join(f"{k}=?" for k in sets)
        await self.db.execute(f"UPDATE downloads SET {cols} WHERE id=?", (*sets.values(), job_id))
        await self.db.commit()

    async def get_download(self, job_id: str, user_id: int) -> dict[str, Any] | None:
        async with self.db.execute("SELECT * FROM downloads WHERE id=? AND user_id=?", (job_id, user_id)) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None

    async def history(self, user_id: int, section: str = "all", limit: int = 20) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 50))
        if section in SECTIONS:
            q, args = "SELECT * FROM downloads WHERE user_id=? AND section=? ORDER BY created_at DESC, rowid DESC LIMIT ?", (user_id, section, limit)
        else:
            q, args = "SELECT * FROM downloads WHERE user_id=? ORDER BY created_at DESC, rowid DESC LIMIT ?", (user_id, limit)
        async with self.db.execute(q, args) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def user_stats(self, user_id: int) -> dict[str, int]:
        stats = {"total": 0, **{s: 0 for s in SECTIONS}}
        async with self.db.execute(
            "SELECT section, COUNT(*) FROM downloads WHERE user_id=? AND status='done' GROUP BY section", (user_id,)
        ) as cur:
            for section, n in await cur.fetchall():
                if section in stats:
                    stats[section] = n
                stats["total"] += n
        return stats

    async def global_stats(self) -> dict[str, int]:
        day_ago = iso(utcnow() - timedelta(days=1))
        out: dict[str, int] = {}

        async def one(q: str, *args: Any) -> int:
            async with self.db.execute(q, args) as cur:
                r = await cur.fetchone()
            return int(r[0] or 0)

        out["users"] = await one("SELECT COUNT(*) FROM users")
        out["active_24h"] = await one("SELECT COUNT(*) FROM users WHERE last_seen >= ?", day_ago)
        out["blocked"] = await one("SELECT COUNT(*) FROM users WHERE is_blocked=1")
        out["downloads"] = await one("SELECT COUNT(*) FROM downloads WHERE status='done'")
        out["downloads_24h"] = await one("SELECT COUNT(*) FROM downloads WHERE status='done' AND created_at >= ?", day_ago)
        out["errors"] = await one("SELECT COUNT(*) FROM downloads WHERE status='error'")
        for s in SECTIONS:
            out[s] = await one("SELECT COUNT(*) FROM downloads WHERE status='done' AND section=?", s)
        return out

    # file_id cache ---------------------------------------------------------
    async def get_cached(self, media_key: str, fmt: str) -> list[dict[str, str]] | None:
        async with self.db.execute(
            "SELECT payload FROM file_cache WHERE media_key=? AND format=?", (media_key, fmt)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        try:
            data = json.loads(row[0])
        except ValueError:
            return None
        return data if isinstance(data, list) and data else None

    async def set_cached(self, media_key: str, fmt: str, items: list[dict[str, str]]) -> None:
        await self.db.execute(
            "INSERT OR REPLACE INTO file_cache(media_key, format, payload, created_at) VALUES (?, ?, ?, ?)",
            (media_key, fmt, json.dumps(items), iso()),
        )
        await self.db.commit()

    async def drop_cached(self, media_key: str, fmt: str) -> None:
        await self.db.execute("DELETE FROM file_cache WHERE media_key=? AND format=?", (media_key, fmt))
        await self.db.commit()

    # callback tokens (callback_data never carries URLs) ----------------------
    async def token_for(self, url: str) -> str:
        """Stable short token for ``url``. Race-free: INSERT OR IGNORE (url is UNIQUE), then SELECT."""
        for _ in range(3):
            await self.db.execute(
                "INSERT OR IGNORE INTO tokens(token, url, created_at) VALUES (?, ?, ?)",
                (secrets.token_urlsafe(8), url, iso()),  # 11 chars
            )
            await self.db.commit()
            async with self.db.execute("SELECT token FROM tokens WHERE url=?", (url,)) as cur:
                row = await cur.fetchone()
            if row:
                return row[0]
        raise RuntimeError("could not allocate callback token")

    async def url_for_token(self, token: str) -> str | None:
        async with self.db.execute("SELECT url FROM tokens WHERE token=?", (token,)) as cur:
            row = await cur.fetchone()
        return row[0] if row else None

    async def purge_tokens(self, older_than_days: int = 30) -> None:
        await self.db.execute("DELETE FROM tokens WHERE created_at < ?", (iso(utcnow() - timedelta(days=older_than_days)),))
        await self.db.commit()
