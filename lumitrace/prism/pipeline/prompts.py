"""Prompt files (``prompts/<task>.md``, see ``prompts/README.md``).

A prompt file has a system part and a user part, separated by marker comments::

    <!-- lumitrace-prompt: system -->
    You are ...
    <!-- lumitrace-prompt: user -->
    Date: {{date}}
    ...

``{{name}}`` placeholders in either part are replaced by :meth:`Prompt.render`. Unknown
placeholders raise ``KeyError`` so a prompt and its caller cannot silently drift apart.
The day template Gemini also sees is ``prompts/day-template.md``, filled in by the caller.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import lumitrace

PROMPT_TASKS = ("fill_day", "update_day")
"""The prompt files under ``prompts/``. Edit the file; git keeps the history."""

_MARKER_RE = re.compile(r"^<!--\s*lumitrace-prompt:\s*(system|user)\s*-->[ \t]*$", re.MULTILINE)
_PLACEHOLDER_RE = re.compile(r"\{\{\s*([a-z_]+)\s*\}\}")
_REPO_ROOT = Path(lumitrace.__file__).resolve().parents[1]


class PromptError(ValueError):
    """A prompt file is missing or malformed."""


@dataclass(frozen=True)
class Prompt:
    task: str
    system: str
    user: str

    @property
    def label(self) -> str:
        """``fill_day``: the name stored in the day file's ``prompt_version``."""
        return self.task

    def render(self, **values: str) -> list[dict[str, str]]:
        """Chat messages with the placeholders filled in."""

        def fill(text: str) -> str:
            def sub(m: re.Match[str]) -> str:
                name = m.group(1)
                if name not in values:
                    raise KeyError(f"prompt {self.label} needs a value for {{{{{name}}}}}")
                return values[name]

            return _PLACEHOLDER_RE.sub(sub, text)

        return [
            {"role": "system", "content": fill(self.system)},
            {"role": "user", "content": fill(self.user)},
        ]


def resolve_prompts_dir(prompts_dir: Path) -> Path:
    """``prompts_dir`` as configured; relative paths fall back to the repository's ``prompts/``."""
    if prompts_dir.is_dir() or prompts_dir.is_absolute():
        return prompts_dir
    candidate = _REPO_ROOT / prompts_dir
    return candidate if candidate.is_dir() else prompts_dir


def day_template_path(prompts_dir: Path) -> Path:
    """``prompts/day-template.md``: the shape pasted into the fill-day user message."""
    return resolve_prompts_dir(prompts_dir) / "day-template.md"


def parse_prompt(task: str, text: str) -> Prompt:
    parts: dict[str, str] = {}
    matches = list(_MARKER_RE.finditer(text))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        parts[m.group(1)] = text[m.end() : end].strip()
    if not parts.get("system") or not parts.get("user"):
        raise PromptError(f"prompt {task} needs system and user parts")
    return Prompt(task=task, system=parts["system"], user=parts["user"])


@lru_cache(maxsize=32)
def _load_cached(directory: str, task: str) -> Prompt:
    path = Path(directory) / f"{task}.md"
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise PromptError(f"prompt file not found: {path}") from exc
    return parse_prompt(task, text)


def load_prompt(prompts_dir: Path, task: str) -> Prompt:
    """Load ``<prompts_dir>/<task>.md``."""
    if task not in PROMPT_TASKS:
        raise PromptError(f"unknown prompt task: {task}")
    return _load_cached(str(resolve_prompts_dir(prompts_dir)), task)


def join_prompt_labels(labels: list[str]) -> str:
    """``fill_day`` or ``update_day``: the ``prompt_version`` stored in front matter."""
    return "+".join(dict.fromkeys(labels))
