"""Model-family-aware parameter shims for OpenAI calls.

GPT-5+ reasoning models reject `temperature` and `max_tokens` (they take
`max_completion_tokens` and reasoning controls instead), while legacy
gpt-4-era models still use the old knobs. Centralizing the branching keeps
call sites model-agnostic so the model can be swapped via config alone.
"""

from __future__ import annotations

from typing import Any

_REASONING_PREFIXES = ("gpt-5", "o1", "o3", "o4")


def is_reasoning_model(model: str) -> bool:
    return (model or "").lower().startswith(_REASONING_PREFIXES)


def chat_tuning(model: str, *, temperature: float, max_tokens: int) -> dict[str, Any]:
    """Sampling/limit kwargs for a chat.completions call."""
    if is_reasoning_model(model):
        return {"max_completion_tokens": max_tokens}
    return {"temperature": temperature, "max_tokens": max_tokens}


def responses_tuning(model: str, *, temperature: float, reasoning_effort: str) -> dict[str, Any]:
    """Sampling/reasoning kwargs for a responses.create call."""
    if is_reasoning_model(model):
        return {"reasoning": {"effort": reasoning_effort}}
    return {"temperature": temperature}
