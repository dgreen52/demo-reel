"""Post-processing: Playwright records .webm; we ship .mp4 + .gif."""

import os
import shutil
import subprocess
from pathlib import Path


def _ffmpeg() -> str:
    """Find ffmpeg: PATH first, then the winget install location."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    winget = (
        Path(os.environ.get("LOCALAPPDATA", ""))
        / "Microsoft" / "WinGet" / "Links" / "ffmpeg.exe"
    )
    if winget.exists():
        return str(winget)
    raise FileNotFoundError("ffmpeg not found on PATH or in winget links")


def _run(args: list[str]) -> None:
    subprocess.run(args, check=True, capture_output=True)


def to_mp4(webm: Path, mp4: Path, trim_start: float = 0.0) -> Path:
    pre = ["-ss", str(trim_start)] if trim_start else []
    _run([_ffmpeg(), "-y", *pre, "-i", str(webm),
          "-c:v", "libx264", "-pix_fmt", "yuv420p",
          "-vf", "crop=trunc(iw/2)*2:trunc(ih/2)*2",  # x264 needs even dims
          "-crf", "22", "-preset", "slow", "-an", str(mp4)])
    return mp4


def to_gif(webm: Path, gif: Path, width: int = 900, fps: int = 12,
           trim_start: float = 0.0) -> Path:
    # Two-pass palette encode: dramatically better colors at readable sizes.
    palette = gif.with_suffix(".palette.png")
    filters = f"fps={fps},scale={width}:-1:flags=lanczos"
    pre = ["-ss", str(trim_start)] if trim_start else []
    _run([_ffmpeg(), "-y", *pre, "-i", str(webm),
          "-vf", f"{filters},palettegen=stats_mode=diff", str(palette)])
    _run([_ffmpeg(), "-y", *pre, "-i", str(webm), "-i", str(palette),
          "-lavfi", f"{filters}[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=4",
          str(gif)])
    palette.unlink(missing_ok=True)
    return gif
