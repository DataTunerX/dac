"""Execution Flow — SG Expert 端 ExecutionTask 模型与 Markdown 渲染。

与 SG Orchestrator / skill-agent 共用同一 Execution Flow 协议。
Expert 仅为消费端（接收上游 EF 状态地图并注入 ReAct 规划上下文），
因此只包含数据模型与 Markdown 渲染，不含帧序列化/反序列化/表格渲染。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional


# ---------------------------------------------------------------------------
# ExecutionTask
# ---------------------------------------------------------------------------

@dataclass
class ExecutionTask:
    """一个 task 的一次执行记录。

    以 task 为视角，只记录：谁、在哪个阶段、做了什么、结果是什么、为什么。
    通过 parent_execution_id 形成层级关系，表达跨 Agent 的委派链。

    与 SG Orchestrator / skill-agent 的 ExecutionTask 完全一致。
    """

    # ── 唯一标识 ──
    execution_id: str

    # ── 时间线定位 ──
    turn: int
    stage: str                 # "pre_exec" | "mid_exec_round_1" | "mid_exec_round_2" | ...

    # ── 身份 ──
    agent: str                 # 执行此 task 的 agent 名称
    role: str                  # "initiator"（本层规划者） | "delegatee"（被委派者）

    # ── 任务与结果 ──
    task: str                  # 此 task 的问题/描述
    result: str = ""           # 此 task 的结果（为空表示未完成/失败）

    # ── 原因 ──
    reason: str = ""           # 为什么规划了这个 task；如果未完成，为什么没完成

    # ── 层级关系 ──
    parent_execution_id: Optional[str] = None   # 父 ExecutionTask 的 execution_id
    delegated_by: Optional[str] = None          # 委派方 agent 名称

    # ── 追踪标识 ──
    run_id: str = ""                # 当前 run 的 ID
    trace_id: str = ""              # 分布式追踪 trace ID
    user_id: str = ""               # 用户 ID

    # ── 序列化 ──

    def to_dict(self) -> dict[str, Any]:
        """转为 dict。"""
        return {
            "execution_id": self.execution_id,
            "turn": self.turn,
            "stage": self.stage,
            "agent": self.agent,
            "role": self.role,
            "task": self.task,
            "result": self.result,
            "reason": self.reason,
            "parent_execution_id": self.parent_execution_id,
            "delegated_by": self.delegated_by,
            "run_id": self.run_id,
            "trace_id": self.trace_id,
            "user_id": self.user_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExecutionTask":
        """从 dict 构造 ExecutionTask。"""
        return cls(
            execution_id=data["execution_id"],
            turn=data["turn"],
            stage=data["stage"],
            agent=data["agent"],
            role=data["role"],
            task=data["task"],
            result=data.get("result", ""),
            reason=data.get("reason", ""),
            parent_execution_id=data.get("parent_execution_id"),
            delegated_by=data.get("delegated_by"),
            run_id=data.get("run_id", ""),
            trace_id=data.get("trace_id", ""),
            user_id=data.get("user_id", ""),
        )


# ---------------------------------------------------------------------------
# 帧检测（从文本流中过滤 EF 帧，避免污染 LLM 聚合文本）
# ---------------------------------------------------------------------------

EXECUTION_FLOW_FRAME_PREFIX = "[[DAC_EXECUTION_FLOW]] "


def is_execution_flow_frame(text: str) -> bool:
    """检查文本行是否为 Execution Flow 帧。"""
    return isinstance(text, str) and text.lstrip().startswith(EXECUTION_FLOW_FRAME_PREFIX)


def strip_execution_flow_lines(text: str) -> str:
    """从文本中移除 Execution Flow 帧行。"""
    if not text:
        return ""
    lines = [line for line in text.splitlines() if not is_execution_flow_frame(line)]
    return "\n".join(lines).strip()


# ---------------------------------------------------------------------------
# 树形结构重建
# ---------------------------------------------------------------------------

def build_tree(tasks: list[dict]) -> list[dict]:
    """按 parent_execution_id 重建树，返回根节点列表。

    每个节点添加临时 ``children`` 字段（list）。
    不修改原始 dict。
    """
    nodes: list[dict] = [dict(t) for t in tasks]
    for n in nodes:
        n.setdefault("children", [])

    by_id: dict[str, dict] = {n["execution_id"]: n for n in nodes}
    roots: list[dict] = []

    for n in nodes:
        pid = n.get("parent_execution_id")
        if pid and pid in by_id:
            by_id[pid]["children"].append(n)
        else:
            roots.append(n)

    return roots


# ---------------------------------------------------------------------------
# Markdown 渲染
# ---------------------------------------------------------------------------

_RENDER_MAX_CHARS = 12_000


def render_execution_flow_md(
    tasks: list[dict] | list[ExecutionTask],
    agent: str = "",
    role: str = "initiator",
    current_agent: str = "",
    show_children: bool = False,
) -> str:
    """将 ExecutionTask 列表渲染为 Markdown 流水账。

    供 ReAct 系统提示使用。输出按 turn → stage 组织：

    - Turn 1 → 首次任务执行 / 补充执行 · 第N Round → Turn 1 总结
    - 最终答案

    Args:
        tasks: ExecutionTask 列表（dict 或 ExecutionTask 对象）
        agent: 当前 Agent 名称
        role: "initiator" 或 "delegatee"
        current_agent: 当前 agent 名称，用于标记「⬅ 当前节点」
        show_children: 是否展开被委派者的内部执行细节（默认关闭）

    Returns:
        Markdown 字符串。空列表返回空字符串。
    """
    if not tasks:
        return ""

    # 统一转为 dict
    dicts: list[dict] = []
    for t in tasks:
        if isinstance(t, ExecutionTask):
            dicts.append(t.to_dict())
        elif isinstance(t, dict):
            dicts.append(t)
        else:
            continue

    if not dicts:
        return ""

    lines: list[str] = ["## 执行流水账", ""]

    # 头部
    if agent:
        if role == "delegatee":
            tag = "被委派者"
        else:
            tag = "发起者"
        lines.append(f"**Agent**: {agent}（{tag}）")

    # run_id / trace_id（从第一个 task 取）
    first = dicts[0]
    run_id = first.get("run_id", "")
    trace_id = first.get("trace_id", "")
    if run_id:
        lines.append(f"**Run ID**: {run_id}")
    if trace_id:
        lines.append(f"**Trace ID**: {trace_id}")
    lines.append("")

    # 分离 turn_summary、final_answer 和普通 task
    summaries: dict[int, dict] = {}  # turn -> summary dict
    final_answer_obj: dict | None = None
    normal_tasks: list[dict] = []

    for d in dicts:
        stage = d.get("stage", "")
        has_parent = d.get("parent_execution_id") is not None
        if stage == "turn_summary" and not has_parent:
            summaries[d.get("turn", 0)] = d
        elif stage == "final_answer" and not has_parent:
            final_answer_obj = d
        else:
            normal_tasks.append(d)

    tree = build_tree(normal_tasks)

    _total_normal = len(tree)
    _summary_turns = sorted(summaries.keys())
    _total_summaries = len(_summary_turns)

    # 按 turn 分组
    by_turn: dict[int, list[dict]] = {}
    for t in tree:
        by_turn.setdefault(t["turn"], []).append(t)

    _summaries_before: dict[int, int] = {}
    _acc = 0
    for tn in sorted(by_turn):
        _summaries_before[tn] = _acc
        if tn in _summary_turns:
            _acc += 1

    for turn_num in sorted(by_turn):
        lines.append("---")
        lines.append("")
        lines.append(f"### Turn {turn_num}")
        lines.append("")

        turn_tasks = by_turn[turn_num]

        # 按 stage 分组
        by_stage: dict[str, list[dict]] = {}
        for t in turn_tasks:
            by_stage.setdefault(t["stage"], []).append(t)

        def _stage_key(s: str) -> tuple[int, int]:
            if s == "pre_exec":
                return (0, 0)
            parts = s.split("_")
            try:
                return (1, int(parts[-1]))
            except (ValueError, IndexError):
                return (2, 0)

        for stage in sorted(by_stage, key=_stage_key):
            stage_tasks = by_stage[stage]
            if stage == "pre_exec":
                lines.append("#### 首次任务执行")
            elif stage.startswith("mid_exec_round_"):
                round_num = stage.split("_")[-1]
                lines.append(f"#### 补充执行 · 第{round_num} Round")
            else:
                lines.append(f"#### {stage}")
            lines.append("")

            _render_task_list_md(stage_tasks, lines, indent=0, current_agent=agent, show_children=show_children)

        # Turn 总结
        summary = summaries.get(turn_num)
        if summary:
            _prev_normal = sum(len(by_turn.get(t, [])) for t in sorted(by_turn) if t < turn_num)
            _no = _prev_normal + _summaries_before[turn_num] + 1
            lines.append(f"#### {_no}. Turn {turn_num} 总结")
            lines.append("")
            lines.append(f"- **结果**: {summary.get('result', '?')}")
            reason = summary.get("reason", "")
            if reason:
                lines.append(f"- **原因**: {reason}")
            lines.append("")

    # 最终答案
    if final_answer_obj:
        _no = _total_normal + _total_summaries + 1
        lines.append("---")
        lines.append("")
        lines.append(f"### {_no}. 最终答案")
        lines.append("")
        result_text = final_answer_obj.get("result", "")
        if result_text:
            lines.append(result_text)
        lines.append("")

    return "\n".join(lines)


def _render_task_list_md(
    tasks: list[dict],
    lines: list[str],
    indent: int = 0,
    current_agent: str = "",
    show_children: bool = False,
) -> None:
    """递归渲染 task 列表为 MD 列表项。

    Args:
        tasks: 任务节点列表（已包含 children 字段）
        lines: 输出行列表
        indent: 缩进层级（0 = 顶层，1+ = 子任务）
        current_agent: 当前 agent 名称，用于标记「⬅ 当前位置」
        show_children: 是否展开被委派者的内部执行细节（默认关闭）
    """
    prefix = "  " * indent
    for i, t in enumerate(tasks, 1):
        agent_name = t.get("agent", "?")
        task_desc = t.get("task", "")
        role = t.get("role", "")
        delegated_by = t.get("delegated_by")

        # 标题行
        is_none_agent = (agent_name or "").strip().upper() == "NONE"
        if is_none_agent:
            title = f"{i}. **NONE**（未派发）→ {task_desc}"
        elif role == "delegatee" and delegated_by:
            title = f"{i}. **{agent_name}**（被委派者 ← {delegated_by}）→ {task_desc}"
        else:
            title = f"{i}. **{agent_name}** → {task_desc}"

        # ── 当前位置标记 ──
        if current_agent and agent_name == current_agent and not is_none_agent:
            title += "  ⬅ **当前节点**"

        lines.append(f"{prefix}{title}")

        # 结果
        result = t.get("result", "")
        if result:
            lines.append(f"{prefix}   - **结果**: {result}")
        elif is_none_agent:
            lines.append(f"{prefix}   - **结果**: （未派发）")
        else:
            lines.append(f"{prefix}   - **结果**: （未完成）")

        # 原因
        reason = t.get("reason", "")
        if reason:
            lines.append(f"{prefix}   - **原因**: {reason}")

        lines.append("")

        # 递归渲染子任务（仅当 show_children=True 时才展开）
        children = t.get("children", [])
        if children and show_children:
            sub_prefix = "  " * (indent + 1)
            lines.append(f"{prefix}   ⤷ **{agent_name} 内部执行**:")
            lines.append("")
            _render_task_list_md(children, lines, indent + 1, current_agent=current_agent, show_children=show_children)