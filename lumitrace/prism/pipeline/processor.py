"""Process one capture end to end: transcribe, store audio and photos, merge into the day file,
record activity, nudge the indexer.

The journal is not written on every capture. While the day is still open (before the rollover
hour, 4 a.m. by default) the transcript is saved and a due marker is left under
``_system/journal-due/``. :meth:`CaptureProcessor.generate_pending` writes the facts and journal
once, for days that have closed. :meth:`CaptureProcessor.generate_day` does that same write
early, for one day, when Flash asks. A day that has already closed (a late upload, or a restart
after 4 a.m.) is written immediately.

Order matters for safety:

1. Compress and transcribe first. If transcription fails nothing has been written, so the capture
   can simply be retried from the inbox.
2. Write audio, photos and the day file with the new transcript block. From here on the capture
   is saved even if the AI steps fail.
3. When the journal is written, re-read the day file and apply the result to the *fresh* copy,
   so an edit the owner made in the meantime is detected and kept.
"""

from __future__ import annotations

import datetime as dt
import logging
import threading
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from lumitrace.frames.daycontent import (
    DayContent,
    apply_timeline_patches,
    from_legacy_day,
    to_legacy_facts,
)
from lumitrace.frames.dayfile import (
    FORMAT_VERSION,
    Capture,
    CaptureKind,
    DayFacts,
    DayFile,
    GeneratedFactsState,
    apply_content_generation,
    audio_file_name,
    content_for_day,
    day_dir,
    day_file_path,
    default_title,
    entry_date,
    generated_facts_path,
    generated_snapshot_path,
    merge_capture,
    merge_content_generation_three_way,
    next_photo_names,
    parse,
    remove_capture,
    render,
    system_path,
    unique_file_name,
)
from lumitrace.nudge import nudge_indexer
from lumitrace.prism.pipeline.activity import ActivityLog, ActivityRecord, safe_error
from lumitrace.prism.pipeline.audio import AudioResult, compress_audio
from lumitrace.prism.pipeline.generate import Generator
from lumitrace.prism.pipeline.llm import LLMClient, LLMError, LLMResult
from lumitrace.prism.pipeline.photos import resize_photo
from lumitrace.prism.pipeline.prompts import Prompt, join_prompt_labels
from lumitrace.prism.pipeline.stt import Transcriber, get_transcriber

if TYPE_CHECKING:
    from lumitrace.config import Settings
    from lumitrace.frames.storage import Storage

log = logging.getLogger(__name__)

NudgeFn = Callable[["Settings", Sequence[str]], bool]
STT_MAX_BYTES = 24 * 1024 * 1024
"""Hosted transcription APIs reject larger files (OpenAI: 25 MB); use the compressed copy."""
STT_FORMATS = {".m4a", ".mp3", ".mp4", ".mpeg", ".mpga", ".wav", ".webm", ".ogg", ".flac"}
JOURNAL_DUE_DIR = "journal-due"
"""``_system/journal-due/YYYY-MM-DD.txt``: a day whose journal is still to be written."""


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
    """``deferred`` (saved; journal waits until the day closes), ``full`` (the 4:05 write),
    ``update`` (changed source merged into a written journal), ``unchanged``, ``skipped`` or
    ``failed``."""
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class _Generated(BaseModel):
    """Output of the AI steps, ready to apply to a fresh copy of the day."""

    mode: str
    content: DayContent
    headline: str = ""
    rewrite_content: bool = False
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
        now: Callable[[], dt.datetime] | None = None,
    ) -> None:
        self.settings = settings
        self.storage = storage
        self.transcriber = transcriber or get_transcriber(settings)
        self.generator = Generator(llm or LLMClient(settings), settings.prompts_dir)
        self.activity = ActivityLog(storage)
        self._nudge = nudge or (lambda s, paths: nudge_indexer(s, paths))
        self._compress = compress or compress_audio
        self._now_fn = now or (lambda: dt.datetime.now(dt.UTC))
        # One writer of day files: a capture and the morning journal never run together.
        self._day_lock = threading.Lock()

    # --- public -------------------------------------------------------------------------

    def entry_date_for(self, captured_at: dt.datetime) -> dt.date:
        return entry_date(captured_at, self.settings.tz, self.settings.day_rollover_hour)

    def entry_date_of(self, req: CaptureRequest) -> dt.date:
        return req.entry_date or self.entry_date_for(req.captured_at)

    def process(self, req: CaptureRequest, attempt: int = 1) -> ProcessResult:
        """Process a capture. Writes one activity record either way; re-raises fatal errors."""
        with self._day_lock:
            return self._process_locked(req, attempt)

    def generate_pending(self) -> list[tuple[dt.date, str]]:
        """Write the journal for every closed day that still has a due marker.

        Returns ``(date, status)`` with status ``full``, ``update``, ``unchanged``, ``skipped``
        or ``failed``.
        A failed day keeps its marker so the next run tries again. An open day is left for the
        run after it closes, unless :meth:`generate_day` is asked to write it now.
        """
        with self._day_lock:
            return self._generate_pending_locked()

    def generate_day(
        self, day_date: dt.date, *, nudge: bool = True, replace_generated: bool = False
    ) -> str:
        """Generate or update one day from its transcripts and My notes.

        The first call fills the title and journal. A later call with new recordings or notes
        rewrites the journal when it is still the model's, and otherwise corrects contradicted
        model sentences and adds what is missing. Facts follow the new complete reply except
        where the owner changed them. ``replace_generated`` runs that update even when the
        source was already processed, so a prompt fix can rewrite model-owned text.
        ``skipped`` means there is no source material; ``unchanged`` means it was already used.
        ``failed`` keeps the due marker so a later run tries again.
        """
        with self._day_lock:
            return self._generate_closed(day_date, nudge=nudge, replace_generated=replace_generated)

    def drop_capture(self, day_date: dt.date, capture_id: str) -> list[str]:
        """Remove one capture from the day file and delete its audio and photos.

        The caller must have checked that the journal has not used this capture. Returns the
        storage paths that changed (for a Spectrum nudge).
        """
        with self._day_lock:
            return self._drop_capture_locked(day_date, capture_id)

    def generation_mode(self, day_date: dt.date, *, replace_generated: bool = False) -> str:
        """Return ``full``, ``update``, ``unchanged`` or ``skipped`` without calling the model."""
        day = self._read_day(day_date)
        if day is None or not (day.notes.strip() or any(c.text.strip() for c in day.captures)):
            return "skipped"
        source_hash = day.compute_source_hash()
        facts_state = self._read_generated_facts(day_date)
        if (
            not replace_generated
            and day.meta.generated_at is not None
            and day.meta.generated_source_hash == source_hash
            and facts_state is not None
            and facts_state.source_hash == source_hash
        ):
            return "unchanged"
        return "update" if day.meta.generated_at is not None else "full"

    def _process_locked(self, req: CaptureRequest, attempt: int) -> ProcessResult:
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
        # Read before the capture write. That write copies the live file, including hand
        # edits, over the snapshot, and the update still needs the previous model text.
        baseline = self._read_snapshot(day_date)
        capture = next((c for c in existing.captures if c.id == req.id), None) if existing else None
        if capture is None:
            capture = self._build_capture(req, local, day_date, record)
            with record.step("write_day") as step:
                day = merge_capture(self._read_day(day_date), capture, day_date)
                self._note_baseline(day)
                self._write_day(day)
                step.detail = {"captures": len(day.captures)}
        else:
            record.warnings.append("capture already in the day file; checking journal only")

        day = self._read_day(day_date)
        has_words = day is not None and (
            bool(day.notes.strip()) or any(c.text.strip() for c in day.captures)
        )
        if not has_words:
            generation = "skipped"
        elif not self._day_is_closed(day_date):
            self._mark_due(day_date)
            generation = "deferred"
        else:
            self._mark_due(day_date)
            generation = self._generate(day_date, record, baseline=baseline)
            if generation != "failed":
                self._clear_due(day_date)
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
        translation = ""  # not stored; the journal reads the Telugu transcript (ADR 0057)
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
            translation = ""

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

    # --- when the journal is written ------------------------------------------------------

    def _now(self) -> dt.datetime:
        return self._now_fn()

    def _open_day(self) -> dt.date:
        return entry_date(self._now(), self.settings.tz, self.settings.day_rollover_hour)

    def _day_is_closed(self, day: dt.date) -> bool:
        """True once the rollover hour has passed and this day no longer accepts new captures
        as "today"."""
        return day < self._open_day()

    @staticmethod
    def _due_path(day: dt.date) -> str:
        return system_path(JOURNAL_DUE_DIR, f"{day.isoformat()}.txt")

    def _mark_due(self, day: dt.date) -> None:
        self.storage.write_text(self._due_path(day), "due\n")

    def _clear_due(self, day: dt.date) -> None:
        self.storage.delete(self._due_path(day), missing_ok=True)

    def _due_dates(self) -> list[dt.date]:
        found: list[dt.date] = []
        for info in self.storage.list(system_path(JOURNAL_DUE_DIR)):
            name = info.path.rsplit("/", 1)[-1]
            if not name.endswith(".txt"):
                continue
            try:
                found.append(dt.date.fromisoformat(name.removesuffix(".txt")))
            except ValueError:
                continue
        return sorted(found)

    def _generate_pending_locked(self) -> list[tuple[dt.date, str]]:
        outcomes: list[tuple[dt.date, str]] = []
        for day_date in self._due_dates():
            if not self._day_is_closed(day_date):
                continue
            outcomes.append((day_date, self._generate_closed(day_date)))
        return outcomes

    def _generate_closed(
        self, day_date: dt.date, *, nudge: bool = True, replace_generated: bool = False
    ) -> str:
        if self.generation_mode(day_date, replace_generated=replace_generated) == "skipped":
            self._clear_due(day_date)
            return "skipped"
        record = ActivityRecord(
            capture_id=f"journal-{day_date.isoformat()}",
            kind="journal",
            entry_date=day_date,
            received_at=self._now(),
        )
        try:
            generation = self._generate(day_date, record, replace_generated=replace_generated)
        except Exception as exc:
            record.errors.append(f"fatal: {safe_error(exc)}")
            record.finish("failed")
            self.activity.append(record)
            raise
        record.generation = generation
        record.finish("done" if generation != "failed" else "failed")
        self.activity.append(record)
        if generation != "failed":
            self._clear_due(day_date)
            if nudge:
                self._nudge_day(day_date)
        return generation

    def _nudge_day(self, day_date: dt.date) -> None:
        try:
            self._nudge(self.settings, [day_file_path(day_date)])
        except Exception as exc:
            log.warning("nudge after journal %s failed: %s", day_date, safe_error(exc))

    def _drop_capture_locked(self, day_date: dt.date, capture_id: str) -> list[str]:
        day = self._read_day(day_date)
        folder = day_dir(day_date)
        gone = None if day is None else next((c for c in day.captures if c.id == capture_id), None)
        paths: list[str] = []
        if gone is not None:
            names = [gone.audio, *gone.photos] if gone.audio else list(gone.photos)
            paths = [f"{folder}/{name}" for name in names]
            for path in paths:
                self.storage.delete(path, missing_ok=True)
        day_path = day_file_path(day_date)
        snapshot_path = generated_snapshot_path(day_date)
        if day is not None and gone is not None:
            updated = remove_capture(day, capture_id)
            if self._keep_day(updated):
                self._write_day(updated)
                if not (updated.notes.strip() or any(c.text.strip() for c in updated.captures)):
                    self._clear_due(day_date)
                paths.append(day_path)
            else:
                self.storage.delete(day_path, missing_ok=True)
                self.storage.delete(snapshot_path, missing_ok=True)
                self._clear_due(day_date)
                paths.extend([day_path, snapshot_path])
        try:
            if paths:
                self._nudge(self.settings, paths)
        except Exception as exc:
            log.warning("nudge after discard %s failed: %s", capture_id, safe_error(exc))
        return paths

    @staticmethod
    def _keep_day(day: DayFile) -> bool:
        if day.captures or day.notes.strip() or day.journal.strip():
            return True
        if day.meta.generated_at is not None:
            return True
        if day.content is not None and day.content != DayContent():
            return True
        return not day.facts.is_empty()

    @staticmethod
    def _note_baseline(day: DayFile) -> None:
        """Remember the generated-looking content and title before the owner can edit.

        A day we just created is empty, so its hash matches and the 4:05 write may replace the
        journal. The 4:05 write is the day's journal. A recording that arrives after that write
        only adds.
        """
        if day.meta.generated_hash is not None:
            return
        blank = DayFile(meta=day.meta.model_copy(update={"generated_hash": None}))
        blank.content = DayContent() if day.content is not None else None
        blank.journal = ""
        blank.facts = DayFacts()
        blank.title = default_title(day.date)
        if day.compute_generated_hash() != blank.compute_generated_hash():
            day.meta.generated_hash = blank.compute_generated_hash()
        else:
            day.meta.generated_hash = day.compute_generated_hash()

    # --- generation ---------------------------------------------------------------------

    def _generate(
        self,
        day_date: dt.date,
        record: ActivityRecord,
        *,
        baseline: DayFile | None = None,
        replace_generated: bool = False,
    ) -> str:
        mode = self.generation_mode(day_date, replace_generated=replace_generated)
        if mode in ("skipped", "unchanged"):
            return mode
        day = self._read_day(day_date)
        assert day is not None
        source_hash = day.compute_source_hash()
        facts_state = self._read_generated_facts(day_date)
        snapshot = baseline if baseline is not None else self._read_snapshot(day_date)
        base_content = self._base_content(facts_state, snapshot)
        source_changed = day.meta.generated_source_hash != source_hash
        content_clean = self._content_is_model_owned(day, base_content)
        legacy = day.content is None or day.meta.lumitrace_format < FORMAT_VERSION
        rewrite_content = (
            mode == "full" or replace_generated or legacy or (content_clean and source_changed)
        )
        generated = self._run_ai(
            mode,
            day,
            record,
            base_content=base_content,
            rewrite_content=rewrite_content and mode != "full",
        )
        if generated is None:
            return "failed"
        with record.step("write_day") as step:
            fresh = self._read_day(day_date)
            assert fresh is not None
            updated = self._apply(
                fresh,
                generated,
                record.models.get("stt"),
                base_content=base_content,
                generated_source_hash=source_hash,
            )
            self._write_day(updated)
            self._write_generated_facts(
                day_date,
                source_hash=source_hash,
                content=generated.content,
            )
            step.detail = {"mode": mode, "rewrite_content": generated.rewrite_content}
        return mode

    @staticmethod
    def _base_content(
        facts_state: GeneratedFactsState | None, snapshot: DayFile | None
    ) -> DayContent | None:
        """Previous model content. Legacy facts and journals are converted on first use."""
        if facts_state is not None:
            if facts_state.content is not None:
                return facts_state.content
            return from_legacy_day(
                facts_state.facts.model_dump(mode="json"),
                facts_state.journal or "",
            )
        if snapshot is not None:
            return content_for_day(snapshot)
        return None

    @staticmethod
    def _content_is_model_owned(day: DayFile, model_content: DayContent | None) -> bool:
        if day.content is None or day.meta.lumitrace_format < FORMAT_VERSION:
            return not day.is_user_edited()
        if model_content is not None:
            return content_for_day(day) == model_content
        return not day.is_user_edited()

    def _run_ai(
        self,
        mode: str,
        day: DayFile,
        record: ActivityRecord,
        *,
        base_content: DayContent | None,
        rewrite_content: bool,
    ) -> _Generated | None:
        gen = self.generator
        if mode == "full" or rewrite_content:
            filled = self._llm_step(
                record,
                "fill_day",
                lambda: gen.fill_day(day.date, day.captures, day.notes),
            )
            if filled is None:
                return None
            draft = filled[0].value
            return _Generated(
                mode=mode,
                content=draft.content,
                headline=draft.headline,
                rewrite_content=rewrite_content,
                models={"fill_day": filled[0].model},
                prompt_labels=[filled[1].label],
            )

        updated = self._llm_step(
            record,
            "update_day",
            lambda: gen.update_day(day.date, day.captures, day.notes, render(day)),
        )
        if updated is None:
            return None
        addition = updated[0].value
        model_base = (base_content or content_for_day(day)).model_copy(deep=True)
        patched_timeline = apply_timeline_patches(
            model_base.timeline,
            additions=addition.additions,
            replacements=addition.replacements,
            deletions=addition.deletions,
        )
        structured = addition.content
        patched_timeline = patched_timeline.model_copy(
            update={
                "highlight": structured.timeline.highlight,
                "context": structured.timeline.context,
                "remember": structured.timeline.remember,
            },
            deep=True,
        )
        model_content = model_base.model_copy(
            update={
                "timeline": patched_timeline,
                "family": structured.family,
                "pregnancy_baby": structured.pregnancy_baby,
                "tags": structured.tags,
            },
            deep=True,
        )
        return _Generated(
            mode=mode,
            content=model_content,
            models={"update_day": updated[0].model},
            prompt_labels=[updated[1].label],
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
                return result
        except Exception:
            log.warning("%s failed for capture %s", name, record.capture_id)
            return None

    @staticmethod
    def _apply(
        day: DayFile,
        generated: _Generated,
        stt_model: str | None,
        *,
        base_content: DayContent | None,
        generated_source_hash: str,
    ) -> DayFile:
        models_used = {**day.meta.models_used, **generated.models}
        if stt_model:
            models_used["stt"] = stt_model
        prompt_version = join_prompt_labels(generated.prompt_labels) or None
        if generated.mode == "full":
            title = default_title(day.date)
            if generated.headline:
                title = f"{title} · {generated.headline}"
            if day.is_user_edited():
                return merge_content_generation_three_way(
                    day,
                    base_content=base_content or DayContent(),
                    content=generated.content,
                    prompt_version=prompt_version,
                    models_used=models_used,
                    generated_source_hash=generated_source_hash,
                )
            return apply_content_generation(
                day,
                content=generated.content,
                title=title,
                prompt_version=prompt_version,
                models_used=models_used,
                generated_source_hash=generated_source_hash,
                force=True,
            )
        return merge_content_generation_three_way(
            day,
            base_content=base_content,
            content=generated.content,
            prompt_version=prompt_version,
            models_used=models_used,
            generated_source_hash=generated_source_hash,
        )

    # --- storage helpers ----------------------------------------------------------------

    def _read_day(self, day_date: dt.date) -> DayFile | None:
        path = day_file_path(day_date)
        try:
            text = self.storage.read_text(path)
        except FileNotFoundError:
            return None
        return parse(text, fallback_date=day_date)

    def _read_snapshot(self, day_date: dt.date) -> DayFile | None:
        path = generated_snapshot_path(day_date)
        if not self.storage.exists(path):
            return None
        try:
            return parse(self.storage.read_text(path), fallback_date=day_date)
        except Exception as exc:
            log.warning("cannot read generated snapshot for %s: %s", day_date, safe_error(exc))
            return None

    def _read_generated_facts(self, day_date: dt.date) -> GeneratedFactsState | None:
        path = generated_facts_path(day_date)
        if not self.storage.exists(path):
            return None
        try:
            state = GeneratedFactsState.model_validate_json(self.storage.read_text(path))
        except Exception as exc:
            log.warning("cannot read generated facts for %s: %s", day_date, safe_error(exc))
            return None
        if state.date != day_date:
            log.warning(
                "generated facts date mismatch for %s: %s",
                day_date,
                state.date,
            )
            return None
        return state

    def _write_generated_facts(
        self,
        day_date: dt.date,
        *,
        source_hash: str,
        content: DayContent,
    ) -> None:
        state = GeneratedFactsState(
            date=day_date,
            source_hash=source_hash,
            facts=DayFacts.model_validate(to_legacy_facts(content)),
            content=content,
        )
        self.storage.write_text(
            generated_facts_path(day_date),
            state.model_dump_json(indent=2) + "\n",
            content_type="application/json",
        )

    def _write_day(self, day: DayFile) -> None:
        text = render(day)
        self.storage.write_text(day_file_path(day.date), text)
        self.storage.write_text(generated_snapshot_path(day.date), text)
