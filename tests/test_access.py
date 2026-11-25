"""Owner-managed access control: open / private mode, access requests, approve / block, Mini App API."""

import asyncio
import datetime as dt

import pytest
from aiogram import Bot, Dispatcher
from aiogram.methods import AnswerCallbackQuery, EditMessageText, SendMessage
from aiogram.types import Update

from bot import texts
from bot.access import Access
from bot.config import Settings
from bot.handlers import setup_dispatcher
from bot.jobs import JobManager
from bot.storage import Storage
from tests import test_api as _api
from tests.conftest import TOKEN, make_init_data
from tests.test_dispatcher import FakeSession, update

SHORT = "https://www.youtube.com/shorts/dQw4w9WgXcQ"
OWNER, ALICE, BOB = 42, 7, 99
env = _api.env  # reuse the API test fixture


def settings(**kw):
    return Settings(_env_file=None, bot_token=TOKEN, **kw)


def callback(data, uid, update_id=50, with_message=True):
    cq = {"id": str(update_id), "chat_instance": "x", "data": data,
          "from": {"id": uid, "is_bot": False, "first_name": f"U{uid}"}}
    if with_message:
        cq["message"] = {"message_id": 777, "date": int(dt.datetime.now().timestamp()),
                         "chat": {"id": uid, "type": "private"}, "text": "old"}
    return Update.model_validate({"update_id": update_id, "callback_query": cq})


@pytest.fixture
async def store():
    s = await Storage(":memory:").open()
    yield s
    await s.close()


# ----------------------------------------------------------------------------- rules
async def test_rules(store):
    a = Access(settings(admin_ids=str(OWNER)), store)
    assert await a.mode() == "open"                                   # default: everyone
    assert (await a.check(BOB)).allowed and (await a.check(OWNER)).reason == "owner"
    await store.set_access(BOB, "blocked")
    assert (await a.check(BOB)).reason == "blocked"                   # blocked even in open mode

    await a.set_mode("private")
    assert (await a.check(ALICE)).reason == "none"
    await store.set_access(ALICE, "pending")
    assert (await a.check(ALICE)).reason == "pending"
    await store.set_access(ALICE, "approved")
    assert (await a.check(ALICE)).allowed
    assert (await a.check(OWNER)).allowed                             # owner always

    pre = Access(settings(admin_ids=str(OWNER), allowed_user_ids="5", access_mode="private"), store)
    assert (await pre.check(5)).reason == "approved"                  # pre-approved via env


async def test_setup_mode_when_private_without_owner(store):
    a = Access(settings(access_mode="private"), store)
    assert (await a.check(BOB)).reason == "setup"
    assert (await Access(settings(), store).check(BOB)).allowed       # open mode works without an owner


def test_allowed_user_ids_become_owner_when_no_admin_ids():
    assert settings(allowed_user_ids="42").admin_ids == [42]
    assert settings(allowed_user_ids="42", admin_ids="9").admin_ids == [9]


# ----------------------------------------------------------------------------- through the dispatcher
async def make_dp(tmp_path, **kw):
    session = FakeSession()
    bot = Bot(TOKEN, session=session)
    storage = await Storage(":memory:").open()
    started = []

    async def runner(job, wd):
        started.append(job)

    jobs = JobManager(runner=runner, download_dir=tmp_path, max_concurrent=1, hourly_limit=10)
    s = settings(**kw)
    dp = Dispatcher(settings=s, db=storage, downloader=object(), jobs=jobs, access=Access(s, storage))
    setup_dispatcher(dp)
    return bot, dp, session, storage, jobs, started


def sent(session):
    return [c for c in session.calls if isinstance(c, SendMessage)]


async def test_open_mode_everyone_can_download(tmp_path):
    bot, dp, session, storage, jobs, started = await make_dp(tmp_path, admin_ids=str(OWNER))
    try:
        await dp.feed_update(bot, update(SHORT, uid=BOB, update_id=1))
        await asyncio.sleep(0.05)
        assert started and started[0].user_id == BOB
    finally:
        await jobs.shutdown(1)
        await storage.close()


async def test_private_request_approve_flow(tmp_path):
    bot, dp, session, storage, jobs, started = await make_dp(tmp_path, admin_ids=str(OWNER), access_mode="private")
    try:
        # stranger gets the notice + request button (once per hour), nothing is downloaded
        await dp.feed_update(bot, update(SHORT, uid=BOB, update_id=1))
        await dp.feed_update(bot, update(SHORT, uid=BOB, update_id=2))
        notices = sent(session)
        assert [m.text for m in notices] == [texts.PRIVATE_BOT]
        assert notices[0].reply_markup.inline_keyboard[0][0].callback_data == "acc:req"
        assert not started

        # /id always works
        await dp.feed_update(bot, update("/id", uid=BOB, update_id=3))
        assert f"<code>{BOB}</code>" in sent(session)[-1].text

        # request -> owner gets approve/reject/block buttons
        await dp.feed_update(bot, callback("acc:req", BOB, update_id=4))
        to_owner = [m for m in sent(session) if m.chat_id == OWNER]
        assert len(to_owner) == 1 and str(BOB) in to_owner[0].text
        datas = [b.callback_data for row in to_owner[0].reply_markup.inline_keyboard for b in row]
        assert datas == [f"acc:ok:{BOB}", f"acc:no:{BOB}", f"acc:ban:{BOB}"]
        assert await storage.get_access(BOB) == "pending"
        alert = [c for c in session.calls if isinstance(c, AnswerCallbackQuery)][-1]
        assert alert.text == texts.REQUEST_SENT

        # a non-owner cannot approve
        await dp.feed_update(bot, callback(f"acc:ok:{BOB}", ALICE, update_id=5))
        assert await storage.get_access(BOB) == "pending"

        # owner approves -> user notified, owner message edited, user can now download
        await dp.feed_update(bot, callback(f"acc:ok:{BOB}", OWNER, update_id=6))
        assert await storage.get_access(BOB) == "approved"
        assert any(m.chat_id == BOB and m.text == texts.USER_APPROVED for m in sent(session))
        assert any(isinstance(c, EditMessageText) and texts.RESULT_APPROVED in c.text for c in session.calls)
        await dp.feed_update(bot, update(SHORT, uid=BOB, update_id=7))
        await asyncio.sleep(0.05)
        assert started and started[0].user_id == BOB
    finally:
        await jobs.shutdown(1)
        await storage.close()


async def test_block_and_owner_commands(tmp_path):
    bot, dp, session, storage, jobs, started = await make_dp(tmp_path, admin_ids=str(OWNER))
    try:
        await dp.feed_update(bot, update(f"/block {BOB}", uid=OWNER, update_id=1))
        assert await storage.get_access(BOB) == "blocked"
        n = len(session.calls)
        await dp.feed_update(bot, update(SHORT, uid=BOB, update_id=2))     # blocked: silent, even in open mode
        await asyncio.sleep(0.05)
        assert len(session.calls) == n and not started

        await dp.feed_update(bot, update(f"/unblock {BOB}", uid=OWNER, update_id=3))
        assert await storage.get_access(BOB) is None
        await dp.feed_update(bot, update(f"/block {OWNER}", uid=OWNER, update_id=4))
        assert sent(session)[-1].text == texts.CANNOT_TARGET_OWNER
        await dp.feed_update(bot, update("/block abc", uid=OWNER, update_id=5))
        assert "Foydalanish" in sent(session)[-1].text

        # non-owner cannot use owner commands
        await dp.feed_update(bot, update("/mode", uid=BOB, update_id=6))
        assert sent(session)[-1].text == texts.OWNER_ONLY

        # owner switches mode with the button; /users lists people
        await dp.feed_update(bot, update("/mode", uid=OWNER, update_id=7))
        kb = sent(session)[-1].reply_markup.inline_keyboard[0]
        assert [b.callback_data for b in kb] == ["acc:mode:open", "acc:mode:private"]
        await dp.feed_update(bot, callback("acc:mode:private", OWNER, update_id=8))
        assert await dp["access"].mode() == "private"
        await dp.feed_update(bot, update(f"/allow {ALICE}", uid=OWNER, update_id=9))
        await dp.feed_update(bot, update("/users", uid=OWNER, update_id=10))
        assert str(ALICE) in sent(session)[-1].text and "Yopiq" in sent(session)[-1].text
    finally:
        await jobs.shutdown(1)
        await storage.close()


async def test_setup_mode_tells_id_and_downloads_nothing(tmp_path):
    bot, dp, session, storage, jobs, started = await make_dp(tmp_path, access_mode="private")
    try:
        await dp.feed_update(bot, update("/start", uid=12345, update_id=1))
        await dp.feed_update(bot, update(SHORT, uid=12345, update_id=2))
        await asyncio.sleep(0.05)
        msgs = sent(session)
        assert msgs and all("ADMIN_IDS=12345" in m.text for m in msgs)
        assert not started
    finally:
        await jobs.shutdown(1)
        await storage.close()


async def test_private_mode_silent_in_groups(tmp_path):
    bot, dp, session, storage, jobs, _ = await make_dp(tmp_path, admin_ids=str(OWNER), access_mode="private")
    try:
        await dp.feed_update(bot, update(SHORT, uid=BOB, chat_type="supergroup", update_id=1))
        assert sent(session) == []
    finally:
        await jobs.shutdown(1)
        await storage.close()


# ----------------------------------------------------------------------------- Mini App API
@pytest.mark.parametrize("mode,status,code", [("open", None, 200), ("private", None, 403),
                                               ("private", "approved", 200), ("open", "blocked", 403)])
async def test_api_follows_access_rules(env, mode, status, code):
    a = Access(settings(admin_ids="1000", access_mode=mode), env.storage)
    if status:
        await env.storage.set_access(42, status)
    env.deps.access = a
    r = await env.client.get("/api/me", headers={"X-Telegram-Init-Data": make_init_data()})
    assert r.status == code
    if code == 403:
        body = await r.json()
        assert body["error"]["code"] == "forbidden" and body["error"]["message"] == texts.ERRORS["forbidden"]
async def test_avatar_uploaded_only_when_changed(tmp_path):
    from bot.main import ensure_avatar

    img = tmp_path / "a.jpg"
    img.write_bytes(b"\xff\xd8\xff fake jpeg v1")
    s = settings(admin_ids="42", bot_avatar_file=str(img), db_path=str(tmp_path / "db.sqlite"))

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
    await ensure_avatar(b, settings(admin_ids="42", bot_avatar_file=""))  # disabled
    assert b.calls == 2
