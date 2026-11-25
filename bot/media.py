"""ffprobe / ffmpeg helpers. Always ``asyncio.create_subprocess_exec`` with argument lists.

Never crops or pads: only the codec/container may change; the display aspect ratio is kept.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

FFMPEG = os.environ.get("FFMPEG_BIN", "ffmpeg")
FFPROBE = os.environ.get("FFPROBE_BIN", "ffprobe")

THUMB_MAX_SIDE = 320
THUMB_MAX_BYTES = 200 * 1024
COMPATIBLE_AUDIO = {"aac", "mp3"}
COMPATIBLE_PIX = {"yuv420p", "yuvj420p"}


class MediaToolError(RuntimeError):
    pass


@dataclass(slots=True)
class VideoProbe:
    width: int | None
    height: int | None
    duration: float | None
    vcodec: str | None
    acodec: str | None
    pix_fmt: str | None
    format_name: str | None
    rotation: int = 0

    @property
    def duration_int(self) -> int | None:
        return int(round(self.duration)) if self.duration else None


async def run_tool(args: list[str], timeout: float = 120.0) -> tuple[int, bytes, bytes]:
    """Run ffmpeg/ffprobe without a shell. Kills the process on timeout."""
    if not args or args[0] not in (FFMPEG, FFPROBE):
        raise MediaToolError("only ffmpeg/ffprobe may be executed")
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        proc.kill()
        await proc.wait()
        raise
    return proc.returncode or 0, out, err


def _parse_ratio(value: str | None) -> float | None:
    if not value or ":" not in value:
        return None
    try:
        a, b = (int(x) for x in value.split(":", 1))
    except ValueError:
        return None
    if a <= 0 or b <= 0:
        return None
    return a / b


def _rotation(stream: dict) -> int:
    for sd in stream.get("side_data_list") or []:
        if "rotation" in sd:
            try:
                return int(float(sd["rotation"]))
            except (TypeError, ValueError):
                pass
    rot = (stream.get("tags") or {}).get("rotate")
    try:
        return int(rot) if rot is not None else 0
    except ValueError:
        return 0


def parse_ffprobe(data: dict) -> VideoProbe:
    streams = data.get("streams") or []
    v = next((s for s in streams if s.get("codec_type") == "video" and not (s.get("disposition") or {}).get("attached_pic")), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    width = height = None
    rotation = 0
    if v:
        width, height = v.get("width"), v.get("height")
        sar = _parse_ratio(v.get("sample_aspect_ratio"))
        if width and height and sar and abs(sar - 1) > 0.01:
            width = int(round(width * sar))  # display width for anamorphic video
        rotation = _rotation(v)
        if width and height and abs(rotation) % 180 == 90:
            width, height = height, width
    duration = None
    for src in (data.get("format") or {}, v or {}, a or {}):
        try:
            if src.get("duration") not in (None, "N/A"):
                duration = float(src["duration"])
                break
        except (TypeError, ValueError):
            continue
    return VideoProbe(
        width=int(width) if width else None,
        height=int(height) if height else None,
        duration=duration,
        vcodec=v.get("codec_name") if v else None,
        acodec=a.get("codec_name") if a else None,
        pix_fmt=v.get("pix_fmt") if v else None,
        format_name=(data.get("format") or {}).get("format_name"),
        rotation=rotation,
    )


async def ffprobe(path: Path) -> VideoProbe:
    rc, out, err = await run_tool(
        [FFPROBE, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path.resolve())],
        timeout=60,
    )
    if rc != 0:
        raise MediaToolError(f"ffprobe failed: {err.decode(errors='replace')[-300:]}")
    return parse_ffprobe(json.loads(out or b"{}"))


def needs_transcode(p: VideoProbe, transcode_non_h264: bool) -> bool:
    if not transcode_non_h264 or p.vcodec is None:
        return False
    return p.vcodec != "h264" or (p.pix_fmt is not None and p.pix_fmt not in COMPATIBLE_PIX)


def build_prepare_args(src: Path, dst: Path, p: VideoProbe, transcode_non_h264: bool) -> list[str]:
    """ffmpeg args producing an mp4 with +faststart (copy when possible, else H.264/AAC)."""
    args = [FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", str(src),
            "-map", "0:v:0", "-map", "0:a:0?", "-sn", "-dn"]
    if needs_transcode(p, transcode_non_h264):
        # Only even-ify dimensions / square pixels (libx264 + yuv420p requirement); no crop/pad.
        args += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
                 "-vf", "scale=trunc(iw*sar/2)*2:trunc(ih/2)*2,setsar=1"]
    else:
        args += ["-c:v", "copy"]
    if p.acodec is None:
        pass
    elif p.acodec in COMPATIBLE_AUDIO:
        args += ["-c:a", "copy"]
    else:
        args += ["-c:a", "aac", "-b:a", "160k"]
    args += ["-movflags", "+faststart", "-f", "mp4", str(dst)]
    return args


async def prepare_video(src: Path, p: VideoProbe, transcode_non_h264: bool = True) -> Path:
    dst = src.with_name(f"{src.stem}.ready.mp4")
    timeout = max(300.0, (p.duration or 0) * 4)
    rc, _, err = await run_tool(build_prepare_args(src, dst, p, transcode_non_h264), timeout=timeout)
    if rc != 0 or not dst.is_file():
        raise MediaToolError(f"ffmpeg failed: {err.decode(errors='replace')[-300:]}")
    return dst


async def make_thumbnail(src: Path, dst: Path, duration: float | None = None) -> Path | None:
    """JPEG, max side 320px, < 200KB, same aspect ratio as the video."""
    at = min(max((duration or 0) * 0.1, 0.0), 3.0)
    for seek in (at, 0.0):
        for q in (4, 8, 14, 22, 31):
            args = [FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin", "-y"]
            if seek > 0:
                args += ["-ss", f"{seek:.2f}"]
            args += ["-i", str(src), "-frames:v", "1",
                     "-vf", f"scale={THUMB_MAX_SIDE}:{THUMB_MAX_SIDE}:force_original_aspect_ratio=decrease,setsar=1",
                     "-q:v", str(q), "-f", "image2", "-c:v", "mjpeg", str(dst)]
            try:
                rc, _, _ = await run_tool(args, timeout=60)
            except asyncio.TimeoutError:
                return None
            if rc != 0 or not dst.is_file() or dst.stat().st_size == 0:
                break  # try next seek position
            if dst.stat().st_size < THUMB_MAX_BYTES:
                return dst
    dst.unlink(missing_ok=True)
    return None


async def to_jpeg(src: Path) -> Path:
    """Convert an image (webp/heic/...) to JPEG for send_photo."""
    dst = src.with_name(f"{src.stem}.jpg")
    if dst == src:
        return src
    rc, _, err = await run_tool(
        [FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", str(src),
         "-frames:v", "1", "-q:v", "3", str(dst)], timeout=60)
    if rc != 0 or not dst.is_file():
        raise MediaToolError(f"image conversion failed: {err.decode(errors='replace')[-300:]}")
    return dst
