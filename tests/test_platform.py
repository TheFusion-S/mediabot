"""Free-hosting helpers: Render URL defaults and the keep-alive pinger."""

import asyncio

from aiohttp import web
from aiohttp.test_utils import TestServer

from bot.config import Settings
from bot.main import keepalive
from tests.conftest import TOKEN


def settings(**kw):
    return Settings(_env_file=None, bot_token=TOKEN, **kw)


def test_render_url_becomes_webapp_and_keepalive_url():
    s = settings(render_external_url="https://mediabot.onrender.com/")
    assert s.webapp_url == "https://mediabot.onrender.com" and s.webapp_enabled
    assert s.keepalive_url == "https://mediabot.onrender.com"


def test_explicit_values_win_and_plain_setups_are_untouched():
    s = settings(render_external_url="https://a.onrender.com", webapp_url="https://custom.example",
                 keepalive_url="https://ping.example")
    assert s.webapp_url == "https://custom.example" and s.keepalive_url == "https://ping.example"
    plain = settings()
    assert plain.webapp_url == "" and plain.keepalive_url == ""
    assert settings(render_external_url="http://insecure").webapp_url == ""   # Mini Apps need https


def test_port_env_is_respected_by_entrypoint_contract(monkeypatch):
    # PaaS sets PORT; docker-entrypoint.sh copies it into WEB_PORT, which Settings reads.
    monkeypatch.setenv("WEB_PORT", "10000")
    assert Settings(_env_file=None, bot_token=TOKEN).web_port == 10000


async def test_keepalive_pings_healthz_until_stopped():
    hits = []

    async def healthz(request):
        hits.append(request.path)
        return web.Response(text="ok")

    app = web.Application()
    app.router.add_get("/healthz", healthz)
    server = TestServer(app)
    await server.start_server()
    stop = asyncio.Event()
    task = asyncio.create_task(keepalive(str(server.make_url("/")), 0.05, stop))
    await asyncio.sleep(0.3)
    stop.set()
    await asyncio.wait_for(task, 2)
    await server.close()
    assert len(hits) >= 2 and set(hits) == {"/healthz"}


async def test_keepalive_survives_unreachable_url():
    stop = asyncio.Event()
    task = asyncio.create_task(keepalive("http://127.0.0.1:9", 0.05, stop))
    await asyncio.sleep(0.2)
    assert not task.done()          # errors are logged, the loop keeps going
    stop.set()
    await asyncio.wait_for(task, 2)
