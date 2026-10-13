"""Audio compression (with fallbacks) and photo resizing."""

from __future__ import annotations

import datetime as dt
import io
import json
import math
import shutil
import struct
import subprocess
import wave
from pathlib import Path

import pytest
from PIL import Image

from lumitrace.config import Settings
from lumitrace.frames.dayfile import day_file_path, parse
from lumitrace.frames.storage.local import LocalStorage
from lumitrace.prism.pipeline.audio import compress_audio, original_ext
from lumitrace.prism.pipeline.llm import LLMClient
from lumitrace.prism.pipeline.photos import resize_photo
from lumitrace.prism.pipeline.processor import CaptureProcessor, CaptureRequest, UploadedFile
from tests.prism.conftest import FakeLLM, NudgeRecorder, image_bytes

OCT10 = dt.date(2026, 10, 10)


def no_tools(name: str) -> None:
    return None


def wav_bytes(seconds: float = 1.0) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(44100)
        frames = int(44100 * seconds)
        w.writeframes(
            b"".join(struct.pack("<hh", int(8000 * math.sin(i / 20)), 0) for i in range(frames))
        )
    return buffer.getvalue()


# --- audio ----------------------------------------------------------------------------------


def test_no_compressor_keeps_original(caplog: pytest.LogCaptureFixture) -> None:
    result = compress_audio(b"RIFFdata", "memo.WAV", 32, which=no_tools)
    assert (result.data, result.ext, result.compressor) == (b"RIFFdata", ".wav", "none")
    assert "neither ffmpeg nor afconvert" in (result.warning or "")
    assert "audio kept uncompressed" in caplog.text
    assert compress_audio(b"x", "Recording.m4a", 32, which=no_tools).ext == ".m4a"
    assert original_ext("voice.MP4") == ".m4a"
    assert original_ext("no-extension") == ".audio"


def test_ffmpeg_failure_falls_back_to_afconvert() -> None:
    commands: list[list[str]] = []

    def run(cmd: list[str], **_: object) -> subprocess.CompletedProcess[bytes]:
        commands.append(cmd)
        if cmd[0] == "ffmpeg":
            return subprocess.CompletedProcess(cmd, 1, b"", b"boom")
        Path(cmd[-1]).write_bytes(b"small")
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    result = compress_audio(b"big original audio", "memo.wav", 24, which=lambda n: n, run=run)
    assert (result.data, result.ext, result.compressor) == (b"small", ".m4a", "afconvert")
    ffmpeg, afconvert = commands
    assert ffmpeg[ffmpeg.index("-ac") + 1] == "1"
    assert ffmpeg[ffmpeg.index("-b:a") + 1] == "24k"
    assert ffmpeg[ffmpeg.index("-c:a") + 1] == "aac"
    assert afconvert[afconvert.index("-b") + 1] == "24000"
    assert afconvert[afconvert.index("-c") + 1] == "1"


def test_all_compressors_failing_keeps_original() -> None:
    def run(cmd: list[str], **_: object) -> subprocess.CompletedProcess[bytes]:
        raise subprocess.TimeoutExpired(cmd, 1)

    result = compress_audio(b"orig", "memo.wav", 32, which=lambda n: n, run=run)
    assert result.compressor == "none"
    assert "ffmpeg: TimeoutExpired; afconvert: TimeoutExpired" in (result.warning or "")


def test_m4a_original_smaller_than_output_is_kept() -> None:
    def run(cmd: list[str], **_: object) -> subprocess.CompletedProcess[bytes]:
        Path(cmd[-1]).write_bytes(b"much bigger output")
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    result = compress_audio(b"tiny", "a.m4a", 32, which=lambda n: n, run=run)
    assert (result.data, result.compressor) == (b"tiny", "none")
    assert result.warning is None


@pytest.mark.skipif(
    not (shutil.which("ffmpeg") or shutil.which("afconvert")), reason="no audio tool installed"
)
def test_real_compressor_makes_mono_m4a() -> None:
    original = wav_bytes(2.0)
    result = compress_audio(original, "memo.wav", 32)
    if result.compressor == "none":
        pytest.skip(f"audio tool present but cannot encode AAC here: {result.warning}")
    assert result.ext == ".m4a"
    assert len(result.data) < len(original) / 10
    assert result.data[4:8] == b"ftyp"


def test_processor_keeps_uncompressed_audio_with_its_extension(
    api_settings: Settings, api_storage: LocalStorage, nudges: NudgeRecorder
) -> None:
    processor = CaptureProcessor(
        api_settings,
        api_storage,
        llm=LLMClient(api_settings, completion_fn=FakeLLM()),
        nudge=nudges,
        compress=lambda data, name, kbps: compress_audio(data, name, kbps, which=no_tools),
    )
    at = dt.datetime(2026, 10, 10, 21, 30, tzinfo=api_settings.tz)
    api_storage.write_bytes("_system/inbox/w/audio.wav", b"Spoken words.")
    req = CaptureRequest(
        id="w",
        kind="recording",
        received_at=at,
        captured_at=at,
        audio=UploadedFile(path="_system/inbox/w/audio.wav", filename="memo.wav"),
    )
    result = processor.process(req)
    assert result.audio == "2026-10-10-2130.wav"
    assert api_storage.read_bytes("2026/10/2026-10-10/2026-10-10-2130.wav") == b"Spoken words."
    assert parse(api_storage.read_text(day_file_path(OCT10))).meta.audio == ["2026-10-10-2130.wav"]
    assert any("audio kept uncompressed" in w for w in result.warnings)
    record = json.loads(api_storage.read_text("_system/activity/2026/10.jsonl"))
    step = next(s for s in record["steps"] if s["name"] == "compress_audio")
    assert step["detail"]["compressor"] == "none"


# --- photos ---------------------------------------------------------------------------------


def test_resize_fits_max_dimension_as_jpeg() -> None:
    out = resize_photo(image_bytes((4000, 3000)), 2048, 85)
    with Image.open(io.BytesIO(out)) as img:
        assert img.format == "JPEG"
        assert img.size == (2048, 1536)
    small = resize_photo(image_bytes((300, 200)), 2048, 85)
    with Image.open(io.BytesIO(small)) as img:
        assert img.size == (300, 200)


def test_resize_applies_exif_rotation_and_strips_exif() -> None:
    img = Image.new("RGB", (400, 100), (10, 20, 30))
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 90° clockwise to display
    exif[0x8825] = {2: (30.0, 15.0, 0.0)}  # some GPS data
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", exif=exif)
    out = resize_photo(buffer.getvalue(), 2048, 85)
    with Image.open(io.BytesIO(out)) as result:
        assert result.size == (100, 400)
        assert not result.getexif()


def test_resize_flattens_transparency() -> None:
    out = resize_photo(image_bytes((50, 50), mode="RGBA"), 2048, 85)
    with Image.open(io.BytesIO(out)) as img:
        assert img.mode == "RGB"


def test_resize_reads_heic() -> None:
    pillow_heif = pytest.importorskip("pillow_heif")
    buffer = io.BytesIO()
    try:
        pillow_heif.from_pillow(Image.new("RGB", (640, 480), (1, 2, 3))).save(buffer, format="HEIF")
    except Exception as exc:
        pytest.skip(f"no HEIF encoder available: {exc}")
    out = resize_photo(buffer.getvalue(), 320, 80)
    with Image.open(io.BytesIO(out)) as img:
        assert (img.format, img.size) == ("JPEG", (320, 240))


def test_resize_rejects_non_images() -> None:
    with pytest.raises(OSError):
        resize_photo(b"definitely not an image", 2048, 85)


def test_processor_numbers_photos_and_skips_bad_ones(
    processor: CaptureProcessor, api_settings: Settings, api_storage: LocalStorage
) -> None:
    def request(capture_id: str, minute: int, photos: list[bytes]) -> CaptureRequest:
        at = dt.datetime(2026, 10, 10, 21, minute, tzinfo=api_settings.tz)
        refs = []
        for i, data in enumerate(photos, start=1):
            path = f"_system/inbox/{capture_id}/photo-{i:02d}.png"
            api_storage.write_bytes(path, data)
            refs.append(UploadedFile(path=path, filename=f"IMG_{i}.png"))
        return CaptureRequest(
            id=capture_id, kind="note", received_at=at, captured_at=at, text="Pics.", photos=refs
        )

    settings_dim = api_settings.photo_max_dimension
    first = processor.process(request("p1", 0, [image_bytes((3000, 1000)), b"broken"]))
    assert first.photos == ["photo-01.jpg"]
    assert any(w.startswith("photos: skipped one") for w in first.warnings)
    second = processor.process(request("p2", 5, [image_bytes(), image_bytes()]))
    assert second.photos == ["photo-02.jpg", "photo-03.jpg"]
    with Image.open(io.BytesIO(api_storage.read_bytes("2026/10/2026-10-10/photo-01.jpg"))) as img:
        assert max(img.size) == settings_dim
    day = parse(api_storage.read_text(day_file_path(OCT10)))
    assert day.meta.photos == ["photo-01.jpg", "photo-02.jpg", "photo-03.jpg"]
