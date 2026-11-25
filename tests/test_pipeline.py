import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from bot.downloader import DownloadResult, FormatOption, MediaInfo
from bot.errors import AppError, SizeExceeded
from bot.jobs import JobManager
from bot.pipeline import Pipeline
from bot.platforms import classify
from bot.sender import MediaItem, Sender
from bot.storage import Storage
from tests.conftest import ffmpeg_video, requires_ffmpeg

pytestmark = requires_ffmpeg
MB = 1024 * 1024


def media_info(link, *, w, h, formats=None, items=1, duration=1):
    return MediaInfo(platform=link.platform, kind=link.kind, section=link.section, id=link.id,
                     url=link.canonical_url, title="Ajoyib <video>", author="Muallif",
                     thumbnail="https://i.ytimg.com/x.jpg", duration=duration, width=w, height=h,
                     orientation="vertical" if h > w else "horizontal", items_count=items,
                     formats=formats or [FormatOption("auto", "Avto", None, None, True)])


class FakeDownloader:
    def __init__(self, media, files_by_fmt):
        self.media = media
        self.files_by_fmt = files_by_fmt  # fmt -> list[Path] | Exception
        self.calls = []
        self.probes = 0

    async def probe(self, link):
        self.probes += 1
        return self.media

    async def download(self, link, fmt, workdir, on_progress=None):
        self.calls.append((link.canonical_url, fmt))
        workdir.mkdir(parents=True, exist_ok=True)
        if on_progress:
            on_progress(0.5)
            on_progress(1.0)
        src = self.files_by_fmt[fmt]
        if isinstance(src, Exception):
            raise src
        out = []
        for i, p in enumerate(src):
            dst = workdir / f"{i:02d}_{p.name}"
            shutil.copy(p, dst)
            out.append(dst)
        return DownloadResult(files=out, format=fmt)


class FakeSender:
    def __init__(self):
        self.calls = []
        self.n = 0

    def _fid(self, t):
        self.n += 1
        return {"type": t, "file_id": f"{t}-{self.n}"}

    async def send_video(self, chat_id, item, *, caption=None, reply_markup=None, reply_to=None, plain=False):
        assert item.path.is_file() and (item.thumbnail is None or item.thumbnail.is_file())
        self.calls.append(("video", chat_id, item, caption, reply_markup))
        return self._fid("video")

    async def send_audio(self, chat_id, item, *, caption=None, reply_to=None, plain=False):
        self.calls.append(("audio", chat_id, item, caption, None))
        return self._fid("audio")

    async def send_photo(self, chat_id, item, *, caption=None, reply_to=None, plain=False):
        self.calls.append(("photo", chat_id, item, caption, None))
        return self._fid("photo")

    async def send_media_group(self, chat_id, items, *, caption=None, reply_to=None, plain=False):
        self.calls.append(("group", chat_id, items, caption, None))
        return [self._fid(i.type) for i in items]

    async def send_cached(self, chat_id, entries, *, caption=None, reply_markup=None, reply_to=None, plain=False):
        self.calls.append(("cached", chat_id, entries, caption, reply_markup))


@pytest.fixture
async def storage():
    s = await Storage(":memory:").open()
    yield s
    await s.close()


def make(tmp_path, storage, downloader, sender, max_mb=50):
    p = Pipeline(downloader=downloader, sender=sender, storage=storage, max_upload_bytes=max_mb * MB,
                 limits={"max_upload_mb": max_mb})
    jm = JobManager(runner=p, download_dir=tmp_path / "dl", max_concurrent=2, hourly_limit=100, storage=storage)
    return p, jm


async def run_job(jm, link, fmt="auto", user=1):
    job = await jm.submit(user_id=user, chat_id=user, link=link, fmt=fmt)
    await jm.wait(job, 30)
    return job


async def test_vertical_short_sent_with_real_dimensions(tmp_path, storage, vertical_mp4):
    link = classify("https://www.youtube.com/shorts/dQw4w9WgXcQ")
    dl = FakeDownloader(media_info(link, w=360, h=640), {"auto": [vertical_mp4]})
    sender = FakeSender()
    _, jm = make(tmp_path, storage, dl, sender)
    job = await run_job(jm, link)
    assert job.status == "done", job.error
    kind, chat, item, caption, markup = sender.calls[0]
    assert kind == "video" and chat == 1
    assert (item.width, item.height, item.duration) == (360, 640, 1)
    assert item.thumbnail is not None and item.thumbnail.suffix == ".jpg"
    assert "&lt;video&gt;" in caption  # title is HTML-escaped
    cb = markup.inline_keyboard[0][0].callback_data
    assert cb.startswith("dl:") and cb.endswith(":audio") and "http" not in cb and len(cb.encode()) <= 64
    token = cb.split(":")[1]
    assert await storage.url_for_token(token) == link.canonical_url
    assert job.title == "Ajoyib <video>"
    assert list((tmp_path / "dl").iterdir()) == []  # temp dir removed

    # second request -> file_id cache, no download
    job2 = await run_job(jm, link)
    assert job2.status == "done" and sender.calls[-1][0] == "cached"
    assert sender.calls[-1][2][0]["file_id"] == "video-1"
    assert len(dl.calls) == 1


async def test_horizontal_video(tmp_path, storage, horizontal_mp4):
    link = classify("https://youtu.be/dQw4w9WgXcQ")
    dl = FakeDownloader(media_info(link, w=640, h=360), {"720": [horizontal_mp4]})
    sender = FakeSender()
    _, jm = make(tmp_path, storage, dl, sender)
    job = await run_job(jm, link, "720")
    assert job.status == "done"
    item = sender.calls[0][2]
    assert (item.width, item.height) == (640, 360)


async def test_non_h264_is_transcoded(tmp_path, storage, horizontal_mpeg4):
    from bot import media as m

    link = classify("https://youtu.be/dQw4w9WgXcQ")
    dl = FakeDownloader(media_info(link, w=640, h=360), {"auto": [horizontal_mpeg4]})
    sender = FakeSender()
    p, jm = make(tmp_path, storage, dl, sender)
    seen = {}
    orig = sender.send_video

    async def spy(chat_id, item, **kw):
        seen["probe"] = await m.ffprobe(item.path)
        return await orig(chat_id, item, **kw)

    sender.send_video = spy
    job = await run_job(jm, link)
    assert job.status == "done"
    assert seen["probe"].vcodec == "h264" and (seen["probe"].width, seen["probe"].height) == (640, 360)


async def test_auto_downgrade_when_too_large(tmp_path, storage, horizontal_mp4):
    big = ffmpeg_video(tmp_path / "big.mp4", 640, 360, seconds=2, extra=["-vf", "noise=alls=80:allf=t", "-qp", "0"])
    assert big.stat().st_size > MB
    link = classify("https://youtu.be/dQw4w9WgXcQ")
    formats = [FormatOption(i, i, None, None, True) for i in ("auto", "1080", "720", "480", "360", "audio")]
    dl = FakeDownloader(media_info(link, w=640, h=360, formats=formats),
                        {"1080": [big], "720": SizeExceeded(), "480": [horizontal_mp4]})
    sender = FakeSender()
    p, jm = make(tmp_path, storage, dl, sender, max_mb=1)
    job = await run_job(jm, link, "1080")
    assert job.status == "done", job.error
    assert [c[1] for c in dl.calls] == ["1080", "720", "480"]
    # the "480" attempt delivered a 640x360 file: the label reflects the REAL resolution
    assert "360p" in sender.calls[0][3] and "360p" in job.note
    api = job.to_api()
    assert api["used_format"] == "360" and "360p" in api["note"]
    # cached under the requested format (with note) and the delivered tier (without note), keyed by limit
    req = await storage.get_cached(link.media_key, p.cache_key("1080"))
    direct = await storage.get_cached(link.media_key, p.cache_key("360"))
    assert p.cache_key("1080") == "1080@1"
    assert req[0]["used_format"] == "360" and "360p" in req[0]["note"]
    assert direct[0]["note"] == ""
    # a cache hit keeps used_format + note
    job2 = await run_job(jm, link, "1080")
    assert sender.calls[-1][0] == "cached" and job2.used_format == "360" and "360p" in job2.note
    assert "360p" in sender.calls[-1][3]
    # a larger limit does not reuse the low-tier cache entry
    p2, _ = make(tmp_path, storage, dl, sender, max_mb=50)
    assert await storage.get_cached(link.media_key, p2.cache_key("1080")) is None


async def test_estimated_too_big_tiers_are_skipped(tmp_path, storage, horizontal_mp4):
    link = classify("https://youtu.be/dQw4w9WgXcQ")
    formats = [FormatOption("1080", "1080p", 1080, 99 * MB, False), FormatOption("720", "720p", 720, 10 * MB, True)]
    dl = FakeDownloader(media_info(link, w=640, h=360, formats=formats), {"720": [horizontal_mp4]})
    _, jm = make(tmp_path, storage, dl, FakeSender())
    job = await run_job(jm, link, "1080")
    assert job.status == "done" and [c[1] for c in dl.calls] == ["720"]


async def test_too_large_even_at_360(tmp_path, storage):
    link = classify("https://youtu.be/dQw4w9WgXcQ")
    dl = FakeDownloader(media_info(link, w=640, h=360), {f: SizeExceeded() for f in ("auto", "720", "480", "360")})
    _, jm = make(tmp_path, storage, dl, FakeSender())
    job = await run_job(jm, link, "auto")
    assert job.status == "error" and job.error["code"] == "too_large"
    assert "50" in job.error["message"]


async def test_probe_error_propagates(tmp_path, storage):
    link = classify("https://youtu.be/dQw4w9WgXcQ")

    class Failing(FakeDownloader):
        async def probe(self, link):
            raise AppError("private")

    _, jm = make(tmp_path, storage, Failing(None, {}), FakeSender())
    job = await run_job(jm, link)
    assert job.error["code"] == "private"
    row = await storage.get_download(job.id, 1)
    assert row["status"] == "error" and row["error_code"] == "private"


async def test_instagram_carousel_media_group(tmp_path, storage, vertical_mp4):
    photo = tmp_path / "p.jpg"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=400x500:duration=0.1",
                    "-frames:v", "1", str(photo)], check=True)
    link = classify("https://www.instagram.com/p/C1a2B3c4D5e/")
    dl = FakeDownloader(media_info(link, w=400, h=500, items=2), {"auto": [photo, vertical_mp4]})
    sender = FakeSender()
    _, jm = make(tmp_path, storage, dl, sender)
    job = await run_job(jm, link)
    assert job.status == "done", job.error
    kind, _, items, caption, _ = sender.calls[0]
    assert kind == "group" and [i.type for i in items] == ["photo", "video"]
    assert (items[1].width, items[1].height) == (360, 640)
    cached = await storage.get_cached(link.media_key, "auto@50")
    assert [c["type"] for c in cached] == ["photo", "video"]


async def test_audio_mp3(tmp_path, storage):
    mp3 = tmp_path / "a.mp3"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "sine=duration=1", "-c:a", "libmp3lame",
                    str(mp3)], check=True)
    link = classify("https://youtu.be/dQw4w9WgXcQ")
    dl = FakeDownloader(media_info(link, w=640, h=360), {"audio": [mp3]})
    sender = FakeSender()
    _, jm = make(tmp_path, storage, dl, sender)
    job = await run_job(jm, link, "audio")
    assert job.status == "done", job.error
    kind, _, item, _, _ = sender.calls[0]
    assert kind == "audio" and item.title == "Ajoyib <video>" and item.performer == "Muallif"


# --- Sender against a fake aiogram Bot ------------------------------------------
class FakeBot:
    def __init__(self):
        self.calls = []

    async def send_video(self, **kw):
        self.calls.append(("send_video", kw))
        return SimpleNamespace(video=SimpleNamespace(file_id="VID"), audio=None, photo=None, document=None)

    async def send_media_group(self, **kw):
        self.calls.append(("send_media_group", kw))
        return [SimpleNamespace(video=None, audio=None, photo=[SimpleNamespace(file_id="PH")], document=None)
                for _ in kw["media"]]


async def test_sender_send_video_params(tmp_path, vertical_mp4):
    thumb = tmp_path / "t.jpg"
    thumb.write_bytes(b"jpg")
    bot = FakeBot()
    s = Sender(bot)
    entry = await s.send_video(10, MediaItem(path=vertical_mp4, type="video", width=360, height=640, duration=1,
                                             thumbnail=thumb), caption="x" * 2000)
    assert entry == {"type": "video", "file_id": "VID"}
    kw = bot.calls[0][1]
    assert kw["supports_streaming"] is True
    assert (kw["width"], kw["height"], kw["duration"]) == (360, 640, 1)
    assert Path(kw["thumbnail"].path) == thumb
    assert len(kw["caption"]) == 1024


async def test_sender_media_group_chunks_of_10(tmp_path, vertical_mp4):
    bot = FakeBot()
    s = Sender(bot)
    items = [MediaItem(path=vertical_mp4, type="photo") for _ in range(12)]
    out = await s.send_media_group(1, items, caption="c")
    assert len(bot.calls) == 2 and len(bot.calls[0][1]["media"]) == 10 and len(out) == 12
    assert bot.calls[0][1]["media"][0].caption == "c" and bot.calls[1][1]["media"][0].caption is None
