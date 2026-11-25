"""JobManager: queue + global semaphore, one active job per user, hourly limit, progress state.

The actual work is done by a *runner* coroutine ``runner(job, workdir)`` (see pipeline.py),
which keeps this module independent of yt-dlp/Telegram and easy to test.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Protocol

from .errors import AppError
from .platforms import Link
from .ratelimit import RateLimiter
from .storage import iso

log = logging.getLogger(__name__)

STATUSES = ("queued", "downloading", "processing", "uploading", "done", "error")
FINAL = ("done", "error")


@dataclass(eq=False)
class Job:
    id: str
    user_id: int
    chat_id: int
    link: Link
    format: str
    origin: str = "bot"  # "bot" | "webapp"
    title: str | None = None
    thumbnail: str | None = None
    reply_to: int | None = None
    status: str = "queued"
    progress: int = 0
    error: dict[str, str] | None = None
    note: str | None = None
    used_format: str | None = None  # quality actually sent (e.g. "auto" -> "720"); None until done
    created_at: str = field(default_factory=iso)
    finished_monotonic: float | None = None
    done_event: asyncio.Event = field(default_factory=asyncio.Event)
    version: int = 0
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def finished(self) -> bool:
        return self.status in FINAL

    def set(self, status: str | None = None, progress: int | float | None = None) -> None:
        if self.finished:
            return
        if status is not None:
            if status not in STATUSES:
                raise ValueError(status)
            self.status = status
        if progress is not None:
            self.progress = max(0, min(100, int(progress)))
        self.version += 1

    def to_api(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "progress": self.progress,
            "format": self.format,
            "used_format": self.used_format if self.status == "done" else None,
            "note": self.note,
            "error": self.error,
            "media": {
                "title": self.title,
                "thumbnail": self.thumbnail,
                "kind": self.link.kind,
                "section": self.link.section,
            },
            "created_at": self.created_at,
        }


def job_from_row(row: dict[str, Any]) -> dict[str, Any]:
    """API Job shape from a persisted downloads row (finished or orphaned job)."""
    status = row["status"]
    error = None
    if status not in FINAL:  # process restarted while running
        status = "error"
        error = AppError("internal").to_dict()
    elif status == "error":
        error = {"code": row.get("error_code") or "internal",
                 "message": row.get("error_message") or AppError("internal").message}
    return {
        "id": row["id"],
        "status": status,
        "progress": 100 if status == "done" else 0,
        "format": row["format"],
        "used_format": row.get("used_format") if status == "done" else None,
        "note": row.get("note"),
        "error": error,
        "media": {"title": row.get("title"), "thumbnail": row.get("thumbnail"),
                  "kind": row["kind"], "section": row["section"]},
        "created_at": row["created_at"],
    }


Runner = Callable[[Job, Path], Awaitable[None]]


class HistoryStore(Protocol):  # subset of Storage used here
    async def add_download(self, row: dict[str, Any]) -> None: ...
    async def update_download(self, job_id: str, **fields: Any) -> None: ...


class JobManager:
    def __init__(
        self,
        *,
        runner: Runner,
        download_dir: Path,
        max_concurrent: int,
        hourly_limit: int,
        storage: HistoryStore | None = None,
        limits: dict[str, int] | None = None,
        retention_sec: float = 3600.0,
        limiter: RateLimiter | None = None,
    ) -> None:
        self.runner = runner
        self.download_dir = Path(download_dir)
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.max_concurrent = max_concurrent
        self.limiter = limiter or RateLimiter(hourly_limit, 3600.0)
        self.storage = storage
        self.limits = limits or {}
        self.retention_sec = retention_sec
        self.jobs: dict[str, Job] = {}
        self.active_by_user: dict[int, str] = {}
        self._tasks: set[asyncio.Task] = set()
        self._closing = False
        self._lock = asyncio.Lock()

    def wipe_download_dir(self) -> int:
        """Remove leftovers of a previous run (crash / kill -9). Call once at startup."""
        removed = 0
        if not self.download_dir.is_dir():
            return 0
        for child in self.download_dir.iterdir():
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink(missing_ok=True)
            removed += 1
        return removed

    # -- queries -------------------------------------------------------------
    def get(self, job_id: str, user_id: int | None = None) -> Job | None:
        job = self.jobs.get(job_id)
        if job is None or (user_id is not None and job.user_id != user_id):
            return None
        return job

    def active_job(self, user_id: int) -> Job | None:
        jid = self.active_by_user.get(user_id)
        return self.jobs.get(jid) if jid else None

    def hourly_used(self, user_id: int) -> int:
        return self.limiter.used(user_id)

    @property
    def active_count(self) -> int:
        return len(self.active_by_user)

    @property
    def running_count(self) -> int:
        return self.max_concurrent - self.semaphore._value  # noqa: SLF001

    # -- submit --------------------------------------------------------------
    async def submit(
        self,
        *,
        user_id: int,
        chat_id: int,
        link: Link,
        fmt: str,
        origin: str = "bot",
        title: str | None = None,
        thumbnail: str | None = None,
        reply_to: int | None = None,
        extra: dict[str, Any] | None = None,
    ) -> Job:
        if self._closing:
            raise AppError("internal")
        async with self._lock:
            self._purge()
            if user_id in self.active_by_user:
                raise AppError("busy")
            if not self.limiter.hit(user_id):
                raise AppError("rate_limited", **self.limits)
            job = Job(
                id=uuid.uuid4().hex[:16],
                user_id=user_id,
                chat_id=chat_id,
                link=link,
                format=fmt,
                origin=origin,
                title=title,
                thumbnail=thumbnail,
                reply_to=reply_to,
                extra=dict(extra or {}),
            )
            self.jobs[job.id] = job
            self.active_by_user[user_id] = job.id
        await self._persist_new(job)
        task = asyncio.create_task(self._run(job), name=f"job-{job.id}")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return job

    async def _persist_new(self, job: Job) -> None:
        if self.storage is None:
            return
        try:
            await self.storage.add_download({
                "id": job.id, "user_id": job.user_id, "platform": job.link.platform, "kind": job.link.kind,
                "section": job.link.section, "media_id": job.link.id, "url": job.link.canonical_url,
                "title": job.title, "thumbnail": job.thumbnail, "format": job.format, "status": job.status,
                "created_at": job.created_at,
            })
        except Exception:  # history must never break a download
            log.exception("failed to persist job %s", job.id)

    async def _persist_final(self, job: Job) -> None:
        if self.storage is None:
            return
        try:
            await self.storage.update_download(
                job.id, status=job.status, title=job.title, thumbnail=job.thumbnail,
                kind=job.link.kind, section=job.link.section,
                used_format=job.used_format if job.status == "done" else None, note=job.note,
                error_code=(job.error or {}).get("code"), error_message=(job.error or {}).get("message"),
                finished_at=iso(),
            )
        except Exception:
            log.exception("failed to update job %s", job.id)

    async def _run(self, job: Job) -> None:
        workdir = self.download_dir / uuid.uuid4().hex
        try:
            async with self.semaphore:
                if self._closing:
                    raise AppError("internal")
                workdir.mkdir(parents=True, exist_ok=True)
                await self.runner(job, workdir)
            job.set("done", 100)
        except AppError as exc:
            job.error = exc.to_dict()
            job.status = "error"
        except asyncio.CancelledError:
            job.error = AppError("internal").to_dict()
            job.status = "error"
        except Exception:
            log.exception("job %s failed", job.id)
            job.error = AppError("internal").to_dict()
            job.status = "error"
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
            job.version += 1
            job.finished_monotonic = time.monotonic()
            if self.active_by_user.get(job.user_id) == job.id:
                del self.active_by_user[job.user_id]
            try:
                await asyncio.shield(self._persist_final(job))
            finally:
                job.done_event.set()

    def _purge(self) -> None:
        now = time.monotonic()
        for jid in [j.id for j in self.jobs.values()
                    if j.finished_monotonic is not None and now - j.finished_monotonic > self.retention_sec]:
            self.jobs.pop(jid, None)

    async def wait(self, job: Job, timeout: float | None = None) -> Job:
        await asyncio.wait_for(job.done_event.wait(), timeout)
        return job

    async def shutdown(self, timeout: float = 10.0) -> None:
        """Stop accepting jobs, cancel running ones and wait for their cleanup."""
        self._closing = True
        tasks = list(self._tasks)
        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.wait(tasks, timeout=timeout)
