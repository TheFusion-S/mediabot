"""Real yt-dlp (no network): a stub extractor returns formats served from a local HTTP server.

Verifies our option dict against the real YoutubeDL: format_sort picks the right tier by the
*smallest* dimension, video+audio are merged into mp4, progress hooks fire, MP3 extraction works,
and max_filesize makes the downloader report SizeExceeded.
"""

import asyncio
import subprocess
import threading
from functools import partial
from pathlib import Path
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest

from bot import media
from bot.downloader import Downloader
from bot.errors import SizeExceeded
from bot.platforms import classify
from tests.conftest import requires_ffmpeg

pytestmark = requires_ffmpeg
yt_dlp = pytest.importorskip("yt_dlp")


def _gen(args):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True, timeout=60)


@pytest.fixture(scope="module")
def http_media(tmp_path_factory):
    root = tmp_path_factory.mktemp("srv")
    for name, (w, h) in {"v1080.mp4": (1080, 1920), "v720.mp4": (720, 1280), "v360.mp4": (360, 640)}.items():
        _gen(["-f", "lavfi", "-i", f"testsrc=size={w}x{h}:rate=10:duration=1", "-c:v", "libx264",
              "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-an", str(root / name)])
    _gen(["-f", "lavfi", "-i", "sine=duration=1", "-c:a", "aac", str(root / "a.m4a")])

    class Quiet(SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

    class QuietServer(ThreadingHTTPServer):
        def handle_error(self, request, client_address):  # aborted transfers (size-limit test) -> BrokenPipe
            pass

    srv = QuietServer(("127.0.0.1", 0), partial(Quiet, directory=str(root)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    yield root, base
    srv.shutdown()


def stub_factory(base, root, seen_urls):
    def fmt(fid, w, h, name):
        return {"format_id": fid, "url": f"{base}/{name}", "ext": "mp4", "vcodec": "avc1.64001f", "acodec": "none",
                "width": w, "height": h, "protocol": "http", "filesize": (root / name).stat().st_size}

    info = {
        "id": "dQw4w9WgXcQ", "title": "Vertical test", "extractor": "stub", "extractor_key": "Stub",
        "webpage_url": "https://www.youtube.com/shorts/dQw4w9WgXcQ", "duration": 1,
        "formats": [
            fmt("v360", 360, 640, "v360.mp4"), fmt("v720", 720, 1280, "v720.mp4"),
            fmt("v1080", 1080, 1920, "v1080.mp4"),
            {"format_id": "a", "url": f"{base}/a.m4a", "ext": "m4a", "vcodec": "none", "acodec": "mp4a.40.2",
             "protocol": "http", "abr": 128, "filesize": (root / "a.m4a").stat().st_size},
        ],
    }

    class StubYDL(yt_dlp.YoutubeDL):
        def extract_info(self, url, download=True, ie_key=None, extra_info=None, process=True, force_generic_extractor=False):
            seen_urls.append(url)
            data = {**info, "formats": [dict(f) for f in info["formats"]]}
            return self.process_ie_result(data, download=download) if process else data

    def factory(opts):
        opts = {**opts, "proxy": ""}  # local server: bypass any environment proxy
        return StubYDL(opts)

    return factory


@pytest.mark.parametrize("fmt,expect", [("auto", (1080, 1920)), ("720", (720, 1280)), ("480", (360, 640)),
                                        ("360", (360, 640))])
async def test_real_ytdlp_tier_selection_keeps_vertical(http_media, tmp_path, fmt, expect):
    root, base = http_media
    seen = []
    d = Downloader(max_upload_bytes=50 * 2**20, max_duration_sec=600, ydl_factory=stub_factory(base, root, seen))
    progress = []
    res = await d.download(classify("https://youtube.com/shorts/dQw4w9WgXcQ?x=1"), fmt, tmp_path / "w",
                           progress.append)
    await asyncio.sleep(0)
    assert seen == ["https://www.youtube.com/shorts/dQw4w9WgXcQ"]
    assert len(res.files) == 1 and res.files[0].suffix == ".mp4"
    p = await media.ffprobe(res.files[0])
    assert (p.width, p.height) == expect
    assert p.acodec == "aac", "audio must be merged in"
    assert progress and progress[-1] <= 1.0
    d.close()


async def test_real_ytdlp_audio_mp3(http_media, tmp_path):
    root, base = http_media
    d = Downloader(max_upload_bytes=50 * 2**20, max_duration_sec=600, ydl_factory=stub_factory(base, root, []))
    res = await d.download(classify("https://youtu.be/dQw4w9WgXcQ"), "audio", tmp_path / "w")
    assert [f.suffix for f in res.files] == [".mp3"]
    assert (await media.ffprobe(res.files[0])).acodec == "mp3"
    d.close()


async def test_real_ytdlp_max_filesize(http_media, tmp_path):
    root, base = http_media
    d = Downloader(max_upload_bytes=1000, max_duration_sec=600, ydl_factory=stub_factory(base, root, []))
    with pytest.raises(SizeExceeded):
        await d.download(classify("https://youtu.be/dQw4w9WgXcQ"), "auto", tmp_path / "w")
    d.close()


async def test_real_ytdlp_probe(http_media):
    root, base = http_media
    d = Downloader(max_upload_bytes=50 * 2**20, max_duration_sec=600, ydl_factory=stub_factory(base, root, []))
    m = await d.probe(classify("https://www.youtube.com/watch?v=dQw4w9WgXcQ"))
    # vertical <=180s /watch link is re-labelled as a Short
    assert (m.section, m.kind, m.orientation) == ("shorts", "short", "vertical")
    assert m.width == 1080 and m.height == 1920
    d.close()


async def test_real_ytdlp_instagram_carousel_mixed(http_media, tmp_path, monkeypatch):
    import bot.downloader as dmod

    root, base = http_media
    _gen(["-f", "lavfi", "-i", "testsrc=size=400x500:duration=0.1", "-frames:v", "1", str(root / "photo.jpg")])
    monkeypatch.setattr(dmod, "best_image_url", lambda entry: entry["thumbnails"][0]["url"])
    vid = {"id": "item2", "formats": [
        {"format_id": "v", "url": f"{base}/v360.mp4", "ext": "mp4", "vcodec": "avc1", "acodec": "none",
         "width": 360, "height": 640, "protocol": "http"},
        {"format_id": "a", "url": f"{base}/a.m4a", "ext": "m4a", "vcodec": "none", "acodec": "mp4a.40.2",
         "protocol": "http"}]}
    img = {"id": "item1", "thumbnails": [{"url": f"{base}/photo.jpg", "width": 400, "height": 500}]}
    playlist = {"_type": "playlist", "id": "C1a2B3c4D5e", "title": "Post by x", "entries": [img, vid],
                "extractor": "stub", "extractor_key": "Stub", "webpage_url": "https://www.instagram.com/p/C1a2B3c4D5e/"}

    class StubYDL(yt_dlp.YoutubeDL):
        def extract_info(self, url, download=True, process=True, **kw):
            import copy
            return copy.deepcopy(playlist)

    d = Downloader(max_upload_bytes=50 * 2**20, max_duration_sec=600,
                   ydl_factory=lambda o: StubYDL({**o, "proxy": ""}))
    res = await d.download(classify("https://www.instagram.com/p/C1a2B3c4D5e/"), "auto", tmp_path / "w")
    assert [p.suffix for p in res.files] == [".jpg", ".mp4"]
    v = await media.ffprobe(res.files[1])
    assert (v.width, v.height) == (360, 640)
    d.close()


def test_best_image_url_only_instagram_cdn():
    from bot.downloader import best_image_url

    ok = "https://scontent-ams2-1.cdninstagram.com/v/t51/abc.jpg?x=1"
    assert best_image_url({"thumbnails": [{"url": "https://evil.com/a.jpg", "width": 9999, "height": 9999},
                                          {"url": ok, "width": 1080, "height": 1350}]}) == ok
    for bad in ("http://scontent.cdninstagram.com/a.jpg", "https://cdninstagram.com.evil.com/a.jpg",
                "https://x@scontent.cdninstagram.com/a.jpg", "https://scontent.cdninstagram.com:8443/a.jpg",
                "file:///etc/passwd"):
        assert best_image_url({"thumbnails": [{"url": bad}]}) is None


# --- photo posts / carousels through the REAL probe path (QA-H1) ------------------------
def _ig_stub(base, root, payload):
    """Stub Instagram extractor: extract_info goes through the real process_ie_result when process=True."""
    import copy

    class StubYDL(yt_dlp.YoutubeDL):
        def extract_info(self, url, download=True, ie_key=None, extra_info=None, process=True, force_generic_extractor=False):
            data = copy.deepcopy(payload)
            return self.process_ie_result(data, download=download) if process else data

    return lambda o: StubYDL({**o, "proxy": ""})


def _photo_entry(base, pid="p1"):
    return {"id": pid, "title": "Photo by x",
            "thumbnails": [{"url": f"{base}/photo.jpg", "width": 400, "height": 500},
                           {"url": f"{base}/small.jpg", "width": 80, "height": 100}]}


def _ig_meta(**kw):
    return {"extractor": "Instagram", "extractor_key": "Instagram",
            "webpage_url": "https://www.instagram.com/p/C1a2B3c4D5e/", **kw}


async def test_real_probe_carousel_with_photo(http_media):
    root, base = http_media
    vid = {"id": "v1", "duration": 5.0, "formats": [
        {"format_id": "v", "url": f"{base}/v360.mp4", "ext": "mp4", "vcodec": "avc1", "acodec": None,
         "width": 360, "height": 640, "protocol": "http"}]}
    payload = _ig_meta(_type="playlist", id="C1a2B3c4D5e", title="Post by x", entries=[_photo_entry(base), vid])
    d = Downloader(max_upload_bytes=50 * 2**20, max_duration_sec=600, ydl_factory=_ig_stub(base, root, payload))
    m = await d.probe(classify("https://www.instagram.com/p/C1a2B3c4D5e/"))
    assert m.items_count == 2 and m.kind == "post" and m.section == "instagram"
    assert (m.width, m.height, m.orientation) == (400, 500, "vertical")  # first item = photo dims
    assert [f.id for f in m.formats] == ["auto"]
    d.close()


async def test_real_probe_and_download_single_photo_post(http_media, tmp_path, monkeypatch):
    import bot.downloader as dmod

    root, base = http_media
    _gen(["-f", "lavfi", "-i", "testsrc=size=400x500:duration=0.1", "-frames:v", "1", str(root / "photo.jpg")])
    monkeypatch.setattr(dmod, "best_image_url", lambda entry: f"{base}/photo.jpg")
    payload = _ig_meta(**_photo_entry(base, "C1a2B3c4D5e"))
    d = Downloader(max_upload_bytes=50 * 2**20, max_duration_sec=600, ydl_factory=_ig_stub(base, root, payload))
    link = classify("https://www.instagram.com/p/C1a2B3c4D5e/")
    m = await d.probe(link)
    assert m.is_photo and m.items_count == 1 and m.duration is None
    assert (m.width, m.height) == (400, 500)
    assert [f.id for f in m.formats] == ["auto"]  # no MP3 for a photo
    res = await d.download(link, "auto", tmp_path / "w")
    assert [p.suffix for p in res.files] == [".jpg"]
    d.close()


async def test_real_probe_reel_with_unknown_acodec_offers_mp3(http_media):
    root, base = http_media
    payload = _ig_meta(id="C1a2B3c4D5e", title="Video by x", duration=1.0, formats=[
        {"format_id": "p", "url": f"{base}/v360.mp4", "ext": "mp4", "width": 360, "height": 640, "protocol": "http"}])
    d = Downloader(max_upload_bytes=50 * 2**20, max_duration_sec=600, ydl_factory=_ig_stub(base, root, payload))
    m = await d.probe(classify("https://www.instagram.com/reel/C1a2B3c4D5e/"))
    assert [f.id for f in m.formats] == ["auto", "audio"]
    d.close()


# --- cookies are never written back to COOKIES_FILE (QA-H2 / SEC-M2) ------------------------
COOKIE_TEXT = ("# Netscape HTTP Cookie File\n# user comment that yt-dlp would drop on save\n"
               ".instagram.com\tTRUE\t/\tTRUE\t2000000000\tsessionid\tabc\n")


@pytest.fixture
def world_tmp():
    """A temp dir an unprivileged uid can traverse (pytest's tmp root is 0700)."""
    import shutil
    import tempfile

    d = Path(tempfile.mkdtemp(prefix="mb-ro-"))
    d.chmod(0o755)
    yield d
    for p in d.rglob("*"):
        if p.is_dir():
            p.chmod(0o755)
    shutil.rmtree(d, ignore_errors=True)


def test_readonly_cookies_file_is_copied_not_written(world_tmp):
    """Runs as an unprivileged user (root would bypass file permissions)."""
    import os
    import sys
    import textwrap

    tmp_path = world_tmp

    ck_dir = tmp_path / "ro"
    ck_dir.mkdir()
    ck = ck_dir / "cookies.txt"
    ck.write_text(COOKIE_TEXT)
    ck.chmod(0o444)
    ck_dir.chmod(0o555)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    scratch.chmod(0o777)
    script = textwrap.dedent(f"""
        import os, sys, asyncio
        if os.geteuid() == 0:
            os.setgid(65534); os.setuid(65534)
        sys.path.insert(0, {str(Path(__file__).resolve().parent.parent)!r})
        import yt_dlp
        from pathlib import Path
        from bot.downloader import Downloader
        from bot.platforms import classify
        seen = []
        class Stub(yt_dlp.YoutubeDL):
            def extract_info(self, url, download=True, process=True, **kw):
                seen.append(self.params.get("cookiefile"))
                assert len(self.cookiejar) == 1  # cookies were loaded from the copy
                return {{"id": "dQw4w9WgXcQ", "title": "t", "duration": 5, "formats": [
                    {{"format_id": "18", "url": "https://x/v.mp4", "ext": "mp4", "vcodec": "avc1", "acodec": "mp4a",
                      "width": 640, "height": 360}}]}}
        d = Downloader(max_upload_bytes=1 << 20, max_duration_sec=600, cookies_file=Path({str(ck)!r}),
                       ydl_factory=Stub, scratch_dir=Path({str(scratch)!r}))
        m = asyncio.run(d.probe(classify("https://youtu.be/dQw4w9WgXcQ")))
        assert seen and seen[0] != {str(ck)!r}, seen
        assert not os.path.exists(seen[0]), "probe cookie copy must be removed"
        print("OK", m.title)
    """)
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    p = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=60, env=env,
                       cwd=str(scratch))
    assert p.returncode == 0, p.stderr[-2000:]
    assert "OK" in p.stdout
    assert ck.read_text() == COOKIE_TEXT  # original untouched


async def test_download_uses_private_cookie_copy(http_media, tmp_path):
    root, base = http_media
    ck = tmp_path / "cookies.txt"
    ck.write_text(COOKIE_TEXT)
    seen = []
    factory = stub_factory(base, root, [])

    def spy(opts):
        seen.append(opts.get("cookiefile"))
        return factory(opts)

    d = Downloader(max_upload_bytes=50 * 2**20, max_duration_sec=600, ydl_factory=spy, cookies_file=ck)
    work = tmp_path / "w"
    await d.download(classify("https://youtu.be/dQw4w9WgXcQ"), "360", work)
    assert seen == [str(work / ".cookies.txt")]
    assert ck.read_text() == COOKIE_TEXT  # yt-dlp re-saved the copy, never the original
    assert (work / ".cookies.txt").read_text() != COOKIE_TEXT
    d.close()


# --- progress / size guards (QA-M6, SEC-L3) -------------------------------------------------
@pytest.fixture(scope="module")
def progressive(http_media):
    root, base = http_media
    _gen(["-f", "lavfi", "-i", "testsrc=size=640x360:rate=10:duration=1", "-f", "lavfi", "-i", "sine=duration=1",
          "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
          str(root / "prog.mp4")])
    return root, base


def _single_format_factory(base, root, keep_max_filesize=True):
    info = {"id": "dQw4w9WgXcQ", "title": "t", "extractor": "stub", "extractor_key": "Stub", "duration": 1,
            "webpage_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "formats": [{"format_id": "18", "url": f"{base}/prog.mp4", "ext": "mp4", "vcodec": "avc1.42001e",
                         "acodec": "mp4a.40.2", "width": 640, "height": 360, "protocol": "http"}]}

    class StubYDL(yt_dlp.YoutubeDL):
        def extract_info(self, url, download=True, process=True, **kw):
            data = {**info, "formats": [dict(f) for f in info["formats"]]}
            return self.process_ie_result(data, download=download) if process else data

    def factory(opts):
        opts = {**opts, "proxy": ""}
        if not keep_max_filesize:
            opts.pop("max_filesize", None)  # simulate HLS/DASH: no Content-Length based check
        return StubYDL(opts)

    return factory


@pytest.mark.parametrize("fmt", ["360", "auto"])
async def test_progress_reaches_100_percent(progressive, http_media, tmp_path, fmt):
    root, base = progressive
    progress = []
    d = Downloader(max_upload_bytes=50 * 2**20, max_duration_sec=600,
                   ydl_factory=_single_format_factory(base, root) if fmt == "360" else stub_factory(base, root, []))
    await d.download(classify("https://youtu.be/dQw4w9WgXcQ"), fmt, tmp_path / "w", progress.append)
    await asyncio.sleep(0.05)
    assert progress and progress[-1] == 1.0
    assert progress == sorted(progress)
    d.close()


async def test_progress_hook_enforces_size_limit_without_content_length(progressive, tmp_path):
    root, base = progressive
    limit = (root / "prog.mp4").stat().st_size // 3
    d = Downloader(max_upload_bytes=limit, max_duration_sec=600,
                   ydl_factory=_single_format_factory(base, root, keep_max_filesize=False))
    with pytest.raises(SizeExceeded):
        await d.download(classify("https://youtu.be/dQw4w9WgXcQ"), "360", tmp_path / "w")
    d.close()


def test_only_youtube_and_instagram_extractors_loaded():
    from bot.downloader import build_ydl_opts

    y = yt_dlp.YoutubeDL({**build_ydl_opts(fmt=None, workdir=None), "quiet": True})
    names = sorted(ie.IE_NAME.lower() for ie in y._ies.values())
    assert names == ["instagram", "youtube"]
    for url in ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "https://www.youtube.com/shorts/dQw4w9WgXcQ",
                "https://www.instagram.com/reel/C1a2B3c4D5e/", "https://www.instagram.com/p/C1a2B3c4D5e/"):
        assert any(ie.suitable(url) for ie in y._ies.values()), url
    assert not any(ie.suitable("https://evil.com/video.mp4") for ie in y._ies.values())
