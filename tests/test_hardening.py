"""Regression tests for the security audit + QA review fixes."""

import asyncio
import sqlite3
import threading
import time

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.methods import SendMessage
from pydantic import ValidationError

from bot import texts
from bot.config import Settings
from bot.downloader import Downloader, build_formats, plan_attempts, media_from_info, tier_label
from bot.errors import AppError
from bot.jobs import Job, JobManager, job_from_row
from bot.pipeline import Pipeline
from bot.platforms import analyze_full, classify
from bot.ratelimit import RateLimiter
from bot.sender import CAPTION_LIMIT, MediaItem, _caption
from bot.storage import Storage
from tests.conftest import TOKEN, make_init_data
from tests.test_downloader import HORIZONTAL_FORMATS, VERTICAL_FORMATS, FakeYDL, yt_info

MB = 1024 * 1024
YT = classify("https://youtu.be/dQw4w9WgXcQ")


# --- SEC-L1 / QA-L9: link parsing ---------------------------------------------------------
@pytest.mark.parametrize("url", [
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ%0a",
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ%0A",
    "https://youtu.be/dQw4w9WgXcQ%0a",
    "https://www.youtube.com/shorts/dQw4w9WgXcQ%0a",
    "https://www.instagram.com/reel/C1a2B3c4D5e%0a/",
])
def test_trailing_newline_ids_rejected(url):
    assert classify(url) is None


def test_instagram_share_links_unsupported_with_hint():
    for url in ("https://www.instagram.com/share/reel/BAabc123xyz/", "https://www.instagram.com/share/p/BAabc123/"):
        link, code, reason = analyze_full(url)
        assert link is None and code == "unsupported" and reason == "ig_share"


async def test_api_share_link_message(tmp_path):
    from tests.test_api import H

    from aiohttp.test_utils import TestClient, TestServer
    from bot.webapp_api import ApiDeps, create_app

    storage = await Storage(":memory:").open()
    jobs = JobManager(runner=None, download_dir=tmp_path, max_concurrent=1, hourly_limit=1)
    app = create_app(ApiDeps(bot_token=TOKEN, storage=storage, downloader=None, jobs=jobs, webapp_dir=tmp_path,
                             max_upload_mb=50, max_duration_min=120, hourly_limit=30))
    async with TestClient(TestServer(app)) as c:
        r = await c.post("/api/probe", json={"url": "https://www.instagram.com/share/reel/BAabc123xyz/"}, headers=H)
        body = await r.json()
        assert r.status == 400 and body["error"] == {"code": "unsupported", "message": texts.IG_SHARE_LINK}
        # initData older than the 6h default is rejected
        old = make_init_data(auth_date=int(time.time()) - 7 * 3600)
        r = await c.get("/api/me", headers={"X-Telegram-Init-Data": old})
        assert r.status == 401
        recent = make_init_data(auth_date=int(time.time()) - 5 * 3600)
        assert (await c.get("/api/me", headers={"X-Telegram-Init-Data": recent})).status == 200
        csp = (await c.get("/")).headers["Content-Security-Policy"]
        for part in ("base-uri 'none'", "form-action 'none'", "object-src 'none'", "frame-ancestors"):
            assert part in csp
    await storage.close()


# --- SEC-M3: DEV_MODE guard -----------------------------------------------------------------
@pytest.mark.parametrize("env,ok", [
    ({"DEV_MODE": "true", "WEB_HOST": "127.0.0.1"}, True),
    ({"DEV_MODE": "true", "WEB_HOST": "localhost"}, True),
    ({"DEV_MODE": "true", "WEB_HOST": "::1"}, True),
    ({"DEV_MODE": "true", "WEB_HOST": "0.0.0.0"}, False),
    ({"DEV_MODE": "true", "WEB_HOST": "192.168.1.5"}, False),
    ({"DEV_MODE": "true", "WEB_HOST": "127.0.0.1", "WEBAPP_URL": "https://app.example.com"}, False),
    ({"DEV_MODE": "false", "WEB_HOST": "0.0.0.0", "WEBAPP_URL": "https://app.example.com"}, True),
])
def test_dev_mode_guard(monkeypatch, env, ok):
    monkeypatch.setenv("BOT_TOKEN", TOKEN)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    if ok:
        Settings(_env_file=None)
    else:
        with pytest.raises(ValidationError, match="DEV_MODE"):
            Settings(_env_file=None)


def test_init_data_max_age_setting(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", TOKEN)
    assert Settings(_env_file=None).init_data_max_age_hours == 6
    monkeypatch.setenv("INIT_DATA_MAX_AGE_HOURS", "25")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


# --- QA-M4 / QA-L11: formats -----------------------------------------------------------------
def test_auto_reports_first_fitting_tier():
    by = {o.id: o for o in build_formats(yt_info(HORIZONTAL_FORMATS), "videos", 50 * MB)}
    assert by["1080"].fits is False
    assert (by["auto"].size, by["auto"].height, by["auto"].fits) == (by["720"].size, 720, True)
    none_fit = {o.id: o for o in build_formats(yt_info(HORIZONTAL_FORMATS), "videos", 1 * MB)}
    assert none_fit["auto"].fits is False and none_fit["auto"].height == 360


def test_shorts_auto_uses_hidden_tiers_for_planning():
    link = classify("https://www.youtube.com/shorts/dQw4w9WgXcQ")
    m = media_from_info(link, yt_info(VERTICAL_FORMATS, 1080, 1920, 30), 15 * MB)
    assert [f.id for f in m.formats] == ["auto", "audio"]
    assert m.formats[0].height == 720  # 1080 tier (23 MB) does not fit 15 MB
    assert plan_attempts("auto", m) == ["720", "480", "360"]


def test_instagram_unknown_acodec_offers_audio():
    info = {"duration": 10, "formats": [{"format_id": "p", "width": 720, "height": 1280, "ext": "mp4",
                                         "filesize": MB}]}
    assert [o.id for o in build_formats(info, "instagram", 50 * MB)] == ["auto", "audio"]
    video_only = {"duration": 10, "formats": [{"format_id": "v", "width": 720, "height": 1280, "vcodec": "avc1",
                                               "acodec": "none", "filesize": MB}]}
    assert [o.id for o in build_formats(video_only, "instagram", 50 * MB)] == ["auto"]


@pytest.mark.parametrize("fmt,w,h,label", [
    ("auto", 1080, 1920, "1080"), ("auto", 1920, 1036, "1080"), ("auto", 720, 1280, "720"),
    ("auto", 426, 240, "240"), ("720", 1280, 720, "720"), ("audio", None, None, "audio"),
    ("480", 640, 360, "360"), ("1080", 1280, 720, "720"), ("1080", 1080, 1920, "1080"),
])
def test_tier_label(fmt, w, h, label):
    assert tier_label(fmt, h, w) == label


def test_job_api_used_format_and_note():
    job = Job(id="a1", user_id=1, chat_id=1, link=YT, format="auto")
    job.used_format, job.note = "720", "ℹ️ x"
    assert job.to_api()["used_format"] is None  # only once done
    job.status = "done"
    api = job.to_api()
    assert api["used_format"] == "720" and api["note"] == "ℹ️ x"
    row = {"id": "a1", "status": "done", "format": "auto", "used_format": "720", "note": "n", "title": None,
           "thumbnail": None, "kind": "video", "section": "videos", "created_at": "2026-01-01T00:00:00+00:00"}
    assert job_from_row(row)["used_format"] == "720" and job_from_row(row)["note"] == "n"


async def test_used_format_and_note_persisted(tmp_path):
    storage = await Storage(":memory:").open()

    async def runner(job, wd):
        job.used_format, job.note = "480", "ℹ️ note"

    jm = JobManager(runner=runner, download_dir=tmp_path, max_concurrent=1, hourly_limit=5, storage=storage)
    job = await jm.submit(user_id=3, chat_id=3, link=YT, fmt="1080")
    await jm.wait(job, 3)
    row = await storage.get_download(job.id, 3)
    assert (row["used_format"], row["note"]) == ("480", "ℹ️ note")
    await storage.close()


async def test_storage_migrates_old_schema(tmp_path):
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.execute("""CREATE TABLE downloads (id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, platform TEXT NOT NULL,
        kind TEXT NOT NULL, section TEXT NOT NULL, media_id TEXT NOT NULL, url TEXT NOT NULL, title TEXT,
        thumbnail TEXT, format TEXT NOT NULL, status TEXT NOT NULL, error_code TEXT, error_message TEXT,
        created_at TEXT NOT NULL, finished_at TEXT)""")
    con.commit()
    con.close()
    s = await Storage(path).open()
    await s.update_download("x", used_format="720", note="n")  # columns exist
    await s.close()


# --- SEC-L4: token_for race -------------------------------------------------------------------
async def test_token_for_is_stable_under_concurrency(tmp_path):
    s = await Storage(tmp_path / "t.db").open()
    url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    tokens = await asyncio.gather(*(s.token_for(url) for _ in range(20)))
    assert len(set(tokens)) == 1 and await s.url_for_token(tokens[0]) == url
    await s.close()


# --- SEC-L2: limiter pruning --------------------------------------------------------------------
def test_rate_limiter_prunes_idle_keys():
    now = [0.0]
    rl = RateLimiter(5, 10, clock=lambda: now[0])
    for uid in range(5000):
        rl.hit(uid)
    assert len(rl) == 5000
    now[0] = 11
    rl.prune()
    assert len(rl) == 0
    rl.used(123)
    rl.allowed(124)
    assert len(rl) == 0  # reads never create keys
    rl.PRUNE_EVERY = 10
    for i in range(30):
        rl.hit(10_000 + i)
    now[0] = 30
    for i in range(10):
        rl.hit(1)
    assert len(rl) == 1  # periodic sweep dropped the expired keys


def test_rate_limiter_time_based_sweep_after_burst():
    now = [0.0]
    rl = RateLimiter(8, 10, clock=lambda: now[0])
    for uid in range(20_000):
        rl.hit(uid)
    now[0] = 10_000
    rl.hit(10**9)  # first hit after the quiet period sweeps everything expired
    assert len(rl) == 1


# --- SEC-M1: probe isolation, negative cache, coalescing ------------------------------------------
class BlockingYDL(FakeYDL):
    gate = threading.Event()

    def extract_info(self, url, download=False, process=True):
        if self.opts.get("skip_download"):  # probe
            BlockingYDL.gate.wait(5)
        return super().extract_info(url, download, process)


@pytest.fixture
def blocking():
    FakeYDL.instances = []
    FakeYDL.info = yt_info(HORIZONTAL_FORMATS)
    FakeYDL.produce = ["01_dQw4w9WgXcQ.mp4"]
    FakeYDL.error = None
    BlockingYDL.gate = threading.Event()
    yield BlockingYDL
    BlockingYDL.gate.set()


async def test_slow_probes_do_not_starve_downloads(blocking, tmp_path):
    d = Downloader(max_upload_bytes=50 * MB, max_duration_sec=7200, ydl_factory=BlockingYDL,
                   max_workers=1, probe_workers=1, probe_queue_timeout=0.2, min_free_bytes=0)
    probes = [asyncio.create_task(d.probe(classify(f"https://youtu.be/{i:011d}"))) for i in range(6)]
    await asyncio.sleep(0.05)
    t0 = time.monotonic()
    res = await d.download(YT, "720", tmp_path / "w")
    assert res.files and time.monotonic() - t0 < 1.0
    # queued probes beyond the bounded pool fail fast with a "busy" message instead of piling up
    done = await asyncio.gather(*probes[1:], return_exceptions=True)
    assert all(isinstance(e, AppError) and e.code == "rate_limited" for e in done)
    blocking.gate.set()
    await probes[0]
    d.close()


async def test_negative_cache_and_coalescing():
    FakeYDL.instances = []
    FakeYDL.info = yt_info(HORIZONTAL_FORMATS)
    FakeYDL.error = Exception("ERROR: Video unavailable")
    d = Downloader(max_upload_bytes=50 * MB, max_duration_sec=7200, ydl_factory=FakeYDL)
    for _ in range(3):
        with pytest.raises(AppError) as e:
            await d.probe(YT)
        assert e.value.code == "not_found"
    assert len(FakeYDL.instances) == 1
    FakeYDL.error = None
    other = classify("https://youtu.be/aaaaaaaaaaa")
    a, b = await asyncio.gather(d.probe(other), d.probe(other))
    assert a is b and len(FakeYDL.instances) == 2
    d.close()


async def test_youtube_without_formats_is_an_error():
    FakeYDL.instances = []
    FakeYDL.error = None
    FakeYDL.info = {"id": "dQw4w9WgXcQ", "title": "t", "duration": 10, "formats": []}
    d = Downloader(max_upload_bytes=50 * MB, max_duration_sec=7200, ydl_factory=FakeYDL)
    with pytest.raises(AppError):
        await d.probe(YT)
    d.close()


async def test_probe_opts_ignore_no_formats():
    FakeYDL.instances = []
    FakeYDL.error = None
    FakeYDL.info = yt_info(HORIZONTAL_FORMATS)
    d = Downloader(max_upload_bytes=50 * MB, max_duration_sec=7200, ydl_factory=FakeYDL)
    await d.probe(YT)
    opts = FakeYDL.instances[0].opts
    # only Instagram probes ignore "no formats" (photo posts); on YouTube it would hide the bot-check error
    assert "ignore_no_formats_error" not in opts and opts["allowed_extractors"] == ["youtube", "instagram"]
    d.close()


# --- SEC-L3: disk space -------------------------------------------------------------------------
async def test_low_disk_space_refused(tmp_path):
    d = Downloader(max_upload_bytes=50 * MB, max_duration_sec=7200, ydl_factory=FakeYDL, min_free_bytes=1 << 62)
    with pytest.raises(AppError) as e:
        await d.download(YT, "720", tmp_path / "w")
    assert e.value.message == texts.NO_DISK_SPACE
    d.close()


# --- SEC-L5: stale workdirs -----------------------------------------------------------------------
def test_wipe_download_dir(tmp_path):
    (tmp_path / "abc").mkdir()
    (tmp_path / "abc" / "x.mp4").write_bytes(b"1")
    (tmp_path / "stray.part").write_bytes(b"1")
    jm = JobManager(runner=None, download_dir=tmp_path, max_concurrent=1, hourly_limit=1)
    assert jm.wipe_download_dir() == 2 and list(tmp_path.iterdir()) == []
    assert JobManager(runner=None, download_dir=tmp_path / "missing", max_concurrent=1,
                      hourly_limit=1).wipe_download_dir() == 0


async def test_cancel_waits_for_worker_before_returning(tmp_path):
    started, finished = threading.Event(), threading.Event()

    class SlowYDL(FakeYDL):
        def process_ie_result(self, info, download=True):
            started.set()
            for _ in range(50):
                for h in self.opts.get("progress_hooks", []):
                    h({"status": "downloading", "filename": "f", "downloaded_bytes": 1, "total_bytes": 100})
                time.sleep(0.02)
            finished.set()

    FakeYDL.info = yt_info(HORIZONTAL_FORMATS)
    FakeYDL.error = None
    d = Downloader(max_upload_bytes=50 * MB, max_duration_sec=7200, ydl_factory=SlowYDL, min_free_bytes=0)
    task = asyncio.create_task(d.download(YT, "720", tmp_path / "w"))
    await asyncio.get_running_loop().run_in_executor(None, started.wait, 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    # the hook raised Cancelled -> worker stopped before download() returned
    assert not finished.is_set()
    await asyncio.sleep(0.1)
    d.close()


# --- QA-L7 / SEC-L7: captions and send retries ---------------------------------------------------
def test_caption_truncation_never_splits_entities():
    raw = "x" * (CAPTION_LIMIT - 3) + "&amp;tail"
    out = _caption(raw)
    assert len(out) <= CAPTION_LIMIT and "&am" not in out and out.endswith("…")


def test_title_truncated_before_escaping():
    p = Pipeline(downloader=None, sender=None, storage=None, max_upload_bytes=MB)
    job = Job(id="a", user_id=1, chat_id=1, link=YT, format="auto", title="&" * 2000)
    cap = p.caption(job)
    assert cap.count("&amp;") == 800 and not cap.endswith("&")
    assert p.caption(job, plain=True) == "🎬 " + "&" * 800


class FlakySender:
    def __init__(self, failures):
        self.failures = list(failures)
        self.calls = []

    async def send_video(self, chat_id, item, *, caption=None, reply_markup=None, reply_to=None, plain=False):
        self.calls.append({"plain": plain, "thumb": item.thumbnail, "caption": caption})
        if self.failures:
            raise self.failures.pop(0)
        return {"type": "video", "file_id": "F"}


def _bad(msg="Bad Request: can't parse entities"):
    return TelegramBadRequest(method=SendMessage(chat_id=1, text="x"), message=msg)


def _retry():
    return TelegramRetryAfter(method=SendMessage(chat_id=1, text="x"), message="flood", retry_after=0)


@pytest.mark.parametrize("failures,expect_plain", [([_retry()], [False, False]),
                                                  ([_bad()], [False, True]),
                                                  ([_retry(), _bad()], [False, False, True])])
async def test_send_retries(tmp_path, failures, expect_plain):
    thumb = tmp_path / "t.jpg"
    thumb.write_bytes(b"j")
    sender = FlakySender(failures)
    p = Pipeline(downloader=None, sender=sender, storage=None, max_upload_bytes=MB)
    job = Job(id="a", user_id=1, chat_id=1, link=YT, format="auto", title="<b>T</b>")
    item = MediaItem(path=tmp_path / "v.mp4", type="video", width=1, height=1, duration=1, thumbnail=thumb)
    out = await p._send(job, [item], "auto")
    assert out == [{"type": "video", "file_id": "F"}]
    assert [c["plain"] for c in sender.calls] == expect_plain
    if expect_plain[-1]:
        assert sender.calls[-1]["thumb"] is None and sender.calls[-1]["caption"] == "🎬 <b>T</b>"


async def test_send_gives_up_after_second_retry_after(tmp_path):
    sender = FlakySender([_retry(), _retry()])
    p = Pipeline(downloader=None, sender=sender, storage=None, max_upload_bytes=MB)
    job = Job(id="a", user_id=1, chat_id=1, link=YT, format="auto")
    with pytest.raises(AppError):
        await p._send(job, [MediaItem(path=tmp_path / "v.mp4", type="video")], "auto")


# --- bot handlers -------------------------------------------------------------------------------
async def test_start_job_survives_failing_error_message(tmp_path):
    from bot.handlers.common import start_job

    class Bot:
        async def send_message(self, *a, **kw):
            raise _retry()

    jm = JobManager(runner=None, download_dir=tmp_path, max_concurrent=1, hourly_limit=0)
    assert await start_job(bot=Bot(), jobs=jm, chat_id=1, user_id=1, link=YT, fmt="auto") is None


async def test_history_refused_in_groups():
    from bot.handlers.start import cmd_history
    from tests.test_bot import FakeMsg

    m = FakeMsg("/history", chat_type="supergroup")
    replies = []
    m.reply = lambda text, **kw: _coro(replies.append(text))
    await cmd_history(m, db=None)
    assert replies == [texts.HISTORY_PRIVATE_ONLY]


async def _coro(v):
    return v


async def test_preview_uses_probe_limiter(tmp_path):
    from bot.handlers import links
    from tests.test_bot import FakeBot, FakeDownloader, FakeMsg

    storage = await Storage(":memory:").open()
    jm = JobManager(runner=None, download_dir=tmp_path, max_concurrent=1, hourly_limit=5)
    probes = []

    class D(FakeDownloader):
        async def probe(self, link):
            probes.append(link)
            raise AppError("not_found")

    rl = RateLimiter(1, 600)
    for _ in range(2):
        m = FakeMsg("https://youtu.be/dQw4w9WgXcQ")
        await links.on_message(m, FakeBot(), storage, D(), jm, rl)
    assert len(probes) == 1 and m.replies == ["❌ " + texts.PROBE_RATE_LIMITED]
    await storage.close()


async def test_share_link_reply_in_private(tmp_path):
    from bot.handlers import links
    from tests.test_bot import FakeBot, FakeDownloader, FakeMsg

    m = FakeMsg("https://www.instagram.com/share/reel/BAabc123xyz/")
    jm = JobManager(runner=None, download_dir=tmp_path, max_concurrent=1, hourly_limit=5)
    await links.on_message(m, FakeBot(), None, FakeDownloader(), jm)
    assert m.replies == [texts.IG_SHARE_LINK]



def test_audio_source_limit_is_looser_than_video():
    d = Downloader.__new__(Downloader)
    d.max_upload_bytes = 50 * MB
    assert d._source_limit("720") == 50 * MB
    assert d._source_limit("audio") > 50 * MB
