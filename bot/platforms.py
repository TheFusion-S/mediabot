"""Strict link allowlist and canonical URL building.

User-supplied text is never passed to yt-dlp. We extract an ID from an allowlisted URL
and rebuild a canonical URL from scratch; only that canonical URL is used downstream.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

YOUTUBE_HOSTS = frozenset({"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"})
INSTAGRAM_HOSTS = frozenset({"instagram.com", "www.instagram.com", "m.instagram.com"})
ALLOWED_HOSTS = YOUTUBE_HOSTS | INSTAGRAM_HOSTS

# Always used with .fullmatch(): "$" would also accept a trailing "\n" (e.g. v=ID%0a).
YT_ID_RE = re.compile(r"[A-Za-z0-9_-]{11}")
IG_CODE_RE = re.compile(r"[A-Za-z0-9_-]{5,64}")
IG_USER_RE = re.compile(r"[A-Za-z0-9._]{1,30}")

IG_KINDS = {"reel": "reel", "reels": "reel", "tv": "reel", "p": "post"}

SECTIONS = ("instagram", "shorts", "videos")

MAX_URL_LEN = 2048
_LEADING = "<([{\"'«“‘"
_TRAILING = ">)]}\"'».,!?;:“”’"
_ALLOWED_CHARS_RE = re.compile(r"[\x21-\x7e]+")  # printable ASCII, no spaces (used with fullmatch)


@dataclass(frozen=True, slots=True)
class Link:
    platform: str  # "youtube" | "instagram"
    kind: str  # "reel" | "post" | "short" | "video"
    id: str
    canonical_url: str
    section: str  # "instagram" | "shorts" | "videos"

    @property
    def media_key(self) -> str:
        return f"{self.platform}:{self.id}"


def youtube_link(video_id: str, short: bool) -> Link:
    if short:
        return Link("youtube", "short", video_id, f"https://www.youtube.com/shorts/{video_id}", "shorts")
    return Link("youtube", "video", video_id, f"https://www.youtube.com/watch?v={video_id}", "videos")


def instagram_link(code: str, kind: str) -> Link:
    path = "reel" if kind == "reel" else "p"
    return Link("instagram", kind, code, f"https://www.instagram.com/{path}/{code}/", "instagram")


class _HostOnly(Exception):
    """Host is allowlisted but the path is not a supported media page."""

    def __init__(self, reason: str | None = None):
        super().__init__(reason)
        self.reason = reason


def _candidates(text: str) -> list[str]:
    out: list[str] = []
    for raw in text.split():
        tok = raw.strip(_LEADING).rstrip(_TRAILING)
        if not tok:
            continue
        low = tok.lower()
        if "://" in low:
            if low.startswith(("http://", "https://")):
                out.append(tok)
            continue
        # Scheme-less "youtu.be/ID" style: only when the token *starts* with an allowed host.
        host_part = re.split(r"[/?#]", low, maxsplit=1)[0]
        if host_part in ALLOWED_HOSTS:
            out.append("https://" + tok)
    return out


def _parse(url: str) -> Link | None:
    """Return a Link, None for a rejected URL, or raise _HostOnly."""
    if len(url) > MAX_URL_LEN or not _ALLOWED_CHARS_RE.fullmatch(url) or "\\" in url:
        return None
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https"):
        return None
    netloc = parts.netloc
    # No userinfo, no port, no IPv6 literal, no percent-encoding in host.
    if not netloc or any(c in netloc for c in "@:[]%"):
        return None
    host = netloc.lower()
    if host not in ALLOWED_HOSTS:
        return None

    raw_path = parts.path or "/"
    if "//" in raw_path:
        return None
    segs = [s for s in raw_path.strip("/").split("/")] if raw_path.strip("/") else []

    if host in YOUTUBE_HOSTS:
        return _parse_youtube(host, segs, parts.query)
    return _parse_instagram(segs)


def _parse_youtube(host: str, segs: list[str], query: str) -> Link:
    if host == "youtu.be":
        if len(segs) == 1 and YT_ID_RE.fullmatch(segs[0]):
            return youtube_link(segs[0], short=False)
        raise _HostOnly
    if segs == ["watch"]:
        try:
            vals = parse_qs(query, keep_blank_values=True).get("v", [])
        except ValueError:
            vals = []
        if vals and YT_ID_RE.fullmatch(vals[0]):
            return youtube_link(vals[0], short=False)
        raise _HostOnly
    if len(segs) == 2 and segs[0] in ("shorts", "live", "embed"):
        if YT_ID_RE.fullmatch(segs[1]):
            return youtube_link(segs[1], short=segs[0] == "shorts")
    raise _HostOnly


def _parse_instagram(segs: list[str]) -> Link:
    if segs and segs[0].lower() == "share":
        # /share/reel/<token>/ is an opaque redirect token, not a media code.
        raise _HostOnly("ig_share")
    if len(segs) == 3 and IG_USER_RE.fullmatch(segs[0]) and segs[0].lower() not in IG_KINDS:
        segs = segs[1:]
    if len(segs) == 2 and segs[0].lower() in IG_KINDS and IG_CODE_RE.fullmatch(segs[1]):
        return instagram_link(segs[1], IG_KINDS[segs[0].lower()])
    raise _HostOnly


def analyze_full(text: str | None) -> tuple[Link | None, str | None, str | None]:
    """``(link, None, None)`` for the first supported link, else ``(None, error_code, reason)``.

    error_code is ``"unsupported"`` when an allowlisted host was found with an unsupported
    page (channel, profile, stories, share-token, ...) and ``"invalid_url"`` otherwise.
    ``reason`` is a finer hint (e.g. ``"ig_share"``) or None.
    """
    if not text or not isinstance(text, str):
        return None, "invalid_url", None
    saw_host = False
    reason: str | None = None
    for cand in _candidates(text[:8192]):
        try:
            link = _parse(cand)
        except _HostOnly as exc:
            saw_host = True
            reason = reason or exc.reason
            continue
        if link is not None:
            return link, None, None
    return None, ("unsupported" if saw_host else "invalid_url"), reason


def analyze(text: str | None) -> tuple[Link | None, str | None]:
    link, code, _ = analyze_full(text)
    return link, code


def reject_message(code: str, reason: str | None) -> str | None:
    """Specific Uzbek message for a rejected link, or None for the generic one."""
    from . import texts

    if reason == "ig_share":
        return texts.IG_SHARE_LINK
    return None


def classify(text: str | None) -> Link | None:
    """First supported Instagram/YouTube link in ``text`` or ``None``."""
    return analyze(text)[0]


def reclassify_as_short(link: Link, width: int | None, height: int | None, duration: float | None) -> Link:
    """A /watch link to a vertical clip <= 180s is really a Short."""
    if (
        link.platform == "youtube"
        and link.kind == "video"
        and width
        and height
        and height > width
        and duration is not None
        and duration <= 180
    ):
        return Link("youtube", "short", link.id, link.canonical_url, "shorts")
    return link
