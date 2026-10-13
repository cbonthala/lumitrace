"""Process one capture end to end: transcribe, store audio and photos, merge into the day file,
regenerate facts and journal without overwriting the owner's edits, record activity, nudge the
indexer.

Order matters for safety:

1. Compress and transcribe first. If transcription fails nothing has been written, so the capture
   can simply be retried from the inbox.
2. Write audio, photos and the day file with the new transcript block. From here on the capture
   is saved even if the AI steps fail.
3. Run the AI steps, then re-read the day file and apply the result to the *fresh* copy, so an
   edit the owner made in the meantime is detected and kept.
"""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from lumitrace.frames.dayfile import (
    CAPTURE_LABELS,
    Capture,
    CaptureKind,
    DayFacts,
    DayFile,
    apply_generation,
    audio_file_name,
    day_dir,
    day_file_path,
    default_title,
    entry_date,
    generated_snapshot_path,
    merge_capture,
    merge_generation_additive,
    next_photo_names,
    parse,
    render,
    unique_file_name,
)
from lumitrace.nudge import nudge_indexer
from lumitrace.prism.pipeline.activity import ActivityLog, ActivityRecord, safe_error
from lumitrace.prism.pipeline.audio import AudioResult, compress_audio
from lumitrace.prism.pipeline.generate import Generator
from lumitrace.prism.pipeline.llm import LLMClient, LLMError, LLMResult
from lumitrace.prism.pipeline.photos import resize_photo
from lumitrace.prism.pipeline.prompts import Prompt, combined_version
from lumitrace.prism.pipeline.stt import Transcriber, get_transcriber

if TYPE_CHECKING:
    from lumitrace.config import Settings
    from lumitrace.frames.storage import Storage

log = logging.getLogger(__name__)

NudgeFn = Callable[["Settings", Sequence[str]], bool]
STT_MAX_BYTES = 24 * 1024 * 1024
"""Hosted transcription APIs reject larger files (OpenAI: 25 MB); use the compressed copy."""
STT_FORMATS = {".m4a", ".mp3", ".mp4", ".mpeg", ".mpga", ".wav", ".webm", ".ogg", ".flac"}


class UploadedFile(BaseModel):
    path: str
    """Storage path of the raw upload in the inbox."""
    filename: str
    """The client's file name (only its extension is used)."""
    size: int = 0


class CaptureRequest(BaseModel):
    """Everything the API received for one capture (the inbox manifest)."""

    id: str
    kind: CaptureKind
    received_at: dt.datetime
    captured_at: dt.datetime
    """Timezone-aware."""
    entry_date: dt.date | None = None
    """The day chosen by the sender (``date`` field); None = derived from ``captured_at``."""
    text: str = ""
    """Typed note text (notes only)."""
    location: str | None = None
    audio: UploadedFile | None = None
    photos: list[UploadedFile] = Field(default_factory=list)


class ProcessResult(BaseModel):
    entry_date: dt.date
    day_file: str
    audio: str | None = None
    photos: list[str] = Field(default_factory=list)
    generation: str
    """``full``, ``additive``, ``skipped`` or ``failed`` (transcript saved, AI steps failed)."""
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class _Generated(BaseModel):
    """Output of the AI steps, ready to apply to a fresh copy of the day."""

    mode: str
    facts: DayFacts
    journal: str | None = None
    headline: str = ""
    addendum: str | None = None
    models: dict[str, str] = Field(default_factory=dict)
    prompt_labels: list[str] = Field(default_factory=list)


class CaptureProcessor:
    def __init__(
        self,
        settings: Settings,
        storage: Storage,
        *,
        transcriber: Transcriber | None = None,
        llm: LLMClient | None = None,
        nudge: NudgeFn | None = None,
        compress: Callable[[bytes, str, int], AudioResult] | None = None,
    ) -> None:
        self.settings = settings
        self.storage = storage
        self.transcriber = transcriber or get_transcriber(settings)
        self.generator = Generator(llm or LLMClient(settings), settings.prompts_dir)
        self.activity = ActivityLog(storage)
        self._nudge = nudge or (lambda s, paths: nudge_indexer(s, paths))
        self._compress = compress or compress_audio

    # --- public -------------------------------------------------------------------------

    def entry_date_for(self, captured_at: dt.datetime) -> dt.date:
        return entry_date(captured_at, self.settings.tz, self.settings.day_rollover_hour)

    def entry_date_of(self, req: CaptureRequest) -> dt.date:
        return req.entry_date or self.entry_date_for(req.captured_at)

    def process(self, req: CaptureRequest, attempt: int = 1) -> ProcessResult:
        """Process a capture. Writes one activity record either way; re-raises fatal errors."""
        local = req.captured_at.astimezone(self.settings.tz)
        day_date = self.entry_date_of(req)
        record = ActivityRecord(
            capture_id=req.id,
            kind=req.kind,
            attempt=attempt,
            entry_date=day_date,
            received_at=req.received_at,
        )
        try:
            result = self._process(req, local, day_date, record)
        except Exception as exc:
            message = f"fatal: {safe_error(exc)}"
            if not any(e.endswith(safe_error(exc)) for e in record.errors):
                record.errors.append(message)
            record.finish("failed")
            self.activity.append(record)
            raise
        record.finish("done")
        self.activity.append(record)
        result.errors = list(record.errors)
        result.warnings = list(record.warnings)
        return result

    # --- steps --------------------------------------------------------------------------

    def _process(
        self, req: CaptureRequest, local: dt.datetime, day_date: dt.date, record: ActivityRecord
    ) -> ProcessResult:
        day_path = day_file_path(day_date)
        existing = self._read_day(day_date)
        capture = next((c for c in existing.captures if c.id == req.id), None) if existing else None
        if capture is None:
            capture = self._build_capture(req, local, day_date, record)
            with record.step("write_day") as step:
                day = merge_capture(self._read_day(day_date), capture, day_date)
                self._write_day(day)
                step.detail = {"captures": len(day.captures)}
        else:
            record.warnings.append("capture already in the day file; regenerating only")

        generation = self._generate(day_date, capture, local, record)
        record.generation = generation

        paths = [day_path]
        if capture.audio:
            paths.append(f"{day_dir(day_date)}/{capture.audio}")
        paths.extend(f"{day_dir(day_date)}/{p}" for p in capture.photos)
        with record.step("nudge") as step:
            try:
                step.detail = {"accepted": bool(self._nudge(self.settings, paths))}
            except Exception as exc:
                step.detail = {"accepted": False, "error": safe_error(exc)}
        return ProcessResult(
            entry_date=day_date,
            day_file=day_path,
            audio=capture.audio,
            photos=list(capture.photos),
            generation=generation,
        )

    def _build_capture(
        self, req: CaptureRequest, local: dt.datetime, day_date: dt.date, record: ActivityRecord
    ) -> Capture:
        text = req.text.strip()
        translation = ""
        audio: AudioResult | None = None
        if req.audio is not None:
            raw = self.storage.read_bytes(req.audio.path)
            with record.step("compress_audio") as step:
                audio = self._compress(raw, req.audio.filename, self.settings.audio_bitrate_kbps)
                step.detail = {
                    "bytes_in": len(raw),
                    "bytes_out": len(audio.data),
                    "compressor": audio.compressor,
                }
                if audio.warning:
                    record.warnings.append(f"compress_audio: {audio.warning}")
            stt_data, stt_name = self._stt_input(raw, req.audio.filename, audio)
            with record.step("transcribe") as step:
                transcript = self.transcriber.transcribe(stt_data, stt_name)
                step.model = transcript.model
                step.cost_usd = transcript.cost_usd
                detail = {"audio_bytes": len(stt_data), "chars": len(transcript.text)}
                if transcript.translation:
                    detail["translation_chars"] = len(transcript.translation)
                step.detail = detail
            record.warnings.extend(f"transcribe: {w}" for w in transcript.warnings)
            record.models["stt"] = transcript.model
            text = "\n\n".join(t for t in (text, transcript.text) if t)
            translation = transcript.translation

        listing = [f.path.rsplit("/", 1)[-1] for f in self.storage.list(day_dir(day_date))]
        audio_name: str | None = None
        if audio is not None:
            base = audio_file_name(day_date, local)
            audio_name = unique_file_name(base.rsplit(".", 1)[0] + audio.ext, listing)
            self.storage.write_bytes(f"{day_dir(day_date)}/{audio_name}", audio.data)
            listing.append(audio_name)

        photo_names: list[str] = []
        if req.photos:
            with record.step("photos") as step:
                resized: list[bytes] = []
                failed = 0
                for upload in req.photos:
                    try:
                        resized.append(
                            resize_photo(
                                self.storage.read_bytes(upload.path),
                                self.settings.photo_max_dimension,
                                self.settings.photo_jpeg_quality,
                            )
                        )
                    except Exception as exc:
                        failed += 1
                        record.warnings.append(f"photos: skipped one ({safe_error(exc)})")
                photo_names = next_photo_names(listing, len(resized))
                for name, data in zip(photo_names, resized, strict=True):
                    self.storage.write_bytes(f"{day_dir(day_date)}/{name}", data)
                step.detail = {
                    "received": len(req.photos),
                    "saved": len(resized),
                    "skipped": failed,
                    "bytes_out": sum(len(d) for d in resized),
                }

        return Capture(
            id=req.id,
            kind=req.kind,
            captured_at=local,
            text=text,
            translation=translation,
            audio=audio_name,
            photos=photo_names,
            location=req.location,
        )

    @staticmethod
    def _stt_input(raw: bytes, filename: str, audio: AudioResult) -> tuple[bytes, str]:
        """Send the original audio (best quality) unless it is too big or in a format hosted
        APIs reject; then use the compressed ``.m4a`` copy if there is one."""
        suffix = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if suffix in STT_FORMATS and len(raw) <= STT_MAX_BYTES:
            return raw, f"audio{suffix}"
        if audio.compressor != "none":
            return audio.data, f"audio{audio.ext}"
        return raw, f"audio{suffix or audio.ext}"

    # --- generation ---------------------------------------------------------------------

    def _generate(
        self, day_date: dt.date, capture: Capture, local: dt.datetime, record: ActivityRecord
    ) -> str:
        day = merge_capture(self._read_day(day_date), capture, day_date)
        if not any(c.text.strip() for c in day.captures):
            return "skipped"
        for _ in range(2):
            mode = "additive" if day.is_user_edited() else "full"
            if mode == "additive" and not capture.text.strip():
                return "skipped"
            generated = self._run_ai(mode, day, capture, record)
            if generated is None:
                return "failed"
            with record.step("write_day") as step:
                fresh = merge_capture(self._read_day(day_date), capture, day_date)
                if mode == "full" and fresh.is_user_edited():
                    step.detail = {"retry": "edited during generation"}
                    day = fresh
                    continue
                updated = self._apply(fresh, generated, capture, local, record.models.get("stt"))
                self._write_day(updated)
                step.detail = {"mode": mode}
            return mode
        record.warnings.append("day kept changing during generation; journal not updated")
        return "failed"

    def _run_ai(
        self, mode: str, day: DayFile, capture: Capture, record: ActivityRecord
    ) -> _Generated | None:
        gen = self.generator
        labels: list[str] = []
        models: dict[str, str] = {}
        source = day.captures if mode == "full" else [capture]

        facts_result = self._llm_step(
            record, "extract_facts", lambda: gen.extract_facts(day.date, source)
        )
        if facts_result is not None:
            labels.append(facts_result[1].label)
            models["extract_facts"] = facts_result[0].model
        facts = facts_result[0].value if facts_result else None

        if mode == "full":
            journal_result = self._llm_step(
                record,
                "write_journal",
                lambda: gen.write_journal(day.date, day.captures, facts or day.facts),
            )
            if facts_result is None and journal_result is None:
                return None
            journal, headline = day.journal, ""
            if journal_result is not None:
                labels.append(journal_result[1].label)
                models["write_journal"] = journal_result[0].model
                journal = journal_result[0].value.journal
                headline = journal_result[0].value.headline
            return _Generated(
                mode=mode,
                facts=facts or day.facts,
                journal=journal,
                headline=headline,
                models=models,
                prompt_labels=labels,
            )

        addendum_result = self._llm_step(
            record, "journal_addendum", lambda: gen.write_addendum(day.date, capture, day.journal)
        )
        if facts_result is None and addendum_result is None:
            return None
        addendum = None
        if addendum_result is not None:
            labels.append(addendum_result[1].label)
            models["journal_addendum"] = addendum_result[0].model
            addendum = addendum_result[0].value.text or None
        return _Generated(
            mode=mode,
            facts=facts or DayFacts(),
            addendum=addendum,
            models=models,
            prompt_labels=labels,
        )

    @staticmethod
    def _llm_step[T](
        record: ActivityRecord,
        name: str,
        call: Callable[[], tuple[LLMResult[T], Prompt]],
    ) -> tuple[LLMResult[T], Prompt] | None:
        try:
            with record.step(name) as step:
                try:
                    result = call()
                except LLMError as exc:
                    step.detail = {"attempts": [a.__dict__ for a in exc.attempts]}
                    step.error = "all models failed"
                    raise
                step.model = result[0].model
                step.cost_usd = result[0].cost_usd
                if len(result[0].attempts) > 1:
                    step.detail = {"attempts": [a.__dict__ for a in result[0].attempts]}
                record.models[name] = result[0].model
                record.prompt_versions[name] = result[1].version
                return result
        except Exception:
            log.warning("%s failed for capture %s", name, record.capture_id)
            return None

    @staticmethod
    def _apply(
        day: DayFile,
        generated: _Generated,
        capture: Capture,
        local: dt.datetime,
        stt_model: str | None,
    ) -> DayFile:
        models_used = {**day.meta.models_used, **generated.models}
        if stt_model:
            models_used["stt"] = stt_model
        prompt_version = combined_version(generated.prompt_labels) or None
        if generated.mode == "full":
            title = default_title(day.date)
            if generated.headline:
                title = f"{title} · {generated.headline}"
            return apply_generation(
                day,
                facts=generated.facts,
                journal=generated.journal or "",
                title=title,
                prompt_version=prompt_version,
                models_used=models_used,
            )
        label = CAPTURE_LABELS.get(capture.kind, capture.kind)
        return merge_generation_additive(
            day,
            facts=generated.facts,
            journal_addendum=generated.addendum,
            addendum_label=f"{local:%H:%M} · {label}",
            prompt_version=prompt_version,
            models_used=models_used,
        )

    # --- storage helpers ----------------------------------------------------------------

    def _read_day(self, day_date: dt.date) -> DayFile | None:
        path = day_file_path(day_date)
        try:
            text = self.storage.read_text(path)
        except FileNotFoundError:
            return None
        return parse(text, fallback_date=day_date)

    def _write_day(self, day: DayFile) -> None:
        text = render(day)
        self.storage.write_text(day_file_path(day.date), text)
        self.storage.write_text(generated_snapshot_path(day.date), text)
