# 0030. Hybrid search with reciprocal rank fusion

- Status: accepted
- Date: 2026-10-10

## Context

Journal questions mix exact words ("horchata", a name) and fuzzy meaning ("when was I stressed
about work?"). FTS5 is good at the first, embeddings at the second. Their scores (bm25 vs cosine
distance) are on different scales, so adding them needs tuning we have no data for yet. Date
filters ("in September") must be exact, not a post-filter that can leave too few results.

## Decision

* Run both rankings and merge with reciprocal rank fusion: `score = Σ 1 / (60 + rank)`, each
  list fetching `max(4 × limit, 20)` candidates. Ties: better single rank, then lower id.
* Keyword query: words only, stop words dropped (unless nothing else is left), each word
  quoted and ORed, so FTS5 operators typed by the AI client are inert and never cause syntax
  errors; bm25 rewards passages matching more and rarer words.
* Date filters in SQL on both sides; for sqlite-vec, `rowid IN (SELECT id FROM passages WHERE
  date ...)` inside the KNN query (supported by sqlite-vec 0.1.9, verified in tests), so the
  `k` nearest are taken *within* the range.
* Degrade to keyword-only with a note if the query embedding fails or the index was built
  with another embedding model.

## Consequences

* No score tuning needed; adding a third ranking (e.g. facts) later is one more list.
* The meaning list always returns neighbours, even for nonsense queries, so results are never
  "empty" when the index has vectors; the server instructions tell the AI to judge relevance
  and say when nothing relevant was found. `matched_by` shows which ranking found each hit.
* RRF ignores score gaps; revisit with the answer-quality check once it exists.
