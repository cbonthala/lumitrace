# 0018. Follow the original transcript over the translation; fill the author's block

- Status: accepted (refines 0016)
- Date: 2026-10-13

## Context

The first real Telugu days with Sarvam (ADR 0015) and the 0016 prompts had good transcripts but
still lost or misplaced facts. Sarvam's English translation mixes up pronouns ("he didn't give
it" for "she", "my father" for the speaker talking about himself as his child's "Dad") and turns
idioms into the wrong feeling (being pestered became "excited"). The 0016 rule "when the
translation and the original disagree, leave the detail out" made the models drop exactly those
parts, including feelings people expressed. `gpt-4o-mini` also copied breakfast into lunch and
left the author's family block empty despite being told to fill it.

A dry run of the same day (no writes) compared the options: `gpt-4o` with the old prompts fixed
some of it; the new prompts with `gpt-4o` filled the author's block but put the author at the
park; the new prompts with `gpt-4.1` got lunch, the author's block and who went to the park
right.

## Decision

* `extract_facts` v4, `write_journal` v3, `journal_addendum` v3:
  * read both texts and **follow the original when they disagree**; drop a detail only when
    neither makes sense;
  * parents talking about themselves in their child's words ("Dad went to bed early") mean the
    author; speech-to-text may split such words;
  * the author's family block always repeats the author's own mood, meals, places, activities
    and moments;
  * a meal eaten without a named food is described from the entry ("food from the deli"),
    never borrowed from another meal; a meal's type may come from the order of events;
  * feelings and worries anyone expressed are kept (as moments, and in the journal).
* Recommended models for mixed-language entries: `openai/gpt-4.1` for both
  `LUMITRACE_LLM_EXTRACT_FACTS_MODEL` and `LUMITRACE_LLM_WRITE_JOURNAL_MODEL`. The code defaults
  are unchanged; this is a deployment setting.

## Consequences

* About the same price per day as `gpt-4o` and more than `gpt-4o-mini` (one facts and one
  journal call per recording).
* Passages the original garbles are still lost; that is a speech-to-text limit.
* Examples in the prompts stay fictional (Maya, Leo), never the owner's days.
