"""Turn-based retry loop for SkillAgentExecutor (LLM-evaluated version).

Provides :class:`SkillAgentExecutorWithTurns` — a subclass of the base
:class:`SkillAgentExecutor` that wraps the plan → execute → mid-exec cycle
in a ``while`` loop bounded by ``max_loops``.  After each turn, the
accumulated results are summarized AND evaluated by an LLM
(:meth:`SkillAgentExecutor._summarize_with_evaluation`).  If the LLM
judges the information is sufficient, the answer is returned immediately.
Otherwise, the missing information is injected as ``failure_context``
into the next turn's planner.

    10|Usage
-----
In ``server.py``, pass ``--max-loops 2`` (or any value > 1) to enable
turn mode.  The default ``--max-loops 1`` uses the original single-shot
:class:`SkillAgentExecutor`.

Design principles
-----------------
- **LLM-evaluated**: turn exit is decided by the summary LLM, not by
  per-task status checks.  The LLM sees the full picture (query, all
  task results, upstream context) and judges whether the answer is
  sufficient.
- **Incremental**: the base :class:`SkillAgentExecutor` is untouched
  (except for the ``_execute_plan_and_mid_exec`` extraction and
  the new ``_summarize_with_evaluation`` method).
- **Accumulating**: results from all turns are accumulated, so no
  completed work is discarded.
"""

from __future__ import annotations

import json
import logging
import os

from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import TextPart
from a2a.utils import new_agent_text_message, new_task

from . import broadcast_capability_check as sg_broadcast
from .skill_agent import (
    SkillAgentExecutor,
    PRE_MAKE_PLAN_MESSAGE_TYPE,
    _log_boxed_document,
)
from .execution_flow import ExecutionTask, render_execution_flow_md, render_execution_flow_table

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_MAX_LOOPS = 2


# ---------------------------------------------------------------------------
# Helper functions for turn-record data access
# ---------------------------------------------------------------------------

def _accumulated_task_results(turn_records: list[dict]) -> dict[int, str]:
    """Flatten all turns' task results into a dict with globally unique IDs."""
    result: dict[int, str] = {}
    _seq = 0
    for r in turn_records:
        for _tid, _res in r["task_results"].items():
            _seq += 1
            result[_seq] = _res
    return result


def _accumulated_delegate_results(turn_records: list[dict]) -> dict[str, str]:
    """Merge all turns' delegate results."""
    result: dict[str, str] = {}
    for r in turn_records:
        result.update(r["delegate_results"])
    return result


def _build_executed_tasks(turn_records: list[dict]) -> list[dict]:
    """Build executed_tasks for upstream_context from all turn records."""
    tasks: list[dict] = []
    _seq = 0
    for r in turn_records:
        _plan_meta_by_id = {m["id"]: m for m in r["plan"]}
        for _tid, _res in r["task_results"].items():
            _seq += 1
            _meta = _plan_meta_by_id.get(_tid, {})
            tasks.append({
                "task_id": _seq,
                "description": _meta.get("description", ""),
                "agent": _meta.get("agent", ""),
                "status": "completed",
                "result": _res,
            })
    return tasks


def _accumulated_execution_flow_tasks(turn_records: list[dict]) -> list[dict]:
    """Flatten all turns' execution_flow_tasks into a single list of dicts."""
    tasks: list[dict] = []
    for r in turn_records:
        ef_tasks = r.get("execution_flow_tasks", [])
        for t in ef_tasks:
            if isinstance(t, ExecutionTask):
                tasks.append(t.to_dict())
            elif isinstance(t, dict):
                tasks.append(t)
    return tasks


def _build_turn_context_md(
    upstream_context: dict,
    failure_context: str = "",
    turn_records: list[dict] | None = None,
    current_agent: str = "",
) -> str:
    """Build a unified Markdown context document for the planner's group_memory.

    Sections:
      0. Upstream Execution Flow (delegator's execution history)
      1. Upstream inner context (deeper delegation chain)
      2. Executed tasks and full results
      3. Evaluation feedback (failure_context)
    """
    sections: list[str] = []

    # ── Section 0: Upstream Execution Flow ──
    # 被委派 agent 在 Turn 1 时 turn_records 为空，但上游 agent 已经执行了
    # 一些任务并委派了当前 agent。通过 upstream_context["execution_flow"] 将
    # 上游的执行轨迹注入到 Planner 上下文中，让被委派 agent 的 Planner 能够
    # 看到完整的执行历史（谁委派了我、为什么委派、之前做了什么）。
    upstream_ef = upstream_context.get("execution_flow")
    if upstream_ef and isinstance(upstream_ef, list):
        # 上游 EF 是 dict 列表，需要转换为 ExecutionTask 兼容格式
        ef_dicts: list[dict] = []
        for ef_item in upstream_ef:
            if isinstance(ef_item, ExecutionTask):
                ef_dicts.append(ef_item.to_dict())
            elif isinstance(ef_item, dict):
                ef_dicts.append(ef_item)
        if ef_dicts:
            ef_md = render_execution_flow_md(ef_dicts, current_agent=current_agent)
            if ef_md:
                sections.append(ef_md)

    # # ── Section 1: Upstream inner context ──
    # upstream_inner = upstream_context.get("upstream_context")
    # if upstream_inner:
    #     sections.append("## 上游上下文")
    #     sections.append(
    #         f"```json\n{json.dumps(upstream_inner, ensure_ascii=False, indent=2)}\n```"
    #     )

    # ── Section 2: Executed tasks and results ──
    # NOTE: _build_executed_tasks 已注释，Execution Flow 已覆盖其全部信息。
    # 如果测试无问题，后续将删除 _build_executed_tasks 及其相关代码。
    if turn_records:
        # executed = _build_executed_tasks(turn_records)
        # if executed:
        #     sections.append("## 已执行任务及结果")
        #     sections.append("以下为所有 Turn 已完成任务的完整结果，请勿重复查询。")
        #     for t in executed:
        #         sections.append(f"### Task #{t['task_id']} -> `{t['agent']}`")
        #         sections.append(f"**描述**: {t['description']}")
        #         sections.append(f"**结果**:\n\n```\n{t['result']}\n```")

        # ── Section 2b: Execution Flow (流水账) ──
        all_ef = _accumulated_execution_flow_tasks(turn_records)
        if all_ef:
            ef_md = render_execution_flow_md(all_ef, current_agent=current_agent)
            if ef_md:
                sections.append(ef_md)

    # ── Section 3: Evaluation feedback ──
    if failure_context:
        sections.append("## 上轮评估反馈")
        sections.append(failure_context)

    if not sections:
        return ""
    return "\n\n".join(sections)


# ---------------------------------------------------------------------------
# SkillAgentExecutorWithTurns
# ---------------------------------------------------------------------------

class SkillAgentExecutorWithTurns(SkillAgentExecutor):
    """SkillAgentExecutor with LLM-evaluated turn-based retry loop.

    Wraps the plan → execute → mid-exec cycle in a ``while`` loop bounded
    by ``max_loops``.  After each turn the accumulated results are passed
    to :meth:`_summarize_with_evaluation`; if the LLM judges the answer
    is sufficient the loop exits early.  Otherwise the missing-info
    description is injected into the next turn's planner ``group_memory``
    as ``failure_context``.

    Parameters
    ----------
    max_loops : int
        Maximum number of total execution turns.  ``max_loops=1`` means
        one execution only (no retry), equivalent to the base
        :class:`SkillAgentExecutor`.  Default ``2``.
    """

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def __init__(self, *args, max_loops: int = DEFAULT_MAX_LOOPS, **kwargs):
        super().__init__(*args, **kwargs)
        self.max_loops = max(1, int(max_loops))
        logger.info(
            "[TurnLoop] SkillAgentExecutorWithTurns initialized | max_loops=%d",
            self.max_loops,
        )

    # ------------------------------------------------------------------
    # Turn loop execution
    # ------------------------------------------------------------------

    async def execute(self, context, event_queue):
        """Execute with LLM-evaluated turn-based retry loop.

        Flow
        ----
        ::

            [Step 0]   Capability check fast-path
            [Step 1-2] Infrastructure setup (once)
            ┌─ Turn loop ───────────────────────────────────────────┐
            │ [Step 3-5] _execute_plan_and_mid_exec()               │
            │ [Step 5.5] _summarize_with_evaluation()               │
            │            → satisfactory? break (answer is final)    │
            │            → not satisfactory? inject missing_info    │
            │              as failure_context for next turn          │
            └───────────────────────────────────────────────────────┘
            [Step 6]   (if all turns exhausted) final _summarize()
            [Step 7]   Return + persist
        """
        from a2a.server.agent_execution import RequestContext

        query = context.get_user_input()
        metadata = dict(context.metadata or {})
        self.metadata = metadata

        # ---- Step 0: Capability check fast-path ----
        if isinstance(metadata, dict) and metadata.get(
            "message_type"
        ) == "capability_check":
            await self.handle_capability_check(context, event_queue, query)
            return

        if isinstance(metadata, dict) and metadata.get(
            "message_type"
        ) == PRE_MAKE_PLAN_MESSAGE_TYPE:
            await self.handle_pre_make_plan(context, event_queue, query)
            return

        # ── Debug: print full metadata on execute entry (after fast-paths) ──
        logger.info(
            "[ExecuteEntry] metadata dump | agent_id=%s skip_history_write=%s "
            "collaboration_delegation=%s delegator_name=%s hop_remaining=%s "
            "delegation_chain=%s history_owner_agent_id=%s run_id=%s "
            "user_id=%s full_metadata=%s",
            self.agent_id,
            metadata.get("skip_history_write"),
            metadata.get("collaboration_delegation"),
            metadata.get("delegator_name"),
            metadata.get("hop_remaining"),
            metadata.get("delegation_chain"),
            metadata.get("history_owner_agent_id"),
            metadata.get("run_id"),
            metadata.get("user_id"),
            json.dumps(metadata, ensure_ascii=False, default=str),
        )
        # ─────────────────────────────────────────────────────────────────

        user_id = str(metadata.get("user_id", ""))
        run_id = str(metadata.get("run_id", ""))
        trace_id = str(metadata.get("trace_id", ""))
        skip_history_write = bool(metadata.get("skip_history_write", False))
        self._progress_context = {
            "run_id": run_id,
            "user_id": user_id,
            "agent_id": self.agent_id,
        }

        task = context.current_task
        if not task:
            task = new_task(context.message)
            await event_queue.enqueue_event(task)

        updater = TaskUpdater(event_queue, task.id, task.context_id)

        # ---- Delegation context ----
        is_delegated = metadata.get("collaboration_delegation") is True
        hop_remaining = int(metadata.get("hop_remaining", 0))
        delegation_chain = list(metadata.get("delegation_chain", []))
        upstream_context = dict(metadata.get("upstream_context", {}))

        # ── DAG banner: log enforcement status at collaboration entry ──
        _dag_enabled = self._dag_enforcement_enabled()
        self_name = self._self_planner_agent_name()
        if _dag_enabled:
            self._log_dag_startup(
                is_delegated=is_delegated,
                self_name=self_name,
                chain=delegation_chain,
            )
        else:
            logger.info(
                "[DAG] DAG enforcement DISABLED (CROSS_SG_ENFORCE_DAG=false) | "
                "chain=%s self=%s",
                delegation_chain,
                self_name,
            )

        if is_delegated:
            current_hop = hop_remaining
        else:
            current_hop = int(os.getenv("CROSS_SG_MAX_HOP", "5"))

        # ── DAG Layer 1: cycle detection — abort if self already in chain ──
        if _dag_enabled and self_name in delegation_chain:
            self._log_dag_event(
                "CYCLE_DETECTED",
                chain=delegation_chain,
                self_name=self_name,
                detail=f"self={self_name} 已存在于委派链中！",
            )
            logger.warning(
                "[Cross-SG][DAG] cycle detected! self=%s already in chain=%s, aborting collaboration",
                self_name,
                delegation_chain,
            )
            return {
                "answer": "",
                "tasks": [],
                "reason": "dag_cycle_detected",
                "status": "fail",
            }

        # Guard: hop exhausted — stop immediately, do not execute any tasks.
        if is_delegated and current_hop <= 0:
            await self._emit_progress(
                updater,
                "collab_started",
                message=(
                    f"Collaborative execution aborted "
                    f"(SG: {self.agent_id}, delegated: {is_delegated}, "
                    f"hop: {current_hop}) — hop exhausted"
                ),
                status="done",
                extra={
                    "sg_label": self.agent_id,
                    "is_delegated": is_delegated,
                    "hop": current_hop,
                    "chain_depth": len(delegation_chain),
                },
            )
            return {
                "answer": "",
                "tasks": [],
                "reason": "hop_exhausted",
                "status": "fail",
            }

        await self._emit_progress(
            updater,
            "collab_started",
            message=(
                f"Collaborative execution started "
                f"(SG: {self.agent_id}, delegated: {is_delegated}, "
                f"hop: {current_hop})"
            ),
            status="running",
            extra={
                "sg_label": self.agent_id,
                "is_delegated": is_delegated,
                "hop": current_hop,
                "chain_depth": len(delegation_chain),
            },
        )
        # --- Data Flow: log upstream context at entry ---
        _upstream_summary = self._format_upstream_context_summary(upstream_context)
        logger.info(
            "[TurnLoop][CollabEntry] execute started | agent=%s is_delegated=%s "
            "hop=%d chain=%s upstream=%s",
            self.agent_id,
            is_delegated,
            current_hop,
            delegation_chain,
            _upstream_summary,
        )

        # ---- Step 1: Ensure SkillRunner ----
        skill_runner = await self._ensure_skill_runner()

        # ---- Step 2: Build agent card pool ----
        if isinstance(metadata, dict) and metadata.get(
            sg_broadcast.ROUTING_AGENT_POOL_KEY
        ):
            sg_broadcast.log_routing_agent_pool_received(metadata)

        self._init_routing_pool_from_metadata(metadata)
        all_cards, own_names, collab_names = await self._resolve_planner_agent_pool(
            query
        )

        logger.info(
            "[TurnLoop] planning pool: local=%s peers=%d total=%d",
            self._self_planner_agent_name(),
            len(collab_names),
            len(all_cards),
        )

        # ==================================================================
        # Turn loop
        # ==================================================================
        total_turns = 0
        failure_context = ""
        turn_records: list[dict] = []
        final_answer: str | None = None
        base_group_memory = await self._get_memory(query)

        while total_turns < self.max_loops:
            total_turns += 1
            logger.info(
                "[TurnLoop] turn %d/%d started | failure_context_chars=%d current_hop=%d",
                total_turns,
                self.max_loops,
                len(failure_context),
                current_hop,
            )
            await self._emit_progress(
                updater,
                "turn_started",
                message=f"Turn {total_turns}/{self.max_loops} started",
                status="running",
                extra={"turn": total_turns, "max_turns": self.max_loops},
            )

            # Execute one turn (Steps 3-5)
            # Build group_memory for this turn: base memory + turn context.
            turn_context_md = _build_turn_context_md(
                upstream_context=upstream_context,
                failure_context=failure_context,
                turn_records=turn_records,
                current_agent=self._self_planner_agent_name(),
            )
            if base_group_memory:
                group_memory = f"{base_group_memory}\n\n{turn_context_md}" if turn_context_md else base_group_memory
            else:
                group_memory = turn_context_md

            # ── 日志: 打印 _build_turn_context_md 构建的完整上下文 ──
            _log_boxed_document(
                f"[TurnContext] Turn {total_turns} Pre-Exec group_memory",
                meta_lines=[
                    f"turn_context={len(turn_context_md)} chars    "
                    f"base_memory={len(base_group_memory or '')} chars    "
                    f"total={len(group_memory or '')} chars",
                    f"turn_records={len(turn_records)}    "
                    f"failure_context={'有' if failure_context else '无'}",
                ],
                body_label="turn_context_md",
                body=turn_context_md or "(空)",
                log=logger,
            )

            task_results, delegate_results, remaining_hop, plan_task_meta, turn_ef_tasks = await self._execute_plan_and_mid_exec(
                query=query,
                all_cards=all_cards,
                own_names=own_names,
                collab_names=collab_names,
                skill_runner=skill_runner,
                metadata=metadata,
                user_id=user_id,
                run_id=run_id,
                trace_id=trace_id,
                updater=updater,
                upstream_context=upstream_context,
                is_delegated=is_delegated,
                current_hop=current_hop,
                delegation_chain=delegation_chain,
                failure_context=failure_context,
                prior_delegate_results=_accumulated_delegate_results(turn_records),
                group_memory=group_memory,
                turn=total_turns,
            )
            # Update hop from the execution -- this is consumed by pre-exec
            # and mid-exec delegation edges within the turn.
            current_hop = remaining_hop

            # Record this turn's results.
            turn_records.append({
                "turn": total_turns,
                "plan": plan_task_meta,
                "task_results": task_results,
                "delegate_results": delegate_results,
                "execution_flow_tasks": turn_ef_tasks,
            })

            # Build upstream_context for the next turn from all turn_records.
            upstream_context = dict(upstream_context)
            upstream_context["executed_tasks"] = _build_executed_tasks(turn_records)
            # Propagate accumulated Execution Flow so downstream delegations
            # in subsequent turns can see earlier-turn EF history.
            upstream_context["execution_flow"] = _accumulated_execution_flow_tasks(turn_records)

            # ---- Guard: hop exhausted — stop turns or reset hop ----
            # Hop limits the depth of a single delegation chain, not the
            # total number of delegations from the entry-point agent.
            #
            # - Delegated agent (mid-chain): hop exhausted means the chain
            #   cannot go deeper.  Break now and return whatever we have.
            # - Entry-point agent (originator): hop exhausted means the
            #   current chain is done, but the entry agent can start a new
            #   chain in the next turn.  Reset hop to the initial value and
            #   continue the loop (evaluation + possibly Turn N+1).
            if current_hop <= 1:
                if is_delegated:
                    logger.info(
                        "[TurnLoop] hop exhausted after turn %d (current_hop=%d) — "
                        "breaking loop to produce summary from accumulated results",
                        total_turns,
                        current_hop,
                    )
                    await self._emit_progress(
                        updater,
                        "turn_hop_exhausted",
                        message=(
                            f"Turn {total_turns}: hop exhausted, "
                            f"stopping turns and proceeding to summary"
                        ),
                        status="done",
                        extra={"turn": total_turns, "hop": current_hop},
                    )
                    break
                else:
                    _initial_hop = int(os.getenv("CROSS_SG_MAX_HOP", "5"))
                    logger.info(
                        "[TurnLoop] hop exhausted after turn %d (current_hop=%d) — "
                        "entry-point agent, resetting hop to %d and continuing",
                        total_turns,
                        current_hop,
                        _initial_hop,
                    )
                    current_hop = _initial_hop
                    # Do NOT break — fall through to evaluation.

            # ---- LLM-evaluated summary: is the answer sufficient? ----
            await self._emit_progress(
                updater,
                "summarizing",
                message=f"Turn {total_turns}: evaluating with LLM...",
                status="running",
            )

            # --- Data Flow: summary input ---
            self._log_summary_input(
                task_results=_accumulated_task_results(turn_records),
                delegate_results=_accumulated_delegate_results(turn_records),
            )

            eval_result = await self._summarize_with_evaluation(
                original_query=query,
                task_results=_accumulated_task_results(turn_records),
                delegate_results=_accumulated_delegate_results(turn_records),
                upstream_context=upstream_context,
                user_id=user_id,
                run_id=run_id,
                trace_id=trace_id,
                execution_flow_tasks=_accumulated_execution_flow_tasks(turn_records),
                agent_role="delegatee" if is_delegated else "initiator",
                turn=total_turns,
            )

            if eval_result.satisfactory:
                # Debug: log last-turn vs accumulated task_results
                _last_tr = turn_records[-1]["task_results"]
                _acc_tr = _accumulated_task_results(turn_records)
                _acc_dr = _accumulated_delegate_results(turn_records)
                logger.info(
                    "[TurnLoop] satisfactory → _summarize | "
                    "turn=%d total_turns=%d "
                    "last_turn_task_count=%d acc_task_count=%d "
                    "last_turn_task_ids=%s acc_task_ids=%s",
                    total_turns,
                    len(turn_records),
                    len(_last_tr),
                    len(_acc_tr),
                    list(_last_tr.keys()),
                    list(_acc_tr.keys()),
                )
                for _tid, _res in _last_tr.items():
                    logger.info(
                        "[TurnLoop] last_turn_task[%d] len=%d preview=%s",
                        _tid,
                        len(_res or ""),
                        (_res or "")[:200],
                    )
                if self.summarize_enabled is False:
                    # Extra verbosity when passthrough is active — helps
                    # diagnose why results may appear duplicated.
                    _all_ids = list(_acc_tr.keys())
                    _all_keys = list((turn_records[-1].get("task_results") or {}).keys())
                    logger.info(
                        "[TurnLoop] PASSTHROUGH-DEBUG | "
                        "summarize_enabled=%s turn=%d "
                        "tr[-1] keys=%s acc_tr keys=%s "
                        "dr keys=%s acc_dr keys=%s",
                        self.summarize_enabled,
                        total_turns,
                        _all_keys,
                        _all_ids,
                        list((turn_records[-1].get("delegate_results") or {}).keys()),
                        list(_acc_dr.keys()),
                    )
                    # Dump EVERY turn's raw task_results so we can tell if
                    # two turns returned the same content.
                    for _ti, _tr in enumerate(turn_records):
                        _tr_tr = _tr.get("task_results") or {}
                        logger.info(
                            "[TurnLoop] PASSTHROUGH-DEBUG turn_record[%d] "
                            "turn=%d task_count=%d task_ids=%s",
                            _ti,
                            _tr.get("turn"),
                            len(_tr_tr),
                            list(_tr_tr.keys()),
                        )
                        for _tid, _res in _tr_tr.items():
                            logger.info(
                                "[TurnLoop] PASSTHROUGH-DEBUG "
                                "turn_record[%d].task[%d] len=%d "
                                "hash=%s preview=%s",
                                _ti,
                                _tid,
                                len(_res or ""),
                                hash(_res),
                                (_res or "")[:200],
                            )
                # Only pass the last turn's task_results — previous unsatisfactory
                # turns are noise in passthrough mode (the LLM path gets full
                # context via execution_flow_tasks anyway).
                final_answer = await self._summarize(
                    original_query=query,
                    task_results=turn_records[-1]["task_results"],
                    delegate_results=_accumulated_delegate_results(turn_records),
                    upstream_context=upstream_context,
                    user_id=user_id,
                    run_id=run_id,
                    trace_id=trace_id,
                    execution_flow_tasks=_accumulated_execution_flow_tasks(turn_records),
                    agent_role="delegatee" if is_delegated else "initiator",
                )
                # Record turn_summary as formal ExecutionTask (success)
                ts_task = ExecutionTask(
                    execution_id=f"turn-summary-t{total_turns}",
                    turn=total_turns,
                    stage="turn_summary",
                    agent=self._self_planner_agent_name(),
                    role="initiator",
                    task=f"Turn {total_turns} 评估结果",
                    result="success",
                    reason=eval_result.rationale or "信息充足",
                    parent_execution_id=None,
                    delegated_by=None,
                    run_id=run_id,
                    trace_id=trace_id,
                    user_id=user_id,
                )
                turn_records[-1]["execution_flow_tasks"].append(ts_task)
                await self._emit_execution_flow(updater, ts_task)
                # Record final_answer as formal ExecutionTask
                fa_task = ExecutionTask(
                    execution_id=f"final-answer-t{total_turns}",
                    turn=total_turns,
                    stage="final_answer",
                    agent=self._self_planner_agent_name(),
                    role="initiator",
                    task="最终答案",
                    result=final_answer,
                    reason=eval_result.rationale or "",
                    parent_execution_id=None,
                    delegated_by=None,
                    run_id=run_id,
                    trace_id=trace_id,
                    user_id=user_id,
                )
                turn_records[-1]["execution_flow_tasks"].append(fa_task)
                await self._emit_execution_flow(updater, fa_task)
                logger.info(
                    "[TurnLoop] answer satisfactory after %d turn(s) — exiting",
                    total_turns,
                )
                await self._emit_progress(
                    updater,
                    "turn_complete",
                    message=f"Answer satisfactory after {total_turns} turn(s)",
                    status="done",
                    extra={"turns": total_turns},
                )
                break

            # Not satisfactory — prepare failure context for next turn
            # Record turn_summary as formal ExecutionTask for this turn
            reason_parts: list[str] = []
            if eval_result.missing_info:
                reason_parts.append(f"缺少信息: {eval_result.missing_info}")
            if eval_result.rationale:
                reason_parts.append(f"评估理由: {eval_result.rationale}")
            reason_text = "；".join(reason_parts) if reason_parts else "信息不足"

            ts_task = ExecutionTask(
                execution_id=f"turn-summary-t{total_turns}",
                turn=total_turns,
                stage="turn_summary",
                agent=self._self_planner_agent_name(),
                role="initiator",
                task=f"Turn {total_turns} 评估结果",
                result="fail",
                reason=reason_text,
                parent_execution_id=None,
                delegated_by=None,
                run_id=run_id,
                trace_id=trace_id,
                user_id=user_id,
            )
            turn_records[-1]["execution_flow_tasks"].append(ts_task)
            await self._emit_execution_flow(updater, ts_task)

            # ── Retry guard: gap outside the capability boundary ──
            # If the evaluator judged the missing information as NOT obtainable
            # by further execution (e.g. the result explicitly lacks an ability
            # that no agent in the pool declares), retrying would deterministically
            # fail.  Stop the loop here and summarise from what we have, instead of
            # burning the remaining turns and still producing the same answer.
            if not eval_result.gap_obtainable:
                logger.warning(
                    "[TurnLoop] turn %d not satisfactory BUT gap_obtainable=False — "
                    "stopping retries (unobtainable gap) | missing_info=%s",
                    total_turns,
                    eval_result.missing_info,
                )
                await self._emit_progress(
                    updater,
                    "turn_no_retry",
                    message=(
                        f"Turn {total_turns}: 缺失信息超出可获取范围，"
                        f"停止重试并以当前结果作答 — {reason_text}"
                    ),
                    status="done",
                    extra={
                        "turn": total_turns,
                        "gap_obtainable": False,
                        "missing_info": eval_result.missing_info,
                        "rationale": eval_result.rationale,
                    },
                )
                # --- Data Flow: summary input (unobtainable gap) ---
                self._log_summary_input(
                    task_results=_accumulated_task_results(turn_records),
                    delegate_results=_accumulated_delegate_results(turn_records),
                    extra_desc=(
                        f"forced, unobtainable gap at turn {total_turns}"
                    ),
                )
                # Reuse the evaluator's answer as the final answer when it
                # exists — it already reflects the factual results and does not
                # fabricate for the missing part.  Fall back to _summarize.
                final_answer = eval_result.answer or await self._summarize(
                    original_query=query,
                    task_results=turn_records[-1]["task_results"],
                    delegate_results=_accumulated_delegate_results(turn_records),
                    upstream_context=upstream_context,
                    user_id=user_id,
                    run_id=run_id,
                    trace_id=trace_id,
                    execution_flow_tasks=_accumulated_execution_flow_tasks(turn_records),
                    agent_role="delegatee" if is_delegated else "initiator",
                )
                fa_task = ExecutionTask(
                    execution_id=f"final-answer-t{total_turns}-nogap",
                    turn=total_turns,
                    stage="final_answer",
                    agent=self._self_planner_agent_name(),
                    role="initiator",
                    task="最终答案",
                    result=final_answer,
                    reason=f"缺失信息不可获取，提前收尾：{eval_result.missing_info}",
                    parent_execution_id=None,
                    delegated_by=None,
                    run_id=run_id,
                    trace_id=trace_id,
                    user_id=user_id,
                )
                turn_records[-1]["execution_flow_tasks"].append(fa_task)
                await self._emit_execution_flow(updater, fa_task)
                break

            failure_context = (
                f"【上轮评估反馈】当前信息不足以完整回答用户问题。"
                f"缺失信息：{eval_result.missing_info}"
                if eval_result.missing_info
                else "【上轮评估反馈】当前信息不足，请调整策略重新获取关键数据。"
            )
            logger.info(
                "[TurnLoop] turn %d not satisfactory — continuing | missing_info=%s hop=%d",
                total_turns,
                eval_result.missing_info,
                current_hop,
            )

            await self._emit_progress(
                updater,
                "turn_retry",
                message=(
                    f"Turn {total_turns}: answer not satisfactory, "
                    f"retrying with feedback — {reason_text}"
                ),
                status="running",
                extra={
                    "turn": total_turns,
                    "missing_info": eval_result.missing_info,
                    "rationale": eval_result.rationale,
                },
            )

        if final_answer is None:
            # Loop exhausted: either max turns reached or hop exhausted.
            # Produce a final answer without evaluation (forced output).
            # - Delegated agent: hop exhausted means the chain is done.
            # - Entry-point agent: hop is reset every turn, so reaching
            #   here always means max turns exhausted.
            reason = (
                "hop exhausted"
                if is_delegated and current_hop <= 1
                else f"max turns ({self.max_loops}) reached"
            )
            logger.warning(
                "[TurnLoop] %s (%d turns) — producing final answer",
                reason,
                total_turns,
            )

            # Choose the right event name and message based on actual reason
            if is_delegated and current_hop <= 1:
                event_name = "turn_hop_exhausted_final"
                display_msg = (
                    f"Hop exhausted after {total_turns} turn(s), "
                    f"producing final answer from accumulated results"
                )

                await self._emit_progress(
                    updater,
                    event_name,
                    message=display_msg,
                    status="done",
                    extra={"turns": total_turns, "max_loops": self.max_loops},
                )

            # --- Data Flow: summary input (forced after max turns) ---
            self._log_summary_input(
                task_results=_accumulated_task_results(turn_records),
                delegate_results=_accumulated_delegate_results(turn_records),
                extra_desc=f"forced, {reason}",
            )

            final_answer = await self._summarize(
                original_query=query,
                task_results=turn_records[-1]["task_results"],
                delegate_results=_accumulated_delegate_results(turn_records),
                upstream_context=upstream_context,
                user_id=user_id,
                run_id=run_id,
                trace_id=trace_id,
                execution_flow_tasks=_accumulated_execution_flow_tasks(turn_records),
                agent_role="delegatee" if is_delegated else "initiator",
            )

            # Record final_answer for exhausted case as formal ExecutionTask
            fa_task = ExecutionTask(
                execution_id=f"final-answer-t{total_turns}-exhausted",
                turn=total_turns,
                stage="final_answer",
                agent=self._self_planner_agent_name(),
                role="initiator",
                task="最终答案",
                result=final_answer,
                reason=reason,
                parent_execution_id=None,
                delegated_by=None,
                run_id=run_id,
                trace_id=trace_id,
                user_id=user_id,
            )
            turn_records.append({
                "turn": total_turns,
                "plan": [],
                "task_results": {},
                "delegate_results": {},
                "execution_flow_tasks": [fa_task],
            })
            await self._emit_execution_flow(updater, fa_task)

        # ==================================================================
        # Step 6 (summarize already done in the loop): final_answer is set
        # ==================================================================

        await self._emit_progress(
            updater,
            "final_answer_ready",
            message=f"Final answer ready ({len(final_answer or '')} chars)",
            status="done",
            extra={"answer_chars": len(final_answer or ""), "total_turns": total_turns},
        )

        # Log data flow: summary output
        self._log_data_flow(
            direction="SUMMARY_OUTPUT",
            description=(
                f"Summary LLM 产出最终回答 → 返回 "
                f"{self._self_planner_agent_name()}"
            ),
            source_id="SummaryLLM",
            target_id=self._self_planner_agent_name(),
            payload_chars=len(final_answer or ""),
            payload_preview=(final_answer or "")[:1000],
        )

        # ==================================================================
        # Step 7: Return + persist
        # ==================================================================
        await updater.add_artifact(
            [TextPart(text=final_answer)],
            name="final-answer",
        )

        md = self.metadata if isinstance(self.metadata, dict) else {}
        if skip_history_write:
            logger.info(
                "[HistoryFlow] skill-agent-turn history-skip skip_history_write=%s run_id=%s",
                skip_history_write,
                md.get("run_id", ""),
            )
        else:
            await self.add_history(query, final_answer)
            self.schedule_add_memory(query, final_answer)

        await updater.complete(
            message=new_agent_text_message("", context_id=task.context_id)
        )

        # ── Log Execution Flow ──
        all_ef = _accumulated_execution_flow_tasks(turn_records)
        if all_ef:
            role = "delegatee" if is_delegated else "initiator"
            ef_md = render_execution_flow_md(all_ef, agent=self._self_planner_agent_name(), role=role, current_agent=self._self_planner_agent_name())
            logger.info(
                "[ExecutionFlow] run_id=%s trace_id=%s user_id=%s turns=%d\n%s",
                run_id, trace_id, user_id, total_turns, ef_md,
            )
            # ── Execution Flow 表格快照（调试用） ──
            ef_table = render_execution_flow_table(all_ef, current_agent=self._self_planner_agent_name())
            if ef_table:
                logger.info(
                    "[ExecutionFlowTable] run_id=%s trace_id=%s turns=%d\n%s",
                    run_id, trace_id, total_turns, ef_table,
                )
        else:
            logger.info("[ExecutionFlow] no execution flow tasks recorded (run_id=%s turns=%d)", run_id, total_turns)