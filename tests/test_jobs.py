import asyncio

import pytest

from bot.errors import AppError
from bot.jobs import JobManager, job_from_row
from bot.platforms import classify
from bot.ratelimit import RateLimiter
from bot.storage import Storage
from tests.conftest import wait_until

LINK = classify("https://www.youtube.com/shorts/dQw4w9WgXcQ")


class ControlledRunner:
    def __init__(self):
        self.running = 0
        self.max_running = 0
        self.release = asyncio.Event()
        self.workdirs = []
        self.fail_with = None

    async def __call__(self, job, workdir):
        self.workdirs.append(workdir)
        assert workdir.is_dir()
        (workdir / "partial.mp4").write_bytes(b"data")
        self.running += 1
        self.max_running = max(self.max_running, self.running)
        job.set("downloading", 10)
        try:
            await self.release.wait()
            if self.fail_with:
                raise self.fail_with
        finally:
            self.running -= 1


def manager(tmp_path, runner, **kw):
    return JobManager(runner=runner, download_dir=tmp_path, max_concurrent=kw.pop("max_concurrent", 2),
                      hourly_limit=kw.pop("hourly_limit", 30), **kw)


async def test_global_semaphore_limits_concurrency(tmp_path):
    r = ControlledRunner()
    jm = manager(tmp_path, r, max_concurrent=2)
    jobs = [await jm.submit(user_id=i, chat_id=i, link=LINK, fmt="auto") for i in range(5)]
    await wait_until(lambda: r.running == 2)
    await asyncio.sleep(0.05)
    assert r.running == 2
    assert sum(j.status == "queued" for j in jobs) == 3
    r.release.set()
    for j in jobs:
        await jm.wait(j, 3)
    assert r.max_running == 2
    assert all(j.status == "done" and j.progress == 100 for j in jobs)


async def test_one_active_job_per_user(tmp_path):
    r = ControlledRunner()
    jm = manager(tmp_path, r)
    j1 = await jm.submit(user_id=1, chat_id=1, link=LINK, fmt="auto")
    with pytest.raises(AppError) as e:
        await jm.submit(user_id=1, chat_id=1, link=LINK, fmt="720")
    assert e.value.code == "busy" and e.value.status == 409
    other = await jm.submit(user_id=2, chat_id=2, link=LINK, fmt="auto")
    r.release.set()
    await jm.wait(j1, 3)
    await jm.wait(other, 3)
    j3 = await jm.submit(user_id=1, chat_id=1, link=LINK, fmt="auto")
    await jm.wait(j3, 3)
    assert j3.status == "done"


async def test_hourly_rate_limit(tmp_path):
    r = ControlledRunner()
    r.release.set()
    jm = manager(tmp_path, r, hourly_limit=2, limits={"hourly_limit": 2})
    for _ in range(2):
        await jm.wait(await jm.submit(user_id=1, chat_id=1, link=LINK, fmt="auto"), 3)
    with pytest.raises(AppError) as e:
        await jm.submit(user_id=1, chat_id=1, link=LINK, fmt="auto")
    assert e.value.code == "rate_limited" and e.value.status == 429 and "2" in e.value.message
    assert jm.hourly_used(1) == 2
    await jm.wait(await jm.submit(user_id=2, chat_id=2, link=LINK, fmt="auto"), 3)


async def test_workdir_always_cleaned_and_errors_mapped(tmp_path):
    r = ControlledRunner()
    jm = manager(tmp_path, r)
    r.fail_with = AppError("not_found")
    j = await jm.submit(user_id=1, chat_id=1, link=LINK, fmt="auto")
    r.release.set()
    await jm.wait(j, 3)
    assert j.status == "error" and j.error["code"] == "not_found" and j.error["message"]
    assert not r.workdirs[0].exists()

    r.fail_with = RuntimeError("boom secret")
    j2 = await jm.submit(user_id=1, chat_id=1, link=LINK, fmt="auto")
    await jm.wait(j2, 3)
    assert j2.error["code"] == "internal" and "boom" not in j2.error["message"]
    assert not r.workdirs[1].exists()
    assert list(tmp_path.iterdir()) == []


async def test_shutdown_cancels_and_cleans(tmp_path):
    r = ControlledRunner()
    jm = manager(tmp_path, r)
    j = await jm.submit(user_id=1, chat_id=1, link=LINK, fmt="auto")
    await wait_until(lambda: r.running == 1)
    await jm.shutdown(2)
    assert j.status == "error" and not r.workdirs[0].exists()
    with pytest.raises(AppError):
        await jm.submit(user_id=3, chat_id=3, link=LINK, fmt="auto")


async def test_job_api_shape_and_ownership(tmp_path):
    r = ControlledRunner()
    jm = manager(tmp_path, r)
    j = await jm.submit(user_id=1, chat_id=1, link=LINK, fmt="auto", title="T", thumbnail="https://x/y.jpg")
    api = j.to_api()
    assert set(api) == {"id", "status", "progress", "format", "used_format", "note", "error", "media", "created_at"}
    assert api["media"] == {"title": "T", "thumbnail": "https://x/y.jpg", "kind": "short", "section": "shorts"}
    assert jm.get(j.id, 1) is j and jm.get(j.id, 2) is None
    r.release.set()
    await jm.wait(j, 3)


async def test_history_persisted(tmp_path):
    storage = await Storage(":memory:").open()
    r = ControlledRunner()
    r.release.set()
    jm = manager(tmp_path / "dl", r, storage=storage)
    j = await jm.submit(user_id=5, chat_id=5, link=LINK, fmt="auto")
    await jm.wait(j, 3)
    await asyncio.sleep(0.05)
    row = await storage.get_download(j.id, 5)
    assert row["status"] == "done" and row["section"] == "shorts"
    assert job_from_row(row)["progress"] == 100
    assert (await storage.user_stats(5)) == {"total": 1, "instagram": 0, "shorts": 1, "videos": 0}
    await storage.close()


def test_job_from_row_orphaned():
    row = {"id": "a", "status": "downloading", "format": "auto", "title": None, "thumbnail": None,
           "kind": "video", "section": "videos", "created_at": "2026-01-01T00:00:00+00:00"}
    assert job_from_row(row)["status"] == "error"


def test_rate_limiter_window():
    now = [0.0]
    rl = RateLimiter(2, 10, clock=lambda: now[0])
    assert rl.hit(1) and rl.hit(1) and not rl.hit(1)
    assert rl.used(1) == 2 and rl.retry_after(1) == 10
    now[0] = 10.5
    assert rl.allowed(1) and rl.hit(1)
