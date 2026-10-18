# 0048. One Sarvam transcript job; the journal reads the Telugu

- Status: accepted; the prompt names are superseded by 0050
- Date: 2026-10-17

## Context

Sarvam Saaras v4 was running two jobs on every recording: a `codemix` transcript and a
`translate` job that wrote English (ADR 0015). The English gave actions to the wrong person
and turned idioms into the wrong feeling (ADR 0018). The journal prompt then read both texts.
The translation was a second, worse source.

## Decision

* Sarvam runs one job: `LUMITRACE_SARVAM_MODEL` (`saaras:v4`), `LUMITRACE_SARVAM_MODE`
  (`codemix`), language from `LUMITRACE_STT_LANGUAGE` (`te` becomes `te-IN`), and the existing
  keyterms (family names plus `LUMITRACE_STT_KEYTERMS`). `LUMITRACE_SARVAM_TRANSLATE` is removed.
  This supersedes the translate-job half of ADR 0015.
* `write_journal` v6 and `journal_addendum` v6 receive the code-mixed transcript, `{{glossary}}`
  from `secrets/family.md`, and `{{keyterms}}`. They do not receive an English translation or
  the extracted facts JSON. This supersedes the "show both texts to the journal" instruction in
  ADR 0016 and ADR 0018. Those decisions still govern fact extraction.
* `extract_facts` still runs for the day file. A capture that already has a stored translation
  (an older file) is still shown to fact extraction. New captures have none.
* `Capture.translation` stays in the day-file format so older files still parse (ADR 0043).
  Sarvam no longer fills it.
* Which model writes the journal stays `LUMITRACE_LLM_WRITE_JOURNAL_MODEL`, with
  `LUMITRACE_LLM_FALLBACK_MODEL` on error or timeout. This decision does not change those.

## Consequences

* One Sarvam job per recording, so about half the audio minutes.
* The journal model has to read Telugu. A weak model will mis-assign who did what, with no
  English hint to lean on.
* Older day files keep their translation blocks, and Spectrum still indexes them.
