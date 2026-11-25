"""Entry point: ``python -m bot.main`` — bot polling + aiohttp web server in one process."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import signal
import sys

from pydantic import ValidationError

log = logging.getLogger("bot")

_TOKEN_PATTERN = re.compile(r"\d{3,15}:[A-Za-z0-9_-]{20,}")


class RedactFilter(logging.Filter):
    """Masks anything that looks like a bot token (also in exception text)."""

    def __init__(self, secrets: list[str] | None = None):
        super().__init__()
        self.secrets = [s for s in (secrets or []) if s]

    def _clean(self, text: str) -> str:
        for s in self.secrets:
            text = text.replace(s, "***")
        return _TOKEN_PATTERN.sub("***", text)

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:  # pragma: no cover
            return True
        cleaned = self._clean(msg)
        if record.exc_info and record.exc_info[1] is not None:
            import traceback

            record.exc_text = self._clean("".join(traceback.format_exception(*record.exc_info)))
            record.exc_info = None
        if cleaned != msg or record.args:
            record.msg, record.args = cleaned, None
        return True


def setup_logging(level: str = "INFO", secrets: list[str] | None = None) -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handler.addFilter(RedactFilter(secrets))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper() if isinstance(level, str) else level)
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)


async def ensure_avatar(bot, settings) -> None:
    """Set the bot's profile photo from BOT_AVATAR_FILE, but only when the image changed."""
    import hashlib

    from aiogram.types import FSInputFile, InputProfilePhotoStatic

    path = settings.bot_avatar_file
    if path is None:
        return
    if not path.is_file():
        log.warning("BOT_AVATAR_FILE=%s not found; avatar not set", path)
        return
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    marker = settings.db_path.parent / ".avatar.sha256"
    try:
        if marker.read_text().strip() == digest:
            return
    except OSError:
        pass
    try:
        await bot.set_my_profile_photo(photo=InputProfilePhotoStatic(photo=FSInputFile(path)))
    except Exception as exc:
        log.warning("could not set bot avatar: %s", exc)
        return
    try:
        marker.write_text(digest)
    except OSError:
        pass
    log.info("bot avatar updated from %s", path)


def load_settings():
    from .config import Settings

    try:
        return Settings()
    except ValidationError as exc:
        missing = [".".join(map(str, e["loc"])).upper() for e in exc.errors()]
        if "BOT_TOKEN" in missing:
            print("XATO: BOT_TOKEN o'rnatilmagan yoki noto'g'ri. .env faylida BOT_TOKEN=... ni ko'rsating "
                  "(@BotFather'dan oling).\nERROR: BOT_TOKEN is missing or invalid. Set it in the environment or .env.",
                  file=sys.stderr)
        else:
            msg = "; ".join(f"{'.'.join(map(str, e['loc'])).upper() or 'SETTINGS'}: {e['msg']}" for e in exc.errors())
            print(f"XATO: sozlamalar noto'g'ri / invalid settings: {_TOKEN_PATTERN.sub('***', msg)}", file=sys.stderr)
        return None


async def run(settings) -> None:
    from aiogram import Bot, Dispatcher
    from aiogram.client.default import DefaultBotProperties
    from aiogram.client.session.aiohttp import AiohttpSession
    from aiogram.client.telegram import TelegramAPIServer
    from aiogram.enums import ParseMode
    from aiogram.types import BotCommand, BotCommandScopeChat, MenuButtonWebApp, WebAppInfo
    from aiohttp import web

    from . import texts
    from .downloader import Downloader
    from .access import Access
    from .handlers import setup_dispatcher
    from .jobs import JobManager
    from .pipeline import Pipeline
    from .ratelimit import RateLimiter
    from .sender import Sender
    from .storage import Storage
    from .webapp_api import ApiDeps, create_app

    token = settings.bot_token.get_secret_value()
    session = AiohttpSession(
        api=TelegramAPIServer.from_base(settings.telegram_api_base, is_local=True)
    ) if settings.telegram_api_base else AiohttpSession()
    bot = Bot(token=token, session=session, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

    settings.download_dir.mkdir(parents=True, exist_ok=True)
    storage = await Storage(settings.db_path).open()
    await storage.purge_tokens()
    downloader = Downloader(
        max_upload_bytes=settings.max_upload_bytes,
        max_duration_sec=settings.max_duration_sec,
        cookies_file=settings.cookies_file,
        max_workers=settings.max_concurrent_downloads + 1,
        probe_workers=2,
        scratch_dir=settings.download_dir,
    )
    if settings.cookies_file and not settings.cookies_file.is_file():
        log.warning("COOKIES_FILE=%s does not exist; continuing without cookies", settings.cookies_file)
    sender = Sender(bot)
    pipeline = Pipeline(downloader=downloader, sender=sender, storage=storage,
                        max_upload_bytes=settings.max_upload_bytes,
                        transcode_non_h264=settings.transcode_non_h264, limits=settings.limits)
    jobs = JobManager(runner=pipeline, download_dir=settings.download_dir,
                      max_concurrent=settings.max_concurrent_downloads,
                      hourly_limit=settings.user_hourly_limit, storage=storage, limits=settings.limits)
    stale = jobs.wipe_download_dir()
    if stale:
        log.info("removed %d stale item(s) from %s", stale, settings.download_dir)
    probe_limiter = RateLimiter(60, 600)  # shared by the Mini App API and the bot preview
    access = Access(settings, storage)

    app = create_app(ApiDeps(
        bot_token=token, storage=storage, downloader=downloader, jobs=jobs, webapp_dir=settings.webapp_dir,
        max_upload_mb=settings.max_upload_mb, max_duration_min=settings.max_duration_min,
        hourly_limit=settings.user_hourly_limit, dev_mode=settings.dev_mode,
        probe_limiter=probe_limiter, init_data_max_age=int(settings.init_data_max_age_hours * 3600),
        access=access,
    ))
    mode = await access.mode()
    if not access.owners:
        log.warning("ADMIN_IDS is empty: no bot owner. Send /id to the bot, put ADMIN_IDS=<id> into the "
                    "settings and restart to get /mode, /users, /stats.")
    log.info("access mode: %s, owners: %d", mode, len(access.owners))
    runner = web.AppRunner(app, access_log=None, handle_signals=False)
    await runner.setup()
    site = web.TCPSite(runner, settings.web_host, settings.web_port)

    dp = Dispatcher(settings=settings, db=storage, downloader=downloader, jobs=jobs, probe_limiter=probe_limiter,
                    access=access)
    setup_dispatcher(dp)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError, RuntimeError):
            loop.add_signal_handler(sig, stop.set)

    try:
        await site.start()
        log.info("web server on http://%s:%s (webapp dir: %s)", settings.web_host, settings.web_port,
                 settings.webapp_dir)
        if settings.dev_mode:
            log.warning("DEV_MODE=true: /api/* accepts requests WITHOUT Telegram initData (dev user id=1). "
                        "Never enable in production!")
        me = await wait_for_telegram(bot, stop)
        if me is not None:
            log.info("bot @%s started", me.username)
            try:
                await bot.set_my_commands([BotCommand(command=c, description=d) for c, d in texts.COMMANDS.items()])
                owner_cmds = [BotCommand(command=c, description=d)
                              for c, d in {**texts.COMMANDS, **texts.OWNER_COMMANDS}.items()]
                for owner in access.owners:  # owners also see /mode, /users, /stats in their menu
                    with contextlib.suppress(Exception):
                        await bot.set_my_commands(owner_cmds, scope=BotCommandScopeChat(chat_id=owner))
                await bot.set_my_description(description=texts.BOT_DESCRIPTION)
                await bot.set_my_short_description(short_description=texts.BOT_SHORT_DESCRIPTION)
                await ensure_avatar(bot, settings)
                if settings.webapp_enabled:
                    await bot.set_chat_menu_button(menu_button=MenuButtonWebApp(
                        text=texts.MENU_BUTTON, web_app=WebAppInfo(url=settings.webapp_url)))
                elif settings.webapp_url:
                    log.warning("WEBAPP_URL must be https:// for Telegram Mini Apps; menu button not set")
            except Exception as exc:
                log.warning("bot setup call failed: %s", exc)
            polling = asyncio.create_task(dp.start_polling(
                bot, allowed_updates=dp.resolve_used_update_types(), handle_signals=False, close_bot_session=False))
            stopper = asyncio.create_task(stop.wait())
            done, _ = await asyncio.wait({polling, stopper}, return_when=asyncio.FIRST_COMPLETED)
            if stopper in done:
                with contextlib.suppress(RuntimeError):
                    await dp.stop_polling()
                try:
                    await asyncio.wait_for(polling, 10)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    polling.cancel()
            else:
                stopper.cancel()
                polling.result()  # re-raise unexpected polling errors
    finally:
        log.info("shutting down...")
        await jobs.shutdown()
        await runner.cleanup()
        downloader.close()
        await storage.close()
        await bot.session.close()
        log.info("bye")


async def wait_for_telegram(bot, stop: asyncio.Event, max_delay: float = 60.0):
    """get_me() with exponential backoff; returns None if shutdown was requested first."""
    delay = 2.0
    while not stop.is_set():
        try:
            return await bot.get_me()
        except Exception as exc:  # network errors, Telegram outages
            log.warning("Telegram API unreachable (%s); retrying in %.0fs", exc, delay)
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(stop.wait(), delay)
        delay = min(delay * 2, max_delay)
    return None


def main() -> int:
    setup_logging("INFO")
    settings = load_settings()
    if settings is None:
        return 2
    setup_logging(settings.log_level, [settings.bot_token.get_secret_value()])
    try:
        asyncio.run(run(settings))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
