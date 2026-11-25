import asyncio
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.methods import SendMessage

from bot import texts
from bot.config import Settings
from bot.downloader import FormatOption, MediaInfo
from bot.errors import AppError
from bot.handlers import admin, callbacks, links
from bot.jobs import JobManager
from bot.keyboards import DownloadCB, quality_keyboard
from bot.main import RedactFilter
from bot.platforms import classify
from bot.progress import MIN_EDIT_INTERVAL, ProgressReporter
from bot.storage import Storage
from tests.conftest import TOKEN

ROOT = Path(__file__).resolve().parent.parent


# --- fakes ----------------------------------------------------------------------
class FakeMsg:
    _next = 100

    def __init__(self, text="", chat_type="private", user_id=42, bot=None):
        self.text = text
        self.caption = None
        self.entities = None
        self.caption_entities = None
        self.chat = SimpleNamespace(id=user_id if chat_type == "private" else -1001, type=chat_type)
        self.from_user = SimpleNamespace(id=user_id, is_bot=False, first_name="Ali", username="ali")
        FakeMsg._next += 1
        self.message_id = FakeMsg._next
        self.bot = bot
        self.replies = []
        self.photos = []
        self.answers = []
        self.edited = []
        self.deleted = False

    async def reply(self, text, **kw):
        self.replies.append(text)
        m = FakeMsg(chat_type=self.chat.type)
        m.text = text
        return m

    async def answer(self, text, **kw):
        self.answers.append((text, kw))

    async def answer_photo(self, photo, **kw):
        self.photos.append((photo, kw))

    async def edit_text(self, text, **kw):
        self.edited.append(text)

    async def delete(self):
        self.deleted = True


class FakeBot:
    def __init__(self):
        self.sent = []
        self.edits = []
        self.deleted = []

    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text))
        return SimpleNamespace(message_id=len(self.sent))

    async def edit_message_text(self, text, chat_id, message_id):
        self.edits.append((time.monotonic(), text))

    async def delete_message(self, chat_id, message_id):
        self.deleted.append(message_id)


class FakeDownloader:
    def __init__(self, media=None, error=None):
        self.media, self.error = media, error

    async def probe(self, link):
        if self.error:
            raise self.error
        return self.media


def video_media(link, w=1920, h=1080):
    section = "videos" if h <= w else "shorts"
    kind = "video" if section == "videos" else "short"
    return MediaInfo(platform="youtube", kind=kind, section=section, id=link.id, url=link.canonical_url,
                     title="Nom <b>", author="Kanal", thumbnail="https://i.ytimg.com/x.jpg", duration=600,
                     width=w, height=h, orientation="horizontal", items_count=1,
                     formats=[FormatOption("auto", "Avto", 1080, 1, True),
                              FormatOption("1080", "1080p", 1080, 80 * 2**20, False),
                              FormatOption("720", "720p", 720, 30 * 2**20, True),
                              FormatOption("audio", "MP3", None, 1, True)])


@pytest.fixture
async def ctx(tmp_path):
    storage = await Storage(":memory:").open()
    started = []

    async def runner(job, workdir):
        started.append(job)
        await asyncio.sleep(0)

    jobs = JobManager(runner=runner, download_dir=tmp_path, max_concurrent=2, hourly_limit=10)
    yield SimpleNamespace(storage=storage, jobs=jobs, bot=FakeBot(), started=started)
    await jobs.shutdown(1)
    await storage.close()


async def test_private_message_without_link(ctx):
    m = FakeMsg("salom")
    await links.on_message(m, ctx.bot, ctx.storage, FakeDownloader(), ctx.jobs)
    assert m.replies == [texts.NO_LINK]


async def test_group_message_without_link_is_silent(ctx):
    m = FakeMsg("salom https://evil.com", chat_type="supergroup")
    await links.on_message(m, ctx.bot, ctx.storage, FakeDownloader(), ctx.jobs)
    assert m.replies == [] and ctx.bot.sent == []


async def test_unsupported_youtube_page(ctx):
    m = FakeMsg("https://www.youtube.com/@kanal")
    await links.on_message(m, ctx.bot, ctx.storage, FakeDownloader(), ctx.jobs)
    assert m.replies == [texts.error_text("unsupported")]


@pytest.mark.parametrize("url", ["https://www.youtube.com/shorts/dQw4w9WgXcQ",
                                 "https://www.instagram.com/reel/C1a2B3c4D5e/"])
async def test_short_and_reel_start_immediately(ctx, url):
    m = FakeMsg(f"qara {url}", chat_type="group")
    await links.on_message(m, ctx.bot, ctx.storage, FakeDownloader(), ctx.jobs)
    await asyncio.sleep(0.05)
    assert ctx.bot.sent[0] == (-1001, texts.STATUS_QUEUED)
    job = ctx.started[0]
    assert job.format == "auto" and job.link.canonical_url == url and job.chat_id == -1001


async def test_youtube_video_shows_quality_picker(ctx):
    link = classify("https://youtu.be/dQw4w9WgXcQ")
    m = FakeMsg("https://youtu.be/dQw4w9WgXcQ")
    await links.on_message(m, ctx.bot, ctx.storage, FakeDownloader(video_media(link)), ctx.jobs)
    assert not ctx.started
    photo, kw = m.photos[0]
    assert photo == "https://i.ytimg.com/x.jpg"
    assert "Nom &lt;b&gt;" in kw["caption"]
    rows = kw["reply_markup"].inline_keyboard
    datas = [b.callback_data for row in rows for b in row]
    labels = [b.text for row in rows for b in row]
    assert all(d.startswith("dl:") and len(d.encode()) <= 64 and "youtu" not in d for d in datas)
    assert {d.split(":")[2] for d in datas} == {"1080", "720", "audio"}
    assert any(label.startswith(texts.OVER_LIMIT_MARK) and "1080p" in label for label in labels)
    token = datas[0].split(":")[1]
    assert await ctx.storage.url_for_token(token) == link.canonical_url


async def test_vertical_watch_link_downloads_as_short(ctx):
    link = classify("https://youtu.be/dQw4w9WgXcQ")
    m = FakeMsg("https://youtu.be/dQw4w9WgXcQ")
    media = video_media(link, 1080, 1920)
    await links.on_message(m, ctx.bot, ctx.storage, FakeDownloader(media), ctx.jobs)
    await asyncio.sleep(0.05)
    assert ctx.started[0].link.section == "shorts" and not m.photos


async def test_preview_error_is_shown(ctx):
    m = FakeMsg("https://youtu.be/dQw4w9WgXcQ")
    await links.on_message(m, ctx.bot, ctx.storage, FakeDownloader(error=AppError("private")), ctx.jobs)
    assert not m.photos


class FakeCb:
    def __init__(self, user_id=42):
        self.from_user = SimpleNamespace(id=user_id)
        self.message = SimpleNamespace(chat=SimpleNamespace(id=user_id), message_id=5)
        self.answers = []

    async def answer(self, text=None, show_alert=False):
        self.answers.append((text, show_alert))


async def test_callback_with_valid_token(ctx):
    token = await ctx.storage.token_for("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    cb = FakeCb()
    await callbacks.on_download(cb, DownloadCB(token=token, fmt="720"), ctx.bot, ctx.storage, ctx.jobs)
    await asyncio.sleep(0.05)
    assert ctx.started[0].format == "720"
    assert ctx.started[0].link.canonical_url == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


@pytest.mark.parametrize("token,fmt", [("missing0000", "720"), ("__VALID__", "best")])
async def test_callback_rejected(ctx, token, fmt):
    if token == "__VALID__":
        token = await ctx.storage.token_for("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    cb = FakeCb()
    await callbacks.on_download(cb, DownloadCB(token=token, fmt=fmt), ctx.bot, ctx.storage, ctx.jobs)
    assert cb.answers == [(texts.LINK_EXPIRED, True)] and not ctx.started


async def test_callback_busy_user_gets_message(ctx):
    token = await ctx.storage.token_for("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    gate = asyncio.Event()

    async def slow(job, wd):
        await gate.wait()

    ctx.jobs.runner = slow
    await callbacks.on_download(FakeCb(), DownloadCB(token=token, fmt="720"), ctx.bot, ctx.storage, ctx.jobs)
    await callbacks.on_download(FakeCb(), DownloadCB(token=token, fmt="480"), ctx.bot, ctx.storage, ctx.jobs)
    assert any(texts.error_text("busy") in t for _, t in ctx.bot.sent)
    gate.set()


def test_quality_keyboard_size_limits():
    link = classify("https://youtu.be/dQw4w9WgXcQ")
    kb = quality_keyboard("A" * 11, video_media(link))
    for row in kb.inline_keyboard:
        for b in row:
            assert len(b.callback_data.encode()) <= 64


# --- progress -----------------------------------------------------------------------
async def test_progress_reporter_throttles(tmp_path):
    assert MIN_EDIT_INTERVAL >= 1.5
    gate = asyncio.Event()

    async def runner(job, wd):
        for i in range(60):
            job.set("downloading", i)
            await asyncio.sleep(0.01)
        job.set("processing", 92)
        await gate.wait()

    jm = JobManager(runner=runner, download_dir=tmp_path, max_concurrent=1, hourly_limit=5)
    bot = FakeBot()
    job = await jm.submit(user_id=1, chat_id=1, link=classify("https://youtu.be/dQw4w9WgXcQ"), fmt="auto")
    rep = ProgressReporter(bot, 1, 99, job, interval=0.2)
    task = rep.start()
    await asyncio.sleep(1.0)
    gate.set()
    await asyncio.wait_for(task, 3)
    times = [t for t, _ in bot.edits]
    assert 1 <= len(times) <= 7
    assert all(b - a >= 0.19 for a, b in zip(times, times[1:]))
    assert any("%" in text for _, text in bot.edits)
    assert bot.deleted == [99]  # done -> progress message removed


async def test_progress_reporter_shows_error(tmp_path):
    async def runner(job, wd):
        raise AppError("not_found")

    jm = JobManager(runner=runner, download_dir=tmp_path, max_concurrent=1, hourly_limit=5)
    bot = FakeBot()
    job = await jm.submit(user_id=1, chat_id=1, link=classify("https://youtu.be/dQw4w9WgXcQ"), fmt="auto")
    await asyncio.wait_for(ProgressReporter(bot, 1, 99, job, interval=0.05).run(), 3)
    assert bot.edits[-1][1] == "❌ " + texts.error_text("not_found")


# --- admin ---------------------------------------------------------------------------
async def test_broadcast_handles_blocked_and_retry_after():
    storage = await Storage(":memory:").open()
    for uid in (1, 2, 3):
        await storage.upsert_user(uid, "u", None)
    method = SendMessage(chat_id=1, text="x")
    retried = []

    class B:
        async def send_message(self, uid, text, parse_mode=None):
            if uid == 2:
                raise TelegramForbiddenError(method=method, message="bot was blocked by the user")
            if uid == 3 and not retried:
                retried.append(1)
                raise TelegramRetryAfter(method=method, message="flood", retry_after=0)

    res = await admin.broadcast(B(), storage, await storage.active_user_ids(), text="hi", delay=0)
    assert res == {"sent": 2, "blocked": 1, "failed": 0}
    assert await storage.active_user_ids() == [1, 3]
    stats = await storage.global_stats()
    assert stats["users"] == 3 and stats["blocked"] == 1
    await storage.close()


async def test_admin_commands_require_admin(monkeypatch):
    settings = Settings(_env_file=None, bot_token=TOKEN, admin_ids="7")
    m = FakeMsg("/stats", user_id=42)
    storage = await Storage(":memory:").open()
    await admin.cmd_stats(m, settings, storage, SimpleNamespace(active_count=0))
    assert m.answers[0][0] == texts.ADMIN_ONLY
    m2 = FakeMsg("/stats", user_id=7)
    await admin.cmd_stats(m2, settings, storage, SimpleNamespace(active_count=2))
    assert "Statistika" in m2.answers[0][0] and "2" in m2.answers[0][0]
    await storage.close()


# --- config / main -----------------------------------------------------------------
def test_settings_parsing(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", TOKEN)
    monkeypatch.setenv("ADMIN_IDS", "1, 2;3")
    monkeypatch.setenv("TELEGRAM_API_BASE", "")
    monkeypatch.setenv("COOKIES_FILE", "")
    monkeypatch.setenv("MAX_UPLOAD_MB", "2000")
    s = Settings(_env_file=None)
    assert s.admin_ids == [1, 2, 3] and s.telegram_api_base is None and s.cookies_file is None
    assert s.max_upload_bytes == 2000 * 2**20 and s.max_duration_min == 120 and s.max_concurrent_downloads == 3
    assert s.user_hourly_limit == 30 and s.transcode_non_h264 is True and s.dev_mode is False
    assert TOKEN not in repr(s)
    assert not s.webapp_enabled
    monkeypatch.setenv("WEBAPP_URL", "https://app.example.com")
    assert Settings(_env_file=None).webapp_enabled


def test_settings_rejects_bad_token(monkeypatch):
    from pydantic import ValidationError

    monkeypatch.setenv("BOT_TOKEN", "not-a-token")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_main_without_token_exits_cleanly(tmp_path):
    env = {k: v for k, v in os.environ.items() if k != "BOT_TOKEN"}
    env["PYTHONPATH"] = str(ROOT)
    p = subprocess.run([sys.executable, "-m", "bot.main"], cwd=tmp_path, env=env, capture_output=True,
                       text=True, timeout=60)
    assert p.returncode == 2
    assert "BOT_TOKEN" in p.stderr and "Traceback" not in p.stderr


def test_redact_filter_masks_tokens():
    rec = logging.LogRecord("x", logging.INFO, "f", 1, "calling https://api.telegram.org/bot%s/getMe", (TOKEN,), None)
    RedactFilter([TOKEN]).filter(rec)
    assert TOKEN not in rec.getMessage() and "***" in rec.getMessage()
    try:
        raise RuntimeError(f"fail {TOKEN}")
    except RuntimeError:
        rec2 = logging.LogRecord("x", logging.ERROR, "f", 1, "boom", (), sys.exc_info())
    RedactFilter([TOKEN]).filter(rec2)
    assert TOKEN not in (rec2.exc_text or "")
