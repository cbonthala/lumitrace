"""Text embeddings shared by the indexer (passages) and the MCP server (queries).

Both sides must embed with the same model and dimension, so always go through
:func:`embed_texts`. ``Settings.embedding_model = "fake"`` gives deterministic offline vectors
(hashed bag of words) for tests and local development without API keys.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lumitrace.config import Settings

FAKE_MODEL = "fake"
_WORD_RE = re.compile(r"\w+", re.UNICODE)


def fake_embedding(text: str, dimension: int) -> list[float]:
    """Deterministic unit vector; texts sharing words get similar vectors."""
    vec = [0.0] * dimension
    for word in _WORD_RE.findall(text.casefold()):
        digest = hashlib.sha256(word.encode()).digest()
        idx = int.from_bytes(digest[:4], "little") % dimension
        vec[idx] += 1.0 if digest[4] & 1 else -1.0
    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0:
        vec[0] = 1.0
        return vec
    return [v / norm for v in vec]


def embed_texts(
    texts: Sequence[str], settings: Settings, batch_size: int = 64
) -> list[list[float]]:
    """Embed ``texts`` with ``settings.embedding_model``; each vector has
    ``settings.embedding_dimension`` floats. Raises ``ValueError`` on a dimension mismatch."""
    if not texts:
        return []
    dim = settings.embedding_dimension
    if settings.embedding_model == FAKE_MODEL:
        return [fake_embedding(t, dim) for t in texts]

    import litellm

    out: list[list[float]] = []
    for start in range(0, len(texts), batch_size):
        batch = list(texts[start : start + batch_size])
        resp = litellm.embedding(
            model=settings.embedding_model,
            input=batch,
            timeout=settings.llm_timeout_seconds,
        )
        data = sorted(resp.data, key=lambda d: d["index"] if isinstance(d, dict) else d.index)
        for item in data:
            vector = item["embedding"] if isinstance(item, dict) else item.embedding
            if len(vector) != dim:
                raise ValueError(
                    f"{settings.embedding_model} returned {len(vector)} dims, "
                    f"LUMITRACE_EMBEDDING_DIMENSION is {dim}"
                )
            out.append([float(v) for v in vector])
    return out
