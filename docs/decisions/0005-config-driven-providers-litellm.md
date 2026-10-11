# 0005. Config-driven providers via LiteLLM

- Status: accepted
- Date: 2026-10-10

## Context

Model quality, price and privacy terms change quickly. The owner may want Claude on Bedrock,
OpenAI, or a local Ollama model, and different models per task.

## Decision

All AI calls go through LiteLLM using model strings from config: one per task
(`LIFELOG_LLM_EXTRACT_FACTS_MODEL`, `LIFELOG_LLM_WRITE_JOURNAL_MODEL`), a fallback
(`LIFELOG_LLM_FALLBACK_MODEL`), embeddings (`LIFELOG_EMBEDDING_MODEL`) and speech to text
(`LIFELOG_STT_PROVIDER` / `LIFELOG_STT_MODEL`; Amazon Transcribe as a non-LiteLLM option).
`fake` providers exist for offline tests.

## Consequences

- Switching providers is a config change plus a quality check, not a code change.
- Each day file and activity record stores the models and prompt version used, so quality can be
  compared across models.
- LiteLLM is a large dependency and its behaviour differs slightly per provider; keep the code
  defensive and tested with mocks.
