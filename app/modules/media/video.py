"""Valida y convierte videos sin modificar sus originales."""

import math
import os
import re
import subprocess
from pathlib import Path

import imageio_ffmpeg


class InvalidVideo(ValueError):
    pass


def run(arguments: list[str], timeout: int = 30):
    try:
        return subprocess.run(
            [imageio_ffmpeg.get_ffmpeg_exe(), "-nostdin", "-hide_banner", *arguments],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
            check=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except (OSError, subprocess.SubprocessError):
        raise InvalidVideo("Video could not be processed") from None


def input_options(source: Path):
    with source.open("rb") as stream:
        header = stream.read(4096)
    if header[4:8] == b"ftyp":
        return ["-f", "mov", "-enable_drefs", "0", "-use_absolute_path", "0"]
    if header[:4] == b"\x1aE\xdf\xa3" and b"\x42\x82\x84webm" in header:
        return ["-f", "matroska"]
    raise InvalidVideo("Only self-contained MP4, MOV and WebM videos are supported")


def input_args(source: Path):
    return [
        "-protocol_whitelist",
        "file",
        *input_options(source),
        "-threads",
        "2",
        "-max_alloc",
        "67108864",
        "-i",
        str(source),
    ]


def inspect_video(source: Path, *, max_bytes=100 * 1024 * 1024, max_seconds=120):
    if not 0 < source.stat().st_size <= max_bytes:
        raise InvalidVideo("Video exceeds the file size limit or is empty")
    result = run(
        [
            *input_args(source),
            "-map",
            "0:v:0",
            "-an",
            "-frames:v",
            "1",
            "-threads",
            "2",
            "-f",
            "null",
            "-",
        ]
    )
    duration = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", result.stderr)
    dimensions = re.search(r"Video:.*?\b(\d{2,5})x(\d{2,5})\b", result.stderr)
    if not duration or not dimensions:
        raise InvalidVideo("Video duration and resolution must be available")
    hours, minutes, seconds = map(float, duration.groups())
    seconds += hours * 3600 + minutes * 60
    width, height = map(int, dimensions.groups())
    if (
        not math.isfinite(seconds)
        or not 0 < seconds <= max_seconds
        or min(width, height) < 2
        or max(width, height) > 3840
        or width * height > 3840 * 2160
    ):
        raise InvalidVideo("Video exceeds the duration or resolution limit")
    return {"duration": seconds, "width": width, "height": height}


def convert_video(source: Path, destination: Path, *, max_bytes=100 * 1024 * 1024, max_seconds=120):
    source = source.resolve(strict=True)
    inspect_video(source, max_bytes=max_bytes, max_seconds=max_seconds)
    # Una carpeta nueva evita sobrescribir el original u otra conversión.
    destination.mkdir(parents=True, exist_ok=False)
    output = destination / "web720.mp4"
    try:
        run(
            [
                *input_args(source),
                "-map",
                "0:v:0",
                "-map",
                "0:a:0?",
                "-map_metadata",
                "-1",
                "-map_chapters",
                "-1",
                "-sn",
                "-dn",
                "-t",
                str(max_seconds + 1),
                "-vf",
                "scale=w='min(1280,iw)':h='min(720,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2,setsar=1",
                "-filter_threads",
                "1",
                "-c:v",
                "libx264",
                "-threads",
                "2",
                "-preset",
                "fast",
                "-crf",
                "24",
                "-pix_fmt",
                "yuv420p",
                "-r",
                "30",
                "-maxrate",
                "2M",
                "-bufsize",
                "4M",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                "-ac",
                "2",
                "-movflags",
                "+faststart",
                "-fs",
                "52428800",
                str(output),
            ],
            timeout=150,
        )
        inspect_video(output, max_bytes=52428799, max_seconds=max_seconds + 0.1)
        return output
    except Exception:
        # Un archivo incompleto no debe terminar publicado.
        output.unlink(missing_ok=True)
        destination.rmdir()
        raise
