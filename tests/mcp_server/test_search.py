from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from lifelog.config import Settings
from lifelog.embeddings import embed_texts
from lifelog.index.schema import META_EMBEDDING_MODEL, connect, set_meta
from lifelog.mcp_server import search as S
from lifelog.mcp_server.dates import DateArgumentError
from lifelog.mcp_server.index import INDEX_EMPTY_NOTE, INDEX_MISSING_NOTE
from lifelog.mcp_server.tools import LifeLogTools, ToolInputError

# --- query building ------------------------------------------------------------------------


def test_fts_expression_quotes_every_term() -> None:
    expr = S.fts_match_expression('pasta AND "NEAR(x" -tacos* OR')
    assert expr == '"pasta" OR "near" OR "x" OR "tacos"'


def test_fts_expression_drops_stopwords_but_keeps_all_stopword_queries() -> None:
    assert S.fts_match_expression("what did I eat") == '"eat"'
    assert S.fts_match_expression("what did I") == '"what" OR "did" OR "i"'
    assert S.fts_match_expression("?!") is None


def test_fts_expression_is_valid_fts5(settings: Settings, populated: Path) -> None:
    conn = connect(populated, settings.embedding_dimension, read_only=True)
    for query in ['"unbalanced', "NOT", "a:b c^d", "(pasta", "café ñandú"]:
        S.keyword_ranking(conn, query, None, None, 5)  # must not raise a syntax error
    conn.close()


# --- reciprocal rank fusion ----------------------------------------------------------------


def test_rrf_rewards_items_in_both_lists() -> None:
    fused = S.reciprocal_rank_fusion({"keyword": [1, 2, 3], "meaning": [3, 1, 4]})
    assert [i for i, _, _ in fused] == [1, 3, 2, 4]
    scores = {i: s for i, s, _ in fused}
    assert scores[1] == pytest.approx(1 / 61 + 1 / 62)
    assert scores[3] == pytest.approx(1 / 63 + 1 / 61)
    assert dict((i, src) for i, _, src in fused)[1] == ["keyword", "meaning"]
    assert dict((i, src) for i, _, src in fused)[4] == ["meaning"]


def test_rrf_ties_are_deterministic_and_duplicates_ignored() -> None:
    fused = S.reciprocal_rank_fusion({"a": [7, 7, 9], "b": [5]})
    assert [i for i, _, _ in fused] == [5, 7, 9]
    assert fused[0][1] == pytest.approx(1 / 61)
    assert S.reciprocal_rank_fusion({}) == []


def test_rrf_respects_k() -> None:
    fused = S.reciprocal_rank_fusion({"a": [1]}, k=0)
    assert fused[0][1] == pytest.approx(1.0)


# --- rankings with date filters in SQL -----------------------------------------------------


def _dates_of(conn, ids: list[int]) -> set[str]:
    if not ids:
        return set()
    marks = ",".join("?" * len(ids))
    return {r[0] for r in conn.execute(f"SELECT date FROM passages WHERE id IN ({marks})", ids)}


def test_keyword_and_vector_rankings_apply_date_filters(
    settings: Settings, populated: Path
) -> None:
    conn = connect(populated, settings.embedding_dimension, read_only=True)
    start, end = dt.date(2025, 1, 1), dt.date(2026, 9, 30)
    kw = S.keyword_ranking(conn, "pasta", start, end, 50)
    assert kw and _dates_of(conn, kw) <= {"2025-10-10", "2026-09-15"}
    all_kw = S.keyword_ranking(conn, "pasta", None, None, 50)
    assert "2026-10-10" in _dates_of(conn, all_kw)

    [vector] = embed_texts(["pasta dinner"], settings)
    vec = S.vector_ranking(conn, vector, start, end, 50)
    assert vec and _dates_of(conn, vec) <= {"2025-10-10", "2026-09-15"}
    only_old = S.vector_ranking(conn, vector, None, dt.date(2024, 12, 31), 50)
    assert _dates_of(conn, only_old) == {"2024-10-10"}
    conn.close()


# --- the search tool -----------------------------------------------------------------------


def test_search_finds_the_right_day(tools: LifeLogTools, populated: Path) -> None:
    out = tools.search("pumpkin patch")
    top = out["results"][0]
    assert top["date"] == "2024-10-10"
    assert set(top) >= {"date", "section", "heading", "snippet", "path", "score", "matched_by"}
    assert top["path"] == "2024/10/2024-10-10/2024-10-10.md"
    assert "keyword" in top["matched_by"]
    assert out["search_modes"] == ["keyword", "meaning"]
    assert "pumpkin" in top["snippet"].lower()


def test_search_results_are_in_rrf_order(tools: LifeLogTools, populated: Path) -> None:
    out = tools.search("grandma rose pasta", limit=20)
    scores = [r["score"] for r in out["results"]]
    assert scores == sorted(scores, reverse=True)
    assert out["results"][0]["date"] == "2026-09-15"


def test_search_date_filters(tools: LifeLogTools, populated: Path) -> None:
    out = tools.search("pasta", from_date="2026-01-01", limit=50)
    assert out["results"]
    assert all(r["date"] >= "2026-01-01" for r in out["results"])
    out = tools.search("pasta", to_date="2025-12-31", limit=50)
    assert {r["date"] for r in out["results"]} <= {"2024-10-10", "2025-10-10"}
    out = tools.search("pasta", from_date="2025-10-10", to_date="2025-10-10")
    assert {r["date"] for r in out["results"]} == {"2025-10-10"}
    assert out["from_date"] == out["to_date"] == "2025-10-10"


def test_search_limit(tools: LifeLogTools, populated: Path) -> None:
    assert len(tools.search("pasta", limit=2)["results"]) == 2


def test_search_bad_arguments(tools: LifeLogTools, populated: Path) -> None:
    with pytest.raises(ToolInputError):
        tools.search("   ")
    with pytest.raises(DateArgumentError):
        tools.search("pasta", from_date="last tuesday")
    with pytest.raises(DateArgumentError):
        tools.search("pasta", from_date="2026-10-10", to_date="2026-01-01")


def test_search_missing_index(tools: LifeLogTools) -> None:
    out = tools.search("pasta")
    assert out["results"] == [] and out["note"] == INDEX_MISSING_NOTE


def test_search_empty_index(tools: LifeLogTools, settings: Settings) -> None:
    connect(settings.index_path, settings.embedding_dimension).close()
    out = tools.search("pasta")
    assert out["results"] == [] and out["note"] == INDEX_EMPTY_NOTE


def test_search_corrupt_index_is_treated_as_missing(
    tools: LifeLogTools, settings: Settings
) -> None:
    Path(settings.index_path).parent.mkdir(parents=True)
    Path(settings.index_path).write_bytes(b"not a database")
    assert tools.search("pasta")["note"] == INDEX_MISSING_NOTE


def test_search_falls_back_to_keywords_when_embedding_fails(
    tools: LifeLogTools, populated: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*args: object, **kwargs: object) -> list[list[float]]:
        raise RuntimeError("provider down")

    monkeypatch.setattr(S, "embed_texts", boom)
    out = tools.search("pumpkin")
    assert out["search_modes"] == ["keyword"]
    assert out["results"][0]["date"] == "2024-10-10"
    assert "unavailable" in out["note"]


def test_search_skips_vectors_from_another_embedding_model(
    tools: LifeLogTools, settings: Settings, populated: Path
) -> None:
    conn = connect(populated, settings.embedding_dimension)
    with conn:
        set_meta(conn, META_EMBEDDING_MODEL, "openai/other-model")
    conn.close()
    out = tools.search("pumpkin")
    assert out["search_modes"] == ["keyword"]
    assert "different embedding model" in out["note"]


def test_search_reports_nothing_found(tools: LifeLogTools, populated: Path) -> None:
    out = tools.search("zzzz", from_date="2030-01-01")
    assert out["results"] == []
    assert "No matching entries" in out["note"]


# --- snippets ------------------------------------------------------------------------------


def test_snippet_centres_on_the_first_term() -> None:
    text = ("word " * 200) + "the pumpkin was huge " + ("tail " * 200)
    snippet = S.make_snippet(text, ["pumpkin"], width=80)
    assert "pumpkin" in snippet
    assert snippet.startswith("…") and snippet.endswith("…")
    assert len(snippet) <= 82


def test_snippet_short_text_is_whole() -> None:
    assert S.make_snippet("Short\n text.", ["x"]) == "Short text."
