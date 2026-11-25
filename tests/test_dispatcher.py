"""End-to-end through aiogram's Dispatcher with a fake Telegram session (no network)."""

import asyncio
import datetime as dt

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.methods import AnswerCallbackQuery, EditMessageText, SendMessage, SendPhoto
from aiogram.types import Chat, Message, Update

from bot import texts
from bot.config import Settings
from bot.handlers import setup_dispatcher
from bot.jobs import JobManager
from bot.storage import Storage
from tests.conftest import TOKEN


class FakeSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.calls = []

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if isinstance(method, (SendMessage, SendPhoto, EditMessageText)):
            chat_id = getattr(method, "chat_id", 1) or 1
            return Message(message_id=len(self.calls) + 1000, date=dt.datetime.now(),
                           chat=Chat(id=int(chat_id), type="private"), text=getattr(method, "text", None))
        if isinstance(method, AnswerCallbackQuery):
            return True
        return True

    async def stream_content(self, *a, **kw):  # pragma: no cover
        yield b""

    async def close(self):
        pass


def update(text, chat_type="private", uid=42, update_id=1):
    chat = {"id": uid if chat_type == "private" else -100, "type": chat_type}
    return Update.model_validate({"update_id": update_id, "message": {
        "message_id": update_id, "date": int(dt.datetime.now().timestamp()), "chat": chat,
        "from": {"id": uid, "is_bot": False, "first_name": "Ali"}, "text": text,
        "entities": [{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}] if text.startswith("/") else None,
    }})


@pytest.fixture
async def wired(tmp_path):
    session = FakeSession()
    bot = Bot(TOKEN, session=session)
    storage = await Storage(":memory:").open()
    started = []

    async def runner(job, wd):
        started.append(job)

    jobs = JobManager(runner=runner, download_dir=tmp_path, max_concurrent=1, hourly_limit=10)
    settings = Settings(_env_file=None, bot_token=TOKEN, webapp_url="https://app.example.com", admin_ids="42")
    dp = Dispatcher(settings=settings, db=storage, downloader=object(), jobs=jobs)
    setup_dispatcher(dp)
    yield bot, dp, session, storage, started
    await jobs.shutdown(1)
    await storage.close()


async def test_start_command_sends_webapp_button_and_records_user(wired):
    bot, dp, session, storage, _ = wired
    await dp.feed_update(bot, update("/start"))
    sent = [c for c in session.calls if isinstance(c, SendMessage)]
    assert "Assalomu alaykum" in sent[0].text
    btn = sent[0].reply_markup.inline_keyboard[0][0]
    assert btn.web_app.url == "https://app.example.com"
    assert await storage.active_user_ids() == [42]


async def test_link_message_starts_job_through_dispatcher(wired):
    bot, dp, session, storage, started = wired
    await dp.feed_update(bot, update("https://www.youtube.com/shorts/dQw4w9WgXcQ", update_id=2))
    await asyncio.sleep(0.05)
    assert started and started[0].link.section == "shorts"
    assert any(isinstance(c, SendMessage) and c.text == texts.STATUS_QUEUED for c in session.calls)


async def test_group_noise_ignored_and_admin_stats(wired):
    bot, dp, session, storage, _ = wired
    await dp.feed_update(bot, update("salom hammaga", chat_type="supergroup", update_id=3))
    assert session.calls == []
    await dp.feed_update(bot, update("/stats", update_id=4))
    assert "Statistika" in session.calls[-1].text
