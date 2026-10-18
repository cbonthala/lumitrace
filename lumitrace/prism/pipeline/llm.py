"""JSON-producing LLM calls through LiteLLM, with a per-task model and a fallback model.

Every model string comes from config (``LUMITRACE_LLM_*``). The special model string ``fake``
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

from lumitrace.prism.pipeline.activity import safe_error

if TYPE_CHECKING:
    from lumitrace.config import Settings

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


_TRUNCATED_REASONS = frozenset({"length", "max_tokens"})


def model_max_output_tokens(model: str) -> int | None:
    """The model's output-token ceiling from LiteLLM's price table, or None if unknown.

    A missing model returns None without a lookup error. ``fake`` and test model names are
    unknown, so offline calls leave the provider default in place.
    """
    try:
        import litellm
    except Exception:
        return None
    info = litellm.model_cost.get(model)
    if not isinstance(info, dict):
        return None
    raw = info.get("max_output_tokens") or info.get("max_tokens")
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        return None
    value = int(raw)
    return value if value > 0 else None


def _finish_reason(resp: Any) -> str:
    try:
        choice = resp["choices"][0] if isinstance(resp, dict) else resp.choices[0]
    except (AttributeError, IndexError, KeyError, TypeError):
        return ""
    if isinstance(choice, dict):
        reason = choice.get("finish_reason")
    else:
        reason = getattr(choice, "finish_reason", None)
    return str(reason or "").casefold()


def _completion_tokens(resp: Any) -> int | None:
    usage = resp.get("usage") if isinstance(resp, dict) else getattr(resp, "usage", None)
    if usage is None:
        return None
    raw = (
        usage.get("completion_tokens")
        if isinstance(usage, dict)
        else getattr(usage, "completion_tokens", None)
    )
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        return None
    return int(raw)


def _should_raise_output_limit(
    reason: str,
    tokens: int | None,
    limit: int | None,
    ceiling: int | None,
    raised: bool,
) -> bool:
    """True when the reply stopped for length and the model allows a higher ceiling."""
    if raised or reason not in _TRUNCATED_REASONS or ceiling is None:
        return False
    if limit is not None and limit >= ceiling:
        return False
    return tokens is None or tokens < int(ceiling * 0.9)


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
        max_tokens: int | None = None,
    ) -> LLMResult[T]:
        """Ask ``model`` (then the fallback) for JSON and validate it with ``parse``.

        A reply that is not valid JSON or fails ``parse`` counts as a failure of that model.
        Raises :class:`LLMError` if every model fails.

        ``max_tokens`` is the output ceiling for the first try. When it is omitted, the call
        uses the model's own maximum (Gemini 3.8 Flash is 65536). A reply that stops because
        it hit a lower ceiling is retried once at that maximum.
        """
        attempts: list[Attempt] = []
        for candidate in self.models_for(model):
            if candidate == FAKE_MODEL:
                started = time.monotonic()
                try:
                    value = parse(fake())
                except Exception as exc:
                    ms = int((time.monotonic() - started) * 1000)
                    attempts.append(Attempt(candidate, False, ms, safe_error(exc)))
                    log.warning("%s failed on %s: %s", task, candidate, safe_error(exc))
                    continue
                ms = int((time.monotonic() - started) * 1000)
                attempts.append(Attempt(candidate, True, ms))
                return LLMResult(value=value, model=candidate, attempts=attempts)

            ceiling = model_max_output_tokens(candidate)
            limit = max_tokens if max_tokens is not None else ceiling
            raised = False
            while True:
                started = time.monotonic()
                cost: float | None = None
                try:
                    kwargs: dict[str, Any] = {
                        "model": candidate,
                        "messages": messages,
                        "response_format": {"type": "json_object"},
                        "timeout": self.settings.llm_timeout_seconds,
                        "num_retries": self.settings.llm_max_retries,
                        "drop_params": True,
                    }
                    if limit is not None:
                        kwargs["max_tokens"] = limit
                    resp = self._complete(**kwargs)
                    cost = response_cost(resp)
                    reason = _finish_reason(resp)
                    tokens = _completion_tokens(resp)
                    log.info(
                        "%s: model=%s max_output_tokens=%s model_max_output_tokens=%s "
                        "finish=%s completion_tokens=%s",
                        task,
                        candidate,
                        limit if limit is not None else "default",
                        ceiling if ceiling is not None else "unknown",
                        reason or "unknown",
                        tokens if tokens is not None else "unknown",
                    )
                    if _should_raise_output_limit(reason, tokens, limit, ceiling, raised):
                        ms = int((time.monotonic() - started) * 1000)
                        attempts.append(Attempt(candidate, False, ms, "output truncated", cost))
                        log.warning(
                            "%s hit the output token limit on %s "
                            "(completion_tokens=%s, max_output_tokens=%s); "
                            "retrying with max_output_tokens=%s",
                            task,
                            candidate,
                            tokens if tokens is not None else "unknown",
                            limit if limit is not None else "default",
                            ceiling,
                        )
                        limit = ceiling
                        raised = True
                        continue
                    if reason in _TRUNCATED_REASONS:
                        log.warning(
                            "%s output hit the model max on %s "
                            "(completion_tokens=%s, max_output_tokens=%s)",
                            task,
                            candidate,
                            tokens if tokens is not None else "unknown",
                            limit if limit is not None else "default",
                        )
                    raw = extract_json(_message_content(resp))
                    value = parse(raw)
                except Exception as exc:
                    ms = int((time.monotonic() - started) * 1000)
                    attempts.append(Attempt(candidate, False, ms, safe_error(exc), cost))
                    log.warning("%s failed on %s: %s", task, candidate, safe_error(exc))
                    break
                ms = int((time.monotonic() - started) * 1000)
                attempts.append(Attempt(candidate, True, ms, None, cost))
                return LLMResult(value=value, model=candidate, attempts=attempts)
        raise LLMError(task, attempts)
