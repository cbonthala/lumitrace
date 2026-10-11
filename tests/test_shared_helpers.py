from __future__ import annotations

import json
import math

import httpx

from lumen.config import Settings
from lumen.embeddings import embed_texts, fake_embedding
from lumen.nudge import nudge_indexer


def test_fake_embeddings_are_deterministic_unit_vectors(settings: Settings) -> None:
    a, b, c = embed_texts(["pancakes with Maya", "pancakes with Maya", "tax forms"], settings)
    assert a == b
    assert len(a) == settings.embedding_dimension
    assert math.isclose(sum(v * v for v in a), 1.0, rel_tol=1e-9)
    assert a != c
    assert embed_texts([], settings) == []
    assert fake_embedding("", 4) == [1.0, 0.0, 0.0, 0.0]


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
