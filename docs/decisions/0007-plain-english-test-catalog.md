# 0007. Plain-English test catalog, kept complete by a test

- Status: accepted
- Date: 2026-10-11

## Context

The owner wants to understand what each part of LifeLog does and how it is verified without
reading test code. A written catalog goes stale unless something forces it to follow the tests.

## Decision

`docs/test-cases.md` describes every test in one plain-English line, grouped by component and
feature. Each section has a `File: tests/...` line and each line ends with the test's function
name. `tests/test_docs_test_cases.py` reads the test files with `ast` (no imports, so it can't
be broken by a failing module), lists test functions per file, and compares them with the names
under each section's `File:` line. It fails on tests missing from the catalog and on catalog
entries whose test no longer exists in that file.

Matching is by function name per file, not by pytest node id: parametrized cases share one line,
and the same name in two files (local and Drive storage) is checked separately.

## Consequences

- Every new or renamed test needs a catalog line in the same commit (AGENTS.md rule 8).
- The check can't tell whether a line still describes what the test does; changing what a test
  checks still relies on the author updating its line.
