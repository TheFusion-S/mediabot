
import pytest

from bot import media
from tests.conftest import ffmpeg_video, requires_ffmpeg

pytestmark = requires_ffmpeg


async def test_ffprobe_vertical(vertical_mp4):
    p = await media.ffprobe(vertical_mp4)
    assert (p.width, p.height) == (360, 640)
    assert p.vcodec == "h264" and p.acodec == "aac"
    assert 0.8 <= p.duration <= 1.3


async def test_ffprobe_horizontal(horizontal_mp4):
    p = await media.ffprobe(horizontal_mp4)
    assert (p.width, p.height) == (640, 360)


async def test_thumbnail_keeps_aspect_and_limits(vertical_mp4, horizontal_mp4, tmp_path):
    for src, expect in ((vertical_mp4, (180, 320)), (horizontal_mp4, (320, 180))):
        thumb = await media.make_thumbnail(src, tmp_path / f"{src.stem}.jpg", 1.0)
        assert thumb is not None and thumb.stat().st_size < media.THUMB_MAX_BYTES
        t = await media.ffprobe(thumb)
        assert (t.width, t.height) == expect
        assert t.vcodec == "mjpeg"


async def test_prepare_h264_is_remux_with_faststart(vertical_mp4, tmp_path):
    src = tmp_path / "in.mp4"
    src.write_bytes(vertical_mp4.read_bytes())
    p = await media.ffprobe(src)
    args = media.build_prepare_args(src, tmp_path / "o.mp4", p, True)
    assert "-c:v" in args and args[args.index("-c:v") + 1] == "copy"
    assert "+faststart" in args and "-vf" not in args
    out = await media.prepare_video(src, p, True)
    q = await media.ffprobe(out)
    assert (q.width, q.height, q.vcodec) == (360, 640, "h264")
    data = out.read_bytes()
    assert data.find(b"moov") < data.find(b"mdat"), "moov atom must precede mdat (+faststart)"


async def test_transcode_non_h264_keeps_dimensions(horizontal_mpeg4, tmp_path):
    src = tmp_path / "in.mp4"
    src.write_bytes(horizontal_mpeg4.read_bytes())
    p = await media.ffprobe(src)
    assert p.vcodec == "mpeg4"
    assert media.needs_transcode(p, True) and not media.needs_transcode(p, False)
    out = await media.prepare_video(src, p, True)
    q = await media.ffprobe(out)
    assert (q.width, q.height, q.vcodec, q.acodec) == (640, 360, "h264", "aac")


async def test_transcode_disabled_copies(horizontal_mpeg4, tmp_path):
    src = tmp_path / "in.mp4"
    src.write_bytes(horizontal_mpeg4.read_bytes())
    p = await media.ffprobe(src)
    out = await media.prepare_video(src, p, False)
    assert (await media.ffprobe(out)).vcodec == "mpeg4"


async def test_odd_vertical_dims_transcode_no_crop(tmp_path):
    src = ffmpeg_video(tmp_path / "odd.mp4", 361, 641, vcodec="mpeg4", audio=False)
    p = await media.ffprobe(src)
    out = await media.prepare_video(src, p, True)
    q = await media.ffprobe(out)
    assert q.height > q.width and abs(q.width - 361) <= 1 and abs(q.height - 641) <= 1


def test_parse_ffprobe_rotation_and_sar():
    data = {"streams": [{"codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080,
                         "side_data_list": [{"side_data_type": "Display Matrix", "rotation": -90}]}],
            "format": {"duration": "12.5"}}
    p = media.parse_ffprobe(data)
    assert (p.width, p.height, p.duration) == (1080, 1920, 12.5)
    anam = {"streams": [{"codec_type": "video", "codec_name": "h264", "width": 1440, "height": 1080,
                         "sample_aspect_ratio": "4:3"}], "format": {}}
    assert media.parse_ffprobe(anam).width == 1920
    cover = {"streams": [{"codec_type": "video", "codec_name": "mjpeg", "width": 500, "height": 500,
                          "disposition": {"attached_pic": 1}}, {"codec_type": "audio", "codec_name": "mp3"}],
             "format": {"duration": "3"}}
    assert media.parse_ffprobe(cover).vcodec is None


async def test_run_tool_refuses_other_binaries():
    with pytest.raises(media.MediaToolError):
        await media.run_tool(["sh", "-c", "echo hi"])


async def test_to_jpeg(tmp_path):
    import subprocess

    src = tmp_path / "img.webp"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=200x300:duration=0.1",
                    "-frames:v", "1", str(src)], check=True)
    out = await media.to_jpeg(src)
    assert out.suffix == ".jpg" and (await media.ffprobe(out)).width == 200
