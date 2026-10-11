"""Speech to text, selected by ``LUMEN_STT_PROVIDER``.

* ``litellm``: ``litellm.transcription`` with ``LUMEN_STT_MODEL`` (OpenAI, Azure, Groq, ...).
* ``aws_transcribe``: Amazon Transcribe batch job via an S3 bucket
  (``LUMEN_AWS_TRANSCRIBE_BUCKET``); the media and output objects are deleted afterwards.
* ``fake``: offline; returns the uploaded bytes as text if they are UTF-8 (tests upload text as
  "audio"), otherwise a fixed placeholder.
"""

from __future__ import annotations

import io
import json
import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from lumen.prism.pipeline.llm import response_cost

if TYPE_CHECKING:
    from lumen.config import Settings

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Transcript:
    text: str
    model: str
    """Recorded in ``models_used["stt"]``: a LiteLLM model string, ``aws_transcribe`` or
    ``fake``."""
    cost_usd: float | None = None


class Transcriber(Protocol):
    def transcribe(self, data: bytes, filename: str) -> Transcript: ...


class FakeTranscriber:
    model = "fake"

    def transcribe(self, data: bytes, filename: str) -> Transcript:
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = ""
        if not text.strip() or any(not (c.isprintable() or c.isspace()) for c in text):
            text = f"(fake transcript of {len(data)} bytes of audio)"
        return Transcript(text=text.strip(), model=self.model)


class LiteLLMTranscriber:
    def __init__(self, settings: Settings, transcription_fn: Callable[..., Any] | None = None):
        self.settings = settings
        self._fn = transcription_fn

    def transcribe(self, data: bytes, filename: str) -> Transcript:
        fn = self._fn
        if fn is None:
            import litellm

            fn = litellm.transcription
        buffer = io.BytesIO(data)
        buffer.name = filename
        resp = fn(
            model=self.settings.stt_model,
            file=buffer,
            language=self.settings.stt_language or None,
            timeout=self.settings.llm_timeout_seconds * 5,
            max_retries=self.settings.llm_max_retries,
        )
        text = resp["text"] if isinstance(resp, dict) else resp.text
        return Transcript(
            text=(text or "").strip(),
            model=self.settings.stt_model,
            cost_usd=response_cost(resp, call_type="transcription"),
        )


AWS_MEDIA_FORMATS = {"mp3", "mp4", "wav", "flac", "ogg", "amr", "webm", "m4a"}
_AWS_LOCALES = {
    "en": "en-US",
    "es": "es-US",
    "fr": "fr-FR",
    "de": "de-DE",
    "it": "it-IT",
    "pt": "pt-BR",
    "nl": "nl-NL",
    "ja": "ja-JP",
    "ko": "ko-KR",
    "zh": "zh-CN",
    "hi": "hi-IN",
}


class AWSTranscribeTranscriber:
    """Batch Amazon Transcribe. Turn on the AWS Organizations AI services opt-out policy so
    the audio is not used to improve AWS models (``docs/prism.md``)."""

    model = "aws_transcribe"
    prefix = "lumen-stt"

    def __init__(
        self,
        settings: Settings,
        *,
        s3: Any = None,
        transcribe: Any = None,
        poll_seconds: float = 3.0,
        timeout_seconds: float = 1800.0,
    ) -> None:
        if not settings.aws_transcribe_bucket:
            raise ValueError("LUMEN_AWS_TRANSCRIBE_BUCKET is required for aws_transcribe")
        self.settings = settings
        self.bucket = settings.aws_transcribe_bucket
        if s3 is None or transcribe is None:
            import boto3

            s3 = s3 or boto3.client("s3", region_name=settings.aws_region)
            transcribe = transcribe or boto3.client("transcribe", region_name=settings.aws_region)
        self.s3 = s3
        self.client = transcribe
        self.poll_seconds = poll_seconds
        self.timeout_seconds = timeout_seconds

    def _language_args(self) -> dict[str, Any]:
        lang = (self.settings.stt_language or "").strip()
        if "-" in lang:
            return {"LanguageCode": lang}
        if lang in _AWS_LOCALES:
            return {"LanguageCode": _AWS_LOCALES[lang]}
        return {"IdentifyLanguage": True}

    def transcribe(self, data: bytes, filename: str) -> Transcript:
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext not in AWS_MEDIA_FORMATS:
            raise ValueError(f"Amazon Transcribe cannot read .{ext} audio")
        job = f"lumen-{uuid.uuid4().hex}"
        media_key = f"{self.prefix}/{job}.{ext}"
        output_key = f"{self.prefix}/{job}.json"
        try:
            self.s3.put_object(Bucket=self.bucket, Key=media_key, Body=data)
            self.client.start_transcription_job(
                TranscriptionJobName=job,
                Media={"MediaFileUri": f"s3://{self.bucket}/{media_key}"},
                MediaFormat=ext,
                OutputBucketName=self.bucket,
                OutputKey=output_key,
                **self._language_args(),
            )
            deadline = time.monotonic() + self.timeout_seconds
            while True:
                status = self.client.get_transcription_job(TranscriptionJobName=job)
                state = status["TranscriptionJob"]["TranscriptionJobStatus"]
                if state == "COMPLETED":
                    break
                if state == "FAILED":
                    reason = status["TranscriptionJob"].get("FailureReason", "unknown")
                    raise RuntimeError(f"Amazon Transcribe job failed: {reason}")
                if time.monotonic() > deadline:
                    raise TimeoutError("Amazon Transcribe job timed out")
                time.sleep(self.poll_seconds)
            body = self.s3.get_object(Bucket=self.bucket, Key=output_key)["Body"].read()
            result = json.loads(body)
            text = " ".join(t["transcript"] for t in result["results"]["transcripts"])
            return Transcript(text=text.strip(), model=self.model)
        finally:
            self._cleanup(job, media_key, output_key)

    def _cleanup(self, job: str, *keys: str) -> None:
        for key in keys:
            try:
                self.s3.delete_object(Bucket=self.bucket, Key=key)
            except Exception as exc:
                log.warning("could not delete s3://%s/%s: %s", self.bucket, key, exc)
        try:
            self.client.delete_transcription_job(TranscriptionJobName=job)
        except Exception as exc:
            log.info("could not delete transcription job %s: %s", job, exc)


def get_transcriber(settings: Settings) -> Transcriber:
    if settings.stt_provider == "fake":
        return FakeTranscriber()
    if settings.stt_provider == "litellm":
        return LiteLLMTranscriber(settings)
    if settings.stt_provider == "aws_transcribe":
        return AWSTranscribeTranscriber(settings)
    raise ValueError(f"unknown stt_provider: {settings.stt_provider!r}")
