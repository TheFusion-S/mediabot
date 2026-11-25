import asyncio
import json
import time

import pytest
from aiohttp.test_utils import TestClient, TestServer

from bot.downloader import FormatOption, MediaInfo
from bot.errors import AppError
from bot.jobs import JobManager
from bot.ratelimit import RateLimiter
from bot.storage import Storage
from bot.webapp_api import CSP, ApiDeps, create_app
from tests.conftest import TOKEN, make_init_data

H = {"X-Telegram-Init-Data": make_init_data()}  # user 42
OTHER = {"X-Telegram-Init-Data": make_init_data({"id": 77, "first_name": "Vali"})}
YT_SHORT = "https://www.youtube.com/shorts/dQw4w9WgXcQ"


class FakeDownloader:
    def __init__(self):
        self.error = None
        self.probed = []

    async def probe(self, link):
        self.probed.append(link.canonical_url)
        if self.error:
            raise self.error
        return MediaInfo(platform=link.platform, kind=link.kind, section=link.section, id=link.id,
                         url=link.canonical_url, title="T", author="A", thumbnail="https://i.ytimg.com/x.jpg",
                         duration=30, width=1080, height=1920, orientation="vertical", items_count=1,
                         formats=[FormatOption("auto", "Avto", 1080, 5_000_000, True),
                                  FormatOption("audio", "MP3", None, 700_000, True)])


class Runner:
    def __init__(self):
        self.release = asyncio.Event()

    async def __call__(self, job, workdir):
        job.set("downloading", 40)
        await self.release.wait()


@pytest.fixture
async def env(tmp_path):
    webapp = tmp_path / "webapp"
    webapp.mkdir()
    (webapp / "index.html").write_text("<!doctype html><title>MediaBot</title>")
    (webapp / "app.js").write_text("console.log(1)")
    (webapp / "app.css").write_text("body{}")
    (tmp_path / "secret.txt").write_text("SECRET")
    storage = await Storage(":memory:").open()
    runner = Runner()
    jobs = JobManager(runner=runner, download_dir=tmp_path / "dl", max_concurrent=2, hourly_limit=3,
                      storage=storage, limits={"hourly_limit": 3})
    dl = FakeDownloader()
    deps = ApiDeps(bot_token=TOKEN, storage=storage, downloader=dl, jobs=jobs, webapp_dir=webapp,
                   max_upload_mb=50, max_duration_min=120, hourly_limit=3, dev_mode=False,
                   probe_limiter=RateLimiter(100, 60))
    app = create_app(deps)
    client = TestClient(TestServer(app))
    await client.start_server()
    yield type("Env", (), {"client": client, "deps": deps, "dl": dl, "runner": runner, "jobs": jobs,
                           "storage": storage})
    runner.release.set()
    await jobs.shutdown(2)
    await client.close()
    await storage.close()


def assert_error(body, code):
    assert body["ok"] is False
    assert body["error"]["code"] == code
    assert isinstance(body["error"]["message"], str) and body["error"]["message"]


# --- auth -----------------------------------------------------------------------
@pytest.mark.parametrize("path,method", [("/api/me", "GET"), ("/api/history", "GET"), ("/api/jobs/abc", "GET"),
                                         ("/api/probe", "POST"), ("/api/download", "POST")])
async def test_requires_init_data(env, path, method):
    r = await env.client.request(method, path, json={"url": YT_SHORT})
    assert r.status == 401
    assert_error(await r.json(), "unauthorized")


@pytest.mark.parametrize("header", [
    "garbage",
    make_init_data(token="111:BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"),
    make_init_data(auth_date=int(time.time()) - 90000),
    make_init_data().replace("Ali", "Bob"),
])
async def test_invalid_init_data(env, header):
    r = await env.client.get("/api/me", headers={"X-Telegram-Init-Data": header})
    assert r.status == 401
    assert_error(await r.json(), "unauthorized")


async def test_dev_mode_fallback_user(env):
    env.deps.dev_mode = True
    r = await env.client.get("/api/me")
    body = await r.json()
    assert r.status == 200 and body["user"] == {"id": 1, "first_name": "Dev", "username": "dev"}
    r = await env.client.get("/api/me", headers={"X-Telegram-Init-Data": "tampered"})
    assert r.status == 401  # a bad header is still rejected in dev mode


# --- headers ----------------------------------------------------------------------
@pytest.mark.parametrize("path", ["/", "/app.js", "/api/me", "/nope.js", "/api/unknown"])
async def test_security_headers_everywhere(env, path):
    r = await env.client.get(path, headers=H)
    assert r.headers["Content-Security-Policy"] == CSP
    assert "frame-ancestors https://web.telegram.org https://*.telegram.org" in CSP
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["Referrer-Policy"] == "no-referrer"
    assert "Access-Control-Allow-Origin" not in r.headers


async def test_no_cors_preflight(env):
    r = await env.client.options("/api/probe", headers={"Origin": "https://evil.com",
                                                        "Access-Control-Request-Method": "POST"})
    assert "Access-Control-Allow-Origin" not in r.headers
    assert r.status in (401, 404, 405)


# --- static -----------------------------------------------------------------------
async def test_static_files(env):
    r = await env.client.get("/")
    assert r.status == 200 and "MediaBot" in await r.text() and r.content_type == "text/html"
    for p in ("/app.js", "/app.css", "/static/app.js", "/static/app.css"):
        r = await env.client.get(p)
        assert r.status == 200, p
    assert (await env.client.get("/app.js")).content_type in ("application/javascript", "text/javascript")


@pytest.mark.parametrize("path", ["/static/../secret.txt", "/static/%2e%2e/secret.txt", "/..%2fsecret.txt",
                                  "/secret.txt", "/.env", "/static/.hidden.js", "/index.html.bak"])
async def test_static_traversal_blocked(env, path):
    r = await env.client.get(path)
    assert r.status == 404
    assert "SECRET" not in await r.text()


# --- probe ------------------------------------------------------------------------
async def test_probe_ok(env):
    r = await env.client.post("/api/probe", json={"url": "https://youtube.com/shorts/dQw4w9WgXcQ?si=x",
                                                  "section": "videos"}, headers=H)
    body = await r.json()
    assert r.status == 200 and body["ok"] is True
    m = body["media"]
    assert set(m) == {"platform", "kind", "section", "id", "url", "title", "author", "thumbnail", "duration",
                      "width", "height", "orientation", "items_count", "formats"}
    assert m["section"] == "shorts"  # real section, not the requested one
    assert m["url"] == YT_SHORT and env.dl.probed == [YT_SHORT]
    assert m["formats"][0] == {"id": "auto", "label": "Avto", "height": 1080, "size": 5_000_000, "fits": True}


@pytest.mark.parametrize("payload,code,status", [
    ({"url": "https://evil.com/watch?v=dQw4w9WgXcQ"}, "invalid_url", 400),
    ({"url": "https://youtube.com@evil.com/watch?v=dQw4w9WgXcQ"}, "invalid_url", 400),
    ({"url": "javascript:alert(1)"}, "invalid_url", 400),
    ({"url": ""}, "invalid_url", 400),
    ({"url": "https://www.youtube.com/@channel"}, "unsupported", 400),
    ({"url": 123}, "bad_request", 400),
    ({}, "bad_request", 400),
    ({"url": YT_SHORT, "section": "tiktok"}, "bad_request", 400),
])
async def test_probe_errors(env, payload, code, status):
    r = await env.client.post("/api/probe", json=payload, headers=H)
    assert r.status == status
    assert_error(await r.json(), code)
    assert env.dl.probed == []


@pytest.mark.parametrize("raw", [b"not json", b"[1,2]", b"null", b"\xff\xfe"])
async def test_probe_bad_json(env, raw):
    r = await env.client.post("/api/probe", data=raw, headers={**H, "Content-Type": "application/json"})
    assert r.status == 400
    assert_error(await r.json(), "bad_request")


async def test_body_limit_4kb(env):
    r = await env.client.post("/api/probe", data=json.dumps({"url": YT_SHORT, "pad": "x" * 5000}),
                              headers={**H, "Content-Type": "application/json"})
    assert r.status == 413
    assert_error(await r.json(), "bad_request")


@pytest.mark.parametrize("code,status", [("private", 403), ("not_found", 404), ("too_long", 413),
                                         ("unsupported", 400), ("internal", 500)])
async def test_probe_downloader_errors(env, code, status):
    env.dl.error = AppError(code)
    r = await env.client.post("/api/probe", json={"url": YT_SHORT}, headers=H)
    assert r.status == status
    assert_error(await r.json(), code)


async def test_probe_unexpected_exception_is_internal(env):
    env.dl.error = RuntimeError("token 123456789:AAEhBP0av28Rg3zYz1VGrQ5x5c8-hello-wrld leaked?")
    r = await env.client.post("/api/probe", json={"url": YT_SHORT}, headers=H)
    body = await r.json()
    assert r.status == 500
    assert_error(body, "internal")
    assert "AAEh" not in json.dumps(body)


async def test_probe_rate_limited(env):
    env.deps.probe_limiter = RateLimiter(1, 60)
    assert (await env.client.post("/api/probe", json={"url": YT_SHORT}, headers=H)).status == 200
    r = await env.client.post("/api/probe", json={"url": YT_SHORT}, headers=H)
    assert r.status == 429
    assert_error(await r.json(), "rate_limited")


# --- download / jobs -----------------------------------------------------------------
async def test_download_and_poll_job(env):
    r = await env.client.post("/api/download", json={"url": YT_SHORT, "format": "auto"}, headers=H)
    body = await r.json()
    assert r.status == 200 and body["ok"] is True
    job = body["job"]
    assert set(job) == {"id", "status", "progress", "format", "used_format", "note", "error", "media", "created_at"}
    assert set(job["media"]) == {"title", "thumbnail", "kind", "section"}
    assert job["status"] in ("queued", "downloading") and job["format"] == "auto" and job["error"] is None
    jid = job["id"]
    await asyncio.sleep(0.05)
    r = await env.client.get(f"/api/jobs/{jid}", headers=H)
    j = (await r.json())["job"]
    assert r.status == 200 and j["status"] == "downloading" and j["progress"] == 40
    assert env.jobs.get(jid).chat_id == 42  # result goes to the user's private chat

    # other user cannot see it
    r = await env.client.get(f"/api/jobs/{jid}", headers=OTHER)
    assert r.status == 404
    assert_error(await r.json(), "not_found")

    # busy while active
    r = await env.client.post("/api/download", json={"url": YT_SHORT, "format": "720"}, headers=H)
    assert r.status == 409
    assert_error(await r.json(), "busy")

    env.runner.release.set()
    await env.jobs.wait(env.jobs.get(jid), 2)
    r = await env.client.get(f"/api/jobs/{jid}", headers=H)
    j = (await r.json())["job"]
    assert j["status"] == "done" and j["progress"] == 100

    # from DB after eviction from memory
    env.jobs.jobs.clear()
    r = await env.client.get(f"/api/jobs/{jid}", headers=H)
    assert r.status == 200 and (await r.json())["job"]["status"] == "done"


@pytest.mark.parametrize("payload,code", [
    ({"url": YT_SHORT, "format": "4k"}, "bad_request"),
    ({"url": YT_SHORT, "format": "bv*+ba"}, "bad_request"),
    ({"url": "https://evil.com/x"}, "invalid_url"),
])
async def test_download_validation(env, payload, code):
    r = await env.client.post("/api/download", json=payload, headers=H)
    assert r.status == 400
    assert_error(await r.json(), code)


async def test_download_rate_limit(env):
    env.runner.release.set()
    for _ in range(3):
        r = await env.client.post("/api/download", json={"url": YT_SHORT}, headers=H)
        assert r.status == 200
        await env.jobs.wait(env.jobs.get((await r.json())["job"]["id"]), 2)
    r = await env.client.post("/api/download", json={"url": YT_SHORT}, headers=H)
    assert r.status == 429
    assert_error(await r.json(), "rate_limited")


@pytest.mark.parametrize("jid", ["doesnotexist", "0123456789abcdef", "../etc"])
async def test_job_not_found(env, jid):
    r = await env.client.get(f"/api/jobs/{jid}", headers=H)
    assert r.status == 404
    assert_error(await r.json(), "not_found")


# --- history / me ------------------------------------------------------------------
async def _seed(storage, user_id, n, section, status="done"):
    for i in range(n):
        await storage.add_download({
            "id": f"{section[:2]}{user_id}{i:04d}", "user_id": user_id, "platform": "youtube", "kind": "short",
            "section": section, "media_id": "dQw4w9WgXcQ", "url": YT_SHORT, "title": f"t{i}",
            "thumbnail": None, "format": "auto", "status": status, "created_at": f"2026-01-01T00:{i % 60:02d}:00+00:00",
        })


async def test_history(env):
    await _seed(env.storage, 42, 30, "shorts")
    await _seed(env.storage, 42, 30, "instagram")
    await _seed(env.storage, 77, 5, "videos")
    r = await env.client.get("/api/history", headers=H)
    body = await r.json()
    assert r.status == 200 and len(body["items"]) == 20
    assert set(body["items"][0]) == {"id", "section", "kind", "title", "thumbnail", "url", "format", "status",
                                     "created_at"}
    r = await env.client.get("/api/history?section=shorts&limit=100", headers=H)
    items = (await r.json())["items"]
    assert len(items) == 30 and all(i["section"] == "shorts" for i in items)
    r = await env.client.get("/api/history?section=all&limit=50", headers=H)
    assert len((await r.json())["items"]) == 50
    r = await env.client.get("/api/history?section=videos", headers=H)
    assert (await r.json())["items"] == []  # other user's rows are not visible


@pytest.mark.parametrize("qs", ["section=tiktok", "limit=abc", "limit=0", "limit=-5"])
async def test_history_bad_params(env, qs):
    r = await env.client.get(f"/api/history?{qs}", headers=H)
    assert r.status == 400
    assert_error(await r.json(), "bad_request")


async def test_me(env):
    await _seed(env.storage, 42, 2, "shorts")
    await _seed(env.storage, 42, 1, "videos")
    await _seed(env.storage, 42, 1, "instagram", status="error")
    r = await env.client.post("/api/download", json={"url": YT_SHORT}, headers=H)
    assert r.status == 200
    r = await env.client.get("/api/me", headers=H)
    body = await r.json()
    assert body == {
        "ok": True,
        "user": {"id": 42, "first_name": "Ali", "username": "ali"},
        "stats": {"total": 3, "instagram": 0, "shorts": 2, "videos": 1},
        "limits": {"max_upload_mb": 50, "max_duration_min": 120, "hourly_limit": 3, "hourly_used": 1},
    }


async def test_unknown_api_route_is_json_404(env):
    r = await env.client.get("/api/nope", headers=H)
    assert r.status == 404
    assert_error(await r.json(), "not_found")


async def test_method_not_allowed_json(env):
    r = await env.client.get("/api/probe", headers=H)
    assert r.status == 405
    assert_error(await r.json(), "bad_request")
