# 0015. Sarvam batch speech to text: code-mixed transcript plus an English translation

- Status: accepted
- Date: 2026-10-12

## Context

The owner records in Telugu mixed with English. `openai/gpt-4o-transcribe` with language
detection wrote the English words phonetically in Telugu script, split words at the wrong
places and misheard the family names. The AI steps then read nonsense as facts (a phrase
meaning "in the car itself" became a lunch called "Carlone") and gave actions to the wrong
person. Sarvam's Saaras models are trained on Indian languages and code-mixed speech, have a
`codemix` output (English words in English, Telugu in Telugu script), can translate speech
straight to English, and accept `keyterms` to bias recognition toward names.

Sarvam's REST endpoint only takes audio under 30 seconds; a day's recording is minutes long.
Its batch API takes up to 2 hours: create a job, upload to a presigned URL, start, poll,
download a JSON result.

## Decision

* New `LUMITRACE_STT_PROVIDER=sarvam` in `lumitrace/prism/pipeline/stt.py`, calling the batch
  API with `httpx` (already a dependency) rather than the `sarvamai` SDK, so no new dependency
  and the HTTP layer is easy to imitate in tests (`httpx.MockTransport`).
* Two jobs on the same audio, run at the same time: the transcript in `LUMITRACE_SARVAM_MODE`
  (default `codemix`) and, with `LUMITRACE_SARVAM_TRANSLATE` (default on), a `translate` job
  for English. Translating the audio directly avoids translating an already noisy transcript.
* The transcript stays the raw record (Key rule 3); the translation is stored next to it
  (ADR 0043) and given to the AI steps (ADR 0016).
* A failed transcript fails the capture so the inbox retries it; a failed translation only
  adds a warning, because the transcript alone is still a valid capture.
* `keyterms` = the `LUMITRACE_FAMILY` names plus `LUMITRACE_STT_KEYTERMS` (only `saaras:v4`
  accepts them; at most 50, 64 characters each).
* Error messages never include the presigned upload or download URLs (they carry access
  tokens), and the API key is only sent to `api.sarvam.ai`, never to the storage URL.

## Consequences

* Two Sarvam jobs per recording (twice the audio minutes billed). Turning the translation off
  halves it.
* Sarvam prices in rupees per hour of audio, which LiteLLM does not know, so activity records
  have no `cost_usd` for this step.
* Sarvam has no endpoint to delete a finished job; its retention terms apply to the audio.
* Not verified yet against the real service (the tests imitate it from the documented API).
