import copy
from pathlib import Path

import pytest

from bot.downloader import (
    Downloader,
    MediaInfo,
    build_formats,
    build_ydl_opts,
    collect_files,
    downgrade_chain,
    estimate_size,
    format_sort_for,
    map_ytdlp_error,
    media_from_info,
    orientation_of,
    plan_attempts,
    select_video,
)
from bot import texts
from bot.errors import AppError, SizeExceeded
from bot.platforms import classify

MB = 1024 * 1024


def fmt(fid, w, h, vcodec="avc1.640028", acodec="none", size=None, tbr=None, ext="mp4"):
    return {"format_id": fid, "width": w, "height": h, "vcodec": vcodec, "acodec": acodec,
            "filesize": size, "tbr": tbr, "ext": ext}


AUDIO = {"format_id": "140", "vcodec": "none", "acodec": "mp4a.40.2", "ext": "m4a", "filesize": 3 * MB, "abr": 128}
AUDIO_OPUS = {"format_id": "251", "vcodec": "none", "acodec": "opus", "ext": "webm", "filesize": 3 * MB, "abr": 160}
STORYBOARD = {"format_id": "sb0", "ext": "mhtml", "width": 320, "height": 180, "vcodec": "none", "format_note": "storyboard"}

HORIZONTAL_FORMATS = [
    STORYBOARD,
    fmt("137", 1920, 1080, size=60 * MB),
    fmt("248", 1920, 1080, vcodec="vp9", size=50 * MB, ext="webm"),
    fmt("136", 1280, 720, size=30 * MB),
    fmt("135", 854, 480, size=12 * MB),
    fmt("134", 640, 360, size=6 * MB),
    AUDIO, AUDIO_OPUS,
]
VERTICAL_FORMATS = [
    fmt("v1080", 1080, 1920, size=20 * MB),
    fmt("v720", 720, 1280, size=10 * MB),
    fmt("v360", 360, 640, size=3 * MB),
    AUDIO,
]


def yt_info(formats, w=1920, h=1080, duration=600, **kw):
    return {"id": "dQw4w9WgXcQ", "title": "  Test   video ", "uploader": "Chan", "duration": duration,
            "width": w, "height": h, "formats": formats, "thumbnail": "https://i.ytimg.com/vi/x/maxres.jpg", **kw}


# --- pure format logic -------------------------------------------------------
def test_format_sort_uses_res_smallest_dimension():
    assert format_sort_for("auto") == ["res:1080", "vcodec:h264", "acodec:m4a", "ext:mp4"]
    for n in ("1080", "720", "480", "360"):
        assert format_sort_for(n) == [f"res:{n}", "vcodec:h264", "acodec:m4a", "ext:mp4"]
    assert format_sort_for("audio") is None
    with pytest.raises(ValueError):
        format_sort_for("4k")


def test_downgrade_chain():
    assert downgrade_chain("auto") == ["auto", "720", "480", "360"]
    assert downgrade_chain("1080") == ["1080", "720", "480", "360"]
    assert downgrade_chain("480") == ["480", "360"]
    assert downgrade_chain("360") == ["360"]
    assert downgrade_chain("audio") == ["audio"]


def test_select_video_prefers_h264_and_res_le_n():
    assert select_video(HORIZONTAL_FORMATS, 1080)["format_id"] == "137"  # h264 over vp9
    assert select_video(HORIZONTAL_FORMATS, 720)["format_id"] == "136"
    assert select_video(HORIZONTAL_FORMATS, 400)["format_id"] == "134"
    # vertical: res is the smallest side -> 1080x1920 is "1080"
    assert select_video(VERTICAL_FORMATS, 1080)["format_id"] == "v1080"
    assert select_video(VERTICAL_FORMATS, 720)["format_id"] == "v720"
    # nothing <= N -> smallest above
    assert select_video(VERTICAL_FORMATS, 240)["format_id"] == "v360"


def test_estimate_size_adds_audio():
    size, res = estimate_size(HORIZONTAL_FORMATS, 720, 600)
    assert (size, res) == (33 * MB, 720)


def test_estimate_size_from_tbr():
    f = [fmt("x", 1280, 720, tbr=1000), {"format_id": "a", "vcodec": "none", "acodec": "mp4a", "tbr": 128}]
    size, _ = estimate_size(f, 720, 10)
    assert size == 1000 * 125 * 10 + 128 * 125 * 10


def test_build_formats_videos_section_with_fits():
    opts = build_formats(yt_info(HORIZONTAL_FORMATS), "videos", 50 * MB)
    by = {o.id: o for o in opts}
    assert list(by) == ["auto", "1080", "720", "480", "360", "audio"]
    assert by["1080"].size == 63 * MB and by["1080"].fits is False
    assert by["720"].fits and by["480"].fits and by["360"].fits
    assert by["auto"].fits is True  # auto downgrades, so it fits while any tier fits
    assert by["1080"].height == 1080 and by["360"].height == 360
    assert by["audio"].size == 192 * 125 * 600 and by["audio"].fits


def test_build_formats_dedupes_missing_tiers():
    formats = [fmt("136", 1280, 720, size=30 * MB), fmt("134", 640, 360, size=6 * MB), AUDIO]
    ids = [o.id for o in build_formats(yt_info(formats, 1280, 720), "videos", 50 * MB)]
    assert ids == ["auto", "720", "360", "audio"]


def test_build_formats_shorts_only_auto_and_audio():
    ids = [o.id for o in build_formats(yt_info(VERTICAL_FORMATS, 1080, 1920, 30), "shorts", 50 * MB)]
    assert ids == ["auto", "audio"]


def test_nothing_fits():
    opts = build_formats(yt_info(HORIZONTAL_FORMATS), "videos", 1 * MB)
    assert not any(o.fits for o in opts if o.id != "audio")


def test_plan_attempts_skips_known_too_big():
    media = media_from_info(classify("https://youtu.be/dQw4w9WgXcQ"), yt_info(HORIZONTAL_FORMATS), 50 * MB)
    assert plan_attempts("1080", media) == ["720", "480", "360"]
    assert plan_attempts("auto", media) == ["720", "480", "360"]
    assert plan_attempts("480", media) == ["480", "360"]
    media_small = media_from_info(classify("https://youtu.be/dQw4w9WgXcQ"), yt_info(HORIZONTAL_FORMATS), 1 * MB)
    assert plan_attempts("1080", media_small) == ["360"]  # last resort is still tried
    assert plan_attempts("auto", None) == ["auto", "720", "480", "360"]


@pytest.mark.parametrize("w,h,o", [(1080, 1920, "vertical"), (1920, 1080, "horizontal"), (1080, 1080, "square"),
                                   (1080, 1090, "square"), (None, None, "horizontal")])
def test_orientation(w, h, o):
    assert orientation_of(w, h) == o


def test_media_from_info_shape_and_reclassify():
    link = classify("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    media = media_from_info(link, yt_info(VERTICAL_FORMATS, 1080, 1920, 45), 50 * MB)
    api = media.to_api()
    assert set(api) == {"platform", "kind", "section", "id", "url", "title", "author", "thumbnail", "duration",
                        "width", "height", "orientation", "items_count", "formats"}
    assert api["section"] == "shorts" and api["kind"] == "short"
    assert api["orientation"] == "vertical" and api["title"] == "Test video"
    assert api["url"] == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert set(api["formats"][0]) == {"id", "label", "height", "size", "fits"}


def test_media_from_info_horizontal_stays_video():
    link = classify("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    media = media_from_info(link, yt_info(HORIZONTAL_FORMATS), 50 * MB)
    assert (media.section, media.orientation, media.duration) == ("videos", "horizontal", 600)


def test_media_from_info_carousel():
    link = classify("https://www.instagram.com/p/C1a2B3c4D5e/")
    info = {"_type": "playlist", "id": "C1a2B3c4D5e", "title": "Post by x", "uploader": "x",
            "entries": [yt_info(VERTICAL_FORMATS, 1080, 1350, 10, thumbnail="https://cdn/x.jpg"),
                        yt_info(VERTICAL_FORMATS, 1080, 1080, 5)] + [{}] * 0}
    media = media_from_info(link, info, 50 * MB)
    assert media.items_count == 2 and media.section == "instagram" and media.kind == "post"
    assert [f.id for f in media.formats] == ["auto"]
    assert media.thumbnail == "https://cdn/x.jpg"


def test_non_https_thumbnail_dropped():
    media = media_from_info(classify("https://youtu.be/dQw4w9WgXcQ"),
                            yt_info(HORIZONTAL_FORMATS, thumbnail="http://insecure/x.jpg"), 50 * MB)
    assert media.thumbnail is None


@pytest.mark.parametrize("msg,code", [
    ("ERROR: [youtube] x: Private video. Sign in if you've been granted access", "private"),
    ("ERROR: [Instagram] x: Requested content is not available, rate-limit reached or login required", "private"),
    ("ERROR: [youtube] x: Video unavailable", "not_found"),
    ("ERROR: Unsupported URL: https://x", "unsupported"),
    ("ERROR: x: This live event will begin in 3 hours", "unsupported"),
    ("ERROR: Sign in to confirm you're not a bot", "rate_limited"),
    ("something odd", "internal"),
])
def test_error_mapping(msg, code):
    assert map_ytdlp_error(Exception(msg)).code == code


def test_ydl_opts_are_safe(tmp_path):
    opts = build_ydl_opts(fmt="720", workdir=tmp_path, max_filesize=50 * MB, cookies_file=None)
    assert opts["noplaylist"] is True and opts["ignoreconfig"] is True
    assert opts["quiet"] and opts["no_warnings"] and opts["restrictfilenames"]
    assert opts["format"] == "bv*+ba/b" and opts["format_sort"][0] == "res:720"
    assert opts["merge_output_format"] == "mp4" and opts["max_filesize"] == 50 * MB
    assert opts["outtmpl"]["default"].startswith(str(tmp_path))
    assert "cookiefile" not in opts
    for bad in ("exec", "exec_cmd", "external_downloader", "postprocessor_args", "download_archive"):
        assert bad not in opts
    audio = build_ydl_opts(fmt="audio", workdir=tmp_path, cookies_file=Path("/c.txt"))
    assert audio["format"] == "ba/b" and audio["cookiefile"] == "/c.txt"
    assert audio["postprocessors"] == [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}]
    assert {p["key"] for p in audio["postprocessors"]} <= {"FFmpegExtractAudio"}


# --- Downloader with a fake YoutubeDL ------------------------------------------
class FakeYDL:
    instances: list["FakeYDL"] = []
    info: dict = {}
    produce: list[str] = ["01_dQw4w9WgXcQ.mp4"]
    error: Exception | None = None

    def __init__(self, opts):
        self.opts = opts
        FakeYDL.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def extract_info(self, url, download=False, process=True):
        self.url = url
        if FakeYDL.error:
            raise FakeYDL.error
        return copy.deepcopy(FakeYDL.info)

    def process_ie_result(self, info, download=True):
        home = Path(self.opts["paths"]["home"])
        reqs = []
        for name in FakeYDL.produce:
            for hook in self.opts.get("progress_hooks", []):
                hook({"status": "downloading", "filename": name, "downloaded_bytes": 50, "total_bytes": 100})
                hook({"status": "downloading", "filename": name, "downloaded_bytes": 100, "total_bytes": 100})
            p = home / name
            p.write_bytes(b"x" * 10)
            reqs.append({"filepath": str(p)})
        info["requested_downloads"] = reqs
        return info


@pytest.fixture
def fake_ydl():
    FakeYDL.instances = []
    FakeYDL.info = yt_info(HORIZONTAL_FORMATS)
    FakeYDL.produce = ["01_dQw4w9WgXcQ.mp4"]
    FakeYDL.error = None
    return FakeYDL


def make_downloader(**kw):
    return Downloader(max_upload_bytes=50 * MB, max_duration_sec=7200, ydl_factory=FakeYDL, **kw)


async def test_probe_uses_canonical_url_and_caches(fake_ydl):
    d = make_downloader()
    link = classify("watch this https://youtu.be/dQw4w9WgXcQ?t=10&evil=1")
    m1 = await d.probe(link)
    m2 = await d.probe(link)
    assert isinstance(m1, MediaInfo) and m1 is m2
    assert len(fake_ydl.instances) == 1
    assert fake_ydl.instances[0].url == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    d.close()


async def test_probe_rejects_live_and_too_long(fake_ydl):
    d = make_downloader()
    fake_ydl.info = yt_info(HORIZONTAL_FORMATS, is_live=True)
    with pytest.raises(AppError) as e:
        await d.probe(classify("https://youtu.be/dQw4w9WgXcQ"))
    assert e.value.code == "unsupported"
    fake_ydl.info = yt_info(HORIZONTAL_FORMATS, duration=7201)
    with pytest.raises(AppError) as e:
        await d.probe(classify("https://youtu.be/aaaaaaaaaaa"))
    assert e.value.code == "too_long" and "120" in e.value.message
    d.close()


async def test_probe_maps_errors(fake_ydl):
    fake_ydl.error = Exception("ERROR: Private video")
    d = make_downloader()
    with pytest.raises(AppError) as e:
        await d.probe(classify("https://youtu.be/dQw4w9WgXcQ"))
    assert e.value.code == "private" and e.value.status == 403
    d.close()


async def test_download_reports_progress_and_files(fake_ydl, tmp_path):
    d = make_downloader()
    progress = []
    res = await d.download(classify("https://youtu.be/dQw4w9WgXcQ"), "720", tmp_path / "w", progress.append)
    assert [p.name for p in res.files] == ["01_dQw4w9WgXcQ.mp4"]
    opts = fake_ydl.instances[-1].opts
    assert opts["format_sort"][0] == "res:720" and opts["max_filesize"] == 50 * MB
    assert progress and max(progress) <= 1.0 and progress == sorted(progress)
    d.close()


async def test_download_no_file_due_to_max_filesize(fake_ydl, tmp_path):
    class SkippingYDL(FakeYDL):
        def process_ie_result(self, info, download=True):
            self.opts["logger"].info("[download] File is larger than max-filesize (1 bytes > 0 bytes). Aborting.")
            return info

    d = Downloader(max_upload_bytes=50 * MB, max_duration_sec=7200, ydl_factory=SkippingYDL)
    with pytest.raises(SizeExceeded):
        await d.download(classify("https://youtu.be/dQw4w9WgXcQ"), "1080", tmp_path / "w")
    d.close()


async def test_download_rejects_unknown_format(fake_ydl, tmp_path):
    d = make_downloader()
    with pytest.raises(AppError):
        await d.download(classify("https://youtu.be/dQw4w9WgXcQ"), "best[exec]", tmp_path)
    d.close()


def test_collect_files_skips_fragments(tmp_path):
    for n in ("01_x.f137.mp4", "01_x.mp4.part", "01_x.mp4", "notes.txt"):
        (tmp_path / n).write_bytes(b"1")
    assert [p.name for p in collect_files(None, tmp_path)] == ["01_x.mp4"]


def test_collect_files_ignores_paths_outside_workdir(tmp_path):
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"1")
    work = tmp_path / "w"
    work.mkdir()
    assert collect_files({"requested_downloads": [{"filepath": str(outside)}]}, work) == []


# --- found by live testing: YouTube "confirm you're not a bot" block on datacenter IPs ---------------

@pytest.mark.parametrize("message", [
    "ERROR: [youtube] x: Sign in to confirm you’re not a bot. Use --cookies-from-browser",
    "ERROR: [youtube] x: Sign in to confirm you're not a bot",
    "Unable to download webpage: HTTP Error 429: Too Many Requests",
])
def test_youtube_bot_check_is_reported_clearly(message):
    err = map_ytdlp_error(Exception(message))
    assert err.code == "rate_limited" and err.message == texts.YT_BLOCKED


def test_age_gate_is_still_private():
    assert map_ytdlp_error(Exception("Sign in to confirm your age. This video may be inappropriate")).code == "private"


async def test_youtube_probe_with_only_storyboards_is_a_clear_error(fake_ydl):
    info = yt_info(HORIZONTAL_FORMATS)
    info["formats"] = [{"format_id": "sb0", "ext": "mhtml", "format_note": "storyboard", "vcodec": "none",
                        "acodec": "none", "width": 48, "height": 27}]
    FakeYDL.info = info
    with pytest.raises(AppError) as ei:
        await make_downloader().probe(classify("https://youtu.be/dQw4w9WgXcQ"))
    assert ei.value.code == "rate_limited" and ei.value.message == texts.YT_BLOCKED


async def test_ignore_no_formats_only_for_instagram(fake_ydl):
    d = make_downloader()
    await d.probe(classify("https://youtu.be/dQw4w9WgXcQ"))
    assert "ignore_no_formats_error" not in FakeYDL.instances[-1].opts
