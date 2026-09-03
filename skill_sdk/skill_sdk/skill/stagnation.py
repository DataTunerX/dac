"""
Stagnation detector — detects when the LLM is stuck in a failure loop.

Analysis of Pi Agent Loop revealed zero stagnation detection. The LLM can keep
issuing the same failing tool calls forever until max_steps exhausts.

This module provides:
  - StagnationDetector: tracks consecutive failures, same-cmd repeats,
    and failure patterns across the tool_history.
  - Intervention messages: when thresholds are hit, generates concise
    context warnings injected as HumanMessage so the LLM sees them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class StagnationEvent:
    """A single tool execution event for stagnation analysis."""

    step: int
    tool_name: str
    args: dict[str, Any]
    status: str | None = None  # "success" | "error" | "blocked"
    is_error: bool = False
    error_content: str = ""  # first 200 chars of error content
    cmd: str = ""  # for plan_cmd
    cmd_signature: str = ""  # canonical signature for dedup: json.dumps(args) for all tools


def _parse_tool_result(raw: str | dict | None) -> dict[str, Any] | None:
    if isinstance(raw, dict):
        return raw
    if raw is None:
        return None
    try:
        return json.loads(str(raw))
    except (json.JSONDecodeError, TypeError):
        return None


def _extract_cmd(args: dict[str, Any]) -> str:
    return str(args.get("cmd", "")).strip()


def _extract_tool_call_signature(tool_name: str, args: dict[str, Any]) -> str:
    """Build a canonical signature for deduplication.

    For plan_cmd: use the cmd string directly (exact match).
    For all other tools (web_fetch, etc.): use json.dumps(args, sort_keys=True)
    so the same URL+args combination is detected regardless of dict key order.
    """
    if tool_name == "plan_cmd":
        return _extract_cmd(args)
    try:
        return json.dumps(args, sort_keys=True, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(args)


@dataclass
class StagnationDetector:
    """Tracks tool execution history to detect stagnation patterns.

    Four levels of detection:
      1. Same-cmd repeat: the same tool+args combination was issued and failed before
         (works for ALL tools: plan_cmd, web_fetch, code_exec, etc.).
      2. Consecutive failures: N tool calls in a row were all errors.
      3. Same-error-pattern: the same error type/content keeps appearing.
      4. Total failure ratio: too many tool calls are failing overall.

    Each level has a threshold; when hit, an intervention message is generated.
    """

    same_cmd_repeat_threshold: int = 2
    consecutive_fail_threshold: int = 3
    same_error_pattern_threshold: int = 3
    total_fail_ratio_threshold: float = 0.7

    events: list[StagnationEvent] = field(default_factory=list)
    _last_intervention_step: int = -1

    def record(
        self,
        step: int,
        tool_name: str,
        args: dict[str, Any],
        result_raw: str | dict | None,
    ) -> None:
        parsed = _parse_tool_result(result_raw)
        status = parsed.get("status") if parsed else None
        # Plugin tools (web_fetch, etc.) return {"error": "..."} without is_error=True.
        # Detect errors by presence of "error" key in the result JSON.
        has_error_key = bool(parsed.get("error")) if parsed else False
        is_error = (
            True
            if has_error_key
            else (bool(parsed.get("is_error", False)) if parsed else True)
        )

        content = ""
        if parsed and isinstance(parsed.get("content"), str):
            content = parsed["content"][:200]
        if not content and parsed and isinstance(parsed.get("error"), str):
            content = parsed["error"][:200]

        self.events.append(
            StagnationEvent(
                step=step,
                tool_name=tool_name,
                args=dict(args),
                status=status,
                is_error=is_error,
                error_content=content if is_error else "",
                cmd=_extract_cmd(args) if tool_name == "plan_cmd" else "",
                cmd_signature=_extract_tool_call_signature(tool_name, args),
            )
        )

    def check(self, current_step: int) -> str | None:
        """Check for stagnation and return an intervention message if needed."""
        if current_step - self._last_intervention_step < 3:
            return None
        if len(self.events) < 2:
            return None

        messages: list[str] = []

        msg = self._check_same_cmd_repeat()
        if msg:
            messages.append(msg)

        msg = self._check_consecutive_failures()
        if msg:
            messages.append(msg)

        msg = self._check_same_error_pattern()
        if msg:
            messages.append(msg)

        msg = self._check_total_fail_ratio()
        if msg:
            messages.append(msg)

        if not messages:
            return None

        self._last_intervention_step = current_step
        return "\n\n".join(messages)

    def check_same_cmd_before_execute(
        self, tool_name: str, args: dict[str, Any]
    ) -> str | None:
        """Called BEFORE executing a tool call. If the same tool+args already failed
        enough times, return a preemptive warning.

        Works for ALL tools: plan_cmd uses cmd as the key, other tools
        (web_fetch, etc.) use json.dumps(args) as the signature.
        """
        sig = _extract_tool_call_signature(tool_name, args)
        if not sig:
            return None

        same_failures = [
            e
            for e in self.events
            if e.tool_name == tool_name and e.cmd_signature == sig and e.is_error
        ]

        if len(same_failures) >= self.same_cmd_repeat_threshold:
            steps = [e.step for e in same_failures]
            last_error = same_failures[-1].error_content[:120]
            return (
                f"WARNING: This exact command already failed "
                f"{len(same_failures)} times (steps {steps}). "
                f"Do NOT re-issue it. Last error: {last_error}. "
                "Try a DIFFERENT approach or call finish."
            )
        return None

    def _check_same_cmd_repeat(self) -> str | None:
        """Detect when the same tool+args combination keeps failing.

        Uses cmd_signature for deduplication: for plan_cmd it's the cmd string,
        for all other tools it's json.dumps(args, sort_keys=True).
        """
        sig_failures: dict[str, list[StagnationEvent]] = {}
        for e in self.events:
            if e.is_error and e.cmd_signature:
                sig_failures.setdefault(e.cmd_signature, []).append(e)

        for sig, failures in sig_failures.items():
            if len(failures) >= self.same_cmd_repeat_threshold:
                steps = [e.step for e in failures]
                tool_name = failures[0].tool_name
                # Truncate signature for display
                sig_display = sig[:120] if len(sig) > 120 else sig
                return (
                    f"CRITICAL: Same {tool_name} call failing repeatedly\n"
                    f"`{sig_display}` has failed {len(failures)} times "
                    f"(at steps {steps}).\n"
                    "DO NOT re-issue this call with the same arguments. "
                    "Try a completely different approach:\n"
                    "- For web_fetch: use a different URL or search engine first\n"
                    "- Use a different tool (tavily_search, glob, grep, readline_in_range)\n"
                    "- If you cannot make progress, call finish and explain."
                )
        return None

    def _check_consecutive_failures(self) -> str | None:
        consecutive = 0
        last_idx = -1
        for i, e in enumerate(self.events):
            if e.is_error:
                if last_idx == -1 or i == last_idx + 1:
                    consecutive += 1
                else:
                    consecutive = 1
                last_idx = i
            else:
                consecutive = 0
                last_idx = -1

        if consecutive >= self.consecutive_fail_threshold:
            recent_failures = [e for e in self.events if e.is_error][-consecutive:]
            failure_summary = []
            for f in recent_failures:
                err_brief = f.error_content[:80].replace("\n", " ")
                failure_summary.append(f"  Step {f.step}: {f.tool_name} -> {err_brief}")

            return (
                f"{consecutive} consecutive tool failures\n"
                "Recent failures:\n"
                + "\n".join(failure_summary)
                + f"\n\nYou have been failing for {consecutive} steps in a row. "
                "Stop and re-evaluate:\n"
                "- Are you using the right tools for this task?\n"
                "- Should you gather more information before trying again?\n"
                "- If the task is impossible with available tools, call finish."
            )
        return None

    def _check_same_error_pattern(self) -> str | None:
        error_patterns: dict[str, list[StagnationEvent]] = {}
        for e in self.events:
            if e.is_error and e.error_content:
                fingerprint = e.error_content[:40]
                error_patterns.setdefault(fingerprint, []).append(e)

        for fingerprint, failures in error_patterns.items():
            if len(failures) >= self.same_error_pattern_threshold:
                steps = [e.step for e in failures]
                return (
                    "Same error pattern repeating\n"
                    f"Error pattern `{fingerprint}...` has appeared "
                    f"{len(failures)} times (at steps {steps}).\n"
                    "You are making the same mistake repeatedly. "
                    "Change your strategy or call finish."
                )
        return None

    def _check_total_fail_ratio(self) -> str | None:
        total = len(self.events)
        if total < 4:
            return None
        failed = sum(1 for e in self.events if e.is_error)
        ratio = failed / total

        if ratio >= self.total_fail_ratio_threshold:
            return (
                f"High failure rate: {failed}/{total} tool calls failed "
                f"({ratio:.0%})\n"
                "Most of your tool calls are failing. Consider:\n"
                "- Are you approaching this task correctly?\n"
                "- Do you need to read documentation or help text first?\n"
                "- If the tools are insufficient, call finish and explain."
            )
        return None


def generate_stagnation_intervention(
    detector: StagnationDetector,
    current_step: int,
    tool_history: list[dict[str, Any]],
) -> str | None:
    """Record the latest tool_history entries into the detector, then check.

    Call this after tool results are appended to the context, before the next
    LLM invoke.
    """
    recorded = len(detector.events)
    for i in range(recorded, len(tool_history)):
        entry = tool_history[i]
        tool_name = str(entry.get("tool", ""))
        if not tool_name:
            continue
        detector.record(
            step=current_step,
            tool_name=tool_name,
            args=dict(entry.get("args", {})),
            result_raw=entry.get("result"),
        )

    return detector.check(current_step)