"""Private mode: only ALLOWED_USER_IDS may use the bot and the Mini App API."""

import asyncio

import pytest
from aiogram import Bot, Dispatcher
from aiogram.methods import AnswerCallbackQuery, SendMessage
from aiogram.types import Update

from bot import texts
from bot.config import Settings, access_set
from bot.handlers import setup_dispatcher
from bot.jobs import JobManager
from bot.storage import Storage
from tests.conftest import TOKEN, make_init_data
from tests import test_api as _api
from tests.test_dispatcher import FakeSession, update

SHORT = "https://www.youtube.com/shorts/dQw4w9WgXcQ"
env = _api.env  # reuse the API test fixture


def settings(**kw):
    return Settings(_env_file=None, bot_token=TOKEN, **kw)


def test_access_set_modes():
    assert access_set(settings()) == frozenset()                       # setup mode: nobody
    assert access_set(settings(allowed_user_ids="42, 7")) == {42, 7}
    assert access_set(settings(public_mode=True)) is None              # everyone
    s = settings(allowed_user_ids="42")
    assert s.admin_ids == [42]                                         # owner gets admin commands
    assert settings(allowed_user_ids="42", admin_ids="9").admin_ids == [9]


async def make_dp(tmp_path, **kw):
    session = FakeSession()
    bot = Bot(TOKEN, session=session)
    storage = await Storage(":memory:").open()
    started = []

    async def runner(job, wd):
        started.append(job)

    jobs = JobManager(runner=runner, download_dir=tmp_path, max_concurrent=1, hourly_limit=10)
    dp = Dispatcher(settings=settings(**kw), db=storage, downloader=object(), jobs=jobs)
    setup_dispatcher(dp)
    return bot, dp, session, storage, jobs, started


async def test_stranger_is_blocked_and_owner_works(tmp_path):
    bot, dp, session, storage, jobs, started = await make_dp(tmp_path, allowed_user_ids="42")
    try:
        await dp.feed_update(bot, update(SHORT, uid=99, update_id=1))
        await dp.feed_update(bot, update(SHORT, uid=99, update_id=2))   # second notice suppressed
        await asyncio.sleep(0.05)
        msgs = [c for c in session.calls if isinstance(c, SendMessage)]
        assert [m.text for m in msgs] == [texts.PRIVATE_BOT]
        assert not started and await storage.active_user_ids() == []    # stranger never recorded
        await dp.feed_update(bot, update(SHORT, uid=99, chat_type="supergroup", update_id=3))
        assert len([c for c in session.calls if isinstance(c, SendMessage)]) == 1  # silent in groups

        await dp.feed_update(bot, update(SHORT, uid=42, update_id=4))
        await asyncio.sleep(0.05)
        assert started and started[0].user_id == 42
    finally:
        await jobs.shutdown(1)
        await storage.close()


async def test_setup_mode_tells_id_and_downloads_nothing(tmp_path):
    bot, dp, session, storage, jobs, started = await make_dp(tmp_path)
    try:
        await dp.feed_update(bot, update("/start", uid=12345, update_id=1))
        await dp.feed_update(bot, update(SHORT, uid=12345, update_id=2))
        await asyncio.sleep(0.05)
        msgs = [c for c in session.calls if isinstance(c, SendMessage)]
        assert msgs and all("ALLOWED_USER_IDS=12345" in m.text for m in msgs)
        assert not started
    finally:
        await jobs.shutdown(1)
        await storage.close()


async def test_stranger_callback_gets_alert(tmp_path):
    bot, dp, session, storage, jobs, _ = await make_dp(tmp_path, allowed_user_ids="42")
    try:
        cb = Update.model_validate({"update_id": 9, "callback_query": {
            "id": "1", "chat_instance": "x", "data": "dl:abc:720",
            "from": {"id": 99, "is_bot": False, "first_name": "X"}}})
        await dp.feed_update(bot, cb)
        answers = [c for c in session.calls if isinstance(c, AnswerCallbackQuery)]
        assert answers and answers[0].text == texts.PRIVATE_BOT and answers[0].show_alert
    finally:
        await jobs.shutdown(1)
        await storage.close()


@pytest.mark.parametrize("allowed,status", [(frozenset({42}), 200), (frozenset({7}), 403), (frozenset(), 403)])
async def test_api_only_for_allowed_users(env, allowed, status):
    env.deps.allowed_user_ids = allowed
    r = await env.client.get("/api/me", headers={"X-Telegram-Init-Data": make_init_data()})
    assert r.status == status
    body = await r.json()
    if status == 403:
        assert body["ok"] is False and body["error"]["code"] == "forbidden"
        r2 = await env.client.post("/api/probe", json={"url": SHORT, "section": "shorts"},
                                   headers={"X-Telegram-Init-Data": make_init_data()})
        assert r2.status == 403


async def test_avatar_uploaded_only_when_changed(tmp_path):
    from bot.main import ensure_avatar

    img = tmp_path / "a.jpg"
    img.write_bytes(b"\xff\xd8\xff fake jpeg v1")
    s = settings(allowed_user_ids="42", bot_avatar_file=str(img), db_path=str(tmp_path / "db.sqlite"))

    class FakeBot:
        def __init__(self):
            self.calls = 0

        async def set_my_profile_photo(self, photo):
            assert photo.type == "static"
            self.calls += 1
            return True

    b = FakeBot()
    await ensure_avatar(b, s)
    await ensure_avatar(b, s)          # unchanged -> no second upload
    assert b.calls == 1
    img.write_bytes(b"\xff\xd8\xff fake jpeg v2")
    await ensure_avatar(b, s)          # changed -> uploaded again
    assert b.calls == 2
    await ensure_avatar(b, settings(allowed_user_ids="42", bot_avatar_file=""))  # disabled
    assert b.calls == 2
