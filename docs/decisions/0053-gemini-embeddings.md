# 0053. Search vectors come from Gemini Embedding 2

- Status: accepted
- Date: 2026-10-17

## Context

The day file and its fallback already use Gemini (`GEMINI_API_KEY`). Search still called
OpenAI `text-embedding-3-small` (1536 numbers per passage). The owner wants one provider for
the models Lumitrace calls, besides Sarvam for Telugu speech.

Gemini Embedding 2 (`gemini-embedding-2`) returns 3072 numbers unless the call asks for
another size. 768, 1536, and 3072 are the sizes Google recommends. A shorter vector from this
model is already normalized. Vectors from the old OpenAI model cannot be compared with these.

## Decision

* `LUMITRACE_EMBEDDING_MODEL` is `gemini/gemini-embedding-2`. Spectrum and the Lens both go
  through `embed_texts`, which passes `dimensions` equal to `LUMITRACE_EMBEDDING_DIMENSION`.
* The dimension stays 1536. That is a size this model returns, and it keeps the index the
  same width.
* A model change still rebuilds the index on the next Spectrum start (ADR 0023). Feedback and
  edit signals stay.

## Consequences

* Search no longer needs `OPENAI_API_KEY`. Speech stays Sarvam.
* After deploy, meaning search is incomplete until Spectrum finishes the rebuild. Keyword
  search still works during that time.
* Asking for 3072 later is a dimension change and another rebuild.
