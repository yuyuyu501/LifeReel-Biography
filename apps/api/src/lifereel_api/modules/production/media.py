from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from lifereel_api.modules.production.providers import VideoProviderError


def require_media_tools() -> None:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise VideoProviderError("VIDEO_ASSEMBLY_UNAVAILABLE")


def probe_video(path: Path, require_audio: bool = True) -> dict:
    require_media_tools()
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
            capture_output=True,
            check=True,
            timeout=30,
        )
        data = json.loads(result.stdout)
        video = next(stream for stream in data["streams"] if stream["codec_type"] == "video")
        audio = next(
            (stream for stream in data["streams"] if stream["codec_type"] == "audio"), None
        )
        duration = float(data["format"]["duration"])
        if duration <= 0 or (require_audio and not audio):
            raise ValueError("Missing audio or duration")
        return {
            "duration_seconds": duration,
            "width": video["width"],
            "height": video["height"],
            "has_audio": audio is not None,
            "audio_codec": audio["codec_name"] if audio else None,
        }
    except (subprocess.SubprocessError, ValueError, KeyError, StopIteration) as exc:
        raise VideoProviderError("VIDEO_PROVIDER_OUTPUT_INVALID") from exc


def last_frame(path: Path) -> bytes:
    try:
        result = subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-sseof",
                "-0.15",
                "-i",
                str(path),
                "-frames:v",
                "1",
                "-vf",
                "scale=640:-2",
                "-f",
                "image2pipe",
                "-vcodec",
                "mjpeg",
                "-",
            ],
            capture_output=True,
            check=True,
            timeout=30,
        )
        if not result.stdout:
            raise ValueError("No reference frame")
        return result.stdout
    except (subprocess.SubprocessError, ValueError) as exc:
        raise VideoProviderError("VIDEO_ASSEMBLY_FAILED") from exc


def assemble_videos(paths: list[Path], directory: Path, config: dict) -> tuple[bytes, dict]:
    require_media_tools()
    dimensions = {"16:9": (1280, 720), "9:16": (720, 1280), "1:1": (720, 720)}
    if config["ratio"] not in dimensions or config["resolution"] not in {"720p", "480p"}:
        raise VideoProviderError("VIDEO_PROVIDER_CONFIGURATION_INCOMPLETE")
    width, height = dimensions[config["ratio"]]
    if config["resolution"] == "480p":
        width, height = width * 2 // 3 // 2 * 2, height * 2 // 3 // 2 * 2
    audio = config["generate_audio"]
    try:
        for index, path in enumerate(paths):
            probe_video(path, audio)
            subprocess.run(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-y",
                    "-i",
                    str(path),
                    "-map",
                    "0:v:0",
                    *(["-map", "0:a:0"] if audio else ["-an"]),
                    "-vf",
                    f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                    f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=24",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "veryfast",
                    "-crf",
                    "20",
                    "-pix_fmt",
                    "yuv420p",
                    "-threads",
                    "2",
                    *(["-c:a", "aac", "-ar", "48000", "-ac", "1", "-b:a", "128k"] if audio else []),
                    "-movflags",
                    "+faststart",
                    str(directory / f"normalized-{index}.mp4"),
                ],
                capture_output=True,
                check=True,
                timeout=300,
            )
        listing = directory / "concat.txt"
        listing.write_text(
            "\n".join(f"file 'normalized-{index}.mp4'" for index in range(len(paths))),
            encoding="ascii",
        )
        output = directory / "chapter.mp4"
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-f",
                "concat",
                "-safe",
                "1",
                "-i",
                str(listing),
                "-c",
                "copy",
                "-movflags",
                "+faststart",
                str(output),
            ],
            capture_output=True,
            check=True,
            timeout=120,
        )
        info = probe_video(output, audio)
        return output.read_bytes(), info
    except subprocess.SubprocessError as exc:
        raise VideoProviderError("VIDEO_ASSEMBLY_FAILED") from exc
