"""JSON-producing LLM calls through LiteLLM, with a per-task model and a fallback model.

Every model string comes from config (``BOOKSHELF_LLM_*``). The special model string ``fake``
skips LiteLLM and returns a deterministic answer supplied by the caller, so the whole API runs
offline (tests, local trials).
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, TypeVar

from bookshelf.typewriter.pipeline.activity import safe_error

if TYPE_CHECKING:
    from bookshelf.config import Settings

log = logging.getLogger(__name__)

T = TypeVar("T")
FAKE_MODEL = "fake"
CompletionFn = Callable[..., Any]

_FENCE_RE = re.compile(r"^```[a-zA-Z]*\s*\n?(.*?)\n?```\s*$", re.DOTALL)


class LLMError(RuntimeError):
    """Every model (task model and fallback) failed. ``attempts`` says how."""

    def __init__(self, task: str, attempts: list[Attempt]) -> None:
        summary = "; ".join(f"{a.model}: {a.error}" for a in attempts)
        super().__init__(f"{task} failed on all models ({summary})")
        self.task = task
        self.attempts = attempts


@dataclass
class Attempt:
    model: str
    ok: bool
    ms: int
    error: str | None = None
    cost_usd: float | None = None


@dataclass
class LLMResult[T]:
    value: T
    model: str
    """The model that produced ``value`` (the fallback, if the task model failed)."""
    attempts: list[Attempt] = field(default_factory=list)

    @property
    def cost_usd(self) -> float | None:
        costs = [a.cost_usd for a in self.attempts if a.cost_usd is not None]
        return round(sum(costs), 6) if costs else None


def extract_json(text: str) -> Any:
    """Parse a JSON object from a model reply, tolerating Markdown code fences and chatter."""
    stripped = text.strip()
    fence = _FENCE_RE.match(stripped)
    if fence:
        stripped = fence.group(1).strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        start, end = stripped.find("{"), stripped.rfind("}")
        if start == -1 or end <= start:
            raise
        return json.loads(stripped[start : end + 1])


def _message_content(resp: Any) -> str:
    choice = resp["choices"][0] if isinstance(resp, dict) else resp.choices[0]
    message = choice["message"] if isinstance(choice, dict) else choice.message
    content = message["content"] if isinstance(message, dict) else message.content
    if not content:
        raise ValueError("empty reply")
    return str(content)


def response_cost(resp: Any, call_type: str = "completion") -> float | None:
    """Cost in USD reported by LiteLLM, or None when it does not know the price."""
    hidden = getattr(resp, "_hidden_params", None)
    if isinstance(hidden, dict) and isinstance(hidden.get("response_cost"), int | float):
        return float(hidden["response_cost"])
    try:
        import litellm

        return float(litellm.completion_cost(completion_response=resp, call_type=call_type))
    except Exception:
        return None


class LLMClient:
    def __init__(self, settings: Settings, completion_fn: CompletionFn | None = None) -> None:
        self.settings = settings
        self._completion_fn = completion_fn

    def _complete(self, **kwargs: Any) -> Any:
        if self._completion_fn is not None:
            return self._completion_fn(**kwargs)
        import litellm

        return litellm.completion(**kwargs)

    def models_for(self, model: str) -> list[str]:
        fallback = self.settings.llm_fallback_model
        return [model, fallback] if fallback and fallback != model else [model]

    def complete_json(
        self,
        *,
        task: str,
        model: str,
        messages: list[dict[str, str]],
        parse: Callable[[Any], T],
        fake: Callable[[], Any],
    ) -> LLMResult[T]:
        """Ask ``model`` (then the fallback) for JSON and validate it with ``parse``.

        A reply that is not valid JSON or fails ``parse`` counts as a failure of that model.
        Raises :class:`LLMError` if every model fails.
        """
        attempts: list[Attempt] = []
        for candidate in self.models_for(model):
            started = time.monotonic()
            cost: float | None = None
            try:
                if candidate == FAKE_MODEL:
                    raw = fake()
                else:
                    resp = self._complete(
                        model=candidate,
                        messages=messages,
                        response_format={"type": "json_object"},
                        timeout=self.settings.llm_timeout_seconds,
                        num_retries=self.settings.llm_max_retries,
                        drop_params=True,
                    )
                    cost = response_cost(resp)
                    raw = extract_json(_message_content(resp))
                value = parse(raw)
            except Exception as exc:
                ms = int((time.monotonic() - started) * 1000)
                attempts.append(Attempt(candidate, False, ms, safe_error(exc), cost))
                log.warning("%s failed on %s: %s", task, candidate, safe_error(exc))
                continue
            ms = int((time.monotonic() - started) * 1000)
            attempts.append(Attempt(candidate, True, ms, None, cost))
            return LLMResult(value=value, model=candidate, attempts=attempts)
        raise LLMError(task, attempts)
