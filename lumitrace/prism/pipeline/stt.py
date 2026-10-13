"""Speech to text, selected by ``LUMITRACE_STT_PROVIDER``.

* ``litellm``: ``litellm.transcription`` with ``LUMITRACE_STT_MODEL`` (OpenAI, Azure, Groq, ...).
* ``aws_transcribe``: Amazon Transcribe batch job via an S3 bucket
  (``LUMITRACE_AWS_TRANSCRIBE_BUCKET``); the media and output objects are deleted afterwards.
* ``sarvam``: Sarvam Saaras batch jobs (Indian languages mixed with English, up to 2 hours):
  the transcript in ``LUMITRACE_SARVAM_MODE`` plus, with ``LUMITRACE_SARVAM_TRANSLATE``, an
  English translation of the same audio.
* ``fake``: offline; returns the uploaded bytes as text if they are UTF-8 (tests upload text as
  "audio"), otherwise a fixed placeholder.
"""

from __future__ import annotations

import io
import json
import logging
import mimetypes
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

import httpx

from lumitrace.prism.pipeline.llm import response_cost

if TYPE_CHECKING:
    from lumitrace.config import Settings

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Transcript:
    text: str
    model: str
    """Recorded in ``models_used["stt"]``: a LiteLLM model string, ``aws_transcribe``,
    ``sarvam/<model>`` or ``fake``."""
    cost_usd: float | None = None
    translation: str = ""
    """English translation of the audio, if the provider made one."""
    warnings: tuple[str, ...] = ()
    """Problems that did not stop the transcript (e.g. the translation failed)."""


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
    prefix = "lumitrace-stt"

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
            raise ValueError("LUMITRACE_AWS_TRANSCRIBE_BUCKET is required for aws_transcribe")
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
        job = f"lumitrace-{uuid.uuid4().hex}"
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


SARVAM_API_URL = "https://api.sarvam.ai"
SARVAM_FORMATS = {"wav", "mp3", "aac", "aiff", "ogg", "opus", "flac", "mp4", "m4a", "amr", "webm"}
SARVAM_MAX_KEYTERMS = 50
SARVAM_MAX_KEYTERM_CHARS = 64


class SarvamTranscriber:
    """Sarvam Saaras batch API: create a job, upload to its presigned URL, start, poll, download
    the result JSON. The transcript job and the translation job run at the same time. A failed
    transcript fails the capture (it is retried); a failed translation only adds a warning."""

    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.Client | None = None,
        poll_seconds: float = 3.0,
        timeout_seconds: float = 1800.0,
    ) -> None:
        key = settings.sarvam_api_key.get_secret_value()
        if not key:
            raise ValueError("LUMITRACE_SARVAM_API_KEY is required for sarvam")
        self.settings = settings
        self.model = f"sarvam/{settings.sarvam_model}"
        self._headers = {"api-subscription-key": key}
        self.client = client or httpx.Client(timeout=120)
        self.poll_seconds = poll_seconds
        self.timeout_seconds = timeout_seconds

    def job_parameters(self, mode: str) -> dict[str, Any]:
        lang = (self.settings.stt_language or "").strip()
        params: dict[str, Any] = {
            "model": self.settings.sarvam_model,
            "mode": mode,
            "language_code": lang if "-" in lang else (f"{lang}-IN" if lang else "unknown"),
        }
        terms = [t[:SARVAM_MAX_KEYTERM_CHARS] for t in self.settings.stt_keyterm_list]
        if terms and self.settings.sarvam_model.startswith("saaras:v4"):
            params["keyterms"] = terms[:SARVAM_MAX_KEYTERMS]
        return params

    def transcribe(self, data: bytes, filename: str) -> Transcript:
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext not in SARVAM_FORMATS:
            raise ValueError(f"Sarvam cannot read .{ext} audio")
        name = f"audio.{ext}"
        jobs = {"transcript": self._submit(self.settings.sarvam_mode, name, data)}
        warnings: list[str] = []
        if self.settings.sarvam_translate:
            try:
                jobs["translation"] = self._submit("translate", name, data)
            except Exception as exc:
                warnings.append(f"translation: {_short(exc)}")
        results = self._wait(jobs)
        text = self._output(jobs["transcript"], results["transcript"])
        translation = ""
        if "translation" in jobs:
            try:
                translation = self._output(jobs["translation"], results["translation"])
            except Exception as exc:
                warnings.append(f"translation: {_short(exc)}")
        return Transcript(
            text=text, model=self.model, translation=translation, warnings=tuple(warnings)
        )

    # --- batch job steps ------------------------------------------------------------------

    def _api(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        resp = self.client.request(
            method, f"{SARVAM_API_URL}{path}", headers=self._headers, **kwargs
        )
        _check(resp, f"{method} {path.split('/job/v1')[-1] or '/'}")
        return resp.json()

    def _submit(self, mode: str, name: str, data: bytes) -> str:
        job = self._api(
            "POST", "/speech-to-text/job/v1", json={"job_parameters": self.job_parameters(mode)}
        )
        job_id = job["job_id"]
        links = self._api(
            "POST", "/speech-to-text/job/v1/upload-files", json={"job_id": job_id, "files": [name]}
        )
        url = links["upload_urls"][name]["file_url"]
        resp = self.client.put(
            url,
            content=data,
            headers={
                "x-ms-blob-type": "BlockBlob",
                "Content-Type": mimetypes.guess_type(name)[0] or "application/octet-stream",
            },
        )
        _check(resp, "audio upload")
        self._api("POST", f"/speech-to-text/job/v1/{job_id}/start")
        return job_id

    def _wait(self, jobs: dict[str, str]) -> dict[str, dict[str, Any]]:
        """Poll every job until each is ``Completed`` or ``Failed``."""
        done: dict[str, dict[str, Any]] = {}
        deadline = time.monotonic() + self.timeout_seconds
        while True:
            for key, job_id in jobs.items():
                if key not in done:
                    status = self._api("GET", f"/speech-to-text/job/v1/{job_id}/status")
                    if status.get("job_state") in ("Completed", "Failed"):
                        done[key] = status
            if len(done) == len(jobs):
                return done
            if time.monotonic() > deadline:
                raise TimeoutError("Sarvam job timed out")
            time.sleep(self.poll_seconds)

    def _output(self, job_id: str, status: dict[str, Any]) -> str:
        details = status.get("job_details") or []
        ok = [d for d in details if d.get("state") == "Success" and d.get("outputs")]
        if status.get("job_state") != "Completed" or not ok:
            reason = status.get("error_message") or next(
                (d.get("error_message") for d in details if d.get("error_message")), "unknown"
            )
            raise RuntimeError(f"Sarvam job failed: {reason}")
        output = ok[0]["outputs"][0]["file_name"]
        links = self._api(
            "POST",
            "/speech-to-text/job/v1/download-files",
            json={"job_id": job_id, "files": [output]},
        )
        resp = self.client.get(links["download_urls"][output]["file_url"])
        _check(resp, "result download")
        return (resp.json().get("transcript") or "").strip()


def _check(resp: httpx.Response, what: str) -> None:
    """Raise without echoing the URL: presigned upload and download URLs carry access tokens."""
    if resp.is_success:
        return
    try:
        error = resp.json().get("error")
        message = str(error.get("message", "")) if isinstance(error, dict) else ""
    except (ValueError, AttributeError):
        message = ""
    raise RuntimeError(f"Sarvam {what} failed: HTTP {resp.status_code} {message}".strip())


def _short(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {' '.join(str(exc).split())[:200]}"


def get_transcriber(settings: Settings) -> Transcriber:
    if settings.stt_provider == "fake":
        return FakeTranscriber()
    if settings.stt_provider == "litellm":
        return LiteLLMTranscriber(settings)
    if settings.stt_provider == "aws_transcribe":
        return AWSTranscribeTranscriber(settings)
    if settings.stt_provider == "sarvam":
        return SarvamTranscriber(settings)
    raise ValueError(f"unknown stt_provider: {settings.stt_provider!r}")
