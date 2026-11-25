from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import time
from pathlib import Path
from urllib.parse import urlencode

import pytest

from bot.security import sign

TOKEN = "123456789:AAEhBP0av28Rg3zYz1VGrQ5x5c8-hello-wrld"

requires_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="ffmpeg not installed"
)


def make_init_data(user: dict | None = None, *, token: str = TOKEN, auth_date: int | None = None,
                   extra: dict | None = None) -> str:
    fields = {
        "query_id": "AAHdF6IQAAAAAN0XohDhrOrc",
        "user": json.dumps(user or {"id": 42, "first_name": "Ali", "username": "ali"}, separators=(",", ":")),
        "auth_date": str(int(time.time()) if auth_date is None else auth_date),
        **(extra or {}),
    }
    fields["hash"] = sign(fields, token)
    return urlencode(fields)


@pytest.fixture
def token() -> str:
    return TOKEN


def ffmpeg_video(path: Path, width: int, height: int, *, seconds: float = 1.0, vcodec: str = "libx264",
                 audio: bool = True, extra: list[str] | None = None) -> Path:
    """Generate a tiny synthetic test video with lavfi (test runs only)."""
    args = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"testsrc=size={width}x{height}:rate=15:duration={seconds}"]
    if audio:
        args += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
    args += ["-c:v", vcodec]
    if vcodec == "libx264":
        args += ["-preset", "ultrafast", "-pix_fmt", "yuv420p"]
    if audio:
        args += ["-c:a", "aac", "-shortest"]
    args += (extra or []) + [str(path)]
    subprocess.run(args, check=True, timeout=60)
    return path


@pytest.fixture(scope="session")
def video_dir(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("videos")


@pytest.fixture(scope="session")
def vertical_mp4(video_dir) -> Path:
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not installed")
    return ffmpeg_video(video_dir / "vertical.mp4", 360, 640)


@pytest.fixture(scope="session")
def horizontal_mp4(video_dir) -> Path:
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not installed")
    return ffmpeg_video(video_dir / "horizontal.mp4", 640, 360)


@pytest.fixture(scope="session")
def horizontal_mpeg4(video_dir) -> Path:
    """Non-H.264 (MPEG-4 part 2) video to exercise transcoding."""
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not installed")
    return ffmpeg_video(video_dir / "horizontal_mpeg4.mp4", 640, 360, vcodec="mpeg4")


async def wait_until(pred, timeout: float = 3.0, interval: float = 0.01) -> None:
    deadline = time.monotonic() + timeout
    while not pred():
        if time.monotonic() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(interval)
