"""docs/test-cases.md describes every test in plain English; this keeps it complete."""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "test-cases.md"
FILE_LINE = re.compile(r"^File: `(tests/[\w/]+\.py)`\s*$")
TEST_NAME = re.compile(r"`(test\w*)`")
NO_FILE = "(a section without a 'File: `tests/...`' line)"


def collected_tests() -> dict[str, set[str]]:
    """Test function names per test file, the way pytest finds them (``test*``)."""
    found: dict[str, set[str]] = {}
    for path in sorted((ROOT / "tests").rglob("test_*.py")):
        names: set[str] = set()
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            if isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
                body = node.body
            else:
                body = [node]
            for item in body:
                if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef) and (
                    item.name.startswith("test")
                ):
                    names.add(item.name)
        found[path.relative_to(ROOT).as_posix()] = names
    return found


def documented_tests() -> dict[str, set[str]]:
    """Test names per file in the doc: each heading starts a section, whose 'File:' line names
    the test file its lines describe."""
    found: dict[str, set[str]] = {}
    current: str | None = None
    in_code_block = False
    for line in DOC.read_text(encoding="utf-8").splitlines():
        if line.startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue
        if line.startswith("#"):
            current = None
            continue
        if match := FILE_LINE.match(line):
            current = match.group(1)
            found.setdefault(current, set())
            continue
        names = TEST_NAME.findall(line)
        if names:
            found.setdefault(current or NO_FILE, set()).update(names)
    return found


def test_every_test_is_described_in_test_cases_doc() -> None:
    collected = collected_tests()
    documented = documented_tests()
    assert collected and documented

    missing = [
        f"{path}::{name}"
        for path, names in sorted(collected.items())
        for name in sorted(names - documented.get(path, set()))
    ]
    assert not missing, (
        "These tests are not described in docs/test-cases.md:\n  "
        + "\n  ".join(missing)
        + "\nDescribe each new test in plain English: one line starting 'Checks that ...' "
        "under a section whose 'File: `tests/...`' line names its test file, ending with the "
        "test name in backticks, e.g. <sub>`test_name`</sub>. If you changed what a test "
        "checks, update its line too."
    )

    stale = [
        f"{path}::{name}"
        for path, names in sorted(documented.items())
        for name in sorted(names - collected.get(path, set()))
    ]
    assert not stale, (
        "docs/test-cases.md describes tests that don't exist in that file (renamed, moved or "
        "deleted?):\n  " + "\n  ".join(stale) + "\nUpdate or remove those lines."
    )
