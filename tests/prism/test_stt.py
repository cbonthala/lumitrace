from __future__ import annotations

import io
import json
from types import SimpleNamespace
from typing import Any

import pytest

from lumitrace.config import Settings
from lumitrace.prism.pipeline.stt import (
    AWSTranscribeTranscriber,
    FakeTranscriber,
    LiteLLMTranscriber,
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


def test_get_transcriber(settings: Settings) -> None:
    assert isinstance(get_transcriber(settings), FakeTranscriber)
    s = settings.model_copy(update={"stt_provider": "litellm"})
    assert isinstance(get_transcriber(s), LiteLLMTranscriber)
    with pytest.raises(ValueError, match="BUCKET"):
        get_transcriber(settings.model_copy(update={"stt_provider": "aws_transcribe"}))
