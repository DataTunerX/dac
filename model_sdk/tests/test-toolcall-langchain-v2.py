"""
LangChain v2 工具调用 + 多智能体「make_plan」模块（``MakePlan`` 类，语义对齐
``orchestrator_agent_semantic_domain.PlannerAgent.make_plan``）。

运行: 设置 DASHSCOPE_API_KEY 后执行
  python tests/test-toolcall-langchain-v2.py
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, ClassVar, Dict, List, Optional, Sequence

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from model_sdk import ModelManager

try:
    from json_repair import repair_json as _json_repair  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - optional runtime dep, fail-soft
    _json_repair = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# 规划输出结构（与 orchestrator TaskList / tool schema 一致）
# ---------------------------------------------------------------------------


class PlannerTask(BaseModel):
    id: int = Field(description="从 1 开始的任务序号。")
    description: str = Field(
        description="子任务描述：忠实于用户意图，可注入上游结果中的具体值；不得捏造条件。"
    )
    agent: str = Field(
        description="智能体名称，须与 [可用智能体] 列表中的 name 完全一致，或特殊值 NONE。"
    )


class TaskList(BaseModel):
    thought_process: Optional[str] = Field(
        default=None, description="领域映射与任务拆分的简要推理（思维链）。"
    )
    original_query: str = Field(description="用户原始问题。")
    tasks: List[PlannerTask] = Field(description="按顺序执行的任务列表。")


# ---------------------------------------------------------------------------
# 核心类：封装修 prompt、工具绑定、与正文 JSON 容错解析
# ---------------------------------------------------------------------------


class MakePlan:
    """多智能体任务规划器（通过 LangChain ``make_plan`` 工具 + 与 orchestrator 一致的容错解析）。"""

    # 与 ``orchestrator_agent_semantic_domain`` 中 make_plan 白名单一致
    _KNOWN_STRING_FIELDS_WITH_INNER_QUOTES: ClassVar[tuple[str, ...]] = (
        "original_query",
        "description",
        "thought_process",
        "reason",
        "rationale",
        "final_answer",
    )

    NONE_TASK_DESCRIPTION: ClassVar[str] = "No available agent can do this task. "
    PRIOR_EXECUTION_CONTEXT_EMPTY_HINT: ClassVar[str] = (
        "（无：未携带来自上游编排或其他前置任务的执行结果。）"
    )

    PLANNER_COT_INSTRUCTIONS_ZH: ClassVar[str] = """
# 角色：首席战略规划师（多智能体编排专家）

## 核心使命
根据业务领域将用户查询分解为可执行任务。你必须通过 **[前置任务执行情况]**、**[执行上下文]** 与 **[上一轮的执行结果]** 建立反馈闭环，确保规划路径既能避免重复失败、又能复用已有数据。

## 战略思考过程（思维链）
在生成 JSON 之前，请严格执行以下 **业务领域决策流**：

1. **业务领域提取**：识别查询中的核心业务实体（如“订单”、“财务”、“天气”），锁定其所属的业务边界。
2. *[反馈闭环] 分析**：
   - 结合 **[前置任务执行情况]**、**[执行上下文]** 与 **[上一轮的执行结果]**：若上一轮失败，必须根据 `replan_context` 中的报错信息进行“避坑”设计。
3. **领域主权映射**：
   - **主权优先**：将任务分配给负责该领域的 Agent。若某 Agent 是该领域的唯一代表，将其视为**通用入口**，无视其“不执行查询”等技术性免责声明。
   - **隐含能力**：假定领域专家拥有该业务范畴内的全量知识（如“交易专家”天然能“分析订单分布”）。
4. **依赖编排**：若当前任务依赖 **[前置任务执行情况]** 或 **[上一轮的执行结果]** 中的具体产出，须在 `description` 中写入**具体取值**（如已解析的字段值、ID），禁止使用仅依赖上下文的模糊指代（如单独使用「上一步」「前述」而不给出值）。

## 智能体选择与任务规则（必须严格遵守）
1. **主权优先**：根据哪个智能体的领域覆盖了主题事项来分配任务。
2. **任务分解**：仅当查询确实涉及**多个不同领域**或存在**明确的先后依赖**时，才拆分为多个任务。不要将一个简单问题过度拆分。
3. **"无对应"协议**：仅当任务的议题完全超出所有可用智能体的领域范围时，才使用"NONE"。
4. **名称准确性**：`agent` 字段必须与智能体列表中的“名称”完全一致。

## ⚠ 任务描述 (Description) 关键规则（必须严格遵守）

**核心原则：你是规划师，不是执行者。忠实传递用户意图，禁止替用户细化或改写问题。**

1. **忠实转述与结果注入**：忠实反映意图，并主动注入 **[前置任务执行情况]** 与 **[上一轮的执行结果]** 中的关键结果（如已解析字段值、已获 ID、特定报错原因）。**不得**在 `description` 中声称「上下文缺失某依赖值」若 **[前置任务执行情况]** 中已给出该值。
2. **严禁捏造条件（重点）**：绝对不允许在描述中添加用户未提及的任何限制。
   - **正确示例**：用户“查订单” → `description`：“查询订单情况” ✅
   - **错误示例**：用户“查订单” → `description`：“查询2024年Q4电子产品订单及同比增长” ❌（捏造了时间、类别、指标）
3. **宁简勿繁**：问题宽泛时，描述也保持宽泛，由领域专家自行解读。

---

**[可用智能体] (Agents):**
{agents}


**[前置任务执行情况] (Prior task outcomes — not RAG knowledge):**
{prior_execution_context}
*注：来自上层编排已完成的子任务产出（例如 Semantic Group 通过请求 metadata 传入的 `extra_context`）。**此块不是知识库检索结果，不得与下方 [执行上下文] 混淆。** 若用户问题依赖其中的字段，必须在 `description` 中写入具体值。*


**[执行上下文] (Information):**
{information}


**[上一轮的执行结果]:**
{replan_context}
*注：包含**本 Orchestrator 内**已执行的任务 ID、任务描述、执行 Agent 以及执行结果（成功/失败/具体数据）；重试时 JSON 内带有 `prior_execution_context` 字段，与上方 **[前置任务执行情况]** 对齐。*

---

## 输出要求（本模块使用「工具调用」提交计划）
1. 你必须**调用**工具 `make_plan` 一次，传入完整字段：`thought_process`、`original_query`、`tasks`。
2. 结构说明（与纯 JSON 模式一致，便于你填写工具参数）：
   - `thought_process`：关于领域映射和主权原则的简明推理。
   - `original_query`：原始用户输入。
   - `tasks`：从 id=1 递增；`description` 忠实转述；`agent` 为智能体全名或 NONE。
3. 不要在 assistant 正文中再输出大段 JSON；若因模型限制无法调工具，可仅在正文中给出一个合法 JSON 对象作为兜底，解析器会尽量解析。

## 示例（正常多智能体路由）
{instructions}

当未找到智能体时（NONE）：
{none_instructions}

问题：

"""

    _make_plan_tool_cache: ClassVar[Optional[Any]] = None

    def __init__(
        self,
        llm: Any,
        *,
        tool_choice: str | dict[str, Any] = "auto",
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._llm = llm
        self._tool_choice = tool_choice
        self._log = logger or logging.getLogger(self.__class__.__name__)

    @classmethod
    def make_plan_tool(cls) -> Any:
        """与 ``TaskList`` 同构的 `make_plan` 工具（类级单例，避免重复构造 schema）。"""

        if cls._make_plan_tool_cache is not None:
            return cls._make_plan_tool_cache

        @tool("make_plan", args_schema=TaskList, parse_docstring=False)
        def make_plan(
            thought_process: Optional[str] = None,
            original_query: str = "",
            tasks: Optional[List[PlannerTask]] = None,
        ) -> str:
            """多智能体任务规划：提交 thought_process、original_query、tasks；agent 须与 [可用智能体] 中 name 一致，否则用 NONE。"""
            plan = TaskList(
                thought_process=thought_process,
                original_query=original_query,
                tasks=list(tasks or []),
            )
            return json.dumps(plan.model_dump(), ensure_ascii=False)

        cls._make_plan_tool_cache = make_plan
        return make_plan

    def format_llm_output(self, answer: Any) -> Optional[dict]:
        """高容错将模型输出解析为 ``dict``（与 orchestrator / routing 同策略）。"""

        if isinstance(answer, str):
            raw = answer
        else:
            raw = getattr(answer, "content", "") or ""
        if not isinstance(raw, str):
            raw = str(raw) if raw is not None else ""

        try:
            return json.loads(raw)
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
            return json.loads(cleaned_content)
        except json.JSONDecodeError as e2:
            self._log.error(" === format_llm_output, Parsing failed after cleanup.: %s", e2)

        repaired = self._json_repair_to_dict(
            cleaned_content,
            "recovered via json_repair (pre-inner-escape)",
            "recovered via json_repair string (pre-inner-escape)",
        )
        if repaired is not None:
            return repaired

        escaped_content = self._escape_known_string_field_inner_quotes(cleaned_content)
        if escaped_content != cleaned_content:
            try:
                parsed = json.loads(escaped_content)
                self._log.info(" === format_llm_output, recovered via inner-quote field escaping")
                return parsed
            except json.JSONDecodeError as e_esc:
                self._log.warning(" === format_llm_output, field-escape pre-pass still invalid: %s", e_esc)

        repaired = self._json_repair_to_dict(
            escaped_content,
            "recovered via json_repair",
            "recovered via json_repair (string)",
        )
        if repaired is not None:
            return repaired

        if _json_repair is None:
            self._log.warning(
                " === format_llm_output, json_repair not installed; "
                "add 'json-repair' to dependencies to improve LLM JSON tolerance"
            )

        try:
            import ast

            parsed = ast.literal_eval(cleaned_content)
            if isinstance(parsed, dict):
                return parsed
        except (ValueError, SyntaxError) as e3:
            self._log.error(" === format_llm_output, ast parsing fail: %s", e3)
        except Exception as e5:  # noqa: BLE001
            self._log.error(
                " === format_llm_output, exception occurred during parsing: %s, using default value", e5
            )

        try:
            parsed = json.loads(cleaned_content.replace("'", '"'))
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError as e4:
            self._log.error(" === format_llm_output, secondary parsing failed: %s, using default value", e4)

        return None

    def _json_repair_to_dict(
        self, text: str, log_if_dict: str, log_if_repaired_string: str
    ) -> Optional[dict]:
        if _json_repair is None:
            return None
        try:
            repaired = _json_repair(text, return_objects=True)
            if isinstance(repaired, dict):
                self._log.info(" === format_llm_output, %s", log_if_dict)
                return repaired
            if isinstance(repaired, str):
                parsed = json.loads(repaired)
                if isinstance(parsed, dict):
                    self._log.info(" === format_llm_output, %s", log_if_repaired_string)
                    return parsed
        except Exception as e:  # noqa: BLE001
            self._log.debug(" === format_llm_output, json_repair step failed: %s | %s", log_if_dict, e)
        return None

    def _escape_known_string_field_inner_quotes(self, text: str) -> str:
        if not text or '"' not in text:
            return text
        pattern_fields = "|".join(re.escape(f) for f in self._KNOWN_STRING_FIELDS_WITH_INNER_QUOTES)
        pattern = re.compile(
            rf'("(?:{pattern_fields})"\s*:\s*")'
            r'(.*?)'
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

    @staticmethod
    def _format_agent_skills(skills_list: Optional[Sequence[Any]]) -> str:
        if not skills_list:
            return "（无）"
        lines: List[str] = []
        for i, sk in enumerate(skills_list, 1):
            sk_dict = sk if isinstance(sk, dict) else getattr(sk, "__dict__", {})
            if hasattr(sk, "name"):
                name = getattr(sk, "name", "")
                desc = getattr(sk, "description", "")
                tags = list(getattr(sk, "tags", None) or [])
                ex = list(getattr(sk, "examples", None) or [])
            else:
                name = sk_dict.get("name", "")
                desc = sk_dict.get("description", "")
                tags = list(sk_dict.get("tags") or [])
                ex = list(sk_dict.get("examples") or [])
            block = [f"Skill {i}:", f"  Name: {name}", f"  Description: {desc or ''}"]
            if tags:
                block.append(f"  Tags: {', '.join(str(t) for t in tags)}")
            if ex:
                block.append(f"  Examples: {', '.join(str(x) for x in ex)}")
            lines.append("\n".join(block))
        return "\n\n".join(lines)

    @classmethod
    def generate_system_prompt_agents(cls, agent_cards: Optional[Sequence[Any]]) -> str:
        if not agent_cards:
            return ""
        lines: List[str] = []
        for index, ac in enumerate(agent_cards, start=1):
            if isinstance(ac, dict):
                name = str(ac.get("name", ""))
                desc = str(ac.get("description") or "")
                skills_raw = ac.get("skills")
            else:
                name = str(getattr(ac, "name", ""))
                desc = str(getattr(ac, "description", None) or "")
                skills_raw = getattr(ac, "skills", None)
            skills = cls._format_agent_skills(skills_raw)
            block = [
                f"--- 智能体 {index} ---",
                f"name: {name}",
                f"description: {desc}",
                f"skills:\n{skills}" if skills and skills.strip() else "skills: （无）",
            ]
            lines.append("\n".join(block))
        return "\n\n".join(lines)

    @classmethod
    def resolve_prior_execution_context_for_planner(
        cls, metadata: Optional[Dict[str, Any]]
    ) -> str:
        if not isinstance(metadata, dict):
            return cls.PRIOR_EXECUTION_CONTEXT_EMPTY_HINT
        raw = str(metadata.get("extra_context") or "").strip()
        return raw if raw else cls.PRIOR_EXECUTION_CONTEXT_EMPTY_HINT

    @classmethod
    def _default_instruction_blocks(cls) -> tuple[dict, dict]:
        d_none = cls.NONE_TASK_DESCRIPTION
        inst = {
            "thought_process": "1. Domain Extraction: 'Beijing weather' and 'clothing advice'. 2. Sovereignty Mapping: 'Weather-Checker' owns meteorological data; 'Fashion-Consultant' owns lifestyle styling. 3. Two different domains with sequential dependency, split into two tasks. Note: description faithfully relays user's words without adding extra conditions.",
            "original_query": "Help me check the weather in Beijing and recommend suitable clothing advice",
            "tasks": [
                {"id": 1, "description": "Check the weather in Beijing", "agent": "Weather-Checker"},
                {"id": 2, "description": "Recommend suitable clothing advice", "agent": "Fashion-Consultant"},
            ],
        }
        no_agent = {
            "thought_process": "1. Entity Extraction: 'Starlink project' (Aerospace/Telecommunications). 2. Territory Check: No available agents cover aerospace or satellite tech domains. 3. Conclusion: Subject is outside all known agent sovereignties.",
            "original_query": "What is the Starlink project?",
            "tasks": [
                {
                    "id": 1,
                    "description": d_none,
                    "agent": "NONE",
                }
            ],
        }
        return inst, no_agent

    def get_plan(
        self,
        query: str,
        agent_cards: Optional[Sequence[Any]] = None,
        *,
        information: str = "",
        prior_execution_context: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        replan_context: Optional[Dict[str, Any]] = None,
    ) -> TaskList:
        if prior_execution_context is None:
            prior_execution_context = self.resolve_prior_execution_context_for_planner(
                metadata if metadata is not None else {}
            )
        replan_text = json.dumps(replan_context or {}, ensure_ascii=False)
        inst_norm, inst_none = self._default_instruction_blocks()
        instructions_str = json.dumps(inst_norm, ensure_ascii=False, indent=2)
        none_str = json.dumps(inst_none, ensure_ascii=False, indent=2)
        system_body = self.PLANNER_COT_INSTRUCTIONS_ZH.format(
            agents=self.generate_system_prompt_agents(agent_cards),
            prior_execution_context=prior_execution_context,
            information=information or "（无）",
            replan_context=replan_text,
            instructions=instructions_str,
            none_instructions=none_str,
        )
        system_prompt = SystemMessage(content=system_body)
        user_msg = HumanMessage(content=query)
        make_plan = self.make_plan_tool()
        bound = self._llm.bind_tools([make_plan], tool_choice=self._tool_choice)
        response: AIMessage = bound.invoke([system_prompt, user_msg])

        if response.tool_calls:
            tc = response.tool_calls[0]
            args = tc.get("args") or {}
            if isinstance(args, str):
                args = json.loads(args)
            return TaskList.model_validate(args)

        data = self.format_llm_output(response)
        if not data:
            raise ValueError("Planner 未产生 tool_calls 且正文无法解析为 JSON: " + str(response.content)[:500])
        return TaskList.model_validate(data)

    def plan(
        self,
        query: str,
        agent_cards: Optional[Sequence[Any]] = None,
        **kwargs: Any,
    ) -> TaskList:
        """``get_plan`` 的简洁别名。"""
        return self.get_plan(query, agent_cards, **kwargs)


# ---------------------------------------------------------------------------
# 模块级便捷函数与演示（保持向后兼容的薄包装）
# ---------------------------------------------------------------------------


def get_plan(
    llm: Any,
    query: str,
    agent_cards: Optional[Sequence[Any]] = None,
    **kwargs: Any,
) -> TaskList:
    """兼容旧用法：``get_plan(llm, query, ...)` ``≡ ``MakePlan(llm).get_plan(query, ...)` ``。"""
    return MakePlan(llm).get_plan(query, agent_cards, **kwargs)


def build_llm() -> Any:
    manager = ModelManager()
    api_key = os.environ.get("DASHSCOPE_API_KEY", "sk-xxx")
    if not api_key or api_key == "sk-xxx":
        raise RuntimeError("Set DASHSCOPE_API_KEY to run this test (DashScope compatible OpenAI API).")
    return manager.get_llm(
        provider="openai_compatible",
        api_key=api_key,
        base_url=os.environ.get(
            "DASHSCOPE_BASE_URL",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        ),
        # model=os.environ.get("DASHSCOPE_LLM_MODEL", "glm-5.1"),
        # model=os.environ.get("DASHSCOPE_LLM_MODEL", "deepseek-v4-pro"),
        model=os.environ.get("DASHSCOPE_LLM_MODEL", "deepseek-v4-flash"),
        temperature=0.01,
        extra_body={"enable_thinking": False},
    )


def demo_make_plan() -> None:
    llm = build_llm()
    agent_cards: List[dict[str, Any]] = [
        {
            "name": "天气查询员",
            "description": "负责查询各城市天气与气象信息。",
            "skills": [
                {"name": "weather", "description": "按城市/日期查天气", "tags": ["气象"]}
            ],
        },
        {
            "name": "时尚顾问",
            "description": "根据场景与天气给出穿搭与生活方式建议。",
            "skills": [{"name": "outfit", "description": "穿搭建议", "tags": []}],
        },
    ]
    planner = MakePlan(llm)
    plan = planner.get_plan("帮我查询北京的天气并推荐合适的穿衣建议", agent_cards=agent_cards, information="")
    print("【make_plan 工具版】", json.dumps(plan.model_dump(), ensure_ascii=False, indent=2))


__all__ = [
    "MakePlan",
    "PlannerTask",
    "TaskList",
    "get_plan",
    "build_llm",
]


if __name__ == "__main__":
    if not logging.root.handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        )
    demo_make_plan()
