"""Skill-agent two-phase capability check, reused by SD Orchestrator.

Control flow, prompts, JSON repair, and aggregation are the skill-agent
scheme:

1. Phase 1 ``DOMAIN_CHECK_PROMPT`` — domain overlap only.
2. ``none`` short-circuits; ``has`` / ``uncertain`` enter Phase 2.
3. Phase 2 ``SKILL_CAPABILITY_CHECK_PROMPT`` scores I/D/O/R/C.
4. ``capability_chain.aggregate()`` derives can_handle / can_contribute /
   confidence. The LLM never outputs those booleans.

Prompts are loaded from the sibling ``skill-agent`` tree when present so
local checkouts stay in lock-step; otherwise the vendored copy in
``skill_capability_prompts.py`` is used (generated from the same source).
"""

from __future__ import annotations

import ast
import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from langchain_core.messages import AIMessage, HumanMessage

from . import capability_chain
from . import skill_capability_prompts as _vendored_prompts

logger = logging.getLogger(__name__)

try:
    from json_repair import repair_json as _json_repair
except ImportError:  # pragma: no cover
    _json_repair = None

_KNOWN_STRING_FIELDS_WITH_INNER_QUOTES = (
    "original_query",
    "description",
    "thought_process",
    "reason",
    "rationale",
    "final_answer",
    "contribution",
)


def _skill_agent_source_path() -> Optional[Path]:
    sibling = Path(__file__).resolve().parents[2] / "skill-agent" / "agent" / "skill_agent.py"
    return sibling if sibling.is_file() else None


def _extract_string_assigns(path: Path, names: tuple[str, ...]) -> dict[str, str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    wanted = set(names)
    found: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id in wanted:
                found[target.id] = ast.literal_eval(node.value)
    return found


def load_skill_agent_prompts() -> tuple[str, str]:
    """Return ``(DOMAIN_CHECK_PROMPT, SKILL_CAPABILITY_CHECK_PROMPT)``.

    Prefer the live skill-agent source when this repo layout is available.
    """
    source = _skill_agent_source_path()
    if source is not None:
        try:
            extracted = _extract_string_assigns(
                source, ("DOMAIN_CHECK_PROMPT", "SKILL_CAPABILITY_CHECK_PROMPT")
            )
            domain = extracted.get("DOMAIN_CHECK_PROMPT")
            chain = extracted.get("SKILL_CAPABILITY_CHECK_PROMPT")
            if domain and chain:
                return domain, chain
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[Capability][TwoPhase] failed to load live skill-agent prompts "
                "from %s: %s — using vendored copy",
                source,
                exc,
            )
    return (
        _vendored_prompts.DOMAIN_CHECK_PROMPT,
        _vendored_prompts.SKILL_CAPABILITY_CHECK_PROMPT,
    )


DOMAIN_CHECK_PROMPT, SKILL_CAPABILITY_CHECK_PROMPT = load_skill_agent_prompts()


def _escape_known_string_field_inner_quotes(text: str) -> str:
    """Copied from skill-agent ``skill_agent.py``."""
    if not text or '"' not in text:
        return text
    pattern_fields = "|".join(re.escape(f) for f in _KNOWN_STRING_FIELDS_WITH_INNER_QUOTES)
    pattern = re.compile(
        rf'("(?:{pattern_fields})"\s*:\s*")'
        r"(.*?)"
        r'((?<!\\)"[ \t]*,?[ \t]*$)',
        re.MULTILINE,
    )

    def _repl(m: re.Match[str]) -> str:
        head, body, tail = m.group(1), m.group(2), m.group(3)
        fixed_chars: list[str] = []
        i = 0
        while i < len(body):
            ch = body[i]
            if ch == "\\" and i + 1 < len(body):
                fixed_chars.append(body[i : i + 2])
                i += 2
                continue
            if ch == '"':
                fixed_chars.append('\\"')
                i += 1
                continue
            fixed_chars.append(ch)
            i += 1
        return head + "".join(fixed_chars) + tail

    return pattern.sub(_repl, text)


def parse_llm_json(answer: Any) -> Optional[dict]:
    """Parse LLM plain-text output into a dict.

    Copied from skill-agent ``_parse_json_output``.
    """
    raw = (
        "".join(
            [
                str(p.get("text", "")) if isinstance(p, dict) else (getattr(p, "text", None) or str(p))
                for p in (getattr(answer, "content", None) or [])
            ]
        )
        if isinstance(getattr(answer, "content", None), list)
        else ""
    )
    if not raw:
        raw = getattr(answer, "content", None)
    if not isinstance(raw, str):
        raw = str(answer or "")
    if not raw.strip():
        return None
    try:
        parsed = json.loads(raw, strict=False)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    cleaned_content = raw.strip()
    if cleaned_content.startswith("```json"):
        cleaned_content = cleaned_content[7:]
    elif cleaned_content.startswith("```"):
        cleaned_content = cleaned_content[3:]
    if cleaned_content.endswith("```"):
        cleaned_content = cleaned_content[:-3]
    cleaned_content = cleaned_content.strip()

    try:
        parsed = json.loads(cleaned_content, strict=False)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    escaped_content = _escape_known_string_field_inner_quotes(cleaned_content)
    if escaped_content != cleaned_content:
        try:
            parsed = json.loads(escaped_content, strict=False)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            pass

    if _json_repair is not None:
        try:
            repaired = _json_repair(escaped_content, return_objects=True)
            if isinstance(repaired, dict):
                return repaired
        except Exception:
            pass

    try:
        parsed = ast.literal_eval(cleaned_content)
        if isinstance(parsed, dict):
            return parsed
    except (ValueError, SyntaxError):
        pass

    try:
        parsed = json.loads(cleaned_content.replace("'", '"'), strict=False)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass
    return None


@dataclass
class TwoPhaseResult:
    """Result of skill-agent two-phase capability check."""

    domain_verdict: str = ""
    can_handle: bool = False
    can_contribute: bool = False
    confidence: float = 0.0
    reason: str = ""
    contribution: str = ""
    missing_requirements: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    evidence_grade: str = ""
    handle_score: float = 0.0
    threshold: float = 0.0
    steps: list[dict[str, Any]] = field(default_factory=list)
    contributing_steps: list[int] = field(default_factory=list)
    has_external_dependency: bool = False
    phase2_invoked: bool = False
    failed_stage: str = ""
    score_version: str = capability_chain.SCORE_VERSION


def _max_attempts() -> int:
    try:
        return max(1, int(os.getenv("CAPABILITY_CHECK_MAX_ATTEMPTS", "3") or "3"))
    except ValueError:
        return 3


def _preview_answer(answer: Any) -> str:
    raw = getattr(answer, "content", None)
    if isinstance(raw, list):
        text = "".join(
            str(p.get("text", "")) if isinstance(p, dict) else str(p) for p in raw
        )
    else:
        text = str(raw or answer or "")
    return text[:400]


async def run_two_phase_capability_check(
    llm: Any,
    *,
    query: str,
    agent_name: str,
    agent_description: str,
    agent_skills: str,
    history: str = "（无）",
    domain_prompt: str | None = None,
    chain_prompt_template: str | None = None,
) -> TwoPhaseResult:
    """Run skill-agent Phase 1 domain check then Phase 2 chain scoring.

    ``agent_skills`` is the authoritative body text (SKILL.md for skill-agent,
    SD metadata inventory for SD orchestrator).
    """
    threshold = capability_chain.get_threshold()
    history_text = history or "（无）"
    domain_template = domain_prompt or DOMAIN_CHECK_PROMPT
    chain_template = chain_prompt_template or SKILL_CAPABILITY_CHECK_PROMPT
    max_attempts = _max_attempts()

    domain_prompt_text = domain_template.format(
        agent_name=agent_name,
        agent_description=agent_description,
        agent_skills=agent_skills,
        history=history_text,
        query=query,
    )
    domain_result: Optional[capability_chain.DomainCheckResult] = None
    nudge: Optional[HumanMessage] = None

    for attempt in range(1, max_attempts + 1):
        logger.info(
            "[Capability][Domain] llm_invoke attempt=%d/%d agent=%s",
            attempt,
            max_attempts,
            agent_name,
        )
        attempt_messages = (
            [HumanMessage(content=domain_prompt_text)]
            if nudge is None
            else [HumanMessage(content=domain_prompt_text), AIMessage(content=""), nudge]
        )
        try:
            answer = await llm.ainvoke(attempt_messages)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[Capability][Domain] attempt %d: LLM invoke failed: %s: %s",
                attempt,
                type(exc).__name__,
                exc,
            )
            nudge = HumanMessage(
                content="上一次调用失败。请只输出包含 domain_verdict 和 reason 的 JSON。"
            )
            continue

        result_data = parse_llm_json(answer)
        if result_data is None:
            logger.warning(
                "[Capability][Domain] attempt %d: invalid JSON, nudging | preview=%s",
                attempt,
                _preview_answer(answer),
            )
            nudge = HumanMessage(
                content='输出无法解析。请只输出 JSON：{"domain_verdict": "...", "reason": "..."}'
            )
            continue

        try:
            domain_result = capability_chain.DomainCheckResult.model_validate(result_data)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[Capability][Domain] attempt %d: parse failed: %s", attempt, exc
            )
            nudge = HumanMessage(
                content=f"JSON 解析成功但字段类型不符合 schema：{exc}。请修正后重新输出。"
            )
            continue

        logger.info(
            "[Capability][Domain] verdict=%s agent=%s",
            domain_result.domain_verdict,
            agent_name,
        )
        break

    if domain_result is None:
        return TwoPhaseResult(
            reason=f"domain_check_failed: no valid JSON after {max_attempts} attempts",
            threshold=threshold,
            failed_stage="domain",
        )

    if domain_result.domain_verdict == "none":
        return TwoPhaseResult(
            domain_verdict=domain_result.domain_verdict,
            can_handle=False,
            can_contribute=False,
            confidence=0.0,
            reason=domain_result.reason,
            evidence_grade="D",
            threshold=threshold,
            phase2_invoked=False,
        )

    domain_info = (
        f"domain_verdict: {domain_result.domain_verdict}\n"
        f"reason: {domain_result.reason}"
    )
    chain_prompt = chain_template.format(
        agent_name=agent_name,
        agent_description=agent_description,
        agent_skills=agent_skills,
        history=history_text,
        query=query,
        domain_info=domain_info,
    )
    chain_result: Optional[capability_chain.CapabilityChainResult] = None
    nudge = None

    for attempt in range(1, max_attempts + 1):
        logger.info(
            "[Capability][JSON] llm_invoke attempt=%d/%d agent=%s",
            attempt,
            max_attempts,
            agent_name,
        )
        attempt_messages = (
            [HumanMessage(content=chain_prompt)]
            if nudge is None
            else [HumanMessage(content=chain_prompt), AIMessage(content=""), nudge]
        )
        try:
            answer = await llm.ainvoke(attempt_messages)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[Capability][JSON] attempt %d: LLM invoke failed: %s: %s",
                attempt,
                type(exc).__name__,
                exc,
            )
            nudge = HumanMessage(
                content=(
                    "上一次调用失败。请重新输出一个完整的 JSON 对象，"
                    "字段必须包含 steps、evidence_grade、contribution、"
                    "missing_requirements、risks、reason。"
                )
            )
            continue

        result_data = parse_llm_json(answer)
        if result_data is None:
            logger.warning(
                "[Capability][JSON] attempt %d: invalid JSON, nudging | preview=%s",
                attempt,
                _preview_answer(answer),
            )
            nudge = HumanMessage(
                content=(
                    "输出无法解析为合法 JSON。请只输出一个 JSON 对象，"
                    "字段包含 steps（步骤数组）、evidence_grade（A/B/C/D）、"
                    "contribution（贡献说明，不能贡献时为空字符串）、"
                    "missing_requirements（缺失项列表，无缺失时为 []）、"
                    "risks（风险列表，无风险时为 []）、"
                    "reason（结构化理由）。"
                    "每个步骤的 RatioCheck 必须同时给出 required、matched、ratio、evidence_strength。"
                )
            )
            continue

        result_data.pop("domain_verdict", None)
        try:
            chain_result = capability_chain.parse_chain_result(result_data)
        except Exception as exc:  # noqa: BLE001
            preview = json.dumps(result_data, ensure_ascii=False, default=str)[:400]
            logger.warning(
                "[Capability][JSON] attempt %d: parse_chain_result failed: %s | data=%s",
                attempt,
                exc,
                preview,
            )
            nudge = HumanMessage(
                content=(
                    f"JSON 解析成功，但字段类型不符合 schema：{exc}。\n"
                    "请严格按照以下 schema 修正后重新输出：\n"
                    '- steps 是数组，每项的 inputs 是对象数组 [{"name":"...","source":"..."}]，不能是单个对象\n'
                    '- outputs 是字符串数组 ["..."]，不能是对象\n'
                    '- constraints 是字符串数组 ["..."]，不能是对象\n'
                    "- input_match/data_coverage/result_match/constraint_satisfaction 是对象 "
                    '{"required":["..."],"matched":["..."],"ratio":0.0}，不是数组\n'
                    "- operation_capability 必须是数字 1.0、0.7 或 0\n"
                )
            )
            continue

        logger.info(
            "[Capability][JSON] SELECTED attempt=%d steps=%d",
            attempt,
            len(chain_result.steps),
        )
        break

    if chain_result is None:
        return TwoPhaseResult(
            domain_verdict=domain_result.domain_verdict,
            reason=f"chain_check_failed: no valid JSON after {max_attempts} attempts",
            threshold=threshold,
            phase2_invoked=True,
            failed_stage="chain",
        )

    agg = capability_chain.aggregate(chain_result, threshold=threshold)
    can_handle = agg.can_handle
    can_contribute = agg.can_contribute
    if can_handle:
        can_contribute = True
    return TwoPhaseResult(
        domain_verdict=domain_result.domain_verdict,
        can_handle=can_handle,
        can_contribute=can_contribute,
        confidence=agg.confidence,
        reason=str(chain_result.reason or "").strip()[:2000],
        contribution=agg.contribution,
        missing_requirements=list(agg.missing_requirements or []),
        risks=list(chain_result.risks or []),
        evidence_grade=chain_result.evidence_grade,
        handle_score=agg.handle_score,
        threshold=agg.threshold,
        steps=agg.steps_payload(chain_result),
        contributing_steps=list(agg.contributing_steps or []),
        has_external_dependency=agg.has_external_dependency,
        phase2_invoked=True,
        score_version=capability_chain.SCORE_VERSION,
    )


def matched_evidence_from_steps(steps: list[dict[str, Any]], limit: int = 20) -> list[str]:
    """Collect D-dimension matched items from chain-scoring steps."""
    evidence: list[str] = []
    seen: set[str] = set()
    for step in steps:
        checklists = step.get("checklists") if isinstance(step, dict) else None
        data = checklists.get("D") if isinstance(checklists, dict) else None
        matched = data.get("matched") if isinstance(data, dict) else None
        for item in matched or []:
            text = str(item).strip()
            if not text or text in seen:
                continue
            seen.add(text)
            evidence.append(text)
            if len(evidence) >= limit:
                return evidence
    return evidence
