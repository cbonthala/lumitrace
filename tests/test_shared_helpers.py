from __future__ import annotations

import json
import logging
import math
from types import SimpleNamespace

import httpx
import pytest

from lumitrace.config import Settings
from lumitrace.embeddings import embed_texts, fake_embedding
from lumitrace.logging_setup import setup_logging
from lumitrace.nudge import nudge_indexer


def test_fake_embeddings_are_deterministic_unit_vectors(settings: Settings) -> None:
    a, b, c = embed_texts(["pancakes with Maya", "pancakes with Maya", "tax forms"], settings)
    assert a == b
    assert len(a) == settings.embedding_dimension
    assert math.isclose(sum(v * v for v in a), 1.0, rel_tol=1e-9)
    assert a != c
    assert embed_texts([], settings) == []
    assert fake_embedding("", 4) == [1.0, 0.0, 0.0, 0.0]


def test_provider_embeddings_ask_for_the_configured_size(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, object] = {}

    def _embed(**kwargs: object) -> SimpleNamespace:
        seen.update(kwargs)
        return SimpleNamespace(
            data=[
                SimpleNamespace(index=1, embedding=[0.2] * 8),
                SimpleNamespace(index=0, embedding=[0.1] * 8),
            ]
        )

    import litellm

    monkeypatch.setattr(litellm, "embedding", _embed)
    configured = settings.model_copy(
        update={"embedding_model": "gemini/gemini-embedding-2", "embedding_dimension": 8}
    )
    vectors = embed_texts(["second", "first"], configured)
    assert seen["model"] == "gemini/gemini-embedding-2"
    assert seen["dimensions"] == 8
    assert seen["input"] == ["second", "first"]
    assert vectors == [[0.1] * 8, [0.2] * 8]


def test_provider_embeddings_refuse_the_wrong_size(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    import litellm

    monkeypatch.setattr(
        litellm,
        "embedding",
        lambda **kwargs: SimpleNamespace(data=[SimpleNamespace(index=0, embedding=[1.0, 0.0])]),
    )
    configured = settings.model_copy(
        update={"embedding_model": "gemini/gemini-embedding-2", "embedding_dimension": 8}
    )
    with pytest.raises(ValueError, match="returned 2 dims"):
        embed_texts(["hello"], configured)


def test_fake_embeddings_rank_shared_words_closer(settings: Settings) -> None:
    q, near, far = embed_texts(["pancakes breakfast", "breakfast pancakes syrup", "tax"], settings)
    dot = lambda x, y: sum(i * j for i, j in zip(x, y, strict=True))  # noqa: E731
    assert dot(q, near) > dot(q, far)


def test_nudge_posts_paths(settings: Settings) -> None:
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append({"url": str(request.url), "body": json.loads(request.content)})
        return httpx.Response(202)

    s = settings.model_copy(update={"indexer_nudge_url": "http://indexer:8001/nudge"})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert nudge_indexer(s, ["a.md"], client=client) is True
    assert seen == [{"url": "http://indexer:8001/nudge", "body": {"paths": ["a.md"]}}]


def test_nudge_never_raises(settings: Settings) -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    s = settings.model_copy(update={"indexer_nudge_url": "http://indexer:8001/nudge"})
    with httpx.Client(transport=httpx.MockTransport(boom)) as client:
        assert nudge_indexer(s, client=client) is False
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500))) as client:
        assert nudge_indexer(s, client=client) is False
    assert nudge_indexer(settings) is False


def test_http_client_logs_never_show_request_urls() -> None:
    setup_logging("DEBUG")
    for name in ("httpx", "httpcore"):
        assert not logging.getLogger(name).isEnabledFor(logging.INFO)
        assert logging.getLogger(name).isEnabledFor(logging.WARNING)
