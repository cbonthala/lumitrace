"""Compress voice notes to ``.m4a`` (AAC, mono) at ``BOOKSHELF_AUDIO_BITRATE_KBPS``.

Tries ``ffmpeg`` (in the Docker image), then macOS ``afconvert``. If neither is available or both
fail, the original audio is kept unchanged and a warning is logged, so a capture is never lost
because of compression.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from bookshelf.books.dayfile import AUDIO_EXT

log = logging.getLogger(__name__)

M4A_LIKE = {".m4a", ".mp4"}
_EXT_RE = re.compile(r"^\.[a-z0-9]{1,5}$")


@dataclass(frozen=True)
class AudioResult:
    data: bytes
    ext: str
    """``.m4a`` when compressed (or when the original already was MPEG-4 audio)."""
    compressor: str
    """``ffmpeg``, ``afconvert`` or ``none`` (original kept)."""
    warning: str | None = None


def original_ext(filename: str) -> str:
    """Lower-case extension of an uploaded file, ``.m4a`` for MPEG-4 audio, else ``.audio``."""
    ext = Path(filename).suffix.lower()
    if ext in M4A_LIKE:
        return AUDIO_EXT
    return ext if _EXT_RE.match(ext) else ".audio"


def _commands(src: Path, dst: Path, bitrate_kbps: int) -> list[tuple[str, list[str]]]:
    return [
        (
            "ffmpeg",
            [
                "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                "-i", str(src), "-vn", "-ac", "1", "-c:a", "aac",
                "-b:a", f"{bitrate_kbps}k", "-movflags", "+faststart", str(dst),
            ],
        ),
        (
            "afconvert",
            [
                "afconvert", "-f", "m4af", "-d", "aac", "-c", "1",
                "-b", str(bitrate_kbps * 1000), str(src), str(dst),
            ],
        ),
    ]  # fmt: skip


def compress_audio(
    data: bytes,
    filename: str,
    bitrate_kbps: int,
    *,
    which: Callable[[str], str | None] = shutil.which,
    run: Callable[..., subprocess.CompletedProcess[bytes]] = subprocess.run,
    timeout_seconds: float = 600,
) -> AudioResult:
    """Return compressed ``.m4a`` audio, or the original if no tool could compress it."""
    ext = original_ext(filename)
    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="bookshelf-audio-") as tmp:
        src = Path(tmp) / f"input{Path(filename).suffix.lower() or '.audio'}"
        dst = Path(tmp) / f"output{AUDIO_EXT}"
        src.write_bytes(data)
        for tool, cmd in _commands(src, dst, bitrate_kbps):
            if which(tool) is None:
                continue
            dst.unlink(missing_ok=True)
            try:
                proc = run(cmd, capture_output=True, timeout=timeout_seconds, check=False)
            except (OSError, subprocess.SubprocessError) as exc:
                failures.append(f"{tool}: {type(exc).__name__}")
                continue
            if proc.returncode == 0 and dst.is_file() and dst.stat().st_size > 0:
                out = dst.read_bytes()
                if ext == AUDIO_EXT and len(out) >= len(data):
                    return AudioResult(data, ext, "none", None)
                return AudioResult(out, AUDIO_EXT, tool)
            failures.append(f"{tool}: exit {proc.returncode}")
    reason = "; ".join(failures) if failures else "neither ffmpeg nor afconvert is installed"
    warning = f"audio kept uncompressed ({reason})"
    log.warning(warning)
    return AudioResult(data, ext, "none", warning)
