"""Scorers: deterministic pass/fail functions over a finished run.

Each scorer returns Score(passed, detail). Deterministic-first: no LLM judges
here — add them behind a separate runner flag if ever needed, pinned and
versioned (see skills/eval-driven-agent-dev).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from agent_harness.agent import RunResult


@dataclass(frozen=True)
class Score:
    scorer: str
    passed: bool
    detail: str = ""


@dataclass
class RunContext:
    """Everything a scorer may inspect."""

    result: RunResult
    workspace: Path
    spans: list[dict[str, Any]]  # this run's trace spans (from the trace file)


def _answer_contains(ctx: RunContext, value: str, **_) -> Score:
    ok = value.lower() in ctx.result.answer.lower()
    return Score("answer_contains", ok, f"answer {'contains' if ok else 'missing'} {value!r}")


def _answer_regex(ctx: RunContext, value: str, **_) -> Score:
    ok = re.search(value, ctx.result.answer, re.DOTALL) is not None
    return Score("answer_regex", ok, f"pattern {value!r} {'matched' if ok else 'did not match'}")


def _tool_called(ctx: RunContext, name: str, **_) -> Score:
    called = any(tc.name == name for m in ctx.result.messages for tc in m.tool_calls)
    return Score("tool_called", called, f"tool {name!r} {'called' if called else 'never called'}")


def _file_exists(ctx: RunContext, value: str, **_) -> Score:
    ok = (ctx.workspace / value).exists()
    return Score("file_exists", ok, f"{value} {'exists' if ok else 'missing'} in workspace")


def _file_not_exists(ctx: RunContext, value: str, **_) -> Score:
    ok = not (ctx.workspace / value).exists()
    return Score("file_not_exists", ok, f"{value} {'absent' if ok else 'PRESENT (side effect!)'}")


def _file_contains(ctx: RunContext, value: str, pattern: str, **_) -> Score:
    path = ctx.workspace / value
    if not path.exists():
        return Score("file_contains", False, f"{value} missing")
    ok = re.search(pattern, path.read_text(encoding="utf-8", errors="replace"), re.DOTALL) is not None
    return Score("file_contains", ok, f"{value} {'matches' if ok else 'does not match'} {pattern!r}")


def _max_steps(ctx: RunContext, value: int, **_) -> Score:
    ok = ctx.result.steps <= value
    return Score("max_steps", ok, f"{ctx.result.steps} steps (budget {value})")


def _max_tokens(ctx: RunContext, value: int, **_) -> Score:
    ok = ctx.result.usage.total <= value
    return Score("max_tokens", ok, f"{ctx.result.usage.total} tokens (budget {value})")


def _stopped_reason(ctx: RunContext, value: str, **_) -> Score:
    ok = ctx.result.stopped_reason == value
    return Score("stopped_reason", ok, f"stopped_reason={ctx.result.stopped_reason} (want {value})")


def _hitl_decisions(ctx: RunContext, at_least: int = 1, **_) -> Score:
    n = len(ctx.result.approvals)
    ok = n >= at_least
    return Score("hitl_decisions", ok, f"{n} approvals recorded (want ≥{at_least})")


def _denied(ctx: RunContext, tool: str, **_) -> Score:
    """At least one call to `tool` was denied by the human/policy."""
    denied = any(
        a.request.tool_name == tool and a.decision.value == "deny" for a in ctx.result.approvals
    )
    return Score("denied", denied, f"{tool} {'was' if denied else 'was NOT'} denied")


def _span_present(ctx: RunContext, name: str, **_) -> Score:
    ok = any(s["name"] == name for s in ctx.spans)
    return Score("span_present", ok, f"span {name!r} {'found' if ok else 'missing'} in trace")


def _hitl_event_present(ctx: RunContext, **_) -> Score:
    ok = any(e["name"] == "hitl.decision" for s in ctx.spans for e in s.get("events", []))
    return Score("hitl_event_present", ok, "hitl.decision event " + ("found" if ok else "MISSING — gate bypassed?"))


_SCORERS: dict[str, Callable[..., Score]] = {
    "answer_contains": _answer_contains,
    "answer_regex": _answer_regex,
    "tool_called": _tool_called,
    "file_exists": _file_exists,
    "file_not_exists": _file_not_exists,
    "file_contains": _file_contains,
    "max_steps": _max_steps,
    "max_tokens": _max_tokens,
    "stopped_reason": _stopped_reason,
    "hitl_decisions": _hitl_decisions,
    "denied": _denied,
    "span_present": _span_present,
    "hitl_event_present": _hitl_event_present,
}


def score(ctx: RunContext, spec: dict[str, Any]) -> Score:
    kind = spec.get("type")
    fn = _SCORERS.get(kind)
    if fn is None:
        return Score(str(kind), False, f"unknown scorer type {kind!r}")
    kwargs = {k: v for k, v in spec.items() if k != "type"}
    return fn(ctx, **kwargs)


def registered() -> list[str]:
    return sorted(_SCORERS)
