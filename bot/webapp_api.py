"""aiohttp app: Mini App static files + ``/api/*`` (shapes are a binding contract, see SPEC)."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from aiohttp import web

from . import texts
from .access import Access
from .downloader import FORMAT_IDS, Downloader
from .errors import AppError
from .jobs import JobManager, job_from_row
from .platforms import SECTIONS, analyze_full, reject_message
from .ratelimit import RateLimiter
from .security import InitDataError, WebAppUser, validate_init_data
from .storage import Storage

log = logging.getLogger(__name__)

MAX_BODY = 4096
MAX_URL_FIELD = 2048
INIT_DATA_HEADER = "X-Telegram-Init-Data"
DEV_USER = WebAppUser(id=1, first_name="Dev", username="dev")

CSP = (
    "default-src 'self'; script-src 'self' https://telegram.org; img-src 'self' https: data:; "
    "style-src 'self' 'unsafe-inline'; connect-src 'self'; "
    "frame-ancestors https://web.telegram.org https://*.telegram.org; "
    "base-uri 'none'; form-action 'none'; object-src 'none'"
)
SECURITY_HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}
STATIC_FILE_RE = re.compile(r"^[A-Za-z0-9_-][A-Za-z0-9_.-]{0,100}\.(js|css|svg|png|ico|webp|json|webmanifest|woff2?)$")


@dataclass
class ApiDeps:
    bot_token: str
    storage: Storage
    downloader: Downloader
    jobs: JobManager
    webapp_dir: Path
    max_upload_mb: int
    max_duration_min: int
    hourly_limit: int
    dev_mode: bool = False
    probe_limiter: RateLimiter | None = None
    init_data_max_age: int = 6 * 3600
    # who may use the Mini App (same rules as the bot); None = everyone (tests / dev)
    access: Access | None = None


DEPS = web.AppKey("deps", ApiDeps)
USER = web.RequestKey("webapp_user", WebAppUser)


def ok(**payload: Any) -> web.Response:
    return web.json_response({"ok": True, **payload})


def fail(code: str, message: str | None = None, status: int | None = None) -> web.Response:
    err = AppError(code, message, status=status)
    return web.json_response({"ok": False, "error": err.to_dict()}, status=err.status)


# --------------------------------------------------------------------- middlewares
@web.middleware
async def security_headers(request: web.Request, handler: Callable[[web.Request], Awaitable[web.StreamResponse]]):
    try:
        resp = await handler(request)
    except web.HTTPException as exc:
        if request.path.startswith("/api/"):
            code = {404: "not_found", 401: "unauthorized", 403: "forbidden"}.get(exc.status, "bad_request")
            if exc.status >= 500:
                code = "internal"
            msg = texts.REQUEST_TOO_LARGE if exc.status == 413 else None
            resp = fail(code, msg, status=exc.status)
        else:
            resp = web.Response(status=exc.status, text=f"{exc.status}: {exc.reason}")
            if "Location" in exc.headers:
                resp.headers["Location"] = exc.headers["Location"]
    except Exception:
        log.exception("unhandled error on %s", request.path)
        resp = fail("internal") if request.path.startswith("/api/") else web.Response(status=500, text="Internal error")
    for k, v in SECURITY_HEADERS.items():
        resp.headers[k] = v
    if request.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


@web.middleware
async def auth(request: web.Request, handler: Callable[[web.Request], Awaitable[web.StreamResponse]]):
    if not request.path.startswith("/api/"):
        return await handler(request)
    deps: ApiDeps = request.app[DEPS]
    raw = request.headers.get(INIT_DATA_HEADER, "").strip()
    if not raw:
        if not deps.dev_mode:
            return fail("unauthorized")
        user = DEV_USER
    else:
        try:
            user = validate_init_data(raw, deps.bot_token, max_age=deps.init_data_max_age)
        except InitDataError as exc:
            log.info("initData rejected: %s", exc)
            return fail("unauthorized")
    if deps.access is not None and user is not DEV_USER and not (await deps.access.check(user.id)).allowed:
        log.info("webapp access denied for user %s", user.id)
        return fail("forbidden")
    request[USER] = user
    return await handler(request)


async def read_json(request: web.Request) -> dict[str, Any]:
    if request.content_length is not None and request.content_length > MAX_BODY:
        raise AppError("bad_request", texts.REQUEST_TOO_LARGE, status=413)
    body = await request.content.read(MAX_BODY + 1)
    if len(body) > MAX_BODY:
        raise AppError("bad_request", texts.REQUEST_TOO_LARGE, status=413)
    try:
        data = json.loads(body or b"null")
    except (ValueError, UnicodeDecodeError):
        raise AppError("bad_request") from None
    if not isinstance(data, dict):
        raise AppError("bad_request")
    return data


def api_handler(fn: Callable[[web.Request], Awaitable[web.Response]]):
    async def wrapper(request: web.Request) -> web.Response:
        try:
            return await fn(request)
        except AppError as exc:
            return web.json_response({"ok": False, "error": exc.to_dict()}, status=exc.status)
    wrapper.__name__ = fn.__name__
    return wrapper


def _url_field(data: dict[str, Any]):
    url = data.get("url")
    if not isinstance(url, str) or not url.strip() or len(url) > MAX_URL_FIELD:
        raise AppError("invalid_url" if isinstance(url, str) else "bad_request")
    link, err, reason = analyze_full(url)
    if link is None:
        raise AppError(err or "invalid_url", reject_message(err or "invalid_url", reason))
    return link


# --------------------------------------------------------------------- API
@api_handler
async def api_probe(request: web.Request) -> web.Response:
    deps: ApiDeps = request.app[DEPS]
    user: WebAppUser = request[USER]
    data = await read_json(request)
    section = data.get("section")
    if section is not None and section not in SECTIONS:
        raise AppError("bad_request")
    link = _url_field(data)
    if deps.probe_limiter is not None and not deps.probe_limiter.hit(user.id):
        raise AppError("rate_limited", texts.PROBE_RATE_LIMITED)
    media = await deps.downloader.probe(link)
    return ok(media=media.to_api())


@api_handler
async def api_download(request: web.Request) -> web.Response:
    deps: ApiDeps = request.app[DEPS]
    user: WebAppUser = request[USER]
    data = await read_json(request)
    fmt = data.get("format", "auto")
    if fmt not in FORMAT_IDS:
        raise AppError("bad_request")
    link = _url_field(data)
    try:
        await deps.storage.upsert_user(user.id, user.first_name, user.username)
    except Exception:
        log.exception("upsert_user failed")
    job = await deps.jobs.submit(user_id=user.id, chat_id=user.id, link=link, fmt=fmt, origin="webapp")
    return ok(job=job.to_api())


@api_handler
async def api_job(request: web.Request) -> web.Response:
    deps: ApiDeps = request.app[DEPS]
    user: WebAppUser = request[USER]
    job_id = request.match_info["job_id"]
    if not re.fullmatch(r"[0-9a-f]{1,32}", job_id):
        raise AppError("not_found")
    job = deps.jobs.get(job_id, user.id)
    if job is not None:
        return ok(job=job.to_api())
    row = await deps.storage.get_download(job_id, user.id)
    if row is None:
        raise AppError("not_found")
    return ok(job=job_from_row(row))


@api_handler
async def api_history(request: web.Request) -> web.Response:
    deps: ApiDeps = request.app[DEPS]
    user: WebAppUser = request[USER]
    section = request.query.get("section", "all")
    if section not in (*SECTIONS, "all"):
        raise AppError("bad_request")
    try:
        limit = int(request.query.get("limit", "20"))
    except ValueError:
        raise AppError("bad_request") from None
    if limit < 1:
        raise AppError("bad_request")
    limit = min(limit, 50)
    rows = await deps.storage.history(user.id, section, limit)
    items = []
    for r in rows:
        item = {"id": r["id"], "section": r["section"], "kind": r["kind"], "title": r["title"],
                "thumbnail": r["thumbnail"], "url": r["url"], "format": r["format"],
                "status": r["status"], "created_at": r["created_at"]}
        if item["status"] not in ("done", "error"):
            live = deps.jobs.get(r["id"], user.id)  # still running -> live status
            item["status"] = live.status if live is not None else "error"
            if live is not None:
                item["title"] = item["title"] or live.title
                item["thumbnail"] = item["thumbnail"] or live.thumbnail
        items.append(item)
    return ok(items=items)


@api_handler
async def api_me(request: web.Request) -> web.Response:
    deps: ApiDeps = request.app[DEPS]
    user: WebAppUser = request[USER]
    try:
        await deps.storage.upsert_user(user.id, user.first_name, user.username)
    except Exception:
        log.exception("upsert_user failed")
    stats = await deps.storage.user_stats(user.id)
    return ok(
        user=user.to_api(),
        stats=stats,
        limits={
            "max_upload_mb": deps.max_upload_mb,
            "max_duration_min": deps.max_duration_min,
            "hourly_limit": deps.hourly_limit,
            "hourly_used": deps.jobs.hourly_used(user.id),
        },
    )


# --------------------------------------------------------------------- static
def _static_file(deps: ApiDeps, name: str) -> web.StreamResponse:
    root = deps.webapp_dir.resolve()
    path = (root / name).resolve()
    if root not in path.parents or not path.is_file():
        raise web.HTTPNotFound()
    resp = web.FileResponse(path)
    resp.headers["Cache-Control"] = "no-cache"
    return resp


async def index(request: web.Request) -> web.StreamResponse:
    return _static_file(request.app[DEPS], "index.html")


async def root_asset(request: web.Request) -> web.StreamResponse:
    name = request.match_info["name"]
    if not STATIC_FILE_RE.match(name):
        raise web.HTTPNotFound()
    return _static_file(request.app[DEPS], name)


async def static_asset(request: web.Request) -> web.StreamResponse:
    rel = request.match_info["path"]
    parts = rel.split("/")
    if any(p in ("", ".", "..") or p.startswith(".") for p in parts) or not STATIC_FILE_RE.match(parts[-1]) \
            and not parts[-1].endswith(".html"):
        raise web.HTTPNotFound()
    return _static_file(request.app[DEPS], rel)


async def healthz(request: web.Request) -> web.Response:
    return web.json_response({"ok": True})


def create_app(deps: ApiDeps) -> web.Application:
    app = web.Application(middlewares=[security_headers, auth], client_max_size=MAX_BODY)
    app[DEPS] = deps
    r = app.router
    r.add_post("/api/probe", api_probe)
    r.add_post("/api/download", api_download)
    r.add_get("/api/jobs/{job_id}", api_job)
    r.add_get("/api/history", api_history)
    r.add_get("/api/me", api_me)
    r.add_get("/", index)
    r.add_get("/healthz", healthz)
    r.add_get("/static/{path:.+}", static_asset)
    r.add_get("/{name}", root_asset)
    return app
