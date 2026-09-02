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

import logging
import os

from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import TextPart
from a2a.utils import new_agent_text_message, new_task

from . import broadcast_capability_check as sg_broadcast
from .skill_agent import SkillAgentExecutor, PRE_MAKE_PLAN_MESSAGE_TYPE

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_MAX_LOOPS = 2


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

        user_id = str(metadata.get("user_id", ""))
        run_id = str(metadata.get("run_id", ""))
        trace_id = str(metadata.get("trace_id", ""))
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

        if is_delegated:
            current_hop = hop_remaining
        else:
            current_hop = int(os.getenv("CROSS_SG_MAX_HOP", "5"))

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
        accumulated_task_results: dict[int, str] = {}
        accumulated_delegate_results: dict[str, str] = {}
        final_answer: str | None = None

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
            task_results, delegate_results, remaining_hop = await self._execute_plan_and_mid_exec(
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
            )
            # Update hop from the execution — this is consumed by pre-exec
            # and mid-exec delegation edges within the turn.
            current_hop = remaining_hop

            # Accumulate results across turns
            accumulated_task_results.update(task_results)
            accumulated_delegate_results.update(delegate_results)

            # Update upstream_context with accumulated task results so the
            # next turn's planner can see what was already done.  Without
            # this, Turn 2+ would see the original static upstream_context
            # from the initial delegation and would not know about Turn 1's
            # discoveries, leading to redundant or misaligned planning.
            upstream_context = dict(upstream_context)
            upstream_context["executed_tasks"] = [
                {
                    "task_id": tid,
                    "description": "",
                    "agent": "",
                    "status": "completed",
                    "result": res,
                }
                for tid, res in accumulated_task_results.items() if res
            ]
            upstream_context["key_findings_so_far"] = "\n".join(
                f"[Task#{tid}] {res[:300]}"
                for tid, res in accumulated_task_results.items() if res
            )

            # ---- Guard: hop exhausted — stop turns immediately ----
            # When hop is 1 or below, no further delegation is possible
            # (delegation would give downstream hop_remaining=0, which the
            # entry guard rejects immediately).  Continuing turns would
            # only waste LLM calls on plan + evaluation cycles that cannot
            # produce new data.  Break now and summarize whatever we have.
            if current_hop <= 1:
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

            # ---- LLM-evaluated summary: is the answer sufficient? ----
            await self._emit_progress(
                updater,
                "summarizing",
                message=f"Turn {total_turns}: evaluating with LLM...",
                status="running",
            )

            # --- Data Flow: summary input ---
            self._log_summary_input(
                task_results=accumulated_task_results,
                delegate_results=accumulated_delegate_results,
            )

            eval_result = await self._summarize_with_evaluation(
                original_query=query,
                task_results=accumulated_task_results,
                delegate_results=accumulated_delegate_results,
                upstream_context=upstream_context,
                user_id=user_id,
                run_id=run_id,
                trace_id=trace_id,
            )

            if eval_result.satisfactory:
                final_answer = eval_result.answer
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
            reason_parts: list[str] = []
            if eval_result.missing_info:
                reason_parts.append(f"缺少信息: {eval_result.missing_info}")
            if eval_result.rationale:
                reason_parts.append(f"评估理由: {eval_result.rationale}")
            reason_text = "；".join(reason_parts) if reason_parts else "信息不足"

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
            reason = (
                "hop exhausted"
                if current_hop <= 1
                else f"max turns ({self.max_loops}) reached"
            )
            logger.warning(
                "[TurnLoop] %s (%d turns) — producing final answer",
                reason,
                total_turns,
            )
            await self._emit_progress(
                updater,
                "turn_max_retries",
                message=(
                    f"Max turns ({self.max_loops}) reached, "
                    f"producing final answer"
                ),
                status="done",
                extra={"turns": total_turns, "max_loops": self.max_loops},
            )

            # --- Data Flow: summary input (forced after max turns) ---
            self._log_summary_input(
                task_results=accumulated_task_results,
                delegate_results=accumulated_delegate_results,
                extra_desc=f"forced, {reason}",
            )

            final_answer = await self._summarize(
                original_query=query,
                task_results=accumulated_task_results,
                delegate_results=accumulated_delegate_results,
                upstream_context=upstream_context,
                user_id=user_id,
                run_id=run_id,
                trace_id=trace_id,
            )

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
        owner_agent_id = md.get("history_owner_agent_id")
        is_not_owner = bool(owner_agent_id) and owner_agent_id != self.agent_id
        if md.get("skip_history_write") or is_not_owner:
            skip_reason = (
                "skip_history_write" if md.get("skip_history_write") else "not_owner"
            )
            logger.info(
                "[HistoryFlow] skill-agent-turn history-skip reason=%s run_id=%s",
                skip_reason,
                md.get("run_id", ""),
            )
        else:
            await self.add_history(query, final_answer)
            self.schedule_add_memory(query, final_answer)

        await updater.complete(
            message=new_agent_text_message("", context_id=task.context_id)
        )