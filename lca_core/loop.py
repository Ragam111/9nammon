"""Agent lap loop: observe, reason, act, check.

The lap ceiling is 10. Prompt templates stay short so they are cheap to format.
This loop does not call a model by itself — ``reason`` is the caller's function.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from lca_core.constants import DEFAULT_MAX_LAPS, HARD_LAP_CAP

# Kept short on purpose. Format with render(stage, n).
TEMPLATES = {
    "observe": "obs:{n}",
    "reason": "next:{n}",
    "act": "do:{n}",
    "check": "done?",
}

__all__ = ["LapMetrics", "LoopResult", "TEMPLATES", "render", "run_loop"]


def render(stage: str, n: int = 0) -> str:
    return TEMPLATES[stage].format(n=n)


@dataclass
class LapMetrics:
    lap: int
    observe_ms: float
    reason_ms: float
    act_ms: float
    tokens: int
    prompt: str
    acted: bool


@dataclass
class LoopResult:
    stop_reason: str
    laps: list[LapMetrics] = field(default_factory=list)
    output: Any = None
    tokens_used: int = 0


def run_loop(
    goal_check: Callable,
    observe: Callable,
    reason: Callable,
    act: Callable,
    *,
    max_laps: int = DEFAULT_MAX_LAPS,
    token_budget: int | None = None,
    hard_stop: Callable | None = None,
    clock: Callable[[], float] | None = None,
) -> LoopResult:
    """Run observe → reason → act → check until a stop condition.

    Stop reasons: ``goal``, ``max_laps``, ``token_budget``, ``hard_stop``.
    ``max_laps`` is clamped to ``HARD_LAP_CAP`` (10). When the token budget is
    exceeded, ``act`` is not called for that lap.
    """
    ticks = clock or time.perf_counter
    limit = min(max(int(max_laps), 1), HARD_LAP_CAP)
    laps: list[LapMetrics] = []
    tokens_used = 0
    output = None

    for lap in range(1, limit + 1):
        if hard_stop is not None and hard_stop():
            return LoopResult("hard_stop", laps, output, tokens_used)
        prompt = render("reason", lap)
        t0 = ticks()
        observation = observe()
        t1 = ticks()
        reasoned = reason(observation)
        action, used = _split_reason(reasoned)
        t2 = ticks()
        tokens_used += used
        if token_budget is not None and tokens_used > token_budget:
            laps.append(LapMetrics(lap, _ms(t0, t1), _ms(t1, t2), 0.0, used, prompt, False))
            return LoopResult("token_budget", laps, output, tokens_used)
        output = act(action)
        t3 = ticks()
        laps.append(LapMetrics(lap, _ms(t0, t1), _ms(t1, t2), _ms(t2, t3), used, prompt, True))
        if hard_stop is not None and hard_stop():
            return LoopResult("hard_stop", laps, output, tokens_used)
        if goal_check(output):
            return LoopResult("goal", laps, output, tokens_used)
    return LoopResult("max_laps", laps, output, tokens_used)


def _split_reason(reasoned: Any) -> tuple[Any, int]:
    if isinstance(reasoned, tuple):
        action = reasoned[0] if reasoned else None
        used = int(reasoned[1]) if len(reasoned) > 1 else 0
        return action, used
    return reasoned, 0


def _ms(start: float, end: float) -> float:
    return (end - start) * 1000.0
