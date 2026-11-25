"""yt-dlp wrapper (Python API only, never a shell).

* ``probe()``  -> :class:`MediaInfo` (same fields as the API ``Media`` object), cached 10 min.
* ``download()`` -> downloaded file paths for one format; runs in a thread executor and
  reports progress through a thread-safe callback.

All format decisions are pure functions so they can be unit-tested without network.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import urlsplit

from . import texts
from .errors import AppError, SizeExceeded
from .platforms import Link, reclassify_as_short

log = logging.getLogger(__name__)

FORMAT_IDS = ("auto", "1080", "720", "480", "360", "audio")
VIDEO_TIERS = (1080, 720, 480, 360)
AUDIO_BITRATE_KBPS = 192
PROBE_CACHE_TTL = 600
PROBE_CACHE_MAX = 512
NEG_CACHE_TTL = 60  # failed probes (not found / private / too long ...)
NEG_CACHE_TTL_INTERNAL = 15  # possibly transient failures
SIZE_ABORT_FACTOR = 1.1  # progress-hook guard for streams without Content-Length (HLS/DASH)
# MP3 is extracted from the source stream (for Instagram reels: the whole video file), so the
# source may legitimately be larger than the upload limit; the final MP3 size is checked later.
AUDIO_SOURCE_FACTOR = 4
ALLOWED_EXTRACTORS = ["youtube", "instagram"]  # exact extractor names (regex fullmatch in yt-dlp)
MAX_CAROUSEL_ITEMS = 10

MEDIA_EXTS = {
    "video": {"mp4", "mkv", "webm", "mov", "m4v"},
    "photo": {"jpg", "jpeg", "png", "webp", "heic"},
    "audio": {"mp3", "m4a", "opus", "ogg", "aac"},
}

ProgressCallback = Callable[[float], None]


# --------------------------------------------------------------------------- data
@dataclass(slots=True)
class FormatOption:
    id: str
    label: str
    height: int | None
    size: int | None
    fits: bool

    def to_api(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class MediaInfo:
    platform: str
    kind: str
    section: str
    id: str
    url: str
    title: str
    author: str | None
    thumbnail: str | None
    duration: int | None
    width: int | None
    height: int | None
    orientation: str
    items_count: int = 1
    formats: list[FormatOption] = field(default_factory=list)
    is_live: bool = False
    # Internal (not in the API): size estimates per tier for every section, used for downgrade planning.
    tiers: list[FormatOption] = field(default_factory=list)
    is_photo: bool = False

    def to_api(self) -> dict[str, Any]:
        return {
            "platform": self.platform,
            "kind": self.kind,
            "section": self.section,
            "id": self.id,
            "url": self.url,
            "title": self.title,
            "author": self.author,
            "thumbnail": self.thumbnail,
            "duration": self.duration,
            "width": self.width,
            "height": self.height,
            "orientation": self.orientation,
            "items_count": self.items_count,
            "formats": [f.to_api() for f in self.formats],
        }

    def format(self, fmt_id: str) -> FormatOption | None:
        return next((f for f in self.formats if f.id == fmt_id), None)

    @property
    def link(self) -> Link:
        return Link(self.platform, self.kind, self.id, self.url, self.section)


@dataclass(slots=True)
class DownloadResult:
    files: list[Path]
    format: str
    title: str | None = None
    author: str | None = None
    duration: float | None = None


# --------------------------------------------------------------------------- format logic (pure)
def format_sort_for(fmt: str) -> list[str] | None:
    """yt-dlp ``format_sort``. ``res`` is the *smallest* dimension so 9:16 and 16:9 behave alike."""
    if fmt == "audio":
        return None
    if fmt == "auto":
        n = 1080
    elif fmt in ("1080", "720", "480", "360"):
        n = int(fmt)
    else:
        raise ValueError(f"unknown format {fmt!r}")
    return [f"res:{n}", "vcodec:h264", "acodec:m4a", "ext:mp4"]


def downgrade_chain(fmt: str) -> list[str]:
    """Formats to try, in order, when the result exceeds the upload limit."""
    if fmt == "audio":
        return ["audio"]
    start = 1080 if fmt == "auto" else int(fmt)
    lower = [str(t) for t in VIDEO_TIERS if t < start]
    return [fmt, *lower]


def plan_attempts(fmt: str, media: MediaInfo | None) -> list[str]:
    """Downgrade chain minus tiers that are *known* (estimated) not to fit. Never empty."""
    chain = downgrade_chain(fmt)
    if media is None or media.items_count > 1 or media.is_photo:
        return chain[:1] if media is not None and media.is_photo else chain
    tiers = {t.id: t for t in (media.tiers or [f for f in media.formats if f.id not in ("auto", "audio")])}
    top = max(tiers.values(), key=lambda t: int(t.id), default=None)  # what res:1080 ("auto") picks
    kept: list[str] = []
    for f in chain:
        if f == "audio":
            opt = media.format("audio")
        elif f == "auto":
            opt = top
        else:
            opt = tiers.get(f)
        if opt is not None and opt.size is not None and not opt.fits:
            continue
        kept.append(f)
    return kept or [chain[-1]]


def tier_label(fmt: str, height: int | None, width: int | None) -> str:
    """The quality actually delivered, e.g. ``auto`` that produced a 1080x1920 file -> ``"1080"``."""
    # Always derive the label from the real file: an explicit "480" on a source without a 480 tier
    # may deliver 360p, and that is what the user must be told.
    if fmt == "audio" or not height or not width:
        return fmt
    res = min(width, height)
    for t in sorted(VIDEO_TIERS):
        if res <= t * 1.05:
            return str(t) if res >= t * 0.9 else str(res)
    return str(res)


def _is_storyboard(f: dict) -> bool:
    return f.get("ext") == "mhtml" or "storyboard" in str(f.get("format_note") or "").lower()


def _has_video(f: dict) -> bool:
    if _is_storyboard(f):
        return False
    vc = f.get("vcodec")
    if vc == "none":
        return False
    return vc is not None or bool(f.get("height") or f.get("width"))


def _has_audio(f: dict) -> bool:
    ac = f.get("acodec")
    return ac not in (None, "none")


def _maybe_audio(f: dict) -> bool:
    """acodec None/unknown (common for Instagram progressive mp4) counts as "audio may be present"."""
    if _is_storyboard(f):
        return False
    ac = f.get("acodec")
    return ac != "none" and (ac is not None or _has_video(f))


def _res(f: dict) -> int | None:
    w, h = f.get("width"), f.get("height")
    if w and h:
        return min(int(w), int(h))
    return int(h) if h else None


def _is_h264(f: dict) -> bool:
    return str(f.get("vcodec") or "").lower().startswith(("avc", "h264"))


def _size(f: dict, duration: float | None) -> int | None:
    s = f.get("filesize") or f.get("filesize_approx")
    if s:
        return int(s)
    tbr = f.get("tbr")
    if tbr and duration:
        return int(float(tbr) * 125 * float(duration))
    return None


def select_video(formats: Iterable[dict], n: int) -> dict | None:
    """Emulate ``format_sort=['res:N','vcodec:h264',...]``: largest res <= N (h264 preferred),
    falling back to the smallest res above N."""
    vids = [f for f in formats if _has_video(f) and _res(f)]
    if not vids:
        return None
    below = [f for f in vids if _res(f) <= n]
    key = lambda f: (_res(f), _is_h264(f), f.get("ext") == "mp4", f.get("tbr") or 0)  # noqa: E731
    if below:
        return max(below, key=key)
    smallest = min(_res(f) for f in vids)
    return max((f for f in vids if _res(f) == smallest), key=key)


def select_audio(formats: Iterable[dict]) -> dict | None:
    auds = [f for f in formats if _has_audio(f) and not _has_video(f) and not _is_storyboard(f)]
    if not auds:
        return None
    is_m4a = lambda f: f.get("ext") == "m4a" or str(f.get("acodec") or "").startswith("mp4a")  # noqa: E731
    return max(auds, key=lambda f: (is_m4a(f), f.get("abr") or f.get("tbr") or 0))


def estimate_size(formats: list[dict], n: int, duration: float | None) -> tuple[int | None, int | None]:
    """(estimated bytes, chosen smallest-dimension) for tier ``n``."""
    v = select_video(formats, n)
    if v is None:
        return None, None
    vs = _size(v, duration)
    if _has_audio(v):
        return vs, _res(v)
    a = select_audio(formats)
    if a is None:
        return vs, _res(v)
    as_ = _size(a, duration)
    if vs is None or as_ is None:
        return None, _res(v)
    return vs + as_, _res(v)


def orientation_of(width: int | None, height: int | None) -> str:
    if not width or not height:
        return "horizontal"
    if abs(width - height) <= 0.02 * max(width, height):
        return "square"
    return "vertical" if height > width else "horizontal"


def compute_tiers(info: dict, max_bytes: int) -> list[FormatOption]:
    """Available quality tiers (high -> low) with size estimates, deduplicated by picked resolution."""
    formats = [f for f in (info.get("formats") or []) if isinstance(f, dict)]
    duration = info.get("duration")
    tiers: list[FormatOption] = []
    seen: set[int] = set()
    for n in sorted(VIDEO_TIERS):  # low -> high, dedupe identical picks
        size, res = estimate_size(formats, n, duration)
        if res is None or res in seen or res > n:
            continue
        seen.add(res)
        tiers.append(FormatOption(str(n), texts.FORMAT_LABELS[str(n)], res, size, size is None or size <= max_bytes))
    tiers.sort(key=lambda o: int(o.id), reverse=True)
    return tiers


def build_formats(info: dict, section: str, max_bytes: int, items_count: int = 1,
                  tiers: list[FormatOption] | None = None, is_photo: bool = False) -> list[FormatOption]:
    if items_count > 1 or is_photo:
        return [FormatOption("auto", texts.FORMAT_LABELS["auto"], None, None, True)]
    formats = [f for f in (info.get("formats") or []) if isinstance(f, dict)]
    duration = info.get("duration")
    if tiers is None:
        tiers = compute_tiers(info, max_bytes) if formats else []
    out: list[FormatOption] = []

    # "auto" = best <=1080 that fits (it auto-downgrades): report the first tier that fits.
    has_video = bool(tiers) or not formats
    if has_video:
        if tiers:
            first_fit = next((t for t in tiers if t.fits), None)
            pick = first_fit or tiers[-1]
            out.append(FormatOption("auto", texts.FORMAT_LABELS["auto"], pick.height, pick.size, first_fit is not None))
        else:
            size = info.get("filesize") or info.get("filesize_approx")
            out.append(FormatOption("auto", texts.FORMAT_LABELS["auto"], info.get("height"), size,
                                    size is None or size <= max_bytes))
    if section == "videos":
        out.extend(tiers)

    if (not formats) or any(_maybe_audio(f) for f in formats):
        a_size = int(AUDIO_BITRATE_KBPS * 125 * duration) if duration else None
        out.append(FormatOption("audio", texts.FORMAT_LABELS["audio"], None, a_size, a_size is None or a_size <= max_bytes))
    return out


def _thumbnail(info: dict) -> str | None:
    cand = info.get("thumbnail")
    if isinstance(cand, str) and cand.startswith("https://"):
        return cand
    thumbs = [t for t in (info.get("thumbnails") or []) if isinstance(t, dict)]
    for t in reversed(thumbs):  # yt-dlp orders worst -> best
        url = t.get("url")
        if isinstance(url, str) and url.startswith("https://"):
            return url
    return None


def _entries(info: dict) -> list[dict]:
    return [e for e in (info.get("entries") or []) if isinstance(e, dict)][:MAX_CAROUSEL_ITEMS]


def is_live_info(info: dict) -> bool:
    return bool(info.get("is_live")) or info.get("live_status") in ("is_live", "is_upcoming", "post_live")


def _image_dims(entry: dict) -> tuple[int | None, int | None]:
    thumbs = [t for t in (entry.get("thumbnails") or []) if isinstance(t, dict) and t.get("width") and t.get("height")]
    if not thumbs:
        return None, None
    best = max(thumbs, key=lambda t: int(t["width"]) * int(t["height"]))
    return int(best["width"]), int(best["height"])


def media_from_info(link: Link, info: dict, max_bytes: int) -> MediaInfo:
    entries = _entries(info) if info.get("_type") in ("playlist", "multi_video") else []
    items_count = max(1, len(entries)) if entries else 1
    main = entries[0] if entries else info
    main_is_photo = link.platform == "instagram" and entry_is_image(main)  # photos exist only on Instagram
    is_photo = not entries and main_is_photo

    width, height = main.get("width"), main.get("height")
    if main_is_photo and not (width and height):
        width, height = _image_dims(main)
    duration = None if main_is_photo else (info.get("duration") if not entries else main.get("duration"))
    dur_int = int(round(duration)) if isinstance(duration, (int, float)) else None
    link = reclassify_as_short(link, width, height, duration)

    title = (info.get("title") or main.get("title") or info.get("description") or texts.DEFAULT_TITLE).strip()
    title = " ".join(title.split())[:200] or texts.DEFAULT_TITLE
    author = info.get("uploader") or info.get("channel") or info.get("uploader_id") or main.get("uploader")

    src = info if entries else main
    tiers = compute_tiers(main, max_bytes) if not entries and not is_photo else []
    return MediaInfo(
        platform=link.platform,
        kind=link.kind,
        section=link.section,
        id=link.id,
        url=link.canonical_url,
        title=title,
        author=str(author)[:100] if author else None,
        thumbnail=_thumbnail(main) or _thumbnail(info),
        duration=dur_int,
        width=int(width) if width else None,
        height=int(height) if height else None,
        orientation=orientation_of(width, height),
        items_count=items_count,
        formats=build_formats(src, link.section, max_bytes, items_count, tiers=tiers, is_photo=is_photo),
        is_live=is_live_info(info),
        tiers=tiers,
        is_photo=is_photo,
    )


def map_ytdlp_error(exc: BaseException) -> AppError:
    if isinstance(exc, AppError):
        return exc
    msg = str(exc).lower()
    if "unsupported url" in msg:
        return AppError("unsupported")
    if "max-filesize" in msg or "larger than max" in msg:
        return AppError("too_large")
    if "is live" in msg or "live event" in msg or "premieres in" in msg:
        return AppError("unsupported", texts.LIVE_NOT_SUPPORTED)
    if ("not a bot" in msg or ("sign in to confirm you" in msg and "your age" not in msg)
            or "too many requests" in msg or "http error 429" in msg):
        return AppError("rate_limited", texts.YT_BLOCKED)
    if any(k in msg for k in ("private", "login required", "log in", "login", "sign in to confirm your age",
                              "members-only", "join this channel", "restricted")):
        return AppError("private")
    if any(k in msg for k in ("video unavailable", "not available", "does not exist", "404", "has been removed",
                              "no video formats", "there is no video", "not found", "deleted")):
        return AppError("not_found")
    return AppError("internal")


def build_ydl_opts(
    *,
    fmt: str | None,
    workdir: Path | None,
    cookies_file: Path | None = None,
    max_filesize: int | None = None,
    socket_timeout: int = 30,
    retries: int = 3,
    progress_hook: Callable[[dict], None] | None = None,
    logger: Any = None,
) -> dict[str, Any]:
    """Build a *safe* yt-dlp options dict. No exec / external downloader / custom commands."""
    opts: dict[str, Any] = {
        "noplaylist": True,
        "ignoreconfig": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "restrictfilenames": True,
        "cachedir": False,
        "socket_timeout": socket_timeout,
        "retries": retries,
        "fragment_retries": retries,
        "playlist_items": f"1-{MAX_CAROUSEL_ITEMS}",
        "writethumbnail": False,
        "writesubtitles": False,
        "overwrites": True,
        "logger": logger,
        "allowed_extractors": list(ALLOWED_EXTRACTORS),
    }
    if cookies_file:
        opts["cookiefile"] = str(cookies_file)
    if max_filesize:
        opts["max_filesize"] = int(max_filesize)
    if workdir is not None:
        opts["paths"] = {"home": str(workdir), "temp": str(workdir)}
        opts["outtmpl"] = {"default": str(workdir / "%(autonumber)02d_%(id).40s.%(ext)s")}
    if progress_hook is not None:
        opts["progress_hooks"] = [progress_hook]
    if fmt is not None:
        if fmt == "audio":
            opts["format"] = "ba/b"
            opts["postprocessors"] = [
                {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": str(AUDIO_BITRATE_KBPS)}
            ]
        else:
            opts["format"] = "bv*+ba/b"
            opts["format_sort"] = format_sort_for(fmt)
            opts["merge_output_format"] = "mp4"
    return opts


class _YDLLogger:
    """Routes yt-dlp messages to logging and remembers max-filesize skips."""

    def __init__(self) -> None:
        self.size_skipped = False

    def _check(self, msg: str) -> None:
        if "max-filesize" in msg or "larger than max" in msg.lower():
            self.size_skipped = True

    def debug(self, msg: str) -> None:
        self._check(msg)
        log.debug("yt-dlp: %s", msg)

    def info(self, msg: str) -> None:
        self._check(msg)
        log.debug("yt-dlp: %s", msg)

    def warning(self, msg: str) -> None:
        self._check(msg)
        log.info("yt-dlp warning: %s", msg)

    def error(self, msg: str) -> None:
        log.info("yt-dlp error: %s", msg)


def _default_factory(opts: dict[str, Any]) -> Any:
    import yt_dlp  # imported lazily so tests can run without touching it

    return yt_dlp.YoutubeDL(opts)


try:  # yt-dlp lets DownloadCancelled raised from progress hooks propagate cleanly
    from yt_dlp.utils import DownloadCancelled as _YDLCancelled
except Exception:  # pragma: no cover - yt-dlp is a hard dependency
    class _YDLCancelled(Exception):  # type: ignore[no-redef]
        pass


class Cancelled(_YDLCancelled):
    """Job was cancelled / timed out."""


class SizeAbort(_YDLCancelled):
    """Progress hook saw the download grow past the upload limit (no Content-Length streams)."""


def collect_files(info: dict | None, workdir: Path, scan_fallback: bool = True) -> list[Path]:
    """Final files produced by yt-dlp, in playlist order."""
    found: list[Path] = []
    infos = [info] if info else []
    if info and info.get("_type") in ("playlist", "multi_video"):
        infos = [e for e in (info.get("entries") or []) if isinstance(e, dict)]
    for i in infos:
        for rd in i.get("requested_downloads") or []:
            fp = rd.get("filepath") or rd.get("_filename")
            if fp:
                p = Path(fp)
                if p.is_file() and p not in found:
                    found.append(p)
        fp = i.get("filepath")
        if fp and Path(fp).is_file() and Path(fp) not in found:
            found.append(Path(fp))
    if not found and scan_fallback:
        all_exts = set().union(*MEDIA_EXTS.values())
        for p in sorted(workdir.glob("*")):
            name = p.name
            if not p.is_file() or name.endswith((".part", ".ytdl", ".temp")) or ".part-" in name:
                continue
            parts = name.split(".")
            if len(parts) > 2 and parts[-2].startswith("f") and parts[-2][1:].isdigit():
                continue  # unmerged fragment like x.f137.mp4
            if p.suffix.lower().lstrip(".") in all_exts:
                found.append(p)
    resolved_root = workdir.resolve()
    return [p for p in found if resolved_root in p.resolve().parents]


# Carousel photos are fetched (through yt-dlp's own HTTP client) only from Instagram's CDN.
IMAGE_HOST_SUFFIXES = (".cdninstagram.com", ".fbcdn.net")
IMAGE_MAX_BYTES = 10 * 1024 * 1024
_IMAGE_EXT = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/heic": "heic"}


def entry_is_image(entry: dict) -> bool:
    if entry.get("_type") in ("url", "url_transparent") or entry.get("url"):
        return False
    return not any(_has_video(f) or _has_audio(f) for f in (entry.get("formats") or []) if isinstance(f, dict))


def best_image_url(entry: dict) -> str | None:
    thumbs = [t for t in (entry.get("thumbnails") or []) if isinstance(t, dict) and t.get("url")]
    if not thumbs and entry.get("thumbnail"):
        thumbs = [{"url": entry["thumbnail"]}]
    thumbs.sort(key=lambda t: (t.get("width") or 0) * (t.get("height") or 0))
    for t in reversed(thumbs):
        url = str(t["url"])
        try:
            parts = urlsplit(url)
        except ValueError:
            continue
        host = (parts.hostname or "").lower()
        if parts.scheme == "https" and not parts.port and "@" not in parts.netloc \
                and host.endswith(IMAGE_HOST_SUFFIXES):
            return url
    return None


class Downloader:
    def __init__(
        self,
        *,
        max_upload_bytes: int,
        max_duration_sec: int,
        cookies_file: Path | None = None,
        ydl_factory: Callable[[dict[str, Any]], Any] | None = None,
        max_workers: int = 4,
        probe_workers: int = 2,
        probe_timeout: float = 90.0,
        probe_queue_timeout: float = 20.0,
        download_timeout: float = 3600.0,
        scratch_dir: Path | None = None,
        min_free_bytes: int | None = None,
    ) -> None:
        self.max_upload_bytes = max_upload_bytes
        self.max_duration_sec = max_duration_sec
        self.cookies_file = Path(cookies_file) if cookies_file else None
        self._factory = ydl_factory or _default_factory
        # Separate, bounded pools: slow/abusive probes can never starve running downloads.
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="ytdlp-dl")
        self._probe_pool = ThreadPoolExecutor(max_workers=probe_workers, thread_name_prefix="ytdlp-probe")
        self._probe_sem = asyncio.Semaphore(probe_workers)
        self._cache: OrderedDict[str, tuple[float, MediaInfo]] = OrderedDict()
        self._neg: OrderedDict[str, tuple[float, AppError]] = OrderedDict()
        self._inflight: dict[str, asyncio.Future] = {}
        self.probe_timeout = probe_timeout
        self.probe_queue_timeout = probe_queue_timeout
        self.download_timeout = download_timeout
        self.scratch_dir = Path(scratch_dir) if scratch_dir else None
        # download + merge + ffmpeg output can briefly need ~2x the file size
        self.min_free_bytes = min_free_bytes if min_free_bytes is not None else 2 * max_upload_bytes + 64 * 1024 * 1024
        self._cookie_warned = False

    def close(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
        self._probe_pool.shutdown(wait=False, cancel_futures=True)

    # -- cookies ------------------------------------------------------------
    def _cookie_copy(self, dest_dir: Path) -> Path | None:
        """Private, writable copy of COOKIES_FILE for one YoutubeDL instance.

        yt-dlp rewrites its cookie file on close; the original (possibly read-only, shared
        by concurrent jobs) is therefore never handed to yt-dlp.
        """
        if self.cookies_file is None:
            return None
        try:
            data = self.cookies_file.read_bytes()
        except OSError as exc:
            if not self._cookie_warned:
                log.warning("COOKIES_FILE is not readable (%s); continuing without cookies", exc.strerror)
                self._cookie_warned = True
            return None
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / ".cookies.txt"
        fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        return dest

    # -- checks -------------------------------------------------------------
    def _validate(self, info: dict) -> None:
        if is_live_info(info):
            raise AppError("unsupported", texts.LIVE_NOT_SUPPORTED)
        duration = info.get("duration")
        if isinstance(duration, (int, float)) and duration > self.max_duration_sec:
            raise AppError("too_long", max_duration_min=self.max_duration_sec // 60)

    # -- probe caches ---------------------------------------------------------
    def _cache_get(self, key: str) -> MediaInfo | None:
        item = self._cache.get(key)
        if not item:
            return None
        if item[0] < time.monotonic():
            self._cache.pop(key, None)
            return None
        return item[1]

    def _cache_put(self, key: str, media: MediaInfo) -> None:
        self._cache[key] = (time.monotonic() + PROBE_CACHE_TTL, media)
        self._cache.move_to_end(key)
        while len(self._cache) > PROBE_CACHE_MAX:
            self._cache.popitem(last=False)

    def _neg_get(self, key: str) -> AppError | None:
        item = self._neg.get(key)
        if not item:
            return None
        if item[0] < time.monotonic():
            self._neg.pop(key, None)
            return None
        return item[1]

    def _neg_put(self, key: str, err: AppError) -> None:
        ttl = NEG_CACHE_TTL_INTERNAL if err.code == "internal" else NEG_CACHE_TTL
        self._neg[key] = (time.monotonic() + ttl, err)
        self._neg.move_to_end(key)
        while len(self._neg) > PROBE_CACHE_MAX:
            self._neg.popitem(last=False)

    # -- probe ------------------------------------------------------------------
    def _probe_sync(self, url: str) -> dict:
        tmp = Path(tempfile.mkdtemp(prefix="probe-", dir=self.scratch_dir)) if self.cookies_file else None
        try:
            opts = build_ydl_opts(fmt=None, workdir=None, cookies_file=self._cookie_copy(tmp) if tmp else None,
                                  logger=_YDLLogger())
            opts["skip_download"] = True
            if "instagram.com" in url:
                # photo posts / photo carousel items have no formats. Not for YouTube: there it would
                # swallow real errors such as the "confirm you're not a bot" check.
                opts["ignore_no_formats_error"] = True
            with self._factory(opts) as ydl:
                info = ydl.extract_info(url, download=False)
        finally:
            if tmp is not None:
                shutil.rmtree(tmp, ignore_errors=True)
        if not isinstance(info, dict):
            raise AppError("not_found")
        return info

    async def _probe_uncached(self, link: Link) -> MediaInfo:
        url = link.canonical_url
        loop = asyncio.get_running_loop()
        try:
            try:
                await asyncio.wait_for(self._probe_sem.acquire(), self.probe_queue_timeout)
            except asyncio.TimeoutError:
                raise AppError("rate_limited", texts.SERVER_BUSY) from None  # not negative-cached
            try:
                info = await asyncio.wait_for(loop.run_in_executor(self._probe_pool, self._probe_sync, url),
                                              self.probe_timeout)
            finally:
                self._probe_sem.release()
            self._validate(info)
            media = media_from_info(link, info, self.max_upload_bytes)
            if link.platform == "youtube" and not media.tiers:
                # yt-dlp may leave only storyboard images: missing JS runtime (deno) or a server-side block
                log.warning("probe of %s returned no video formats (is deno + yt-dlp[default] installed?)",
                            link.media_key)
                raise AppError("rate_limited", texts.YT_BLOCKED)
        except AppError as exc:
            if exc.code != "rate_limited":
                self._neg_put(url, exc)
            raise
        except asyncio.TimeoutError:
            err = AppError("internal")
            self._neg_put(url, err)
            raise err from None
        except Exception as exc:  # yt-dlp DownloadError / ExtractorError / network
            log.info("probe failed for %s: %s", link.media_key, exc)
            err = map_ytdlp_error(exc)
            self._neg_put(url, err)
            raise err from None
        self._cache_put(url, media)
        return media

    async def probe(self, link: Link) -> MediaInfo:
        url = link.canonical_url
        cached = self._cache_get(url)
        if cached is not None:
            return cached
        neg = self._neg_get(url)
        if neg is not None:
            raise AppError(neg.code, neg.message, status=neg.status)
        fut = self._inflight.get(url)
        if fut is None:  # coalesce concurrent probes of the same URL
            fut = asyncio.ensure_future(self._probe_uncached(link))
            self._inflight[url] = fut
            fut.add_done_callback(lambda f, u=url: (self._inflight.pop(u, None),
                                                   f.cancelled() or f.exception()))
        return await asyncio.shield(fut)

    # -- download -----------------------------------------------------------
    def _source_limit(self, fmt: str) -> int:
        factor = AUDIO_SOURCE_FACTOR if fmt == "audio" else 1
        return self.max_upload_bytes * factor

    def _make_hook(self, on_progress: ProgressCallback | None, cancel: threading.Event, state: dict,
                   limit: int | None = None) -> Callable:
        hard_limit = (limit or self.max_upload_bytes) * SIZE_ABORT_FACTOR

        def hook(d: dict) -> None:
            if cancel.is_set():
                raise Cancelled()
            status = d.get("status")
            if status not in ("downloading", "finished"):
                return
            info_d = d.get("info_dict") or {}
            item = state.get("item", 0)
            fn = str(d.get("filename") or "")
            sizes: dict[str, int] = state.setdefault("sizes", {}).setdefault(item, {})
            downloaded = int(d.get("downloaded_bytes") or d.get("total_bytes") or 0)
            sizes[fn] = downloaded
            so_far = sum(sizes.values())
            exact = d.get("total_bytes")
            est = exact or d.get("total_bytes_estimate")
            if so_far > hard_limit:
                raise SizeAbort()
            if status == "downloading" and est and (exact or downloaded >= 0.1 * est) \
                    and so_far - downloaded + est > hard_limit:
                raise SizeAbort()
            if on_progress is None:
                return
            # parts = real number of requested formats (1 for progressive/audio, 2 for video+audio)
            req = info_d.get("requested_formats") or []
            ids = [r.get("format_id") for r in req if isinstance(r, dict)]
            n_parts = len(ids) or 1
            idx = ids.index(info_d.get("format_id")) if info_d.get("format_id") in ids else min(len(sizes) - 1, n_parts - 1)
            frac = 1.0 if status == "finished" else ((downloaded / est) if est else 0.0)
            part = (max(0, idx) + min(max(frac, 0.0), 1.0)) / n_parts
            n_items = max(1, state.get("items", 1))
            overall = min(1.0, (item + part) / n_items)
            if overall >= state.get("last", 0.0):
                state["last"] = overall
                on_progress(overall)

        return hook

    def _download_sync(
        self, url: str, fmt: str, workdir: Path, on_progress: ProgressCallback | None, cancel: threading.Event
    ) -> DownloadResult:
        ylog = _YDLLogger()
        state: dict[str, Any] = {}
        opts = build_ydl_opts(
            fmt=fmt,
            workdir=workdir,
            cookies_file=self._cookie_copy(workdir),
            max_filesize=self._source_limit(fmt),
            progress_hook=self._make_hook(on_progress, cancel, state, self._source_limit(fmt)),
            logger=ylog,
        )
        try:
            with self._factory(opts) as ydl:
                raw = ydl.extract_info(url, download=False, process=False)
                if not isinstance(raw, dict):
                    raise AppError("not_found")
                self._validate(raw)
                if raw.get("_type") in ("playlist", "multi_video"):
                    info = raw
                    files = self._download_entries(ydl, raw, fmt, workdir, state, cancel)
                elif url.startswith("https://www.instagram.com/") and entry_is_image(raw):  # single-photo post
                    info = raw
                    img = self._fetch_image(ydl, raw, workdir, 0) if fmt != "audio" else None
                    files = [img] if img else []
                else:
                    info = ydl.process_ie_result(raw, download=True)
                    files = collect_files(info if isinstance(info, dict) else None, workdir)
        except SizeAbort:
            raise SizeExceeded(max_upload_mb=self.max_upload_bytes // (1024 * 1024)) from None
        if not files:
            if ylog.size_skipped or state.get("size_skipped"):
                raise SizeExceeded(max_upload_mb=self.max_upload_bytes // (1024 * 1024))
            raise AppError("not_found")
        src = info if isinstance(info, dict) else raw
        return DownloadResult(
            files=files,
            format=fmt,
            title=src.get("title"),
            author=src.get("uploader") or src.get("channel"),
            duration=src.get("duration"),
        )

    def _download_entries(self, ydl: Any, raw: dict, fmt: str, workdir: Path, state: dict,
                          cancel: threading.Event) -> list[Path]:
        """Instagram carousel: videos via yt-dlp, photos via ydl.urlopen; order preserved."""
        files: list[Path] = []
        entries = [e for e in list(raw.get("entries") or [])[:MAX_CAROUSEL_ITEMS] if isinstance(e, dict)]
        state["items"] = len(entries)
        inherited = ("extractor", "extractor_key", "webpage_url", "original_url", "webpage_url_basename",
                     "webpage_url_domain")
        for idx, entry in enumerate(entries):
            if cancel.is_set():
                raise Cancelled()
            state["item"] = idx
            for key in inherited:
                if raw.get(key) is not None:
                    entry.setdefault(key, raw[key])
            entry.setdefault("playlist_index", idx + 1)
            entry.setdefault("playlist_id", raw.get("id"))
            entry.setdefault("playlist", raw.get("title") or raw.get("id"))
            if entry_is_image(entry):
                if fmt != "audio":
                    img = self._fetch_image(ydl, entry, workdir, idx)
                    if img is not None:
                        files.append(img)
                continue
            try:
                info = ydl.process_ie_result(entry, download=True)
            except Cancelled:
                raise
            except SizeAbort:
                state["size_skipped"] = True  # this item is too big; keep the others
                continue
            except Exception as exc:  # one broken item must not lose the whole carousel
                log.info("carousel item %s failed: %s", idx, exc)
                continue
            files.extend(p for p in collect_files(info, workdir, scan_fallback=False) if p not in files)
        return files

    def _fetch_image(self, ydl: Any, entry: dict, workdir: Path, idx: int) -> Path | None:
        url = best_image_url(entry)
        if url is None:
            return None
        try:
            resp = ydl.urlopen(url)
            ctype = str(resp.headers.get("Content-Type", "")).split(";")[0].strip().lower()
            data = resp.read(IMAGE_MAX_BYTES + 1)
        except Exception as exc:
            log.info("carousel image %s failed: %s", idx, exc)
            return None
        if not data or len(data) > IMAGE_MAX_BYTES:
            return None
        path = workdir / f"{idx + 1:02d}_image.{_IMAGE_EXT.get(ctype, 'jpg')}"
        path.write_bytes(data)
        return path

    def check_disk(self, path: Path) -> None:
        try:
            free = shutil.disk_usage(path).free
        except OSError:
            return
        if free < self.min_free_bytes:
            log.error("low disk space in %s: %d MB free, need %d MB", path, free >> 20, self.min_free_bytes >> 20)
            raise AppError("internal", texts.NO_DISK_SPACE)

    async def download(
        self, link: Link, fmt: str, workdir: Path, on_progress: ProgressCallback | None = None
    ) -> DownloadResult:
        if fmt not in FORMAT_IDS:
            raise AppError("bad_request")
        workdir.mkdir(parents=True, exist_ok=True)
        self.check_disk(workdir)
        loop = asyncio.get_running_loop()
        cancel = threading.Event()

        def safe_progress(v: float) -> None:
            if on_progress is not None:
                loop.call_soon_threadsafe(on_progress, v)

        fut = loop.run_in_executor(self._pool, self._download_sync, link.canonical_url, fmt, workdir, safe_progress, cancel)
        try:
            return await asyncio.wait_for(asyncio.shield(fut), self.download_timeout)
        except asyncio.TimeoutError:
            cancel.set()
            await asyncio.wait([fut], timeout=30)  # let the worker stop before the caller deletes workdir
            raise AppError("internal") from None
        except asyncio.CancelledError:
            cancel.set()
            await asyncio.wait([fut], timeout=30)
            raise
        except AppError:
            raise
        except Cancelled:
            raise AppError("internal") from None
        except Exception as exc:
            log.info("download failed for %s [%s]: %s", link.media_key, fmt, exc)
            raise map_ytdlp_error(exc) from None
