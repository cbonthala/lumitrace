"""Hybrid search: FTS5 keyword ranking (bm25) + sqlite-vec meaning ranking (cosine), merged with
reciprocal rank fusion (RRF). Date filters are applied in SQL on both sides.

See ``docs/decisions/0030-hybrid-search-rrf.md``.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass, field

from lifelog.config import Settings
from lifelog.embeddings import embed_texts
from lifelog.index.schema import META_EMBEDDING_MODEL, get_meta, serialize_embedding

logger = logging.getLogger(__name__)

RRF_K = 60
"""Standard RRF constant: score = sum(1 / (RRF_K + rank)) over the ranked lists (rank from 1)."""

MAX_QUERY_TERMS = 32
SNIPPET_CHARS = 320

_WORD_RE = re.compile(r"\w+", re.UNICODE)

# Dropped from the keyword query (when other words remain) so "what did I eat" does not match
# every passage containing "I". The meaning search still sees the full question.
_STOPWORD_TEXT = """
    a about after again all am an and any are as at be been before being but by can could
    did do does doing during for from had has have having he her here hers him his how i if
    in into is it its me my myself no nor not of off on once only or our ours out over she
    should so some such than that the their theirs them then there these they this those to
    too under until up very was we were what when where which while who whom why will with
    would you your yours
"""
STOPWORDS = frozenset(_STOPWORD_TEXT.split())


@dataclass
class SearchHit:
    passage_id: int
    score: float
    matched_by: list[str]
    date: str | None
    section: str
    heading: str | None
    path: str
    text: str


@dataclass
class SearchOutcome:
    hits: list[SearchHit]
    modes: list[str] = field(default_factory=list)
    """Which rankings ran: ``keyword`` and/or ``meaning``."""
    notes: list[str] = field(default_factory=list)


def query_terms(query: str) -> list[str]:
    words = [w for w in _WORD_RE.findall(query.casefold()) if w.strip("_")]
    content = [w for w in words if w not in STOPWORDS] or words
    return list(dict.fromkeys(content))[:MAX_QUERY_TERMS]


def fts_match_expression(query: str) -> str | None:
    """A safe FTS5 query: every term quoted (so FTS5 syntax in the input is inert), ORed
    together; bm25 rewards passages matching more and rarer terms."""
    terms = query_terms(query)
    if not terms:
        return None
    return " OR ".join(f'"{t}"' for t in terms)


def _date_sql(column: str, start: dt.date | None, end: dt.date | None) -> tuple[str, list[str]]:
    clauses: list[str] = []
    params: list[str] = []
    if start is not None:
        clauses.append(f"{column} >= ?")
        params.append(start.isoformat())
    if end is not None:
        clauses.append(f"{column} <= ?")
        params.append(end.isoformat())
    return " AND ".join(clauses), params


def keyword_ranking(
    conn: sqlite3.Connection,
    query: str,
    start: dt.date | None,
    end: dt.date | None,
    k: int,
) -> list[int]:
    expr = fts_match_expression(query)
    if expr is None:
        return []
    date_sql, date_params = _date_sql("p.date", start, end)
    sql = (
        "SELECT p.id FROM passages_fts JOIN passages p ON p.id = passages_fts.rowid "
        "WHERE passages_fts MATCH ?"
        + (f" AND {date_sql}" if date_sql else "")
        + " ORDER BY bm25(passages_fts), p.date DESC, p.id LIMIT ?"
    )
    return [row[0] for row in conn.execute(sql, [expr, *date_params, k])]


def vector_ranking(
    conn: sqlite3.Connection,
    vector: Sequence[float],
    start: dt.date | None,
    end: dt.date | None,
    k: int,
) -> list[int]:
    date_sql, date_params = _date_sql("date", start, end)
    sql = "SELECT rowid FROM passages_vec WHERE embedding MATCH ? AND k = ?"
    if date_sql:
        sql += f" AND rowid IN (SELECT id FROM passages WHERE {date_sql})"
    sql += " ORDER BY distance"
    return [row[0] for row in conn.execute(sql, [serialize_embedding(vector), k, *date_params])]


def reciprocal_rank_fusion(
    rankings: dict[str, Sequence[int]], k: int = RRF_K
) -> list[tuple[int, float, list[str]]]:
    """Merge ranked id lists. Returns ``(id, score, [list names it appeared in])``, best first.

    Ties are broken by the best single rank, then by id, so the order is deterministic.
    """
    scores: dict[int, float] = {}
    best_rank: dict[int, int] = {}
    sources: dict[int, list[str]] = {}
    for name, ids in rankings.items():
        for rank, item in enumerate(dict.fromkeys(ids), start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
            best_rank[item] = min(best_rank.get(item, rank), rank)
            sources.setdefault(item, []).append(name)
    ordered = sorted(scores, key=lambda i: (-scores[i], best_rank[i], i))
    return [(i, scores[i], sources[i]) for i in ordered]


def _vector_available(conn: sqlite3.Connection, settings: Settings, notes: list[str]) -> bool:
    if conn.execute("SELECT 1 FROM passages_vec LIMIT 1").fetchone() is None:
        return False
    index_model = get_meta(conn, META_EMBEDDING_MODEL)
    if index_model and index_model != settings.embedding_model:
        logger.warning(
            "index embeddings use %s but settings say %s; meaning search disabled",
            index_model,
            settings.embedding_model,
        )
        notes.append(
            "Meaning search is off because the index was built with a different embedding "
            "model; results come from keyword search only. Rebuild the index to fix this."
        )
        return False
    return True


def hybrid_search(
    conn: sqlite3.Connection,
    settings: Settings,
    query: str,
    *,
    start: dt.date | None = None,
    end: dt.date | None = None,
    limit: int = 10,
) -> SearchOutcome:
    candidates = max(limit * 4, 20)
    notes: list[str] = []
    rankings: dict[str, list[int]] = {}

    rankings["keyword"] = keyword_ranking(conn, query, start, end, candidates)

    if _vector_available(conn, settings, notes):
        try:
            [vector] = embed_texts([query], settings)
        except Exception:
            logger.warning("query embedding failed; keyword search only", exc_info=True)
            notes.append("Meaning search is temporarily unavailable; keyword results only.")
        else:
            rankings["meaning"] = vector_ranking(conn, vector, start, end, candidates)

    fused = reciprocal_rank_fusion(rankings)[:limit]
    hits = _load_hits(conn, fused)
    return SearchOutcome(hits=hits, modes=list(rankings), notes=notes)


def _load_hits(
    conn: sqlite3.Connection, fused: list[tuple[int, float, list[str]]]
) -> list[SearchHit]:
    if not fused:
        return []
    ids = [i for i, _, _ in fused]
    placeholders = ",".join("?" * len(ids))
    rows = {
        row["id"]: row
        for row in conn.execute(
            f"SELECT id, path, date, section, heading, text FROM passages "
            f"WHERE id IN ({placeholders})",
            ids,
        )
    }
    hits: list[SearchHit] = []
    for passage_id, score, sources in fused:
        row = rows.get(passage_id)
        if row is None:  # vector row without a passage (should not happen; triggers clean up)
            continue
        hits.append(
            SearchHit(
                passage_id=passage_id,
                score=round(score, 6),
                matched_by=sources,
                date=row["date"],
                section=row["section"],
                heading=row["heading"],
                path=row["path"],
                text=row["text"],
            )
        )
    return hits


def make_snippet(text: str, terms: Sequence[str], width: int = SNIPPET_CHARS) -> str:
    """A window of ``text`` around the first query term (or its start), cut at word edges."""
    flat = " ".join(text.split())
    if len(flat) <= width:
        return flat
    lowered = flat.casefold()
    positions = [m.start() for t in terms if (m := re.search(rf"\b{re.escape(t)}", lowered))]
    pos = min(positions) if positions else 0
    start = max(0, pos - width // 3)
    if start > 0:
        space = flat.find(" ", start)
        start = space + 1 if 0 <= space < pos else start
    end = min(len(flat), start + width)
    if end < len(flat):
        space = flat.rfind(" ", start, end)
        end = space if space > start else end
    return ("…" if start > 0 else "") + flat[start:end] + ("…" if end < len(flat) else "")
