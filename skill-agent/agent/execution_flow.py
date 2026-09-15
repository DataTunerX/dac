"""Execution Flow — 结构化跨 Agent 执行追踪。

与 DAC Progress 并行，通过 A2A artifact ``name="execution-flow"`` 传输。
参照 DAC Progress 的成熟传输机制：

- 帧前缀: ``[[DAC_EXECUTION_FLOW]]``
- 帧格式: ``[[DAC_EXECUTION_FLOW]] {json}\n``
- A2A artifact name: ``"execution-flow"``
- 与 DAC Progress 共存于同一 A2A 流中，各自独立解析

提供:
- ExecutionTask 数据类（9 个固定字段）
- 帧序列化 / 反序列化
- 扁平列表 → 树形结构重建
- Markdown 渲染（供 Planner 的 group_memory 使用）
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Constants (mirrors DAC Progress naming convention)
# ---------------------------------------------------------------------------

EXECUTION_FLOW_FRAME_PREFIX = "[[DAC_EXECUTION_FLOW]] "
EXECUTION_FLOW_SCHEMA_VERSION = "v1"
EXECUTION_FLOW_BASE_FIELDS = (
    "schema_version",
    "execution_id",
    "turn",
    "stage",
    "agent",
    "role",
    "task",
    "result",
    "reason",
    "parent_execution_id",
    "delegated_by",
    "run_id",
    "trace_id",
    "user_id",
)


# ---------------------------------------------------------------------------
# ExecutionTask
# ---------------------------------------------------------------------------

@dataclass
class ExecutionTask:
    """一个 task 的一次执行记录。

    以 task 为视角，只记录：谁、在哪个阶段、做了什么、结果是什么、为什么。
    通过 parent_execution_id 形成层级关系，表达跨 Agent 的委派链。
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

    def to_frame(self) -> str:
        """序列化为 A2A 帧字符串。

        格式: ``[[DAC_EXECUTION_FLOW]] {"schema_version":"v1", ...}\n``
        参照 DAC Progress 的帧格式。
        """
        payload = {
            "schema_version": EXECUTION_FLOW_SCHEMA_VERSION,
            **self.to_dict(),
        }
        return f"{EXECUTION_FLOW_FRAME_PREFIX}{json.dumps(payload, ensure_ascii=False)}\n"

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

    @classmethod
    def from_frame(cls, frame: str) -> Optional["ExecutionTask"]:
        """从帧字符串解析 ExecutionTask。

        返回 None 如果帧格式无效。
        """
        if not isinstance(frame, str):
            return None
        stripped = frame.strip()
        if not stripped.startswith(EXECUTION_FLOW_FRAME_PREFIX):
            return None
        json_str = stripped[len(EXECUTION_FLOW_FRAME_PREFIX):]
        try:
            data = json.loads(json_str)
        except (json.JSONDecodeError, TypeError):
            return None
        # 验证 schema_version
        if data.get("schema_version") != EXECUTION_FLOW_SCHEMA_VERSION:
            return None
        # 验证必填字段
        required = ("execution_id", "turn", "stage", "agent", "role", "task")
        for key in required:
            if key not in data:
                return None
        return cls.from_dict(data)


# ---------------------------------------------------------------------------
# 帧检测（参照 DAC Progress 的 _is_progress_frame）
# ---------------------------------------------------------------------------

def is_execution_flow_frame(text: str) -> bool:
    """检查文本行是否为 Execution Flow 帧。"""
    return isinstance(text, str) and text.lstrip().startswith(EXECUTION_FLOW_FRAME_PREFIX)


def parse_frames(text: str) -> list[ExecutionTask]:
    """从多行文本中解析所有 Execution Flow 帧。

    用于从 A2A 响应中提取子 Agent 的 Execution Flow 帧。
    参照 DAC Progress 的 line-buffered 解析模式。
    """
    tasks: list[ExecutionTask] = []
    for line in text.splitlines():
        task = ExecutionTask.from_frame(line)
        if task is not None:
            tasks.append(task)
    return tasks


def strip_execution_flow_lines(text: str) -> str:
    """从文本中移除 Execution Flow 帧行。

    参照 DAC Progress 的 _strip_progress_lines。
    """
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

    用法::

        tree = build_tree([t.to_dict() for t in tasks])
        # tree[0]["children"] 包含子节点
    """
    # 浅拷贝，避免修改原始 dict
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

def render_execution_flow_md(
    tasks: list[dict] | list[ExecutionTask],
    agent: str = "",
    role: str = "initiator",
    current_agent: str = "",
    show_children: bool = False,
) -> str:
    """将 ExecutionTask 列表渲染为 Markdown 流水账。

    供 Planner 的 group_memory 使用。

    输出结构::

        ## 执行流水账
        **Agent**: xxx（发起者/被委派者）

        ### Turn 1
        #### 首次任务执行
        1. **agent** → task  ⬅ 当前节点
           - **结果**: ...
           - **原因**: ...

        #### 补充执行 · 第1轮
        1. **agent**（被委派者 ← xxx）→ task
           - ...

        #### Turn 1 总结
        - **结果**: fail
        - **原因**: ...

        ...

        ### 最终答案
        xxx

    Args:
        tasks: ExecutionTask 列表（dict 或 ExecutionTask 对象）
        agent: 当前 Agent 名称
        role: "initiator" 或 "delegatee"
        current_agent: 当前 agent 名称，用于标记「⬅ 当前节点」
        show_children: 是否展开被委派者的内部执行细节（默认关闭）。
                       开启后，被委派任务的「⤷ xxx 内部执行」子树会完整渲染。
                       默认关闭以保持上下文精简，避免冗余信息干扰 Planner。

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
    # 只收集 parent_execution_id 为 None（本层根任务）的 summary/final_answer。
    # 被委派 agent 的 summary/final_answer 已设置 parent_execution_id，应作为
    # 普通 task 渲染在对应的树节点下，避免混淆层级关系。
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

    # ── 全局序号计数器，让 turn_summary / final_answer 延续编号 ──
    # 所有会产生编号的项：normal_tasks（树中每个顶层节点算 1 个）+ summaries + final_answer。
    # 注意 _render_task_list_md 内部从 1 重新编号（每个 stage group 内独立），
    # 所以这里我们需要用「正常 task 的总数 + 前面 turn 的 summary 数」来算起始编号。
    _total_normal = len(tree)       # 所有 normal_tasks，每个顶层节点编号占 1
    _summary_turns = sorted(summaries.keys())   # 有 summary 的 turn 列表
    _total_summaries = len(_summary_turns)

    # 按 turn 分组
    by_turn: dict[int, list[dict]] = {}
    for t in tree:
        by_turn.setdefault(t["turn"], []).append(t)

    # ── 统计：每个 turn 之前累积了多少个 summary ──
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

        # stage 排序：pre_exec 最先，mid_exec_round_N 按 N 排序
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
                lines.append(f"#### 补充执行 · 第{round_num}轮")
            else:
                lines.append(f"#### {stage}")
            lines.append("")

            _render_task_list_md(stage_tasks, lines, indent=0, current_agent=agent, show_children=show_children)

        # Turn 总结 — 编号 = 正常 task 总数中在本 turn 之前的 + summary 在本 turn 之前的 + 1
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

    # 最终答案 — 编号 = 正常 task 总数 + 所有 summary 数 + 1
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
        current_agent: 当前 agent 名称，用于标记「当前位置」
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


# ---------------------------------------------------------------------------
# 表格渲染（调试用 — 在 summary 之后打印一份完整的 EF 快照）
# ---------------------------------------------------------------------------

# 列宽设定（固定宽度，内容超出自动换行）
_COL_WIDTHS = {
    "#": 3,
    "execution_id": 24,
    "turn": 4,
    "stage": 14,
    "agent": 14,
    "role": 10,
    "task": 44,
    "result": 58,
}

_COL_KEYS = ["#", "execution_id", "turn", "stage", "agent", "role", "task", "result"]


def _wrap(text: str, width: int) -> list[str]:
    """将文本按指定宽度换行。

    1. 先按换行符（原文字段中的 \\n）切为段落
    2. 每段再按列宽进行 word-wrap（优先在空格处断行）
    """
    if not text:
        return [""]
    result: list[str] = []
    for paragraph in text.split("\n"):
        if not paragraph:
            result.append("")
            continue
        remaining = paragraph
        while remaining:
            if len(remaining) <= width:
                result.append(remaining)
                break
            chunk = remaining[:width + 1]
            break_at = chunk.rfind(" ")
            if break_at >= 0:
                result.append(remaining[:break_at])
                remaining = remaining[break_at + 1:]
            else:
                result.append(remaining[:width])
                remaining = remaining[width:]
    if not result:
        result = [""]
    return result


def render_execution_flow_table(
    tasks: list[dict] | list[ExecutionTask],
    current_agent: str = "",
) -> str:
    """将 ExecutionTask 列表渲染为固定宽度的 ASCII 表格，供调试日志使用。

    列: # | execution_id | turn | stage | agent | task | result | reason

    Args:
        tasks: ExecutionTask 列表（dict 或 ExecutionTask 对象）。
        current_agent: 当前 agent 名称，用于在 task 列标记「⬅ 当前节点」。

    Returns:
        格式化的 ASCII 表格字符串。空列表返回空字符串。
    """
    if not tasks:
        return ""

    # 统一转为 dict
    rows: list[dict] = []
    for t in tasks:
        if isinstance(t, ExecutionTask):
            rows.append(t.to_dict())
        elif isinstance(t, dict):
            rows.append(t)
        else:
            continue
    if not rows:
        return ""

    # 保持插入顺序（_accumulated_execution_flow_tasks 已按 turn/时间顺序追加）

    # ── 构建表格行 ──

    def _task_display(r: dict) -> str:
        """构建 task 列显示文本，含委派关系和当前节点标记。"""
        task = r.get("task", "")
        role = r.get("role", "")
        delegated_by = r.get("delegated_by")
        agent = r.get("agent", "")
        # 委派关系标记
        if role == "delegatee" and delegated_by:
            task = f"{task} (← {delegated_by})"
        # 当前节点标记（跳过 turn_summary / final_answer，它们是元条目不是执行任务）
        if current_agent and agent == current_agent and r.get("stage") not in ("turn_summary", "final_answer"):
            task = f"{task}  ⬅ 当前节点"
        return task

    def _cell_text(r: dict, key: str, seq: int) -> str:
        if key == "#":
            return str(seq)
        if key == "task":
            return _task_display(r)
        return str(r.get(key, ""))

    # ── 表头 + 分隔线 ──
    header_parts = [k.rjust(_COL_WIDTHS[k]) if k == "#" else k.ljust(_COL_WIDTHS[k])
                    for k in _COL_KEYS]
    sep_line = "-" * (sum(_COL_WIDTHS.values()) + (len(_COL_WIDTHS) - 1) * 2)
    row_sep = sep_line
    header = "  ".join(header_parts)

    # ── 数据行（支持多行换行，行间加分隔线） ──
    data_blocks: list[list[str]] = []  # 每个逻辑行 = 一组物理行（不含分隔线）
    for seq, r in enumerate(rows, 1):
        cell_lines: dict[str, list[str]] = {}
        max_lines = 0
        for k in _COL_KEYS:
            raw = _cell_text(r, k, seq)
            if k == "#":
                wrapped = [raw.rjust(_COL_WIDTHS["#"])]
            else:
                wrapped = _wrap(raw, _COL_WIDTHS[k])
            if not wrapped:
                wrapped = [""]
            cell_lines[k] = wrapped
            if len(wrapped) > max_lines:
                max_lines = len(wrapped)
        block: list[str] = []
        for i in range(max_lines):
            parts: list[str] = []
            for k in _COL_KEYS:
                lines_for_cell = cell_lines[k]
                if i < len(lines_for_cell):
                    line = lines_for_cell[i]
                else:
                    line = ""
                parts.append(line.ljust(_COL_WIDTHS[k]))
            block.append("  ".join(parts))
        data_blocks.append(block)

    # ── 组装输出 ──
    total_width = sum(_COL_WIDTHS.values()) + (len(_COL_WIDTHS) - 1) * 2
    out: list[str] = []
    out.append("")
    out.append("=" * total_width)
    out.append("  Execution Flow Table")
    out.append("=" * total_width)
    out.append(header)
    out.append(sep_line)
    for i, block in enumerate(data_blocks):
        out.extend(block)
        # 最后一个 block 后不加分隔线，交给闭合线统一收尾
        if i < len(data_blocks) - 1:
            out.append(row_sep)
    out.append(sep_line)
    out.append(f"  Total: {len(rows)} entries")
    out.append("=" * total_width)

    return "\n".join(out)