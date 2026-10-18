from __future__ import annotations

import io
import json
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from lumitrace.config import Settings
from lumitrace.household import Household, Person
from lumitrace.prism.pipeline.stt import (
    AWSTranscribeTranscriber,
    FakeTranscriber,
    LiteLLMTranscriber,
    SarvamTranscriber,
    get_transcriber,
)


def test_fake_transcriber() -> None:
    fake = FakeTranscriber()
    assert fake.transcribe(b"  Hello there.  ", "a.m4a").text == "Hello there."
    binary = fake.transcribe(b"\x00\x01ftypM4A", "a.m4a")
    assert binary.text == "(fake transcript of 9 bytes of audio)"
    assert binary.model == "fake"


def test_litellm_transcriber_passes_settings(settings: Settings) -> None:
    seen: dict[str, Any] = {}

    def transcription(**kwargs: Any) -> Any:
        seen.update(kwargs)
        return SimpleNamespace(text=" Spoken words. ")

    s = settings.model_copy(update={"stt_model": "openai/whisper-1", "stt_language": "en"})
    result = LiteLLMTranscriber(s, transcription_fn=transcription).transcribe(b"abc", "audio.m4a")
    assert result.text == "Spoken words."
    assert result.model == "openai/whisper-1"
    assert seen["model"] == "openai/whisper-1"
    assert seen["language"] == "en"
    assert isinstance(seen["file"], io.BytesIO) and seen["file"].name == "audio.m4a"


class FakeS3:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.deleted: list[str] = []

    def put_object(self, Bucket: str, Key: str, Body: bytes) -> None:
        self.objects[Key] = Body

    def get_object(self, Bucket: str, Key: str) -> dict:
        return {"Body": io.BytesIO(self.objects[Key])}

    def delete_object(self, Bucket: str, Key: str) -> None:
        self.deleted.append(Key)


class FakeTranscribe:
    def __init__(self, s3: FakeS3, fail: bool = False) -> None:
        self.s3 = s3
        self.fail = fail
        self.started: dict[str, Any] = {}
        self.polls = 0

    def start_transcription_job(self, **kwargs: Any) -> None:
        self.started = kwargs

    def get_transcription_job(self, TranscriptionJobName: str) -> dict:
        self.polls += 1
        if self.polls < 2:
            return {"TranscriptionJob": {"TranscriptionJobStatus": "IN_PROGRESS"}}
        if self.fail:
            return {
                "TranscriptionJob": {"TranscriptionJobStatus": "FAILED", "FailureReason": "bad"}
            }
        out = {"results": {"transcripts": [{"transcript": "Walked the dog."}]}}
        self.s3.objects[self.started["OutputKey"]] = json.dumps(out).encode()
        return {"TranscriptionJob": {"TranscriptionJobStatus": "COMPLETED"}}

    def delete_transcription_job(self, TranscriptionJobName: str) -> None:
        pass


def aws_settings(settings: Settings, language: str = "en") -> Settings:
    return settings.model_copy(
        update={
            "stt_provider": "aws_transcribe",
            "aws_transcribe_bucket": "my-bucket",
            "stt_language": language,
        }
    )


def test_aws_transcribe_round_trip_and_cleanup(settings: Settings) -> None:
    s3 = FakeS3()
    client = FakeTranscribe(s3)
    stt = AWSTranscribeTranscriber(aws_settings(settings), s3=s3, transcribe=client, poll_seconds=0)
    result = stt.transcribe(b"audio", "audio.m4a")
    assert result.text == "Walked the dog."
    assert result.model == "aws_transcribe"
    assert client.started["MediaFormat"] == "m4a"
    assert client.started["LanguageCode"] == "en-US"
    assert client.started["Media"]["MediaFileUri"].startswith("s3://my-bucket/lumitrace-stt/")
    assert sorted(s3.deleted) == sorted(s3.objects)


def test_aws_transcribe_failure_still_cleans_up(settings: Settings) -> None:
    s3 = FakeS3()
    stt = AWSTranscribeTranscriber(
        aws_settings(settings, "xx"),
        s3=s3,
        transcribe=FakeTranscribe(s3, fail=True),
        poll_seconds=0,
    )
    with pytest.raises(RuntimeError, match="job failed"):
        stt.transcribe(b"audio", "audio.wav")
    assert len(s3.deleted) == 2
    with pytest.raises(ValueError, match="cannot read"):
        stt.transcribe(b"audio", "audio.caf")


def test_aws_language_options(settings: Settings) -> None:
    s3 = FakeS3()
    for lang, expected in (
        ("en-GB", {"LanguageCode": "en-GB"}),
        ("es", {"LanguageCode": "es-US"}),
        ("", {"IdentifyLanguage": True}),
    ):
        stt = AWSTranscribeTranscriber(aws_settings(settings, lang), s3=s3, transcribe=object())
        assert stt._language_args() == expected


class FakeSarvam:
    """Imitates the Sarvam batch API and its presigned blob storage."""

    def __init__(
        self, fail_modes: tuple[str, ...] = (), transcripts: dict[str, str] | None = None
    ) -> None:
        self.fail_modes = fail_modes
        self.transcripts = {"translate": "We went to the park.", **(transcripts or {})}
        self.jobs: dict[str, dict[str, Any]] = {}
        self.uploads: dict[str, bytes] = {}
        self.blob_headers: list[httpx.Headers] = []
        self.api_keys: set[str | None] = set()
        self.polls = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = request.url
        if url.host == "blob.example":
            self.blob_headers.append(request.headers)
            if request.method == "PUT":
                self.uploads[url.path] = request.content
                return httpx.Response(201)
            job_id = url.path.split("/")[1]
            mode = self.jobs[job_id]["params"]["mode"]
            text = self.transcripts.get(mode, "mana park ki vellam")
            return httpx.Response(200, json={"transcript": f" {text} ", "language_code": "te-IN"})
        self.api_keys.add(request.headers.get("api-subscription-key"))
        path = url.path.removeprefix("/speech-to-text/job/v1")
        body = json.loads(request.content) if request.content else {}
        if path == "":
            job_id = f"job{len(self.jobs)}"
            self.jobs[job_id] = {"params": body["job_parameters"], "started": False}
            return httpx.Response(202, json={"job_id": job_id, "job_state": "Accepted"})
        if path == "/upload-files":
            name = body["files"][0]
            link = f"https://blob.example/{body['job_id']}/{name}?sig=secret"
            return httpx.Response(200, json={"upload_urls": {name: {"file_url": link}}})
        if path == "/download-files":
            name = body["files"][0]
            link = f"https://blob.example/{body['job_id']}/{name}?sig=secret"
            return httpx.Response(200, json={"download_urls": {name: {"file_url": link}}})
        job_id, action = path.strip("/").split("/")
        if action == "start":
            self.jobs[job_id]["started"] = True
            return httpx.Response(200, json={"job_state": "Running"})
        self.polls += 1
        if self.polls <= 2:
            return httpx.Response(200, json={"job_state": "Running"})
        if self.jobs[job_id]["params"]["mode"] in self.fail_modes:
            failed = {"state": "API Error", "error_message": "audio unreadable", "outputs": []}
            return httpx.Response(200, json={"job_state": "Completed", "job_details": [failed]})
        done = {"state": "Success", "outputs": [{"file_name": "0.json", "file_id": "o"}]}
        return httpx.Response(200, json={"job_state": "Completed", "job_details": [done]})


def sarvam_settings(settings: Settings, **update: Any) -> Settings:
    household = update.pop(
        "household",
        Household(people=(Person("Sam", "me"), Person("Maya", "wife"))),
    )
    values = {
        "stt_provider": "sarvam",
        "sarvam_api_key": SecretStr("sk-test"),
        "stt_language": "te",
        "stt_keyterms": "Corner Bakery",
        **update,
    }
    return settings.model_copy(update=values).with_household(household)


def sarvam(settings: Settings, server: FakeSarvam) -> SarvamTranscriber:
    client = httpx.Client(transport=httpx.MockTransport(server.handler))
    return SarvamTranscriber(settings, client=client, poll_seconds=0)


def test_sarvam_transcript_only(settings: Settings) -> None:
    server = FakeSarvam()
    result = sarvam(sarvam_settings(settings), server).transcribe(b"audio", "audio.m4a")
    assert result.text == "mana park ki vellam"
    assert result.translation == ""
    assert result.model == "sarvam/saaras:v4"
    assert result.warnings == ()
    (job,) = server.jobs.values()
    assert job["params"] == {
        "model": "saaras:v4",
        "mode": "codemix",
        "language_code": "te-IN",
        "keyterms": ["Sam", "Maya", "Corner Bakery"],
    }
    assert job["started"]
    assert set(server.uploads.values()) == {b"audio"}
    assert server.api_keys == {"sk-test"}
    assert all("api-subscription-key" not in h for h in server.blob_headers)
    assert server.blob_headers[0]["x-ms-blob-type"] == "BlockBlob"
    assert {h["content-type"] for h in server.blob_headers if "x-ms-blob-type" in h} == {
        "audio/x-m4a"
    }


def test_sarvam_empty_transcript_is_a_warning(settings: Settings) -> None:
    server = FakeSarvam(transcripts={"codemix": "  "})
    result = sarvam(sarvam_settings(settings), server).transcribe(b"audio", "audio.mp3")
    assert result.text == ""
    assert result.warnings == ("transcript: Sarvam returned no text",)
    assert {h["content-type"] for h in server.blob_headers if "x-ms-blob-type" in h} == {
        "audio/mpeg"
    }


def test_sarvam_options(settings: Settings) -> None:
    server = FakeSarvam()
    s = sarvam_settings(settings, sarvam_model="saaras:v3", stt_language="")
    result = sarvam(s, server).transcribe(b"audio", "audio.wav")
    assert result.translation == ""
    (job,) = server.jobs.values()
    assert job["params"] == {"model": "saaras:v3", "mode": "codemix", "language_code": "unknown"}
    with pytest.raises(ValueError, match="cannot read"):
        sarvam(s, server).transcribe(b"audio", "audio.caf")
    with pytest.raises(ValueError, match="SARVAM_API_KEY"):
        SarvamTranscriber(settings.model_copy(update={"stt_provider": "sarvam"}))


def test_sarvam_failed_transcript_raises_without_leaking_urls(settings: Settings) -> None:
    with pytest.raises(RuntimeError, match="audio unreadable"):
        sarvam(sarvam_settings(settings), FakeSarvam(fail_modes=("codemix",))).transcribe(
            b"audio", "audio.m4a"
        )

    def reject_upload(request: httpx.Request) -> httpx.Response:
        if request.url.host == "blob.example":
            return httpx.Response(403, text="AuthenticationFailed sig=secret")
        return FakeSarvam().handler(request)

    client = httpx.Client(transport=httpx.MockTransport(reject_upload))
    stt = SarvamTranscriber(sarvam_settings(settings), client=client, poll_seconds=0)
    with pytest.raises(RuntimeError) as info:
        stt.transcribe(b"audio", "audio.m4a")
    assert str(info.value) == "Sarvam audio upload failed: HTTP 403"


def test_get_transcriber(settings: Settings) -> None:
    assert isinstance(get_transcriber(settings), FakeTranscriber)
    s = settings.model_copy(update={"stt_provider": "litellm"})
    assert isinstance(get_transcriber(s), LiteLLMTranscriber)
    with pytest.raises(ValueError, match="BUCKET"):
        get_transcriber(settings.model_copy(update={"stt_provider": "aws_transcribe"}))
    assert isinstance(get_transcriber(sarvam_settings(settings)), SarvamTranscriber)
