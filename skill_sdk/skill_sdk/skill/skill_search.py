"""Skill Search — batch+concurrent semantic search for the best matching skill.

Given a user query and a list of loaded skills, this module:
1. Splits skills into batches and runs concurrent LLM calls (BATCH stage) to
   produce a high-recall candidate list.
2. Feeds candidates into a single LLM call (SELECTOR stage) to pick the single
   best skill.

Callers only need to import and call ``run_skill_search``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any

from skill_sdk.api.base import Skill

logger = logging.getLogger(__name__)

MAX_PER_BATCH = 5
DEFAULT_BATCH_SIZE = 100

# ---------------------------------------------------------------------------
# BATCH stage — high-recall candidate selection
# ---------------------------------------------------------------------------

BATCH_SEARCH_SYSTEM = """# 角色：Skill Candidate Matcher

## 使命
你的任务是为后续的精确选择器提供候选列表。**宁可多选，绝不漏选**。

## 规则
1. 基于 skill 的 name 和 description 做语义匹配。
2. **只要 skill 与用户问题有任何关联，就应该选进来**，即使关联很弱。
3. 最多返回 {max_per_batch} 个，按相关性从高到低排序。
4. 不要把同一 skill 重复输出多次。
5. 为每个选中的 skill 给出可信度评分（score: 0-100）和简短的评分理由（reason）。

## 评分规则（仅用于排序，不影响是否入选）
- 90-100: 该 skill 的 description 明确覆盖用户问题的核心意图，是直接的匹配。
- 60-89: 该 skill 的 description 部分覆盖用户意图，但不够直接或有更合适的 skill。
- 30-59: 该 skill 勉强沾边，需要用户补充信息或绕很多弯才能用。
- 10-29: 关联很弱，仅在用户问题极其模糊时才能扯上关系。
- **只要有一点点关联就应该入选**，分数低没关系。只有明确完全无关的才不选。

## 评分时务必注意的事项
1. **不要给万能 skill 打高分**。如果一个 skill 的描述是"可以写代码解决任何问题"（如 code_execution），而用户的问题是关于 Docker、机器学习、CI/CD、Redis、React、API 设计等特定领域，应该给 30-50 分（勉强沾边），把高分留给真正匹配的 skill。
2. **注意 skill 的能力边界**。如果 skill 描述中明确写了它负责什么场景（如"数值/统计/聚合/清洗/小型数据处理"），那超出这个范围的就不该给高分。
3. **不要因为看到"文件"、"读"、"解析"等词就给 read-code 高分**。read-code 的描述是"搜索，定位并阅读本地**代码**"，它处理的是代码文件，不是任意文件。如果用户说的是"某个文件"而没有明确说是代码，read-code 应该给 30-50 分（只能读代码），把高分留给真正处理文件的 skill（如 extract_pdf 处理 PDF，web_fetch 处理网页）。
4. **注意描述中的工具列表**。如果一个 skill 的描述里列出了它使用的子工具（如 read-code 的 grep、glob、readline_in_range、lsp），请根据这些子工具的能力来判断该 skill 真正的覆盖范围。例如 readline_in_range 可以按行范围读取任意文件，所以 read-code 也能处理"读取文件前 N 行"这样的需求。

## 常见误区
- 不要因为用户问题中没有直接提到 skill 的名字就不选。比如"在代码库里找一下某个函数"虽然没有提到"read-code"，但 read-code 就是做这个的。
- 不要因为用户问题描述得模糊就不选。模糊的问题更需要把所有可能的 skill 都列出来，让后续的选择器来精确判断。

## 输出
**只返回 JSON 对象数组**，每个对象包含 name、score、reason 三个字段。
如：[{{"name": "skill_a", "score": 85, "reason": "核心能力匹配"}}, {{"name": "skill_b", "score": 45, "reason": "勉强相关"}}]
完全不相关时返回空数组 []。
不要返回任何其他文本、解释或 Markdown 代码块。"""

# ---------------------------------------------------------------------------
# SELECTOR stage — precision final selection
# ---------------------------------------------------------------------------

SELECTOR_SYSTEM = """# 角色：Skill Selector（首个任务匹配器）

## 使命
从候选列表中选出**最能解决用户第一个核心需求**的 skill。
你只需要匹配用户的**第一个主要任务**，不需要覆盖用户提到的所有后续步骤。

## 核心理念
1. **skill 的 description 是能力概述，不是完整功能清单**。一个 skill 能做的事情可能比 description 里写的更多。
   只要 description 表明该 skill 面向的**领域**与用户问题的**领域**一致，就应该选它。
2. **不要过度分析**。如果用户说"格式化 JSON 然后存数据库"，第一个任务是格式化 JSON，选 jsonfmt 即可。
   不要因为"没有一个 skill 能同时格式化和存数据库"就返回空。

## 决策流程
1. 提取用户问题的**第一个核心需求**（忽略后续步骤和附加需求）。
2. 逐一阅读候选 skill 的 description，判断它能否解决这个核心需求。
3. 选最匹配的那个。如果所有候选都无法解决第一个核心需求，返回空字符串。

## 判断准则
- **聚焦第一个任务，忽略后续步骤**。用户说"生成密码然后连数据库" → 第一个任务是生成密码，选 pwdgen。
- **不要因为 skill 描述不完整就排除它**。skill 描述是概要，不是 API 文档。只要领域一致就应该选。
- **code_execution 的能力边界**：它负责"数值/统计/聚合/清洗/小型数据处理"。如果用户的第一个需求是机器学习训练、前端组件开发、Docker 镜像构建、Redis 分布式锁、Nginx 配置等**特定领域工程任务**，且没有对应的专门 skill，返回空。
- **区分"查看/管理"和"创建/配置"**。skill 描述的是查看已有资源（如 `gh run` 查看 CI 状态），用户要的是创建新东西（如写 CI 配置文件）→ 不匹配，返回空。
- **区分"搜索/查找"和"设计/创建"**。用户要"设计"、"创建"、"编写"某个东西，而 skill 只能"搜索"、"检索"信息 → 不匹配，返回空。

## 评分规则
- 90-100: 该 skill 的领域与用户第一个核心需求一致，可直接处理。
- 70-89: 该 skill 可以处理用户需求，但需要一些适配。
- 低于 70 分的不应作为最终选择。

## 输出
**只返回 JSON**: {"skill": "<name>", "score": <int>, "reason": "<理由>"} 或 {"skill": "", "score": 0, "reason": "<无合适 skill 的原因>"}。
不要返回任何其他文本、解释或 Markdown 代码块。"""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _format_skill_for_prompt(skill: Skill) -> str:
    desc_lit = json.dumps(skill.description, ensure_ascii=False)
    return f"Skill:\n    name: {skill.name}\n    description: {desc_lit}\n"


def _split_into_batches(
    skills: list[Skill], batch_size: int = DEFAULT_BATCH_SIZE
) -> list[list[Skill]]:
    return [skills[i : i + batch_size] for i in range(0, len(skills), batch_size)]


def _parse_batch_result(text: str) -> list[dict[str, Any]] | None:
    text = str(text).strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        result = json.loads(text)
        if isinstance(result, list):
            return _validate_batch_result(result)
        return None
    except json.JSONDecodeError:
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if match:
            try:
                result = json.loads(match.group())
                if isinstance(result, list):
                    return _validate_batch_result(result)
            except json.JSONDecodeError:
                pass
        return None


def _validate_batch_result(items: list[Any]) -> list[dict[str, Any]] | None:
    valid: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, dict) and "name" in item:
            name = str(item["name"]).strip()
            score = _clamp_score(item.get("score", 0))
            reason = str(item.get("reason", "")).strip()
            if name:
                valid.append({"name": name, "score": score, "reason": reason})
        elif isinstance(item, str):
            name = item.strip()
            if name:
                valid.append({"name": name, "score": 80, "reason": ""})
        else:
            return None
    return valid


def _clamp_score(value: Any) -> int:
    try:
        s = int(value)
        return max(0, min(100, s))
    except (TypeError, ValueError):
        return 0


async def _search_single_batch(
    llm: Any,
    query: str,
    batch: list[Skill],
    batch_id: int,
    max_per_batch: int = MAX_PER_BATCH,
    max_retries: int = 0,
) -> list[dict[str, Any]]:
    from langchain_core.messages import HumanMessage, SystemMessage

    skills_text = "\n\n".join(_format_skill_for_prompt(s) for s in batch)
    system = BATCH_SEARCH_SYSTEM.format(max_per_batch=max_per_batch)
    messages = [
        SystemMessage(content=system),
        HumanMessage(content=f"## 用户问题\n{query}\n\n## 本批次可用技能\n\n{skills_text}"),
    ]

    for attempt in range(max_retries + 1):
        try:
            resp = await llm.ainvoke(messages)
            content = str(resp.content).strip() if resp.content else ""
            if not content:
                logger.warning("skill_search batch %d empty response, attempt %d/%d", batch_id, attempt + 1, max_retries + 1)
                if attempt < max_retries:
                    await asyncio.sleep(1.0 * (attempt + 1))
                continue

            candidates = _parse_batch_result(content)
            if candidates is not None:
                if attempt > 0:
                    logger.info("skill_search batch %d succeeded on retry %d", batch_id, attempt)
                logger.info("skill_search batch %d: %d candidates from %d skills", batch_id, len(candidates), len(batch))
                return candidates

            logger.warning("skill_search batch %d JSON parse failed, attempt %d/%d, raw: %.200s", batch_id, attempt + 1, max_retries + 1, content)
        except Exception:
            logger.warning("skill_search batch %d failed attempt %d/%d", batch_id, attempt + 1, max_retries + 1, exc_info=True)

        if attempt < max_retries:
            await asyncio.sleep(1.0 * (attempt + 1))
            messages.append(HumanMessage(
                content='你上一次的回复格式不符合要求。请严格按照规则，**只返回 JSON 对象数组**，每个对象包含 name、score、reason 三个字段，如 [{"name": "skill_a", "score": 85, "reason": "..."}]，完全不相关时返回 []。不要返回任何其他文本、解释或 Markdown 代码块。'
            ))

    logger.warning("skill_search batch %d failed after %d retries", batch_id, max_retries + 1)
    return []


async def _select_best_skill(
    llm: Any,
    query: str,
    candidates: list[dict[str, Any]],
    *,
    max_retries: int = 3,
) -> dict[str, Any]:
    """SELECTOR stage: pick the single best skill from candidates."""
    from langchain_core.messages import HumanMessage, SystemMessage

    skills_text = "\n\n".join(
        f"Skill:\n    name: {c['name']}\n    description: {json.dumps(c['description'], ensure_ascii=False)}\n"
        f"    batch_score: {c.get('score', 0)}\n    batch_reason: {c.get('reason', '')}\n"
        for c in candidates
    )
    messages = [
        SystemMessage(content=SELECTOR_SYSTEM),
        HumanMessage(content=f"## 用户问题\n{query}\n\n## 候选技能\n\n{skills_text}"),
    ]

    selected = ""
    final_score = 0
    final_reason = ""
    content = ""
    for attempt in range(max_retries + 1):
        try:
            resp = await llm.ainvoke(messages)
            content = str(resp.content).strip() if resp.content else ""
            content = re.sub(r"^```(?:json)?\s*", "", content)
            content = re.sub(r"\s*```$", "", content)
            parsed = json.loads(content)
            if "skill" in parsed:
                selected = str(parsed["skill"]).strip()
                final_score = _clamp_score(parsed.get("score", 0))
                final_reason = str(parsed.get("reason", "")).strip()
                if attempt > 0:
                    logger.info("select_best_skill succeeded on retry %d: %s (score=%d)", attempt, selected or "(empty)", final_score)
                break
            logger.warning("select_best_skill JSON missing 'skill' key, attempt %d/%d, raw: %.200s", attempt + 1, max_retries + 1, content)
        except json.JSONDecodeError:
            logger.warning("select_best_skill JSON parse failed, attempt %d/%d, raw: %.200s", attempt + 1, max_retries + 1, content)
        except Exception:
            logger.warning("select_best_skill LLM failed attempt %d/%d", attempt + 1, max_retries + 1, exc_info=True)

        if attempt < max_retries:
            await asyncio.sleep(1.0 * (attempt + 1))
            messages.append(HumanMessage(
                content='你上一次的回复格式不符合要求。请严格按照规则，**只返回 JSON**: {"skill": "<name>", "score": <int>, "reason": "<理由>"} 或 {"skill": "", "score": 0, "reason": "..."}。不要返回任何其他文本、解释或 Markdown 代码块。'
            ))

    if not selected:
        logger.warning("select_best_skill: no selection after %d retries", max_retries + 1)

    return {
        "selected_skill": selected or None,
        "score": final_score,
        "reason": final_reason or "No suitable skill found among candidates.",
        "candidates": candidates,
        "found": bool(selected),
    }


# ---------------------------------------------------------------------------
# Public API — the single entry point
# ---------------------------------------------------------------------------

async def run_skill_search(
    llm: Any,
    query: str,
    skills: list[Skill],
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
    max_per_batch: int = MAX_PER_BATCH,
    max_concurrent_batches: int = 5,
    max_retries: int = 3,
) -> dict[str, Any]:
    """Search for the best matching skill for a user query.

    Runs two stages internally:
    1. **BATCH** — concurrent batch-based candidate search (high recall).
    2. **SELECTOR** — single LLM call to pick the best from candidates (precision).

    Args:
        llm: The LLM instance to use for semantic matching.
        query: The user's natural language query.
        skills: All loaded skills to search through.
        batch_size: Number of skills per batch.
        max_per_batch: Maximum candidates returned per batch.
        max_concurrent_batches: Maximum concurrent LLM calls.
        max_retries: Maximum retries on LLM call or parse failure.

    Returns:
        Dict with:
        - ``selected_skill`` (str or None)
        - ``score`` (int)
        - ``reason`` (str)
        - ``candidates`` (list of {name, description, score, reason})
        - ``found`` (bool)
    """
    if not skills:
        return {"selected_skill": None, "score": 0, "reason": "No skills loaded.", "candidates": [], "found": False}

    # ── BATCH stage ──────────────────────────────────────────────────────
    batches = _split_into_batches(skills, batch_size)
    sem = asyncio.Semaphore(max_concurrent_batches)

    async def _search_one(bid: int, batch: list[Skill]) -> list[dict[str, Any]]:
        async with sem:
            return await _search_single_batch(llm, query, batch, bid, max_per_batch, max_retries)

    t0 = time.perf_counter()
    tasks = [_search_one(i, batch) for i, batch in enumerate(batches)]
    results: list[list[dict[str, Any]]] = await asyncio.gather(*tasks)
    elapsed_ms = (time.perf_counter() - t0) * 1000

    seen: set[str] = set()
    raw_candidates: list[dict[str, Any]] = []
    name_to_skill = {s.name: s for s in skills}
    for batch_results in results:
        for item in batch_results:
            name = item["name"]
            if name not in seen and name in name_to_skill:
                seen.add(name)
                raw_candidates.append({
                    "name": name,
                    "description": name_to_skill[name].description,
                    "score": item["score"],
                    "reason": item["reason"],
                })

    candidates = sorted(raw_candidates, key=lambda c: c["score"], reverse=True)

    logger.info(
        "skill_search BATCH completed: %d batches, %d skills, %d candidates, %.0fms",
        len(batches), len(skills), len(candidates), elapsed_ms,
    )

    if not candidates:
        return {"selected_skill": None, "score": 0, "reason": "skill_search found no matching skills.", "candidates": [], "found": False}

    # ── SELECTOR stage ───────────────────────────────────────────────────
    selected = await _select_best_skill(llm, query, candidates, max_retries=max_retries)

    # Validate the selected skill name is actually registered.
    if selected.get("selected_skill"):
        if selected["selected_skill"] not in name_to_skill:
            logger.warning("skill_search: SELECTOR picked unregistered skill %r, discarding", selected["selected_skill"])
            selected["selected_skill"] = None
            selected["found"] = False
            selected["reason"] = f"Selected skill '{selected['selected_skill']}' not found in registry."

    return selected