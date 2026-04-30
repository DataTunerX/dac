import os
from pathlib import Path
from typing import List, Dict, Optional, Any, Tuple
from model_sdk import ModelManager
from langchain_core.messages import SystemMessage, HumanMessage
from datetime import datetime
import json
import hashlib
import re
import time
import concurrent.futures
from concurrent.futures import ThreadPoolExecutor, as_completed
import ast
import logging
import uuid
from copy import deepcopy
from math import isfinite
from a2a.types import AgentCard, AgentSkill
from semantic_grouper.client.vector_client import VectorClient, Document as VectorDocument
from semantic_grouper.client.semantic_group_client import SemanticGroupClient, SemanticGroupData, DDGroupRelationData
from semantic_grouper.client.semantic_domain_client import SemanticDomainClient

try:
    # json_repair is a tolerant JSON parser designed specifically for LLM output.
    # It handles common failure modes such as unescaped inner double quotes,
    # trailing commas, missing quotes, python-style single quotes, etc.
    from json_repair import repair_json as _json_repair  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - optional runtime dep, fail-soft
    _json_repair = None  # type: ignore[assignment]

# String keys where LLM may put unescaped inner ``"`` in the value. Used by
# ``format_llm_output`` for Agent Card JSON, JOIN/CREATE decision JSON, etc.
# For the arbitration schema (``action``, ``target_group_index``, ``new_group_name``,
# ``reason``, ``confidence``, ``reason_intent``, ``consistency_check_pass``):
# only free-text ``reason`` commonly needs this pre-pass; ``action``/``reason_intent``
# are short enums, ``new_group_name`` is CamelCase-only by contract—still listed
# for rare model slippage. Numbers/bools are not listed.
_KNOWN_STRING_FIELDS_WITH_INNER_QUOTES = (
    "original_query",
    "description",
    "thought_process",
    "reason",
    "rationale",
    "final_answer",
    "new_group_name",
)


def _escape_known_string_field_inner_quotes(text: str) -> str:
    """Best-effort escape of unescaped inner ``"`` inside known single-line
    string fields of a planner-style JSON payload.

    We deliberately restrict the pre-pass to a whitelist of known fields where
    the value is a single JSON string on one line so we can recognize the end
    of the value by the structural pattern ``"`` followed by an optional
    comma/whitespace and a newline. Multi-line values and nested structures
    are left untouched (json_repair handles those as a later fallback).
    """
    if not text or '"' not in text:
        return text

    pattern_fields = "|".join(re.escape(f) for f in _KNOWN_STRING_FIELDS_WITH_INNER_QUOTES)
    # See the sibling implementation in orchestrator_agent_semantic_group.py
    # for detailed rationale about the regex anchoring strategy.
    pattern = re.compile(
        rf'("(?:{pattern_fields})"\s*:\s*")'
        r'(.*?)'
        r'((?<!\\)"[ \t]*,?[ \t]*$)',
        re.MULTILINE,
    )

    def _repl(m: "re.Match[str]") -> str:
        head, body, tail = m.group(1), m.group(2), m.group(3)
        fixed_chars: List[str] = []
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

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("semantic_group")

# Stored at end of dd_group_relation.association_reason to detect SD re-sync content changes.
_DAC_SD_CONTENT_FP_MARKER = "\n__DAC_SD_CONTENT_SHA256__:"

SEMANTIC_GROUP_CONSOLIDATION_SYSTEM_PROMPT = """
你是一个精通领域驱动设计（DDD）和业务建模的资深架构师。你的核心任务是根据业务描述，生成一个高质量的 Agent-to-Agent (A2A) 协议 JSON。

        ### ⚠ 最重要的设计原则（必须贯穿始终）：

        这个 Agent Card 的 description 会被上游编排器（Orchestrator）用来判断"用户的问题是否属于这个 Agent 的业务领域"。
        因此，description 的首要目标不是列举具体功能，而是**清晰定义这个 Agent 所负责的完整语义域（Semantic Domain）**。

        **你必须遵循"语义域优先"原则：**
        1. **整体系统 = 一个Agent**：用户提供的业务描述描述了一个完整系统。无论该系统内部划分了多少个子领域/限界上下文/模块，你必须生成**一个**Agent Card来覆盖该系统的**全部**子领域。绝对不可以只选取其中一个子领域来生成Agent Card。name和description必须体现系统的整体定位，而非某个子领域。
        2. **先定义域，再说能力**：首先用概括性语言说清楚"我负责整个 XXX 领域"，然后再展开细节。
        3. **宽泛包容，而非窄化排斥**：描述要涵盖该领域所有可能的业务问题，包括查询、统计、分析、对比、趋势、预测等各种操作。不要只列举当前已知的具体功能点。
        4. **同义词与关联概念全覆盖**：对于每个核心业务概念，必须同时提及其同义词、近义词、上位词、口语化表达。例如"贷款"同时提及"借款、放款、信贷、授信"。
        5. **避免排他性表述**：绝对不要写"只处理XXX"、"仅限于XXX"、"不负责XXX"这类限定性语句。只要问题与该语义域相关，即使是边缘场景，也应被覆盖。

        ### 输出规则：
        1. **只输出JSON**：不要任何额外文本、解释、Markdown代码块标记。
        2. **严格遵循结构**：必须使用下方提供的完整JSON结构模板。
        3. **确保可解析**：输出的JSON必须能被 `json.loads()` 直接解析。
        4. **引号必须使用ASCII标准双引号**：JSON中的所有引号必须使用ASCII标准双引号(U+0022)，绝对不能使用中文引号、排版引号或其他任何Unicode引号变体。这一点非常关键，使用非标准引号会导致JSON解析失败。

        ### 字段填充指南：

        **一定不能替换的字段**：url, provider, version, documentationUrl, capabilities部分, authentication部分, defaultInputModes部分, defaultOutputModes部分, skill的inputModes, skill的outputModes。

        **1. name 字段**：
        - 格式：驼峰命名法，如 `BankFinancialDataAgent`
        - 要求：体现所负责的**整个系统**的业务领域名称（不要只用某一个子领域命名）
        - 示例：若系统是电商交易平台，应命名为 `EcommerceTransactionAgent`，而非 `EcommerceUserManagementAgent`

        **2. description 字段（核心，约800-1200字）**：
        【请严格按照以下三层结构书写，形成从宏观到微观的完整描述】

        **第一层：语义域声明（最关键，约200字）**
        用2-3句话，清晰、概括地声明本 Agent 负责的完整业务领域。这段话的目的是让编排器一眼就能判断"这个领域涵盖了哪些类型的业务问题"。

        要求：
        - 明确说出所属的**行业**和**业务大类**
        - 列出该领域涉及的**所有核心业务主题词**（含同义词、近义词、口语表达）
        - 使用"涵盖……等一切相关问题"这类包容性语句

        示例：
        > "本Agent是银行业分支机构财务数据领域的全能专家，负责处理与银行网点/支行/分行的财务状况相关的一切问题。覆盖的核心主题包括但不限于：资产负债表、总资产、总负债、净资产、存款（储蓄、定期、活期、对公存款、个人存款、零售存款）、贷款（放款、授信、信贷、按揭、消费贷、对公贷款、零售贷款）、客户规模、员工规模，以及围绕这些数据的查询、统计、分析、对比、排名、趋势等各类操作。"

        **第二层：子领域与业务概念展开（约400-600字）**
        按业务子领域分组，展开描述每个子领域包含的业务概念和典型问题类型。每个子领域都应该：
        - 说明其核心职责
        - 列出涉及的全部业务术语和数据实体（含同义词）
        - 说明该子领域下用户可能提出的问题方向（用"包括XXX类问题"的方式概括，不要举过于具体的例子）

        示例：
        > "【存款业务】管理各分支机构的存款数据，涉及的概念包括：存款结构、存款分布、对公存款与零售存款的区分、活期存款与定期存款的比例、存款总额与趋势变化等。用户可能围绕存款提出查询、汇总、排名、对比、趋势分析等各类问题。"

        **第三层：协作声明（约100-200字）**
        简要说明本 Agent 在多智能体协作中的定位：
        - 当其他 Agent 或用户遇到与本领域相关的任何问题时，都应路由到本 Agent
        - 本 Agent 具备对该领域数据进行多维度分析的能力
        - 如果用户的问题涉及的数据实体属于本领域，无论具体操作方式如何（查询、统计、可视化、导出等），本 Agent 都能处理

        **3. skills 数组**：
        每个 skill 代表该语义域下的一个子领域或核心业务能力：
        - `id`: 如 `deposit-data-analysis`
        - `name`: 如 `存款业务数据服务`
        - `description`: 应包含：
          1. **子领域范围**：这个 skill 覆盖的业务范围
          2. **核心数据实体**：涉及的业务名词和概念（含同义词）
          3. **支持的问题类型**：可以处理哪些类型的业务问题
        - `tags`: 业务标签，要包含同义词和关联词，如 `["deposit", "savings", "存款", "储蓄"]`
        - `examples`: 该子领域下的典型自然语言问题示例

        ### 完整JSON模板（必须严格使用此结构）：
        {
            "name": "根据业务领域填写，如BankFinancialDataAgent",
            "description": "【请严格按照三层结构填充：语义域声明 + 子领域展开 + 协作声明】",
            "url": "http://192.168.xxx.xxx:20002/",
            "provider": null,
            "version": "1.0.0",
            "documentationUrl": null,
            "capabilities": {
                "streaming": "True",
                "pushNotifications": "True",
                "stateTransitionHistory": "False"
            },
            "authentication": {
                "credentials": null,
                "schemes": ["public"]
            },
            "defaultInputModes": ["text", "text/plain"],
            "defaultOutputModes": ["text", "text/plain"],
            "skills": [
                {
                    "id": "子领域标识，如deposit-data-analysis",
                    "name": "子领域名称，如存款业务数据服务",
                    "description": "必须包含：子领域范围、核心数据实体（含同义词）、支持的问题类型",
                    "tags": ["业务标签，含同义词和关联词"],
                    "examples": ["该子领域下的典型自然语言问题示例"],
                    "inputModes": null,
                    "outputModes": null
                }
            ]
        }

        ### 关键检查清单（生成后请自查）：
        1. ✅ description 第一层是否用概括性语言声明了完整的语义域？
        2. ✅ 是否覆盖了所有核心业务名词的同义词和口语表达？
        3. ✅ 是否避免了"只处理"、"仅限于"等排他性表述？
        4. ✅ 是否说明了"任何与该领域相关的问题都能处理"？
        5. ✅ skills 是否按子领域划分，而非按具体操作划分？
        6. ✅ tags 是否包含了足够的同义词和关联词？
        7. ✅ 当输入里已经包含「语义组旧的 description / agent_card」或与成员域语义高度重叠时，输出的 description 必须是**重新归纳后的单一去重正文**，禁止把旧 description 整段保留再在文末追加「补充」造成同一子领域写两遍。

        ### 最终要求：
        1. 基于用户提供的业务描述，生成完整的JSON
        2. description 务必做到"领域覆盖最大化"——宁可多覆盖，不可漏掉相关问题
        3. 确保 skills 真实、具体、可调用
        4. 不要偏离提供的JSON结构
        """

_llm_instance = None


def get_llm():
    """Lazy-init the LLM so the module can be imported without LLM env vars."""
    global _llm_instance
    if _llm_instance is None:
        manager = ModelManager()
        _llm_instance = manager.get_llm(
            provider=os.getenv("PROVIDER", "openai_compatible"),
            api_key=os.getenv("API_KEY"),
            base_url=os.getenv("BASE_URL"),
            model=os.getenv("Model"),
            temperature=0.01,
            extra_body={"enable_thinking": False},
        )
    return _llm_instance

class SemanticGrouper:
    """
    语义域分组器（Semantic Grouper）
    
    核心功能：将新的语义域（Semantic Domain）增量式地归类到现有的语义组（Semantic Group）中。
    
    工作流程：
    1. 向量初筛：使用向量数据库检索与新语义域最相似的 Top-3 候选组
    2. LLM 判定：使用大语言模型分析新语义域与候选组的关系，决定：
       - JOIN：将新语义域加入现有组
       - CREATE：创建新的语义组
    
    设计特点：
    - 增量式处理：每次只处理新的语义域，不需要重新分析所有数据
    - 自动查询：每次处理时自动从向量数据库查询所有现有组，无需外部传入
    - 容错机制：包含重试逻辑和异常处理，确保系统稳定性
    """
    
    def __init__(
        self, 
        vector_client: Optional[VectorClient] = None,
        semantic_group_client: Optional[SemanticGroupClient] = None,
        semantic_domain_client: Optional[SemanticDomainClient] = None,
        collection_name: str = "semantic_groups",
        max_workers: int = 5, 
        batch_size: int = 10
    ):
        """
        初始化 SemanticGrouper
        
        Args:
            llm: LLM 实例，用于决策分析
            vector_client: 向量客户端（可选），用于检索相似组。如果为 None，则无法进行向量检索
            semantic_group_client: 语义组客户端（可选），用于操作语义组数据
            semantic_domain_client: 语义域客户端（可选），用于获取语义域数据。当只剩1个成员时需要使用
            collection_name: 向量数据库集合名称，存储语义组信息
            max_workers: 最大工作线程数（当前未使用，保留用于未来扩展）
            batch_size: 批次大小（当前未使用，保留用于未来扩展）
        """
        self.llm = get_llm()
        self.vector_client = vector_client
        self.semantic_group_client = semantic_group_client
        self.semantic_domain_client = semantic_domain_client
        self.collection_name = collection_name
        self.max_workers = max_workers
        self.batch_size = batch_size

    def _normalize_group_name(self, group_name: Any, fallback: str = "UnnamedGroup") -> str:
        """Normalize group names to ASCII CamelCase for stable storage."""

        def _to_ascii_camel(text: str) -> str:
            tokens = re.findall(r"[A-Za-z0-9]+", text)
            if not tokens:
                return ""
            parts: List[str] = []
            for token in tokens:
                if token.isdigit():
                    parts.append(token)
                else:
                    parts.append(token[0].upper() + token[1:])
            out = "".join(parts)
            if not out:
                return ""
            if out[0].isdigit():
                out = f"Group{out}"
            return out

        normalized = _to_ascii_camel(str(group_name or "").strip())
        if normalized:
            return normalized

        fallback_normalized = _to_ascii_camel(str(fallback or ""))
        return fallback_normalized or "UnnamedGroup"

    @staticmethod
    def _bump_semantic_group_version(current: Any) -> str:
        """
        Next semantic group version for data-services (opaque string; monotonic for common forms).
        - Pure integer: +1
        - Trailing digits: increment that suffix
        - Otherwise: append ".2" for a second revision
        """
        s = str(current).strip() if current is not None else ""
        if not s:
            return "2"
        if s.isdigit():
            return str(int(s) + 1)
        m = re.search(r"(\d+)$", s)
        if m:
            n = int(m.group(1))
            i, j = m.span(1)
            return s[:i] + str(n + 1)
        return f"{s}.2"

    @staticmethod
    def _canonical_semantic_group_fields(
        group_name: Any, description: Any, agent_card: Any
    ) -> tuple[str, str, str]:
        """Normalize group snapshot fields so JSON agent_card compares stably."""
        gn = str(group_name or "").strip()
        desc = str(description or "").strip()
        raw = agent_card
        if raw is None:
            card_norm = ""
        elif isinstance(raw, dict):
            try:
                card_norm = json.dumps(raw, sort_keys=True, ensure_ascii=False)
            except Exception:
                card_norm = str(raw)
        else:
            card_str = str(raw).strip()
            if card_str.startswith("{") or card_str.startswith("["):
                try:
                    card_norm = json.dumps(
                        json.loads(card_str), sort_keys=True, ensure_ascii=False
                    )
                except Exception:
                    card_norm = card_str
            else:
                card_norm = card_str
        return gn, desc, card_norm

    def _version_for_semantic_group_update(
        self,
        group_data_before: Dict[str, Any],
        *,
        new_group_name: str,
        new_description: str,
        new_agent_card: str,
    ) -> str:
        """
        When group_name/description/agent_card semantically change, bump version; else keep stored value.
        """
        old = self._canonical_semantic_group_fields(
            group_data_before.get("group_name"),
            group_data_before.get("description"),
            group_data_before.get("agent_card"),
        )
        new = self._canonical_semantic_group_fields(
            new_group_name, new_description, new_agent_card
        )
        if old == new:
            v = group_data_before.get("version")
            vs = str(v).strip() if v is not None else ""
            return vs or "1"
        return self._bump_semantic_group_version(group_data_before.get("version"))


    def format_llm_output(self, answer) -> dict:
        """Parse the planner LLM output into a dict with heavy tolerance.

        See ``orchestrator_agent_semantic_group.PlannerAgent.format_llm_output``
        for the detailed recovery strategy — this implementation mirrors it.
        """
        raw = getattr(answer, "content", "") or ""

        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass

        cleaned_content = raw.strip()
        if cleaned_content.startswith('```json'):
            cleaned_content = cleaned_content[7:]
        elif cleaned_content.startswith('```'):
            cleaned_content = cleaned_content[3:]
        if cleaned_content.endswith('```'):
            cleaned_content = cleaned_content[:-3]
        cleaned_content = cleaned_content.strip()

        try:
            return json.loads(cleaned_content)
        except json.JSONDecodeError as e2:
            logger.error(f" === format_llm_output, Parsing failed after cleanup.: {e2}")

        escaped_content = _escape_known_string_field_inner_quotes(cleaned_content)
        if escaped_content != cleaned_content:
            try:
                parsed = json.loads(escaped_content)
                logger.info(" === format_llm_output, recovered via inner-quote field escaping")
                return parsed
            except json.JSONDecodeError as e_esc:
                logger.warning(f" === format_llm_output, field-escape pre-pass still invalid: {e_esc}")

        if _json_repair is not None:
            try:
                repaired = _json_repair(escaped_content, return_objects=True)
                if isinstance(repaired, dict):
                    logger.info(" === format_llm_output, recovered via json_repair")
                    return repaired
                if isinstance(repaired, str):
                    parsed = json.loads(repaired)
                    if isinstance(parsed, dict):
                        logger.info(" === format_llm_output, recovered via json_repair (string)")
                        return parsed
            except Exception as e_rep:  # noqa: BLE001
                logger.error(f" === format_llm_output, json_repair failed: {e_rep}")
        else:
            logger.warning(
                " === format_llm_output, json_repair not installed; "
                "add 'json-repair' to dependencies to improve LLM JSON tolerance"
            )

        try:
            import ast
            parsed = ast.literal_eval(cleaned_content)
            if isinstance(parsed, dict):
                return parsed
        except (ValueError, SyntaxError) as e3:
            logger.error(f" === format_llm_output, ast parsing fail: {e3}")
        except Exception as e5:  # noqa: BLE001
            logger.error(f" === format_llm_output, exception occurred during parsing: {e5}, using default value")

        try:
            parsed = json.loads(cleaned_content.replace("'", '"'))
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError as e4:
            logger.error(f" === format_llm_output, secondary parsing failed: {e4}, using default value")

        return None


    def _extract_description_from_agent_card(self, agent_card: Any) -> str:
        """
        从 agent_card 中提取 description 字段
        
        Args:
            agent_card: agent_card，可能是字符串（JSON）、字典或 None
            
        Returns:
            description 字符串，如果提取失败则返回空字符串
        """
        if not agent_card:
            return ''
        
        try:
            # 如果是字符串，尝试解析为 JSON
            if isinstance(agent_card, str):
                try:
                    agent_card_dict = json.loads(agent_card)
                except json.JSONDecodeError:
                    return ''
            elif isinstance(agent_card, dict):
                agent_card_dict = agent_card
            else:
                return ''
            
            # 提取 description 字段
            description = agent_card_dict.get('description', '')
            return description if description else ''
        except Exception as e:
            logger.warning(f"从 agent_card 提取 description 失败: {str(e)}")
            return ''

    def _fetch_all_existing_groups(self) -> List[Dict[str, Any]]:
        """
        从 SemanticGroupClient 获取所有现有的语义组
        
        Returns:
            现有组列表，每个组包含：
            - group_id: 组的唯一标识符
            - group_name: 组名称
            - reason: 组的描述/理由
            - member_dd_ids: 组内成员的数据描述符ID列表
        """
        if not self.semantic_group_client:
            logger.warning("SemanticGroupClient 未配置，无法获取现有组，返回空列表")
            return []
        
        try:
            # 获取所有语义组
            groups_response = self.semantic_group_client.get_all_semantic_groups()
            
            groups_data = groups_response.get('data', [])
            if not isinstance(groups_data, list):
                groups_data = []
            
            existing_groups = []
            for group in groups_data:
                group_id = group.get('id') or group.get('group_id')
                if not group_id:
                    continue
                
                # 获取该组的所有关系，以获取 member_dd_ids
                try:
                    relations_response = self.semantic_group_client.get_relations_by_group_id(
                        group_id
                    )
                    relations_data = relations_response.get('data', [])
                    if not isinstance(relations_data, list):
                        relations_data = []
                    
                    member_dd_ids = [rel.get('sd_id') for rel in relations_data if rel.get('sd_id')]
                except Exception as e:
                    logger.warning(f"获取组 {group_id} 的关系信息失败: {str(e)}")
                    member_dd_ids = []
                
                existing_groups.append({
                    'group_id': group_id,
                    'group_name': group.get('group_name', ''),
                    'reason': group.get('description', ''),
                    'member_dd_ids': member_dd_ids
                })
            
            logger.info(f"从 SemanticGroupClient 获取到 {len(existing_groups)} 个现有组")
            return existing_groups
            
        except Exception as e:
            logger.error(f"获取现有组失败: {str(e)}", exc_info=True)
            return []

    def _search_candidate_groups(
        self, 
        new_domain: Dict[str, Any], 
        top_k: int = 3
    ) -> List[Dict[str, Any]]:
        """
        向量初筛：检索与新语义域最相似的候选组
        
        这是增量式分组的第一步，通过向量相似度搜索快速找到可能相关的现有组。
        使用混合搜索（hybrid search）结合向量相似度和关键词匹配，提高检索准确性。
        
        Args:
            new_domain: 新的语义域描述，包含以下字段：
                       - semantic_domain: 语义域描述文本（优先使用）
                       - dd_name: 数据描述符名称
                       - dd_namespace: 数据描述符命名空间
            top_k: 返回前K个候选组（默认3个，平衡准确性和效率）
            
        Returns:
            候选组列表，每个组包含：
            - group_id: 组的唯一标识符（UUID）
            - group_name: 组名称
            - reason: 组的创建理由
            - member_dd_ids: 组内成员的数据描述符ID列表
            - score: 向量相似度得分
            - hybrid_score: 混合搜索得分
        """
        if not self.vector_client:
            logger.warning("VectorClient 未配置，无法进行向量检索，返回空列表")
            return []
        
        try:
            # 步骤1：构建查询文本
            # 优先使用语义域描述，如果没有则使用名称和命名空间组合
            query_text = new_domain.get('semantic_domain', '')
            logger.info(f"向量检索 - 查询文本长度: {len(query_text)} 字符")
            logger.debug(f"向量检索 - 查询文本前200字符: {query_text[:200]}...")
            
            # 步骤2：调用向量搜索
            logger.info(f"向量检索 - 开始搜索，collection: {self.collection_name}, top_k: {top_k}")
            search_result = self.vector_client.search(
                collection_name=self.collection_name,
                query=query_text,
                search_type="vector",  # 混合搜索：结合向量相似度和关键词匹配
                limit=top_k            # 只返回前 top_k 个结果
            )
            
            # 打印搜索结果的基本信息
            logger.info(f"向量检索 - 搜索结果状态: {search_result.status}")
            logger.info(f"向量检索 - 搜索结果数量: {len(search_result.result)}")
            
            # 步骤3：从搜索结果中提取候选组信息，并通过 SemanticGroupClient 获取详细信息
            candidate_groups = []
            if not self.semantic_group_client:
                logger.warning("SemanticGroupClient 未配置，无法获取组详细信息，返回空列表")
                return []
            
            for idx, result in enumerate(search_result.result):
                logger.info(f"向量检索 - 处理结果 {idx+1}/{len(search_result.result)}")
                logger.info(f"向量检索 - 结果得分: {result.score}, 混合得分: {result.hybrid_score}")
                logger.info(f"向量检索 - 结果内容长度: {len(result.content)} 字符")
                logger.debug(f"向量检索 - 结果内容前200字符: {result.content[:200]}...")
                
                metadata = result.metadata
                logger.info(f"向量检索 - metadata 类型: {type(metadata)}")
                logger.debug(f"向量检索 - metadata 原始值: {metadata}")
                # 将 Pydantic 模型转换为字典（如果还不是字典）
                # 优先使用 model_dump() (Pydantic v2) 或 dict() (Pydantic v1)
                # 注意：需要获取所有字段，包括额外的字段（如 group_id）
                if hasattr(metadata, 'model_dump'):
                    # Pydantic v2: 使用 model_dump() 获取所有字段
                    metadata_dict = metadata.model_dump(exclude_unset=False, exclude_none=False)
                elif hasattr(metadata, 'dict'):
                    # Pydantic v1: 使用 dict() 获取所有字段
                    metadata_dict = metadata.dict(exclude_unset=False, exclude_none=False)
                elif isinstance(metadata, dict):
                    metadata_dict = metadata
                elif hasattr(metadata, '__dict__'):
                    # 对于普通对象，获取所有属性（包括可能通过 __pydantic_extra__ 存储的额外字段）
                    metadata_dict = {}
                    # 获取标准属性
                    for k, v in metadata.__dict__.items():
                        if not k.startswith('_'):
                            metadata_dict[k] = v
                    # 获取 Pydantic 额外字段（如果存在）
                    if hasattr(metadata, '__pydantic_extra__'):
                        metadata_dict.update(metadata.__pydantic_extra__)
                else:
                    metadata_dict = {}
                
                # 只处理包含 group_id 的结果（确保是有效的组）
                logger.info(f"向量检索 - metadata_dict: {metadata_dict}")
                group_id = metadata_dict.get('group_id')
                logger.info(f"向量检索 - 提取的 group_id: {group_id}")
                if not group_id:
                    logger.warning(f"向量检索 - 结果 {idx+1} 没有 group_id，跳过")
                    continue
                
                try:
                    # 通过 SemanticGroupClient 获取组的详细信息
                    group_response = self.semantic_group_client.get_semantic_group_by_id(
                        group_id
                    )
                    group_data = group_response.get('data', {})
                    
                    # 获取该组的所有关系，以获取 member_dd_ids
                    try:
                        relations_response = self.semantic_group_client.get_relations_by_group_id(
                            group_id
                        )
                        relations_data = relations_response.get('data', [])
                        if not isinstance(relations_data, list):
                            relations_data = []
                        
                        member_dd_ids = [rel.get('sd_id') for rel in relations_data if rel.get('sd_id')]
                    except Exception as e:
                        logger.warning(f"获取组 {group_id} 的关系信息失败: {str(e)}")
                        member_dd_ids = []
                    children_count = 0
                    try:
                        children_resp = self.semantic_group_client.get_children_by_parent_id(group_id)
                        children_data = children_resp.get("data", [])
                        if isinstance(children_data, list):
                            children_count = len(children_data)
                    except Exception:
                        children_count = 0
                    
                    candidate_groups.append({
                        'group_id': group_id,  # 优先使用 UUID，最可靠的标识符
                        'group_name': group_data.get('group_name', ''),
                        'reason': group_data.get('description', ''),
                        'member_dd_ids': member_dd_ids,
                        'parent_id': group_data.get('parent_id'),
                        'has_children': children_count > 0,
                        'children_count': children_count,
                        'score': result.score,  # 向量相似度得分
                        'hybrid_score': result.hybrid_score  # 混合搜索得分
                    })
                except Exception as e:
                    logger.warning(f"获取组 {group_id} 的详细信息失败: {str(e)}，跳过该组")
                    continue
            
            logger.info(f"向量检索到 {len(candidate_groups)} 个候选组")
            if len(candidate_groups) == 0 and len(search_result.result) > 0:
                logger.warning(f"向量检索返回了 {len(search_result.result)} 个结果，但没有找到有效的候选组（可能缺少 group_id）")
            return candidate_groups
            
        except Exception as e:
            logger.error(f"向量检索失败: {str(e)}", exc_info=True)
            import traceback
            logger.error(f"向量检索异常堆栈: {traceback.format_exc()}")
            return []

    def _incremental_decision(
        self, 
        new_domain: Dict[str, Any], 
        candidate_groups: List[Dict[str, Any]],
        max_retries: int = 3,
        retry_delay: float = 1.0
    ) -> Dict[str, Any]:
        """
        LLM 判定：决定新语义域应该 JOIN 还是 CREATE
        
        Args:
            new_domain: 新的语义域
            candidate_groups: 候选组列表（最多3个）
            max_retries: 最大重试次数
            retry_delay: 重试延迟
            
        Returns:
            决策结果，格式：{
                "action": "JOIN" | "CREATE",
                "target_group_index": int,  # JOIN 的目标组索引，CREATE 时设为 -1
                "new_group_name": str,  # CREATE 时的新组名
                "reason": str,  # 决策理由
                "confidence": float
            }
        """
        
        prompt = f"""
        你不仅仅是一位出色的数据架构师，也是一位出色业务分析专家，精通各种业务系统的需求范围和业务范围。现在有一个新的数据源（DataDescriptor）需要归类到现有的语义组中。
        
        ### 新的数据源：
        {json.dumps(new_domain, ensure_ascii=False, indent=2)}
        
        ### 候选的现有语义组（通过向量相似度检索得到，按相似度排序）：
        {json.dumps(candidate_groups, ensure_ascii=False, indent=2) if candidate_groups else "无候选组（这是第一个数据源）"}
        
        ### 你的任务：
        请分析新的数据源与候选组的关系，做出以下决策：

        ## 决策规则和优先级

        ### 1. JOIN 现有组（优先级最高）
        **使用条件（满足任一即可）：**
        - **外键关联**：新数据源明确引用现有组的核心表
        - **业务父子关系**：新数据源是现有组的子集或扩展（如：订单项之于订单）
        - **相同业务实体**：描述同一业务对象的不同方面（如：用户基本信息 vs 用户偏好）
        - **数据血缘关系**：有明确的数据流向关系
        - **业务桥梁**：如果新数据源连接多个现有组，选择最匹配的一个组进行 JOIN

        ### 2. CREATE 新组（最后考虑）
        **使用条件：**
        - 与所有现有组在业务逻辑上无关
        - 代表全新的业务领域
        - 未来可能独立演化
        

        # 业务领域的一些参考案例，用于提供什么情况create，什么情况join。 这里的案例不包括所有，具体怎么分组要根据实际情况来判断。

        ## 业务领域识别指南
        根据常见模式识别业务领域：

        ### 电子商务系统特征：
        - 包含用户、商品、订单、支付、物流等实体
        - 实体间有购买、支付、配送等关系
        - 核心表：users, products, orders, payments

        ### CRM系统特征：
        - 包含客户、联系人、商机、活动等
        - 重点是客户关系和销售漏斗
        - 核心表：customers, leads, opportunities, activities

        ### ERP系统特征：
        - 包含供应链、财务、生产、库存等
        - 跨部门业务流程整合
        - 核心表：inventory, suppliers, invoices, production_orders

        ## 评估检查清单
        分析时请依次检查：
        1. ✅ **实体识别**：新数据源的核心实体是什么？
        2. ✅ **关系分析**：与现有组的实体有何关联？（外键、业务逻辑）
        3. ✅ **业务流程**：属于哪个业务流程阶段？
        4. ✅ **数据流向**：数据如何流入/流出？
        5. ✅ **领域边界**：是否符合领域驱动设计（DDD）的界限上下文？

        ## 决策顺序（必须遵守）
        1) 先判断是否能 JOIN 到候选组中的某一个；
        2) 只有在前者不满足时才 CREATE。

        ## Few-shot 示例（帮助你稳定决策）

        示例A（JOIN）：
        - 新数据源：OrderItem/OrderDiscount，明确外键关联到已有 OrderGroup
        - 候选组：["OrderManagementGroup", "ProductGroup"]
        - 输出应为：
        {{
            "action": "JOIN",
            "target_group_index": 0,
            "new_group_name": "",
            "reason": "与订单主实体强关联，属于订单组的扩展。",
            "confidence": 0.92
        }}

        示例B（CREATE）：
        - 新数据源：订单履约与支付（Order/OrderItem/Payment/Shipping）
        - 候选组：["UserAccountManagementAgent", "ProductCoreInventoryAgent"]
        - 判定：与 User/Product 子组不直接关联，应独立成组
        - 输出应为：
        {{
            "action": "CREATE",
            "target_group_index": -1,
            "new_group_name": "EcommerceOrderFulfillmentAgent",
            "reason": "订单履约域应独立成组。",
            "confidence": 0.90
        }}

        示例C（CREATE）：
        - 新数据源：HR 薪酬考勤；候选组仅有电商交易相关组
        - 判定：与候选组无明显业务归属关系
        - 输出应为：
        {{
            "action": "CREATE",
            "target_group_index": -1,
            "new_group_name": "HumanResourceOperationsAgent",
            "reason": "与现有候选组业务域不相关，需独立演化。",
            "confidence": 0.95
        }}


        ### 输出格式：
        请严格按以下 JSON 格式返回，**禁止包含任何 Markdown 代码块标签（如 ```json）、注释或解释性文字**：
        且 `new_group_name` 必须是 **English CamelCase**（仅英文字母和数字、无空格、无中文），例如：
        `EcommerceOrderFulfillmentAgent`、`CustomerProfileAgent`。
        另外必须满足：`action` 与 `reason` 语义必须一致，禁止出现“action=JOIN 但 reason 说明应 CREATE”的矛盾。
        你必须同时返回 `reason_intent` 与 `consistency_check_pass`，并在输出前自检：
        - `reason_intent` 必须与 `action` 完全一致；
        - `consistency_check_pass` 只有在 `action == reason_intent` 且 `reason` 仅解释该 action 时才为 true。
        若冲突，以你最终真正选择的 action 重写 reason，并修正 `reason_intent` 与 `consistency_check_pass`。
        {{
            "action": "JOIN" | "CREATE",
            "target_group_index": 0,  // JOIN 时指定目标组索引（从0开始），CREATE 时设为 -1
            "new_group_name": "EcommerceOrderFulfillmentAgent",  // CREATE 时的新组名，JOIN 时为空字符串
            "reason": "决策理由：说明为什么做出这个决策",
            "confidence": 0.95,  // 置信度 0-1
            "reason_intent": "JOIN" | "CREATE",
            "consistency_check_pass": true
        }}
        """
        
        system_message = SystemMessage(content=prompt)
        human_message = HumanMessage(content="请做出决策")
        
        # 重试逻辑
        last_exception = None
        conflict_retry_used = False
        for attempt in range(max_retries + 1):
            try:
                if attempt > 0:
                    delay = retry_delay * (2 ** (attempt - 1))
                    logger.warning(f"第 {attempt} 次重试，等待 {delay:.2f} 秒后重试...")
                    time.sleep(delay)
                
                logger.info(f"调用 LLM 进行增量决策（尝试 {attempt + 1}/{max_retries + 1}）")
                response = self.llm.invoke([system_message, human_message])
                
                decision = self.format_llm_output(response)
                
                if decision and isinstance(decision, dict):
                    # 验证决策格式
                    action = decision.get('action', '').upper()
                    
                    # 如果 LLM 返回了 MERGE，强制改为 JOIN
                    if action == 'MERGE':
                        logger.warning("LLM 返回 MERGE 操作，但系统不支持 MERGE，强制改为 JOIN")
                        # 选择置信度最高的候选组进行 JOIN
                        if candidate_groups:
                            decision['action'] = 'JOIN'
                            decision['target_group_index'] = 0  # 选择第一个（相似度最高）
                            decision['reason'] = f"原 MERGE 决策不支持，改为 JOIN 到最相似的组: {decision.get('reason', '')}"
                            action = 'JOIN'
                        else:
                            action = 'CREATE'
                            decision['action'] = 'CREATE'
                    
                    if action in ['JOIN', 'CREATE']:
                        reason_text = str(decision.get("reason", ""))
                        reason_intent_raw = str(decision.get("reason_intent", "")).upper().strip()
                        prompt_contract_pass = bool(decision.get("consistency_check_pass", False))
                        prompt_contract_fallback_used = False

                        # Prompt-first 主路径：优先使用模型返回的结构化一致性字段
                        reason_intent = reason_intent_raw if reason_intent_raw in ['JOIN', 'CREATE'] else ""

                        # 字段缺失/非法视为 prompt contract 失败，不再做关键词 hardcode 推断
                        if not reason_intent:
                            reason_intent = "UNKNOWN"
                            prompt_contract_fallback_used = True

                        structured_conflict = reason_intent == "UNKNOWN" or action != reason_intent
                        is_conflict = structured_conflict or (not prompt_contract_pass)

                        decision["reason_intent"] = reason_intent
                        decision["consistency_check_pass"] = prompt_contract_pass
                        decision["prompt_contract_pass"] = prompt_contract_pass
                        decision["prompt_contract_fallback_used"] = prompt_contract_fallback_used
                        # Backward compatibility for old consumers
                        decision["fallback_used"] = prompt_contract_fallback_used
                        decision["decision_conflict"] = False
                        decision["conflict_resolved_by"] = ""
                        decision["retry_attempt"] = 1 if conflict_retry_used else 0

                        if is_conflict:
                            logger.warning(
                                "[DecisionConsistency] prompt contract conflict: action=%s reason_intent=%s pass=%s prompt_contract_fallback_used=%s reason=%s",
                                action,
                                reason_intent,
                                prompt_contract_pass,
                                prompt_contract_fallback_used,
                                reason_text[:300],
                            )
                            if not conflict_retry_used:
                                conflict_retry_used = True
                                logger.info("[DecisionConsistency] 触发一次重试以满足 prompt contract")
                                continue
                            logger.warning("[DecisionConsistency] 重试后仍不满足 prompt contract，降级为 CREATE")
                            action = "CREATE"
                            decision["action"] = "CREATE"
                            decision["target_group_index"] = -1
                            decision["reason_intent"] = "CREATE"
                            decision["consistency_check_pass"] = False
                            decision["prompt_contract_pass"] = False
                            decision["decision_conflict"] = True
                            decision["conflict_resolved_by"] = "prompt_contract_fallback"
                            decision["retry_attempt"] = 1

                        if action in ['CREATE']:
                            fallback_name = f"Group{uuid.uuid4().hex[:8]}"
                            decision['new_group_name'] = self._normalize_group_name(
                                decision.get('new_group_name', ''),
                                fallback=fallback_name,
                            )
                        else:
                            decision['new_group_name'] = ""
                        logger.info(f"LLM 决策成功: {action} (置信度: {decision.get('confidence', 'N/A')})")
                        return decision
                    else:
                        raise ValueError(f"无效的 action: {action}")
                else:
                    raise ValueError("LLM 返回结果格式异常")
                    
            except Exception as e:
                last_exception = e
                error_msg = str(e)
                error_type = type(e).__name__
                
                retryable_errors = (
                    "timeout", "connection", "network", "rate limit", 
                    "429", "500", "502", "503", "504", "service unavailable"
                )
                is_retryable = any(keyword.lower() in error_msg.lower() for keyword in retryable_errors)
                
                if attempt < max_retries:
                    if is_retryable:
                        logger.warning(f"LLM 调用失败（{error_type}）: {error_msg}，将进行重试")
                    else:
                        logger.warning(f"LLM 调用失败（{error_type}）: {error_msg}，尝试重试")
                else:
                    logger.error(f"LLM 调用失败，已重试 {max_retries} 次，放弃重试。最后错误: {error_type}: {error_msg}")
        
        if last_exception:
            raise last_exception
        else:
            raise RuntimeError("LLM 调用失败，未知错误")

    def _safe_score(self, value: Any) -> float:
        try:
            num = float(value)
            if not isfinite(num):
                return 0.0
            return max(0.0, min(1.0, num))
        except Exception:
            return 0.0

    @staticmethod
    def _is_leaf_candidate(candidate: Dict[str, Any]) -> bool:
        """A leaf candidate has no child groups."""
        try:
            has_children = bool(candidate.get("has_children"))
            children_count = int(candidate.get("children_count", 0))
            return (not has_children) and children_count <= 0
        except Exception:
            return False

    CONFIDENCE_GAP_THRESHOLD = 0.05
    JOIN_MIN_VECTOR_SCORE = 0.62
    # Short semantic_domain text yields weaker embeddings; strict 0.62 can veto a unanimous
    # high-confidence LLM JOIN + prompt_contract_pass. Allow JOIN when the model's target
    # still clears a relaxed floor (vector is corroborating, not sole authority).
    JOIN_MIN_VECTOR_SCORE_LLM_CONFIDENT = 0.50
    LLM_JOIN_CONFIDENCE_FOR_RELAXED_VECTOR = 0.85
    MERGE_COVERAGE_THRESHOLD = 0.55

    _FK_RE = re.compile(r'\b[a-z_]+_id\b')
    _CAMEL_ENTITY_RE = re.compile(r'\b[A-Z][a-z]+(?:[A-Z][a-z]+)*\b')
    _SNAKE_ENTITY_RE = re.compile(r'\b[a-z]+_[a-z_]+\b')
    ENTITY_JACCARD_THRESHOLD = 0.15

    def _parse_agent_card(self, agent_card: Any) -> Dict[str, Any]:
        """Parse agent_card from string/dict into a dict, best-effort."""
        if not agent_card:
            return {}
        if isinstance(agent_card, dict):
            return deepcopy(agent_card)
        if isinstance(agent_card, str):
            try:
                parsed = json.loads(agent_card)
                return parsed if isinstance(parsed, dict) else {}
            except Exception:
                return {}
        return {}

    def _merge_unique_strings(self, old_items: List[Any], new_items: List[Any], max_size: int) -> List[Any]:
        """Merge two lists with stable order and string-based uniqueness."""
        out: List[Any] = []
        seen = set()
        for item in (old_items or []) + (new_items or []):
            key = str(item).strip()
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(item)
            if len(out) >= max_size:
                break
        return out

    def _build_preservation_contract(self, card: Dict[str, Any]) -> Dict[str, Any]:
        """Build a deterministic preservation contract from old agent card."""
        if not isinstance(card, dict):
            return {
                "required_name": "",
                "required_description": False,
                "required_skill_ids": [],
            }

        required_name = str(card.get("name", "")).strip()
        required_description = bool(str(card.get("description", "")).strip())
        required_skill_ids: List[str] = []
        for sk in card.get("skills", []) or []:
            if not isinstance(sk, dict):
                continue
            sid = str(sk.get("id", "")).strip()
            if sid and sid not in required_skill_ids:
                required_skill_ids.append(sid)
        return {
            "required_name": required_name,
            "required_description": required_description,
            "required_skill_ids": required_skill_ids,
        }

    def _validate_preservation_contract(
        self,
        contract: Dict[str, Any],
        merged_card: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Validate merged card against preservation contract (prompt-first, structured)."""
        merged = merged_card if isinstance(merged_card, dict) else {}
        merged_name = str(merged.get("name", "")).strip()
        merged_description = str(merged.get("description", "")).strip()
        merged_skills = merged.get("skills", [])
        merged_skill_ids = set()
        if isinstance(merged_skills, list):
            for sk in merged_skills:
                if not isinstance(sk, dict):
                    continue
                sid = str(sk.get("id", "")).strip()
                if sid:
                    merged_skill_ids.add(sid)

        required_name = str(contract.get("required_name", "")).strip()
        required_description = bool(contract.get("required_description", False))
        required_skill_ids = {
            str(x).strip() for x in (contract.get("required_skill_ids", []) or []) if str(x).strip()
        }

        name_preserved = (not required_name) or (merged_name == required_name)
        description_preserved = (not required_description) or bool(merged_description)
        missing_skill_ids = sorted(list(required_skill_ids - merged_skill_ids))
        required_skill_count = len(required_skill_ids)
        retained_skill_count = required_skill_count - len(missing_skill_ids)
        skill_retention_ratio = (
            retained_skill_count / max(1, required_skill_count) if required_skill_count else 1.0
        )

        missing_requirements: List[str] = []
        if not name_preserved:
            missing_requirements.append("required_name")
        if not description_preserved:
            missing_requirements.append("required_description")
        if missing_skill_ids:
            missing_requirements.extend([f"skill_id:{sid}" for sid in missing_skill_ids[:30]])

        passed = name_preserved and description_preserved and not missing_skill_ids
        return {
            "pass": passed,
            "coverage_score": round(skill_retention_ratio, 4),
            "missing_requirements": missing_requirements,
            "required_skill_count": required_skill_count,
            "merged_skill_count": len(merged_skill_ids),
            # Backward-compatible keys:
            "missing_tokens": missing_requirements,
            "old_token_count": required_skill_count,
            "new_token_count": len(merged_skill_ids),
        }

    def safe_merge_agent_card(self, old_card: Dict[str, Any], candidate_card: Dict[str, Any]) -> Dict[str, Any]:
        """Safe merge that preserves old semantics and incrementally adds new info."""
        old = deepcopy(old_card or {})
        cand = deepcopy(candidate_card or {})
        if not old:
            return cand
        if not cand:
            return old

        merged = deepcopy(old)
        merged["name"] = old.get("name") or cand.get("name", "")

        old_desc = str(old.get("description", "")).strip()
        cand_desc = str(cand.get("description", "")).strip()
        if old_desc and cand_desc and cand_desc not in old_desc:
            merged["description"] = f"{old_desc}\n\n【增量语义补充】\n{cand_desc[:4000]}"
        else:
            merged["description"] = old_desc or cand_desc

        old_skills = old.get("skills", []) or []
        cand_skills = cand.get("skills", []) or []
        skill_map: Dict[str, Dict[str, Any]] = {}
        merged_skills: List[Dict[str, Any]] = []

        for sk in old_skills:
            if not isinstance(sk, dict):
                continue
            sid = str(sk.get("id", "")).strip()
            if sid:
                skill_map[sid] = deepcopy(sk)
            merged_skills.append(deepcopy(sk))

        for sk in cand_skills:
            if not isinstance(sk, dict):
                continue
            sid = str(sk.get("id", "")).strip()
            if not sid:
                continue
            if sid in skill_map:
                base = skill_map[sid]
                base["tags"] = self._merge_unique_strings(base.get("tags", []), sk.get("tags", []), max_size=50)
                base["examples"] = self._merge_unique_strings(base.get("examples", []), sk.get("examples", []), max_size=20)
                cdesc = str(sk.get("description", "")).strip()
                bdesc = str(base.get("description", "")).strip()
                if cdesc and cdesc not in bdesc:
                    base["description"] = f"{bdesc}\n增量补充：{cdesc}" if bdesc else cdesc
            else:
                merged_skills.append(deepcopy(sk))
                skill_map[sid] = merged_skills[-1]

        merged["skills"] = merged_skills
        return merged

    def merge_consolidated_agent_card(
        self, old_card: Dict[str, Any], candidate_card: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Apply LLM consolidation output without stacking duplicate prose onto the old card.

        consolidate_semantic_domain(s)_into_semantic_group already passes the stored
        semantic_group_agent_card into the model; the returned candidate is a full
        rewrite. safe_merge_agent_card would append under 【增量语义补充】, duplicating
        the same子领域 blocks (e.g. 商品/订单/用户各写两遍).
        """
        old = deepcopy(old_card or {})
        cand = deepcopy(candidate_card or {})
        if not old:
            return cand
        if not cand:
            return old

        merged = deepcopy(cand)
        merged["name"] = str(old.get("name", "")).strip() or str(
            cand.get("name", "")
        ).strip()

        cand_desc = str(cand.get("description", "")).strip()
        old_desc = str(old.get("description", "")).strip()
        merged["description"] = cand_desc or old_desc

        cand_skills: List[Dict[str, Any]] = []
        for sk in merged.get("skills", []) or []:
            if isinstance(sk, dict):
                cand_skills.append(deepcopy(sk))
        seen_ids = {
            str(s.get("id", "")).strip()
            for s in cand_skills
            if str(s.get("id", "")).strip()
        }
        for sk in old.get("skills", []) or []:
            if not isinstance(sk, dict):
                continue
            sid = str(sk.get("id", "")).strip()
            if sid and sid not in seen_ids:
                cand_skills.append(deepcopy(sk))
                seen_ids.add(sid)
        merged["skills"] = cand_skills
        return merged

    def validate_semantic_coverage(
        self,
        old_card: Dict[str, Any],
        merged_card: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Validate merged card covers old core semantics via structured contract."""
        contract = self._build_preservation_contract(old_card)
        return self._validate_preservation_contract(contract, merged_card)

    @staticmethod
    def _extract_entities(text: str) -> set:
        camel = set(SemanticGrouper._CAMEL_ENTITY_RE.findall(text))
        snake = set(SemanticGrouper._SNAKE_ENTITY_RE.findall(text.lower()))
        return camel | snake

    def _has_strong_join_signal(self, new_domain: Dict[str, Any], candidate: Dict[str, Any]) -> bool:
        text = str(new_domain.get("semantic_domain", ""))
        candidate_text = (
            f"{candidate.get('group_name', '')} "
            f"{candidate.get('reason', '')} "
            f"{candidate.get('description', '')}"
        )
        has_fk = bool(self._FK_RE.search(text.lower()))
        ent_new = self._extract_entities(text)
        ent_cand = self._extract_entities(candidate_text)
        if not ent_new or not ent_cand:
            return has_fk
        jaccard = len(ent_new & ent_cand) / len(ent_new | ent_cand)
        return has_fk and jaccard > self.ENTITY_JACCARD_THRESHOLD

    def _arbitrate_incremental_decision(
        self,
        new_domain: Dict[str, Any],
        candidate_groups: List[Dict[str, Any]],
        llm_decision: Dict[str, Any],
    ) -> Dict[str, Any]:
        llm_action = str(llm_decision.get("action", "CREATE")).upper()
        llm_conf = self._safe_score(llm_decision.get("confidence", 0.5))
        llm_idx = llm_decision.get("target_group_index", -1)
        decision_conflict = bool(llm_decision.get("decision_conflict", False))
        prompt_contract_pass = bool(llm_decision.get("prompt_contract_pass", False))
        prompt_contract_fallback_used = bool(
            llm_decision.get("prompt_contract_fallback_used", llm_decision.get("fallback_used", False))
        )

        best_idx = -1
        best_score = -1.0
        for idx, c in enumerate(candidate_groups):
            s = self._safe_score(c.get("score"))
            if s > best_score:
                best_score = s
                best_idx = idx
        if best_score < 0:
            best_score = 0.0

        # JOIN 只能发生在叶子组（无 children）上
        leaf_indices = [i for i, c in enumerate(candidate_groups) if self._is_leaf_candidate(c)]
        best_leaf_idx = -1
        best_leaf_score = -1.0
        for i in leaf_indices:
            s = self._safe_score(candidate_groups[i].get("score"))
            if s > best_leaf_score:
                best_leaf_score = s
                best_leaf_idx = i
        if best_leaf_score < 0:
            best_leaf_score = 0.0

        strong_join = False
        if 0 <= llm_idx < len(candidate_groups):
            strong_join = self._has_strong_join_signal(new_domain, candidate_groups[llm_idx])
        elif 0 <= best_leaf_idx < len(candidate_groups):
            strong_join = self._has_strong_join_signal(new_domain, candidate_groups[best_leaf_idx])

        # JOIN 的分数仅基于叶子候选；没有叶子候选时 JOIN 直接不可用
        join_score = best_leaf_score if best_leaf_idx >= 0 else 0.0
        if llm_action == "JOIN" and not decision_conflict:
            join_score += 0.12 * llm_conf
        if strong_join:
            join_score += 0.25
        if best_leaf_idx < 0:
            join_score = 0.0

        join_eligible_strict = best_leaf_idx >= 0 and (
            best_leaf_score >= self.JOIN_MIN_VECTOR_SCORE or strong_join
        )
        llm_target_score = (
            self._safe_score(candidate_groups[llm_idx].get("score"))
            if 0 <= llm_idx < len(candidate_groups)
            else 0.0
        )
        llm_relaxed_join = (
            not join_eligible_strict
            and best_leaf_idx >= 0
            and llm_action == "JOIN"
            and not decision_conflict
            and prompt_contract_pass
            and llm_conf >= self.LLM_JOIN_CONFIDENCE_FOR_RELAXED_VECTOR
            and 0 <= llm_idx < len(candidate_groups)
            and self._is_leaf_candidate(candidate_groups[llm_idx])
            and llm_target_score >= self.JOIN_MIN_VECTOR_SCORE_LLM_CONFIDENT
        )
        join_eligible = join_eligible_strict or llm_relaxed_join
        if llm_relaxed_join:
            logger.info(
                "[IncrementalArbitration] llm_confident_JOIN: relax vector floor | "
                "llm_idx=%s llm_target_score=%.4f strict_min=%.2f relaxed_min=%.2f llm_conf=%.4f",
                llm_idx,
                llm_target_score,
                self.JOIN_MIN_VECTOR_SCORE,
                self.JOIN_MIN_VECTOR_SCORE_LLM_CONFIDENT,
                llm_conf,
            )
        if not join_eligible:
            join_score = 0.0
        join_score = max(0.0, min(1.0, join_score))

        create_score = 0.40 + (1.0 - best_score) * 0.50
        if llm_action == "CREATE":
            create_score += 0.12 * llm_conf
        if not candidate_groups:
            create_score = 1.0
        create_score = max(0.0, min(1.0, create_score))

        score_breakdown = {
            "join_score": round(join_score, 4),
            "create_score": round(create_score, 4),
            "best_vector_score": round(best_score, 4),
            "llm_confidence": round(llm_conf, 4),
            "strong_join_signal": strong_join,
            "decision_conflict": decision_conflict,
            "join_eligible": join_eligible,
            "join_eligible_strict": join_eligible_strict,
            "llm_relaxed_join": llm_relaxed_join,
            "llm_target_vector_score": round(llm_target_score, 4),
            "prompt_contract_pass": prompt_contract_pass,
            "prompt_contract_fallback_used": prompt_contract_fallback_used,
            "fallback_used": prompt_contract_fallback_used,
        }

        if (
            llm_action == "JOIN"
            and strong_join
            and 0 <= llm_idx < len(candidate_groups)
            and self._is_leaf_candidate(candidate_groups[llm_idx])
        ):
            return {
                "action": "JOIN",
                "target_group_index": llm_idx,
                "new_group_name": "",
                "reason": llm_decision.get("reason", "规则判定：强外键/实体关联，优先 JOIN"),
                "confidence": llm_conf,
                "llm_action": llm_action,
                "reason_intent": llm_decision.get("reason_intent", ""),
                "decision_conflict": decision_conflict,
                "conflict_resolved_by": llm_decision.get("conflict_resolved_by", ""),
                "prompt_contract_pass": prompt_contract_pass,
                "prompt_contract_fallback_used": prompt_contract_fallback_used,
                "fallback_used": prompt_contract_fallback_used,
                "arbitration_reason": "strong_join_signal_override",
                "score_breakdown": score_breakdown,
            }

        ranking = sorted(
            [("JOIN", join_score), ("CREATE", create_score)],
            key=lambda x: x[1],
            reverse=True,
        )
        final_action = ranking[0][0]
        gap = ranking[0][1] - ranking[1][1]

        # Near-tie fallback would undo llm_relaxed_join (JOIN barely edges CREATE by ~0.05).
        if (
            gap < self.CONFIDENCE_GAP_THRESHOLD
            and final_action != "CREATE"
            and not llm_relaxed_join
        ):
            final_action = "CREATE"
            score_breakdown["confidence_gap_fallback"] = True

        if final_action == "JOIN":
            if (
                llm_action == "JOIN"
                and 0 <= llm_idx < len(candidate_groups)
                and self._is_leaf_candidate(candidate_groups[llm_idx])
            ):
                final_idx = llm_idx
            else:
                final_idx = best_leaf_idx
            if not join_eligible or not (0 <= final_idx < len(candidate_groups)):
                final_action = "CREATE"
                final_idx = -1
            return {
                "action": final_action,
                "target_group_index": final_idx,
                "new_group_name": "",
                "reason": llm_decision.get("reason", "混合仲裁：判定 JOIN"),
                "confidence": llm_conf,
                "llm_action": llm_action,
                "reason_intent": llm_decision.get("reason_intent", ""),
                "decision_conflict": decision_conflict,
                "conflict_resolved_by": llm_decision.get("conflict_resolved_by", ""),
                "prompt_contract_pass": prompt_contract_pass,
                "prompt_contract_fallback_used": prompt_contract_fallback_used,
                "fallback_used": prompt_contract_fallback_used,
                "arbitration_reason": "score_based_join",
                "score_breakdown": score_breakdown,
            }

        return {
            "action": "CREATE",
            "target_group_index": -1,
            "new_group_name": llm_decision.get("new_group_name", ""),
            "reason": llm_decision.get("reason", "混合仲裁：判定 CREATE"),
            "confidence": llm_conf,
            "llm_action": llm_action,
            "reason_intent": llm_decision.get("reason_intent", ""),
            "decision_conflict": decision_conflict,
            "conflict_resolved_by": llm_decision.get("conflict_resolved_by", ""),
            "prompt_contract_pass": prompt_contract_pass,
            "prompt_contract_fallback_used": prompt_contract_fallback_used,
            "fallback_used": prompt_contract_fallback_used,
            "arbitration_reason": "score_based_create",
            "score_breakdown": score_breakdown,
        }

    def _sync_semantic_group_if_sd_already_member(
        self,
        new_domain: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """
        若语义域已在 dd_group_relation 中（含此前 CREATE 产生的单成员组），则：
        - 内容指纹未变：直接返回成功，跳过后续 LLM / 误 CREATE；
        - 已变：对现有 SG 执行与 JOIN 相同的合并与向量更新，并回写 relation 指纹。
        若无组关系则返回 None，由 incremental 主流程继续。
        """
        new_domain_id = new_domain.get("semantic_domain_id")
        if not new_domain_id or not self.semantic_group_client:
            return None
        try:
            relations_response = self.semantic_group_client.get_relations_by_sd_id(
                new_domain_id
            )
        except Exception as e:
            logger.warning(
                "查询 sd 组关系失败，继续正常分组: %s",
                e,
                exc_info=True,
            )
            return None

        relations_data = relations_response.get("data", [])
        if not isinstance(relations_data, list) or not relations_data:
            return None

        rel = relations_data[0]
        target_group_id = rel.get("group_id")
        if not target_group_id:
            return None

        if len(relations_data) > 1:
            group_ids = {
                r.get("group_id")
                for r in relations_data
                if r.get("group_id")
            }
            if len(group_ids) > 1:
                logger.warning(
                    "语义域 %s 对应多条不同 group 关系 %s，按首条刷新",
                    new_domain_id,
                    group_ids,
                )

        fp_new = self._compute_semantic_domain_content_fingerprint(new_domain)
        fp_old = self._read_content_fingerprint_from_relation_reason(
            rel.get("association_reason")
        )

        def _member_sync_response(
            group_data: Dict[str, Any],
            member_dd_ids: List[str],
            reason: str,
            message: str,
            confidence: float,
        ) -> Dict[str, Any]:
            return {
                "status": "success",
                "action": "JOIN",
                "group_id": target_group_id,
                "group_name": group_data.get("group_name", ""),
                "reason": reason,
                "member_dd_ids": member_dd_ids,
                "confidence": confidence,
                "llm_action": "",
                "reason_intent": "",
                "prompt_contract_pass": False,
                "prompt_contract_fallback_used": False,
                "fallback_used": False,
                "decision_conflict": False,
                "conflict_resolved_by": "",
                "arbitration_reason": "",
                "score_breakdown": {},
                "message": message,
            }

        if fp_old == fp_new:
            group_response = self.semantic_group_client.get_semantic_group_by_id(
                target_group_id
            )
            group_data = dict(group_response.get("data") or {})
            rel_resp = self.semantic_group_client.get_relations_by_group_id(
                target_group_id
            )
            rdata = rel_resp.get("data", [])
            if not isinstance(rdata, list):
                rdata = []
            member_dd_ids = [x.get("sd_id") for x in rdata if x.get("sd_id")]
            logger.info(
                "语义域 %s 已在组 %s 中且内容指纹未变，跳过重合并",
                new_domain_id,
                target_group_id,
            )
            return _member_sync_response(
                group_data,
                member_dd_ids,
                "语义域已存在于语义组中",
                f"语义域已存在于语义组中: {group_data.get('group_name', '')}",
                1.0,
            )

        logger.warning(
            "语义域 %s 已在组 %s 中（含 CREATE 入组）但内容已变更，重新合并语义组",
            new_domain_id,
            target_group_id,
        )
        group_response_before = self.semantic_group_client.get_semantic_group_by_id(
            target_group_id
        )
        group_data_before = dict(group_response_before.get("data") or {})
        group_updated = self._refresh_semantic_group_after_member_resync(
            target_group_id,
            new_domain,
            group_data_before,
        )
        rid = rel.get("id")
        if group_updated and rid is not None:
            base = (
                self._strip_content_fingerprint_suffix_from_relation_reason(
                    rel.get("association_reason")
                )
                or "语义组随语义域内容同步更新"
            )
            new_ar = self._embed_content_fingerprint_in_association_reason(base, fp_new)
            try:
                self.semantic_group_client.update_dd_group_relation(int(rid), new_ar)
            except Exception as ex:
                logger.warning(
                    "更新 dd_group_relation 指纹失败: %s",
                    ex,
                    exc_info=True,
                )

        group_response = self.semantic_group_client.get_semantic_group_by_id(
            target_group_id
        )
        group_data = dict(group_response.get("data") or {})
        rel_resp = self.semantic_group_client.get_relations_by_group_id(
            target_group_id
        )
        rdata = rel_resp.get("data", [])
        if not isinstance(rdata, list):
            rdata = []
        member_dd_ids = [x.get("sd_id") for x in rdata if x.get("sd_id")]
        redo_reason = (
            "语义域已入组，已按最新内容更新语义组"
            if group_updated
            else "语义域已入组，合并未产生更新"
        )
        return _member_sync_response(
            group_data,
            member_dd_ids,
            redo_reason,
            f"{redo_reason}: {group_data.get('group_name', '')}",
            0.9,
        )

    def incremental_semantic_group_analyse(
        self,
        new_domain: Dict[str, Any],
        max_retries: int = 3,
        retry_delay: float = 1.0
    ) -> Dict[str, Any]:
        """
        增量式语义域分组分析（处理单个语义域）
        
        核心策略：增量式归纳 (Incremental Induction)
        - 若 sd 已有 dd_group_relation（含此前 CREATE 的单成员组）：按内容指纹同步或跳过重合并，避免重复 CREATE
        - 向量初筛：检索与新 DD 最相似的 Top-3 现有 SemanticGroup
        - LLM 判定：决定 JOIN / CREATE
        
        Args:
            new_domain: 新的语义域，包含以下字段：
                      - semantic_domain_id: 语义域ID
                      - semantic_domain: 语义域描述文本
                      - agent_card: agent card
                      - dd_name: 数据描述符名称（可选）
                      - dd_namespace: 数据描述符命名空间（可选）
            max_retries: 最大重试次数
            retry_delay: 重试延迟
            
        Returns:
            处理后的语义组信息，格式：
            {
                "status": "success" | "error",
                "action": "CREATE" | "JOIN",
                "group_id": str,
                "group_name": str,
                "reason": str,
                "member_dd_ids": List[str],
                "confidence": float,
                "message": str
            }
        """
        if not new_domain:
            logger.warning("新的语义域为空")
            return {
                "status": "error",
                "action": "CREATE",
                "message": "新的语义域为空"
            }
        
        new_domain_id = new_domain.get('semantic_domain_id')
        if not new_domain_id:
            logger.warning("语义域缺少 semantic_domain_id")
            return {
                "status": "error",
                "action": "CREATE",
                "message": "语义域缺少 semantic_domain_id"
            }
        
        logger.info(f"开始处理新语义域: {new_domain_id}")

        existing_member_sync = self._sync_semantic_group_if_sd_already_member(
            new_domain
        )
        if existing_member_sync is not None:
            return existing_member_sync

        # 检查语义组总数，如果为 0 则直接创建第一个分组
        if self.semantic_group_client:
            try:
                total_count = self.semantic_group_client.get_semantic_group_count()
                if total_count == 0:
                    logger.info("语义组总数为 0，直接创建第一个分组，无需分组分析")
                    group_id = str(uuid.uuid4())
                    agent_card = new_domain.get('agent_card', '')  # 直接使用原 semantic domain 的 agent_card
                    description = self._extract_description_from_agent_card(agent_card)  # 从 agent_card 中提取 description
                    
                    # 从原 semantic domain 的 agent_card 中提取 name 作为 group_name
                    try:
                        if agent_card:
                            # agent_card 可能是 JSON 字符串，需要解析
                            if isinstance(agent_card, str):
                                try:
                                    agent_card_dict = json.loads(agent_card)
                                    group_name = agent_card_dict.get('name', f"group-{new_domain_id}")
                                except json.JSONDecodeError:
                                    # 如果不是有效的 JSON，使用默认名称
                                    group_name = f"group-{new_domain_id}"
                            elif isinstance(agent_card, dict):
                                group_name = agent_card.get('name', f"group-{new_domain_id}")
                            else:
                                group_name = f"group-{new_domain_id}"
                        else:
                            group_name = f"group-{new_domain_id}"
                        logger.info(f"使用原 semantic domain 的 agent_card.name 作为 group_name: {group_name}")
                    except Exception as e:
                        logger.warning(f"从 agent_card 提取 name 失败: {str(e)}，使用默认组名", exc_info=True)
                        group_name = f"group-{new_domain_id}"
                    group_name = self._normalize_group_name(group_name, fallback=f"group-{new_domain_id}")
                    
                    # 同步创建到 MySQL 和 pgvector
                    success = self._create_semantic_group_to_db(
                        group_id=group_id,
                        group_name=group_name,
                        description=description,
                        agent_card=agent_card,
                        member_domains=[new_domain],
                        association_reason="创建第一个语义组"
                    )
                    
                    if success:
                        return {
                            "status": "success",
                            "action": "CREATE",
                            "group_id": group_id,
                            "group_name": group_name,
                            "reason": "创建第一个语义组",
                            "member_dd_ids": [new_domain_id],
                            "confidence": 1.0,
                            "message": "成功创建第一个语义组"
                        }
                    else:
                        logger.error("创建第一个分组失败")
                        return {
                            "status": "error",
                            "action": "CREATE",
                            "message": "创建第一个分组失败"
                        }
            except Exception as e:
                logger.warning(f"检查语义组总数失败: {str(e)}，继续正常流程")
        
        # 从 MySQL 查询所有现有组（用于后续匹配）
        existing_groups = self._fetch_all_existing_groups()
        
        logger.info(f"当前有 {len(existing_groups)} 个现有组")
        
        # 步骤1：向量初筛
        candidate_groups = self._search_candidate_groups(new_domain, top_k=3)
        
        # 如果向量数据库未检索到候选组，但已有现有组
        if not candidate_groups and existing_groups:
            logger.info("向量数据库未检索到候选组，使用现有组作为候选，也当作没有相关的，直接创建一个新组")
            group_id = str(uuid.uuid4())
            agent_card = new_domain.get('agent_card', '')  # 直接使用原 semantic domain 的 agent_card
            description = self._extract_description_from_agent_card(agent_card)  # 从 agent_card 中提取 description
            
            # 从原 semantic domain 的 agent_card 中提取 name 作为 group_name
            try:
                if agent_card:
                    # agent_card 可能是 JSON 字符串，需要解析
                    if isinstance(agent_card, str):
                        try:
                            agent_card_dict = json.loads(agent_card)
                            group_name = agent_card_dict.get('name', f"group-{new_domain_id}")
                        except json.JSONDecodeError:
                            # 如果不是有效的 JSON，使用默认名称
                            group_name = f"group-{new_domain_id}"
                    elif isinstance(agent_card, dict):
                        group_name = agent_card.get('name', f"group-{new_domain_id}")
                    else:
                        group_name = f"group-{new_domain_id}"
                else:
                    group_name = f"group-{new_domain_id}"
                logger.info(f"使用原 semantic domain 的 agent_card.name 作为 group_name: {group_name}")
            except Exception as e:
                logger.warning(f"从 agent_card 提取 name 失败: {str(e)}，使用默认组名", exc_info=True)
                group_name = f"group-{new_domain_id}"
            group_name = self._normalize_group_name(group_name, fallback=f"group-{new_domain_id}")
            
            # 同步创建到 MySQL 和 pgvector
            success = self._create_semantic_group_to_db(
                group_id=group_id,
                group_name=group_name,
                description=description,
                agent_card=agent_card,
                member_domains=[new_domain],
                association_reason="向量检索未找到相似组，创建新组"
            )
            
            if success:
                return {
                    "status": "success",
                    "action": "CREATE",
                    "group_id": group_id,
                    "group_name": group_name,
                    "reason": "向量检索未找到相似组，创建新组",
                    "member_dd_ids": [new_domain_id],
                    "confidence": 1.0,
                    "message": "向量检索未找到相似组，成功创建新组"
                }
            else:
                logger.error("创建第一个组失败")
                return {
                    "status": "error",
                    "action": "CREATE",
                    "message": "创建第一个组失败"
                }
        
        # 如果完全没有候选组和现有组，直接创建新组
        if not candidate_groups and not existing_groups:
            logger.info("无现有组，创建第一个组")
            group_id = str(uuid.uuid4())
            agent_card = new_domain.get('agent_card', '')  # 直接使用原 semantic domain 的 agent_card
            description = self._extract_description_from_agent_card(agent_card)  # 从 agent_card 中提取 description
            
            # 从原 semantic domain 的 agent_card 中提取 name 作为 group_name
            try:
                if agent_card:
                    # agent_card 可能是 JSON 字符串，需要解析
                    if isinstance(agent_card, str):
                        try:
                            agent_card_dict = json.loads(agent_card)
                            group_name = agent_card_dict.get('name', f"group-{new_domain_id}")
                        except json.JSONDecodeError:
                            # 如果不是有效的 JSON，使用默认名称
                            group_name = f"group-{new_domain_id}"
                    elif isinstance(agent_card, dict):
                        group_name = agent_card.get('name', f"group-{new_domain_id}")
                    else:
                        group_name = f"group-{new_domain_id}"
                else:
                    group_name = f"group-{new_domain_id}"
                logger.info(f"使用原 semantic domain 的 agent_card.name 作为 group_name: {group_name}")
            except Exception as e:
                logger.warning(f"从 agent_card 提取 name 失败: {str(e)}，使用默认组名", exc_info=True)
                group_name = f"group-{new_domain_id}"
            group_name = self._normalize_group_name(group_name, fallback=f"group-{new_domain_id}")

            # 同步创建到 MySQL 和 pgvector
            success = self._create_semantic_group_to_db(
                group_id=group_id,
                group_name=group_name,
                description=description,
                agent_card=agent_card,
                member_domains=[new_domain],
                association_reason="无现有组，创建第一个语义组"
            )
            
            if success:
                return {
                    "status": "success",
                    "action": "CREATE",
                    "group_id": group_id,
                    "group_name": group_name,
                    "reason": "无现有组，创建第一个语义组",
                    "member_dd_ids": [new_domain_id],
                    "confidence": 1.0,
                    "message": "无现有组，成功创建第一个语义组"
                }
            else:
                logger.error("创建第一个组失败")
                return {
                    "status": "error",
                    "action": "CREATE",
                    "message": "创建第一个组失败"
                }
            
        # 步骤2：LLM 判定
        try:
            llm_decision = self._incremental_decision(new_domain, candidate_groups, max_retries, retry_delay)
            decision = self._arbitrate_incremental_decision(new_domain, candidate_groups, llm_decision)
            action = decision.get('action', '').upper()
            logger.info(
                "[IncrementalArbitration] llm_action=%s reason_intent=%s prompt_contract_pass=%s prompt_contract_fallback_used=%s decision_conflict=%s conflict_resolved_by=%s final_action=%s target_group_index=%s reason=%s score_breakdown=%s",
                decision.get("llm_action", ""),
                llm_decision.get("reason_intent", ""),
                llm_decision.get("prompt_contract_pass", False),
                llm_decision.get("prompt_contract_fallback_used", llm_decision.get("fallback_used", False)),
                llm_decision.get("decision_conflict", False),
                llm_decision.get("conflict_resolved_by", ""),
                action,
                decision.get("target_group_index"),
                decision.get("arbitration_reason", ""),
                decision.get("score_breakdown", {}),
            )
            
            if action == 'JOIN':
                # 加入现有组
                candidate_index = decision.get('target_group_index', -1)
                if 0 <= candidate_index < len(candidate_groups):
                    candidate_group = candidate_groups[candidate_index]
                    # 防御性限制：JOIN 目标必须是叶子组
                    if not self._is_leaf_candidate(candidate_group):
                        logger.warning(
                            "JOIN 目标为非叶子组，禁止直接 JOIN。降级为 CREATE: group=%s, group_id=%s",
                            candidate_group.get('group_name', ''),
                            candidate_group.get('group_id', ''),
                        )
                        action = 'CREATE'
                    target_group_id = candidate_group.get('group_id')
                    if action == 'JOIN' and target_group_id:
                        join_reason = decision.get(
                            'reason', '通过语义相似性分析加入组'
                        )
                        # 检查是否已存在（避免重复添加）
                        if new_domain_id not in candidate_group.get('member_dd_ids', []):
                            group_response_before = (
                                self.semantic_group_client.get_semantic_group_by_id(
                                    target_group_id
                                )
                            )
                            group_data_before = dict(
                                group_response_before.get('data') or {}
                            )

                            success = self._add_member_to_group(
                                group_id=target_group_id,
                                new_domain=new_domain,
                                association_reason=join_reason,
                            )

                            if not success:
                                logger.error(
                                    "添加语义域 %s 到组 %s 失败",
                                    new_domain_id,
                                    target_group_id,
                                )
                                action = 'CREATE'
                            else:
                                group_updated = (
                                    self._refresh_semantic_group_after_member_resync(
                                        target_group_id,
                                        new_domain,
                                        group_data_before,
                                    )
                                )
                                fp_hex = self._compute_semantic_domain_content_fingerprint(
                                    new_domain
                                )
                                group_response = (
                                    self.semantic_group_client.get_semantic_group_by_id(
                                        target_group_id
                                    )
                                )
                                group_data = group_response.get('data', {})
                                relations_response = (
                                    self.semantic_group_client.get_relations_by_group_id(
                                        target_group_id
                                    )
                                )
                                relations_data = relations_response.get('data', [])
                                if not isinstance(relations_data, list):
                                    relations_data = []
                                member_dd_ids = [
                                    rel.get('sd_id')
                                    for rel in relations_data
                                    if rel.get('sd_id')
                                ]
                                if group_updated:
                                    rel_row = next(
                                        (
                                            r
                                            for r in relations_data
                                            if r.get('sd_id') == new_domain_id
                                        ),
                                        None,
                                    )
                                    rid = rel_row.get('id') if rel_row else None
                                    if rid is not None:
                                        new_ar = (
                                            self._embed_content_fingerprint_in_association_reason(
                                                join_reason, fp_hex
                                            )
                                        )
                                        try:
                                            self.semantic_group_client.update_dd_group_relation(
                                                int(rid), new_ar
                                            )
                                        except Exception as ex:
                                            logger.warning(
                                                "更新 dd_group_relation 指纹失败: %s",
                                                ex,
                                                exc_info=True,
                                            )

                                logger.info(
                                    "语义域 %s 加入组: %s (group_id: %s)",
                                    new_domain_id,
                                    group_data.get('group_name'),
                                    target_group_id,
                                )

                                return {
                                    "status": "success",
                                    "action": "JOIN",
                                    "group_id": target_group_id,
                                    "group_name": group_data.get('group_name', ''),
                                    "reason": join_reason,
                                    "member_dd_ids": member_dd_ids,
                                    "confidence": decision.get('confidence', 0.9),
                                    "llm_action": decision.get("llm_action", ""),
                                    "reason_intent": decision.get("reason_intent", ""),
                                    "prompt_contract_pass": decision.get(
                                        "prompt_contract_pass", False
                                    ),
                                    "prompt_contract_fallback_used": decision.get(
                                        "prompt_contract_fallback_used", False
                                    ),
                                    "fallback_used": decision.get(
                                        "prompt_contract_fallback_used", False
                                    ),
                                    "decision_conflict": decision.get(
                                        "decision_conflict", False
                                    ),
                                    "conflict_resolved_by": decision.get(
                                        "conflict_resolved_by", ""
                                    ),
                                    "arbitration_reason": decision.get(
                                        "arbitration_reason", ""
                                    ),
                                    "score_breakdown": decision.get(
                                        "score_breakdown", {}
                                    ),
                                    "message": (
                                        f"成功将语义域加入组: "
                                        f"{group_data.get('group_name', '')}"
                                    ),
                                }
                        else:
                            group_response = (
                                self.semantic_group_client.get_semantic_group_by_id(
                                    target_group_id
                                )
                            )
                            group_data = dict(group_response.get('data') or {})
                            relations_response = (
                                self.semantic_group_client.get_relations_by_group_id(
                                    target_group_id
                                )
                            )
                            relations_data = relations_response.get('data', [])
                            if not isinstance(relations_data, list):
                                relations_data = []
                            member_dd_ids = [
                                rel.get('sd_id')
                                for rel in relations_data
                                if rel.get('sd_id')
                            ]
                            my_rel = next(
                                (
                                    r
                                    for r in relations_data
                                    if r.get('sd_id') == new_domain_id
                                ),
                                None,
                            )
                            fp_new = self._compute_semantic_domain_content_fingerprint(new_domain)
                            fp_old = self._read_content_fingerprint_from_relation_reason(
                                (my_rel or {}).get('association_reason')
                            )
                            if fp_old == fp_new:
                                logger.info(
                                    "语义域 %s 已在组 %s 中且内容指纹未变，跳过重合并",
                                    new_domain_id,
                                    target_group_id,
                                )
                                return {
                                    "status": "success",
                                    "action": "JOIN",
                                    "group_id": target_group_id,
                                    "group_name": group_data.get('group_name', ''),
                                    "reason": "语义域已存在于语义组中",
                                    "member_dd_ids": member_dd_ids,
                                    "confidence": 1.0,
                                    "llm_action": decision.get("llm_action", ""),
                                    "reason_intent": decision.get("reason_intent", ""),
                                    "prompt_contract_pass": decision.get(
                                        "prompt_contract_pass", False
                                    ),
                                    "prompt_contract_fallback_used": decision.get(
                                        "prompt_contract_fallback_used", False
                                    ),
                                    "fallback_used": decision.get(
                                        "prompt_contract_fallback_used", False
                                    ),
                                    "decision_conflict": decision.get(
                                        "decision_conflict", False
                                    ),
                                    "conflict_resolved_by": decision.get(
                                        "conflict_resolved_by", ""
                                    ),
                                    "arbitration_reason": decision.get(
                                        "arbitration_reason", ""
                                    ),
                                    "score_breakdown": decision.get(
                                        "score_breakdown", {}
                                    ),
                                    "message": (
                                        f"语义域已存在于语义组中: "
                                        f"{group_data.get('group_name', '')}"
                                    ),
                                }

                            logger.warning(
                                "语义域 %s 已存在于组 %s 中但内容已变更，重新合并语义组",
                                new_domain_id,
                                target_group_id,
                            )
                            group_data_before = dict(group_data)
                            group_updated = (
                                self._refresh_semantic_group_after_member_resync(
                                    target_group_id,
                                    new_domain,
                                    group_data_before,
                                )
                            )
                            if group_updated and my_rel and my_rel.get('id') is not None:
                                base = self._strip_content_fingerprint_suffix_from_relation_reason(
                                    my_rel.get('association_reason')
                                ) or join_reason
                                new_ar = self._embed_content_fingerprint_in_association_reason(
                                    base, fp_new
                                )
                                try:
                                    self.semantic_group_client.update_dd_group_relation(
                                        int(my_rel['id']), new_ar
                                    )
                                except Exception as ex:
                                    logger.warning(
                                        "更新 dd_group_relation 指纹失败: %s",
                                        ex,
                                        exc_info=True,
                                    )

                            group_response = (
                                self.semantic_group_client.get_semantic_group_by_id(
                                    target_group_id
                                )
                            )
                            group_data = group_response.get('data', {})
                            relations_response = (
                                self.semantic_group_client.get_relations_by_group_id(
                                    target_group_id
                                )
                            )
                            relations_data = relations_response.get('data', [])
                            if not isinstance(relations_data, list):
                                relations_data = []
                            member_dd_ids = [
                                rel.get('sd_id')
                                for rel in relations_data
                                if rel.get('sd_id')
                            ]
                            redo_reason = (
                                "语义域已存在于组中，已按最新内容更新语义组"
                                if group_updated
                                else "语义域已存在于组中，合并未产生更新"
                            )
                            return {
                                "status": "success",
                                "action": "JOIN",
                                "group_id": target_group_id,
                                "group_name": group_data.get('group_name', ''),
                                "reason": redo_reason,
                                "member_dd_ids": member_dd_ids,
                                "confidence": decision.get('confidence', 0.9),
                                "llm_action": decision.get("llm_action", ""),
                                "reason_intent": decision.get("reason_intent", ""),
                                "prompt_contract_pass": decision.get(
                                    "prompt_contract_pass", False
                                ),
                                "prompt_contract_fallback_used": decision.get(
                                    "prompt_contract_fallback_used", False
                                ),
                                "fallback_used": decision.get(
                                    "prompt_contract_fallback_used", False
                                ),
                                "decision_conflict": decision.get(
                                    "decision_conflict", False
                                ),
                                "conflict_resolved_by": decision.get(
                                    "conflict_resolved_by", ""
                                ),
                                "arbitration_reason": decision.get(
                                    "arbitration_reason", ""
                                ),
                                "score_breakdown": decision.get(
                                    "score_breakdown", {}
                                ),
                                "message": (
                                    f"{redo_reason}: "
                                    f"{group_data.get('group_name', '')}"
                                ),
                            }
                    else:
                        logger.warning(f"候选组缺少 group_id，创建新组")
                        action = 'CREATE'
                else:
                    logger.warning(f"候选组索引 {candidate_index} 无效（候选组数量: {len(candidate_groups)}），创建新组")
                    action = 'CREATE'

            if action == 'CREATE':
                # 创建新组
                # 使用LLM决策的reason作为association_reason，如果没有则使用默认值
                association_reason = decision.get('reason', '通过语义分析创建新组')
                group_id = str(uuid.uuid4())
                agent_card = new_domain.get('agent_card', '')  # CREATE 操作直接使用原 semantic domain 的 agent_card
                description = self._extract_description_from_agent_card(agent_card)  # 从 agent_card 中提取 description
                
                # CREATE 操作：直接使用原 semantic domain 的 agent_card 的 name 作为 group_name
                try:
                    if agent_card:
                        # agent_card 可能是 JSON 字符串，需要解析
                        if isinstance(agent_card, str):
                            try:
                                agent_card_dict = json.loads(agent_card)
                                new_group_name = agent_card_dict.get('name', decision.get('new_group_name', f"组-{new_domain_id}"))
                            except json.JSONDecodeError:
                                # 如果不是有效的 JSON，使用 LLM 决策的组名
                                new_group_name = decision.get('new_group_name', f"组-{new_domain_id}")
                        elif isinstance(agent_card, dict):
                            new_group_name = agent_card.get('name', decision.get('new_group_name', f"组-{new_domain_id}"))
                        else:
                            new_group_name = decision.get('new_group_name', f"组-{new_domain_id}")
                    else:
                        # 如果没有 agent_card，使用 LLM 决策的组名
                        new_group_name = decision.get('new_group_name', f"组-{new_domain_id}")
                    logger.info(f"使用原 semantic domain 的 agent_card.name 作为 group_name: {new_group_name}")
                except Exception as e:
                    logger.warning(f"从 agent_card 提取 name 失败: {str(e)}，使用 LLM 决策的组名", exc_info=True)
                    # 如果提取失败，使用 LLM 决策的组名
                    new_group_name = decision.get('new_group_name', f"组-{new_domain_id}")
                new_group_name = self._normalize_group_name(new_group_name, fallback=f"group-{new_domain_id}")
                
                # 同步创建到 MySQL 和 pgvector
                success = self._create_semantic_group_to_db(
                    group_id=group_id,
                    group_name=new_group_name,
                    description=description,
                    agent_card=agent_card,
                    member_domains=[new_domain],
                    association_reason=association_reason
                )
                
                if success:
                    logger.info(f"创建新组: {new_group_name} (group_id: {group_id})")
                    return {
                        "status": "success",
                        "action": "CREATE",
                        "group_id": group_id,
                        "group_name": new_group_name,
                        "reason": association_reason,
                        "member_dd_ids": [new_domain_id],
                        "confidence": decision.get('confidence', 0.9),
                        "llm_action": decision.get("llm_action", ""),
                        "reason_intent": decision.get("reason_intent", ""),
                        "prompt_contract_pass": decision.get("prompt_contract_pass", False),
                        "prompt_contract_fallback_used": decision.get("prompt_contract_fallback_used", False),
                        "fallback_used": decision.get("prompt_contract_fallback_used", False),
                        "decision_conflict": decision.get("decision_conflict", False),
                        "conflict_resolved_by": decision.get("conflict_resolved_by", ""),
                        "arbitration_reason": decision.get("arbitration_reason", ""),
                        "score_breakdown": decision.get("score_breakdown", {}),
                        "message": f"成功创建新组: {new_group_name}"
                    }
                else:
                    logger.error(f"创建新组失败: {new_group_name}")
                    return {
                        "status": "error",
                        "action": "CREATE",
                        "message": f"创建新组失败: {new_group_name}"
                    }
                    
        except Exception as e:
            logger.error(f"处理语义域 {new_domain_id} 时出错: {str(e)}", exc_info=True)
            # 出错时尝试生成 agent_card，如果失败则使用默认名称
            group_id = str(uuid.uuid4())
            error_description = "处理出错，默认创建新组"
            
            try:
                logger.info(f"开始为出错时的组生成 agent_card（基于描述）")
                agent_card_result = self.agent_card(error_description)
                agent_card = json.dumps(agent_card_result, ensure_ascii=False) if isinstance(agent_card_result, dict) else str(agent_card_result)
                # 从 agent_card 中提取 name 作为 group_name
                if isinstance(agent_card_result, dict):
                    group_name = agent_card_result.get('name', f"组-{new_domain_id}")
                else:
                    try:
                        agent_card_dict = json.loads(agent_card) if isinstance(agent_card, str) else {}
                        group_name = agent_card_dict.get('name', f"组-{new_domain_id}")
                    except:
                        group_name = f"组-{new_domain_id}"
                # 从生成的 agent_card 中提取 description
                description = self._extract_description_from_agent_card(agent_card_result)
                logger.info(f"已生成 agent_card，group_name 使用 agent_card.name: {group_name}")
            except Exception as llm_error:
                logger.warning(f"出错时生成 agent_card 失败: {str(llm_error)}，使用默认组名", exc_info=True)
                group_name = f"组-{new_domain_id}"
                agent_card = new_domain.get('agent_card', '')
                # 从原 semantic domain 的 agent_card 中提取 description
                description = self._extract_description_from_agent_card(agent_card)
            group_name = self._normalize_group_name(group_name, fallback=f"group-{new_domain_id}")
            
            # 同步创建到 MySQL 和 pgvector
            success = self._create_semantic_group_to_db(
                group_id=group_id,
                group_name=group_name,
                description=description,
                agent_card=agent_card,
                member_domains=[new_domain],
                association_reason="处理出错，默认创建新组"
            )
            
            if success:
                return {
                    "status": "success",
                    "action": "CREATE",
                    "group_id": group_id,
                    "group_name": group_name,
                    "reason": "处理出错，默认创建新组",
                    "member_dd_ids": [new_domain_id],
                    "confidence": 0.5,
                    "message": "处理出错，默认创建新组成功"
                }
            else:
                return {
                    "status": "error",
                    "action": "CREATE",
                    "message": "处理出错，默认创建新组失败"
                }

    def _build_semantic_group_text(
        self,
        group_name: str,
        description: str,
        member_domains: List[Dict[str, Any]]
    ) -> str:
        """
        构建语义组的文本内容，用于向量化
        
        只使用组的 description（来自 agent_card 的 description），不列出成员域的描述，避免重复。
        因为组的 description 已经是合并了所有成员域的描述，所以不需要再列出每个成员域的描述。
        
        Args:
            group_name: 组名称
            description: 组描述（来自 agent_card 的 description，已经合并了所有成员域的信息）
            member_domains: 组成员语义域列表（如包含 semantic_domain_id，会附加到文本中）
            
        Returns:
            构建的文本内容
        """
        text_parts = [f"语义组名称: {group_name}"]
        
        if description:
            text_parts.append(f"描述: {description}")
        
        # 不再列出成员域描述；仅在提供 semantic_domain_id 时附加成员 ID 列表，便于检索定位。
        member_ids: List[str] = []
        for domain in member_domains or []:
            if not isinstance(domain, dict):
                continue
            sd_id = domain.get("semantic_domain_id")
            if sd_id is None:
                continue
            sd_id_str = str(sd_id).strip()
            if sd_id_str:
                member_ids.append(sd_id_str)
        if member_ids:
            deterministic_ids = sorted(set(member_ids))
            text_parts.append(f"成员语义域ID: {', '.join(deterministic_ids)}")
        
        return "\n".join(text_parts)

    def _create_semantic_group_to_db(
        self,
        group_id: str,
        group_name: str,
        description: str,
        agent_card: str,
        member_domains: List[Dict[str, Any]],
        association_reason: Optional[str] = None
    ) -> bool:
        """
        创建语义组到 MySQL 和 pgvector
        
        Args:
            group_id: 组ID
            group_name: 组名称
            description: 组描述
            member_domains: 组成员语义域列表
            association_reason: 关联原因（用于创建关系）
            
        Returns:
            是否创建成功
        """
        try:
            normalized_group_name = self._normalize_group_name(group_name, fallback=f"group-{group_id}")
            # 1. 创建到 MySQL
            if self.semantic_group_client:
                semantic_group_data = SemanticGroupData(
                    id=group_id,
                    group_name=normalized_group_name,
                    description=description,
                    agent_card=agent_card,
                    version="1",
                )
                self.semantic_group_client.create_semantic_group(
                    semantic_group_data
                )
                logger.info(f"已创建语义组到 MySQL: {normalized_group_name} (group_id: {group_id})")
                
                # 创建关系
                for domain in member_domains:
                    sd_id = domain.get('semantic_domain_id')
                    if sd_id:
                        relation_data = DDGroupRelationData(
                            sd_id=sd_id,
                            group_id=group_id,
                            association_reason=association_reason or "作为新组的初始成员加入"
                        )
                        self.semantic_group_client.create_dd_group_relation(
                            relation_data
                        )
            else:
                logger.warning("SemanticGroupClient 未配置，跳过 MySQL 创建")
            
            # 2. 创建到 pgvector
            if self.vector_client:
                # 构建语义组文本
                group_text = self._build_semantic_group_text(normalized_group_name, description, member_domains)
                
                # 构建 metadata（包含 group_id，用于后续搜索时识别）
                metadata = {
                    "group_id": group_id,
                    "group_name": normalized_group_name
                }
                
                document = VectorDocument(
                    page_content=group_text,
                    metadata=metadata
                )
                
                self.vector_client.add_documents(
                    collection_name=self.collection_name,
                    documents=[document]
                )
                logger.info(f"已创建语义组到 pgvector: {normalized_group_name} (group_id: {group_id})")
            else:
                logger.warning("VectorClient 未配置，跳过 pgvector 创建")
            
            return True
            
        except Exception as e:
            logger.error(f"创建语义组到数据库失败: {str(e)}", exc_info=True)
            return False

    def _delete_group_from_pgvector(
        self,
        group_id: str
    ) -> bool:
        """
        从 pgvector 中删除组的向量数据
        
        Args:
            group_id: 组ID
            
        Returns:
            是否删除成功
        """
        if not self.vector_client:
            logger.warning("VectorClient 未配置，跳过 pgvector 删除")
            return False
        
        try:
            # 通过 metadata 中的 group_id 删除对应的向量数据
            self.vector_client.delete_by_metadata_field(
                collection_name=self.collection_name,
                key="group_id",
                value=group_id
            )
            logger.info(f"已从 pgvector 删除组向量数据: group_id={group_id}")
            return True
            
        except Exception as e:
            logger.error(f"从 pgvector 删除组向量数据失败: {str(e)}", exc_info=True)
            return False

    @staticmethod
    def _normalize_agent_card_for_fingerprint(agent_card: Any) -> str:
        """
        将 agent_card 转为可稳定序列化的字符串，供内容指纹哈希使用。
        使用场景：`_compute_semantic_domain_content_fingerprint` 内部；dict 按 key 排序后 dump，
        避免字段顺序不一致导致假阳性「内容变更」。
        """
        if agent_card is None:
            return ""
        if isinstance(agent_card, dict):
            return json.dumps(agent_card, ensure_ascii=False, sort_keys=True)
        return str(agent_card).strip()

    @staticmethod
    def _compute_semantic_domain_content_fingerprint(domain: Dict[str, Any]) -> str:
        """
        计算「语义域正文」SHA256 指纹（hex），仅包含 `semantic_domain` 文本与 `agent_card` 内容，
        不包含 `semantic_domain_id`、`version` 等元数据，用于判断 DD/SD 重同步后业务描述是否真的变化。

        使用场景：`_sync_semantic_group_if_sd_already_member`、JOIN 分支、新成员入组后写回 relation 等，
        与 `dd_group_relation.association_reason` 末尾嵌入的指纹比对以决定跳过合并或触发 SG 刷新。
        """
        payload = {
            "semantic_domain": domain.get("semantic_domain"),
            "agent_card": SemanticGrouper._normalize_agent_card_for_fingerprint(
                domain.get("agent_card")
            ),
        }
        normalized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    @staticmethod
    def _strip_content_fingerprint_suffix_from_relation_reason(
        association_reason: Optional[str],
    ) -> str:
        """
        去掉 `association_reason` 尾部由 `_DAC_SD_CONTENT_FP_MARKER` 引入的机器指纹段，
        得到纯「人类可读」的关联说明文本。

        使用场景：往 relation 写回新指纹前先剥离旧指纹；或与 LLM 给出的 reason 拼接时避免重复叠加。
        """
        if not association_reason:
            return ""
        idx = association_reason.find(_DAC_SD_CONTENT_FP_MARKER)
        if idx >= 0:
            return association_reason[:idx].rstrip()
        return association_reason.rstrip()

    @staticmethod
    def _embed_content_fingerprint_in_association_reason(
        base_reason: str, fingerprint_hex: str
    ) -> str:
        """
        在关联原因字符串末尾附加固定格式的内容指纹行，便于下次 resync 用
        `_read_content_fingerprint_from_relation_reason` 读出比对。

        使用场景：成员 SD 与 SG 完成一次成功合并/直写后，通过 `PUT dd_group_relation` 持久化，
        使「已在组内且内容未变」时可短路跳过重计算。
        """
        clean = SemanticGrouper._strip_content_fingerprint_suffix_from_relation_reason(
            base_reason
        )
        suffix = f"{_DAC_SD_CONTENT_FP_MARKER}{fingerprint_hex}"
        if clean:
            return f"{clean}{suffix}"
        return suffix

    @staticmethod
    def _read_content_fingerprint_from_relation_reason(
        association_reason: Optional[str],
    ) -> Optional[str]:
        """
        从 `dd_group_relation.association_reason` 解析已存储的内容指纹（hex）；
        若无标记则返回 None（表示尚未写入过指纹或旧数据）。

        使用场景：增量分组前置同步、JOIN「已在组内」分支，与
        `_compute_semantic_domain_content_fingerprint(当前 SD)` 比较以决定是否刷新 SG。
        """
        if not association_reason:
            return None
        idx = association_reason.find(_DAC_SD_CONTENT_FP_MARKER)
        if idx < 0:
            return None
        return association_reason[idx + len(_DAC_SD_CONTENT_FP_MARKER) :].strip() or None

    def _normalize_domain_record_for_group_merge(
        self, data: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """
        将 API / 调用方传入的语义域 dict 规整为合并 LLM 所需的固定键集合
        （`semantic_domain`、`agent_card`、`dd_*`、`semantic_domain_id`）。

        使用场景：`_build_ordered_member_snapshots_for_group_merge` 中处理「当前请求里的变更域」
        与 `get_semantic_domain_by_id` 返回的成员快照，保证下游 consolidate 入参形状一致。
        """
        if not data or not isinstance(data, dict):
            return None
        return {
            "semantic_domain_id": data.get("semantic_domain_id"),
            "semantic_domain": data.get("semantic_domain", "") or "",
            "agent_card": data.get("agent_card", ""),
            "dd_name": data.get("dd_name", "") or "",
            "dd_namespace": data.get("dd_namespace", "") or "",
        }

    def _build_ordered_member_snapshots_for_group_merge(
        self, group_id: str, updated_domain: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        为「多成员 SD 更新后重算整组 SG」构造有序成员快照列表：
        第 1 个元素必须是本次请求携带的 `updated_domain`（保证与管线中最新 SD 一致），
        其余元素按 `dd_group_relation` 中的其它 `sd_id` 从语义域服务拉取。

        使用场景：`_refresh_semantic_group_after_member_resync` 中成员数 > 1 时，
        交给 `consolidate_semantic_domains_into_semantic_group` 做联合归纳。
        单成员组时列表长度仅为 1（仅含变更域），由上层决定是否改走直写而非多域 LLM。
        """
        updated = self._normalize_domain_record_for_group_merge(updated_domain)
        if not updated:
            return []
        updated_id = updated.get("semantic_domain_id")
        ordered: List[Dict[str, Any]] = [updated]
        if not self.semantic_group_client:
            return ordered
        try:
            rel_resp = self.semantic_group_client.get_relations_by_group_id(group_id)
        except Exception as e:
            logger.warning(
                "get_relations_by_group_id 失败，仅使用传入域合并: %s", e, exc_info=True
            )
            return ordered
        rels = rel_resp.get("data", [])
        if not isinstance(rels, list):
            rels = []
        peer_ids = sorted(
            {str(r.get("sd_id")) for r in rels if r.get("sd_id")},
            key=lambda x: x,
        )
        for sid_str in peer_ids:
            if updated_id is not None and sid_str == str(updated_id):
                continue
            domain_data: Optional[Dict[str, Any]] = None
            if self.semantic_domain_client:
                try:
                    dr = self.semantic_domain_client.get_semantic_domain_by_id(sid_str)
                    if isinstance(dr, dict):
                        domain_data = dr.get("data") if "data" in dr else dr
                except Exception as e:
                    logger.warning(
                        "拉取组成员语义域 %s 失败（多成员合并输入可能不完整）: %s",
                        sid_str,
                        e,
                        exc_info=True,
                    )
            coerced = self._normalize_domain_record_for_group_merge(domain_data)
            if coerced:
                ordered.append(coerced)
        return ordered

    def _overwrite_semantic_group_from_single_member_sd(
        self,
        target_group_id: str,
        domain: Dict[str, Any],
        group_data_before: Dict[str, Any],
    ) -> bool:
        """
        单成员语义组（`dd_group_relation` 仅一条且即为当前 `domain`）时，将 SG 视为该 SD 的投影：
        直接用本次 SD 的 `agent_card` 覆盖组的 `agent_card`，并派生 `description`、`group_name`，
        同步更新 pgvector；**不调用** consolidate / MergeGuard。

        使用场景：CREATE 得到的单成员组或等价的「组与 SD 一一对应」场景，SD 更新后 SG 应与 SD 一致，
        由 `_refresh_semantic_group_after_member_resync` 在统计成员数为 1 且 sd_id 匹配时调用。
        """
        if not self.semantic_group_client:
            return False
        try:
            raw_card = domain.get("agent_card", "")
            if isinstance(raw_card, dict):
                new_agent_card = json.dumps(raw_card, ensure_ascii=False)
                parsed_for_name = raw_card
            elif raw_card:
                new_agent_card = str(raw_card)
                parsed_for_name = self._parse_agent_card(raw_card)
            else:
                new_agent_card = ""
                parsed_for_name = {}

            new_group_name = group_data_before.get("group_name", "")
            if isinstance(parsed_for_name, dict) and parsed_for_name.get("name"):
                new_group_name = parsed_for_name.get("name", new_group_name)
            new_group_name = self._normalize_group_name(
                new_group_name,
                fallback=group_data_before.get("group_name", "")
                or f"group-{target_group_id}",
            )
            new_description = self._extract_description_from_agent_card(new_agent_card)

            next_version = self._version_for_semantic_group_update(
                group_data_before,
                new_group_name=new_group_name,
                new_description=new_description,
                new_agent_card=new_agent_card,
            )
            updated_group_data = SemanticGroupData(
                id=target_group_id,
                group_name=new_group_name,
                description=new_description,
                agent_card=new_agent_card,
                version=next_version,
            )
            self.semantic_group_client.update_semantic_group(
                group_id=target_group_id,
                semantic_group=updated_group_data,
            )
            logger.info(
                "已用 SD 快照直接更新组 %s（单成员、跳过 LLM） version=%s",
                target_group_id,
                next_version,
            )
            if self.vector_client:
                group_text = self._build_semantic_group_text(
                    group_name=new_group_name,
                    description=new_description,
                    member_domains=[],
                )
                self._delete_group_from_pgvector(target_group_id)
                self.vector_client.add_documents(
                    collection_name=self.collection_name,
                    documents=[
                        VectorDocument(
                            page_content=group_text,
                            metadata={
                                "group_id": target_group_id,
                                "group_name": new_group_name,
                            },
                        )
                    ],
                )
                logger.info(
                    "已更新组 %s 在 pgvector 中的向量（单成员 SD 直写）",
                    target_group_id,
                )
            return True
        except Exception as e:
            logger.error("单成员 SD 直写 SG 失败: %s", e, exc_info=True)
            return False

    def _refresh_semantic_group_after_member_resync(
        self,
        target_group_id: str,
        new_domain: Dict[str, Any],
        group_data_before: Dict[str, Any],
    ) -> bool:
        """
        在「某成员 SD 已关联到现有 SG」且业务上需要把 SG 与最新语义对齐时执行（指纹判定变更后）：
        - **仅 1 个成员且即本次变更 SD**：`_overwrite_semantic_group_from_single_member_sd` 直写；
        - **多成员**：拉全成员快照后单域或多域 consolidate，再经 MergeGuard 合并、写 MySQL、刷新 pgvector。

        使用场景：`_sync_semantic_group_if_sd_already_member`、JOIN 流程中新成员入组或已在组内内容变更、
        以及首入组用 `_embed_content_fingerprint_in_association_reason` 写指纹前的合并成功路径。
        返回 True 表示 SG 行已成功按本方法路径更新（含单成员直写）；合并失败或未产出 consolidate 结果则为 False。
        """
        group_updated = False
        if not self.semantic_group_client:
            logger.warning(
                "SemanticGroupClient 未配置，跳过成员重同步后的语义组刷新",
            )
            return False
        try:
            if "description" not in group_data_before:
                logger.warning(
                    "组 %s 缺少 description 字段，使用默认值", target_group_id
                )
                group_data_before["description"] = group_data_before.get("group_name", "") or ""

            new_domain_id = new_domain.get("semantic_domain_id", "")

            relation_sd_ids: List[str] = []
            try:
                rr = self.semantic_group_client.get_relations_by_group_id(
                    target_group_id
                )
                rd = rr.get("data", [])
                if isinstance(rd, list):
                    relation_sd_ids = [
                        str(r.get("sd_id")) for r in rd if r.get("sd_id")
                    ]
            except Exception as e:
                logger.warning("统计组成员失败: %s", e, exc_info=True)

            if (
                new_domain_id
                and len(relation_sd_ids) == 1
                and relation_sd_ids[0] == str(new_domain_id)
            ):
                logger.info(
                    "组 %s 仅含当前变更 SD，直接用 SD 更新 SG（跳过 consolidate）",
                    target_group_id,
                )
                return self._overwrite_semantic_group_from_single_member_sd(
                    target_group_id, new_domain, group_data_before
                )

            member_snapshots = self._build_ordered_member_snapshots_for_group_merge(
                target_group_id, new_domain
            )
            if not member_snapshots:
                member_snapshots = [new_domain]

            logger.info(
                "合并语义域到组 %s：成员快照数=%s（含本次变更域及其余成员）",
                target_group_id,
                len(member_snapshots),
            )

            if len(member_snapshots) <= 1:
                consolidated_result = self.consolidate_semantic_domain_into_semantic_group(
                    semantic_domain=member_snapshots[0],
                    semantic_group=group_data_before,
                    max_retries=3,
                    retry_delay=1.0,
                )
            elif not self.semantic_domain_client:
                logger.warning(
                    "多成员组需要 SemanticDomainClient 拉取其余成员；回退为仅变更域与组快照合并"
                )
                consolidated_result = self.consolidate_semantic_domain_into_semantic_group(
                    semantic_domain=new_domain,
                    semantic_group=group_data_before,
                    max_retries=3,
                    retry_delay=1.0,
                )
            else:
                consolidated_result = self.consolidate_semantic_domains_into_semantic_group(
                    semantic_domains=member_snapshots,
                    semantic_group=group_data_before,
                    max_retries=3,
                    retry_delay=1.0,
                )

            if consolidated_result:
                try:
                    logger.info("使用合并后的 agent_card 更新组 %s", target_group_id)
                    old_card = self._parse_agent_card(group_data_before.get("agent_card", ""))
                    candidate_card = (
                        consolidated_result
                        if isinstance(consolidated_result, dict)
                        else self._parse_agent_card(consolidated_result)
                    )
                    merged_card = self.merge_consolidated_agent_card(
                        old_card, candidate_card
                    )
                    coverage_check = self.validate_semantic_coverage(old_card, merged_card)
                    logger.info(
                        "[MergeGuard] group_id=%s pass=%s coverage_score=%s missing_requirements=%s",
                        target_group_id,
                        coverage_check.get("pass"),
                        coverage_check.get("coverage_score"),
                        coverage_check.get("missing_requirements", [])[:10],
                    )
                    if not coverage_check.get("pass", False):
                        logger.warning(
                            "[MergeGuard] 拒绝覆盖更新，保留旧 agent_card: group_id=%s",
                            target_group_id,
                        )
                        new_agent_card_result = old_card
                    else:
                        new_agent_card_result = merged_card

                    new_agent_card = (
                        json.dumps(new_agent_card_result, ensure_ascii=False)
                        if isinstance(new_agent_card_result, dict)
                        else str(new_agent_card_result)
                    )

                    if isinstance(new_agent_card_result, dict):
                        new_group_name = group_data_before.get("group_name", "")
                    else:
                        try:
                            agent_card_dict = (
                                json.loads(new_agent_card)
                                if isinstance(new_agent_card, str)
                                else {}
                            )
                            new_group_name = group_data_before.get(
                                "group_name", ""
                            ) or agent_card_dict.get("name", "")
                        except Exception:
                            new_group_name = group_data_before.get("group_name", "")

                    logger.info(
                        "[MergeGuard] 使用安全合并结果更新组: group_id=%s group_name=%s",
                        target_group_id,
                        new_group_name,
                    )
                    new_group_name = self._normalize_group_name(
                        new_group_name,
                        fallback=group_data_before.get("group_name", "")
                        or f"group-{target_group_id}",
                    )
                    new_description = self._extract_description_from_agent_card(
                        new_agent_card_result
                    )
                except Exception as e:
                    logger.warning(
                        "处理合并后的 agent_card 失败: %s，使用原组的 agent_card 和 group_name",
                        str(e),
                        exc_info=True,
                    )
                    new_agent_card = group_data_before.get("agent_card", "")
                    new_group_name = group_data_before.get("group_name", "")
                    new_description = self._extract_description_from_agent_card(
                        new_agent_card
                    )

                next_version = self._version_for_semantic_group_update(
                    group_data_before,
                    new_group_name=new_group_name,
                    new_description=new_description,
                    new_agent_card=new_agent_card,
                )
                updated_group_data = SemanticGroupData(
                    id=target_group_id,
                    group_name=new_group_name,
                    description=new_description,
                    agent_card=new_agent_card,
                    version=next_version,
                )
                self.semantic_group_client.update_semantic_group(
                    group_id=target_group_id,
                    semantic_group=updated_group_data,
                )
                logger.info(
                    "已更新组 %s 的 group_name、描述和 agent_card（合并后的语义） version=%s",
                    target_group_id,
                    next_version,
                )
                group_updated = True

                if self.vector_client:
                    member_domains = []
                    group_text = self._build_semantic_group_text(
                        group_name=new_group_name,
                        description=new_description,
                        member_domains=member_domains,
                    )
                    self._delete_group_from_pgvector(target_group_id)
                    metadata = {
                        "group_id": target_group_id,
                        "group_name": new_group_name,
                    }
                    document = VectorDocument(
                        page_content=group_text, metadata=metadata
                    )
                    self.vector_client.add_documents(
                        collection_name=self.collection_name,
                        documents=[document],
                    )
                    logger.info(
                        "已更新组 %s 在 pgvector 中的向量数据",
                        target_group_id,
                    )
            else:
                logger.warning(
                    "consolidate_semantic_domain_into_semantic_group 返回的 summary 为空，跳过更新描述"
                )

        except Exception as e:
            logger.warning(
                "合并语义域到组时出错: %s，继续使用原有描述",
                str(e),
                exc_info=True,
            )

        return group_updated

    def _add_member_to_group(
        self,
        group_id: str,
        new_domain: Dict[str, Any],
        association_reason: Optional[str] = None
    ) -> bool:
        """
        将新语义域添加到现有组（JOIN 操作）
        
        Args:
            group_id: 组ID
            new_domain: 新语义域
            association_reason: 关联原因
            
        Returns:
            是否添加成功
        """
        try:
            if not self.semantic_group_client:
                logger.warning("SemanticGroupClient 未配置，跳过添加成员")
                return False
            
            sd_id = new_domain.get('semantic_domain_id')
            if not sd_id:
                logger.warning("新语义域缺少 semantic_domain_id，跳过添加")
                return False
            
            # 创建关系
            relation_data = DDGroupRelationData(
                sd_id=sd_id,
                group_id=group_id,
                association_reason=association_reason or "通过语义相似性分析加入组"
            )
            self.semantic_group_client.create_dd_group_relation(
                relation_data
            )
            
            logger.info(f"已将语义域 {sd_id} 添加到组 {group_id}")
            
            # 注意：pgvector 中的向量不需要立即更新，因为：
            # 1. 向量搜索主要用于初筛，详细信息从 MySQL 获取
            # 2. 如果需要更新向量，可以定期重新构建或增量更新
            # 3. 当前设计下，组的向量表示主要基于组名和描述，成员变化不影响向量
            
            return True
            
        except Exception as e:
            logger.error(f"添加成员到组失败: {str(e)}", exc_info=True)
            return False

    def consolidate_semantic_domain_into_semantic_group(
        self, 
        semantic_domain: Dict[str, Any],
        semantic_group: Dict[str, Any],
        max_retries: int = 3,
        retry_delay: float = 1.0,
        exponential_backoff: bool = True
    ) -> Dict[str, Any]:
        """
        Consolidate semantic domain into semantic group using LLM with retry support
        
        This function uses LLM to consolidate semantic domains into semantic groups.
        It includes retry logic to handle transient failures.
        
        Args:
            semantic_domain: Dictionary containing semantic domain information
                Expected keys: semantic_domain_id, semantic_domain, agent_card, dd_name, dd_namespace
            semantic_group: Dictionary containing semantic group information
                Expected keys: id, group_name, description, version, agent_card
            max_retries: Maximum number of retry attempts (default: 3)
            retry_delay: Initial delay between retries in seconds (default: 1.0)
            exponential_backoff: Whether to use exponential backoff for retries (default: True)
            
        Returns:
            Dictionary containing consolidated result with 'summary' key
            
        Raises:
            ValueError: If semantic_domain/semantic_group is invalid
            RuntimeError: If all retry attempts fail
        """
        # Validate input
        if not isinstance(semantic_domain, dict) or not isinstance(semantic_group, dict):
            raise ValueError("semantic_domain and semantic_group must be dictionaries")
        
        if 'semantic_domain' not in semantic_domain:
            raise ValueError("semantic_domain must contain 'semantic_domain' key")
        
        if 'description' not in semantic_group:
            raise ValueError("semantic_group must contain 'description' key")

        prompt = SEMANTIC_GROUP_CONSOLIDATION_SYSTEM_PROMPT

        old_group_card = self._parse_agent_card(semantic_group.get("agent_card", ""))
        preservation_contract = self._build_preservation_contract(old_group_card)

        content = (
            "将 semantic domain 与 semantic group 做语义合并，输出候选完整 agent_card。\n\n"
            f"semantic_domain_text:\n{semantic_domain.get('semantic_domain', '')}\n\n"
            f"semantic_domain_agent_card:\n{semantic_domain.get('agent_card', '')}\n\n"
            f"semantic_group_description:\n{semantic_group.get('description', '')}\n\n"
            f"semantic_group_agent_card:\n{semantic_group.get('agent_card', '')}\n\n"
            f"must_keep_contract(必须保留):\n{json.dumps(preservation_contract, ensure_ascii=False)}\n\n"
            "要求：严格保留 must_keep_contract 中的 required_name、required_description、required_skill_ids。\n\n"
            "【去重要求】输出的 description 必须是基于 semantic_domain 与语义组信息**重新撰写的单一合并正文**；"
            "若 semantic_group_agent_card / semantic_group_description 与域内容语义重复，须在输出中合并为不重复表述，"
            "禁止整段复制旧组 description 再追加新段落。"
        )

        system_message = SystemMessage(content=prompt)
        human_message = HumanMessage(content=content)
        
        last_exception = None
        
        for attempt in range(max_retries):
            try:
                logger.info(f"Attempting LLM consolidation (attempt {attempt + 1}/{max_retries})")
                
                # Call LLM
                response = self.llm.invoke([system_message, human_message])
                
                # Format output
                llm_result = self.format_llm_output(response)
                
                if llm_result is not None:
                    logger.info(f"LLM consolidation successful on attempt {attempt + 1}")
                    return llm_result
                else:
                    logger.warning(f"LLM returned None result on attempt {attempt + 1}")
                    # Treat None result as a failure and retry
                    last_exception = ValueError("LLM returned None result")
                    
            except Exception as e:
                last_exception = e
                logger.warning(f"LLM consolidation failed on attempt {attempt + 1}/{max_retries}: {e}")
                
                # Don't retry on the last attempt
                if attempt < max_retries - 1:
                    # Calculate delay
                    if exponential_backoff:
                        delay = retry_delay * (2 ** attempt)
                    else:
                        delay = retry_delay
                    
                    logger.info(f"Retrying in {delay} seconds...")
                    time.sleep(delay)
                else:
                    logger.error(f"All {max_retries} attempts failed. Last error: {e}")
        
        # All retries failed
        logger.error(f"Failed to consolidate semantic domain after {max_retries} attempts")
        if last_exception:
            raise RuntimeError(f"Failed to consolidate semantic domain after {max_retries} attempts: {last_exception}") from last_exception
        else:
            raise RuntimeError(f"Failed to consolidate semantic domain after {max_retries} attempts")

    def consolidate_semantic_domains_into_semantic_group(
        self,
        semantic_domains: List[Dict[str, Any]],
        semantic_group: Dict[str, Any],
        max_retries: int = 3,
        retry_delay: float = 1.0,
        exponential_backoff: bool = True,
    ) -> Dict[str, Any]:
        """
        多语义域与同一语义组合并（例如某成员 SD 更新后重算整组）：将全部成员域一并交给 LLM，
        在联合语义上重做归纳，而不是仅把「变更域」与「当前组 agent_card 快照」做一步二元合并。
        列表顺序须为：第一项为本次变更域的最新快照，随后为其它成员的当前快照。
        """
        if not isinstance(semantic_domains, list) or not semantic_domains:
            raise ValueError("semantic_domains must be a non-empty list")
        if not isinstance(semantic_group, dict):
            raise ValueError("semantic_group must be a dictionary")
        if "description" not in semantic_group:
            raise ValueError("semantic_group must contain 'description' key")
        for i, domain in enumerate(semantic_domains):
            if not isinstance(domain, dict):
                raise ValueError(f"semantic_domains[{i}] must be a dictionary")
            if "semantic_domain" not in domain:
                raise ValueError(
                    f"semantic_domains[{i}] must contain 'semantic_domain' key"
                )

        prompt = SEMANTIC_GROUP_CONSOLIDATION_SYSTEM_PROMPT
        old_group_card = self._parse_agent_card(semantic_group.get("agent_card", ""))
        preservation_contract = self._build_preservation_contract(old_group_card)

        domain_blocks: List[str] = []
        for i, d in enumerate(semantic_domains, 1):
            label = f"第 {i} 个语义域成员"
            if i == 1:
                label += (
                    "（【本次触发更新的成员】：必须以本块中的 semantic_domain_text 与 "
                    "semantic_domain_agent_card 为当前最新内容）"
                )
            ident = ""
            ns, name = d.get("dd_namespace") or "", d.get("dd_name") or ""
            if ns and name:
                ident = f" [{ns}/{name}]"
            domain_blocks.append(
                f"### {label}{ident}\n"
                f"semantic_domain_text:\n{d.get('semantic_domain', '')}\n\n"
                f"semantic_domain_agent_card:\n{d.get('agent_card', '')}\n"
            )

        content = (
            "将以下多个 semantic domain 与 semantic group 做语义合并。它们属于同一语义组，"
            "必须视为一个联合系统的全部子域一并重新归纳；须综合所有成员域的信息，"
            "输出候选完整 agent_card；禁止只依据其中一个域忽略其它域。\n\n"
            + "\n".join(domain_blocks)
            + "\n"
            f"semantic_group_description:\n{semantic_group.get('description', '')}\n\n"
            f"semantic_group_agent_card:\n{semantic_group.get('agent_card', '')}\n\n"
            f"must_keep_contract(必须保留):\n"
            f"{json.dumps(preservation_contract, ensure_ascii=False)}\n\n"
            "要求：严格保留 must_keep_contract 中的 required_name、required_description、required_skill_ids。\n\n"
            "【去重要求】多个成员域与 semantic_group 输入之间常有重叠；输出的 description 必须是**一份**联合归纳后的去重正文，"
            "禁止把旧组 description 原样保留再在文末叠加与成员域重复的子领域展开；skills 中同一子领域也只保留合并后的单一描述，"
            "勿在 skill.description 里用「增量补充」堆叠与旧文高度相似的段落。"
        )

        system_message = SystemMessage(content=prompt)
        human_message = HumanMessage(content=content)
        last_exception = None

        for attempt in range(max_retries):
            try:
                logger.info(
                    "Attempting multi-domain LLM consolidation (attempt %s/%s, n_members=%s)",
                    attempt + 1,
                    max_retries,
                    len(semantic_domains),
                )
                response = self.llm.invoke([system_message, human_message])
                llm_result = self.format_llm_output(response)
                if llm_result is not None:
                    logger.info(
                        "Multi-domain LLM consolidation successful on attempt %s",
                        attempt + 1,
                    )
                    return llm_result
                last_exception = ValueError("LLM returned None result")
                logger.warning(
                    "LLM returned None result on attempt %s", attempt + 1
                )
            except Exception as e:
                last_exception = e
                logger.warning(
                    "Multi-domain LLM consolidation failed on attempt %s/%s: %s",
                    attempt + 1,
                    max_retries,
                    e,
                )
                if attempt < max_retries - 1:
                    delay = (
                        retry_delay * (2**attempt)
                        if exponential_backoff
                        else retry_delay
                    )
                    logger.info("Retrying in %s seconds...", delay)
                    time.sleep(delay)
                else:
                    logger.error(
                        "All %s attempts failed. Last error: %s", max_retries, e
                    )

        logger.error(
            "Failed to consolidate %s semantic domains after %s attempts",
            len(semantic_domains),
            max_retries,
        )
        if last_exception:
            raise RuntimeError(
                f"Failed to consolidate semantic domains after {max_retries} attempts: {last_exception}"
            ) from last_exception
        raise RuntimeError(
            f"Failed to consolidate semantic domains after {max_retries} attempts"
        )

    def agent_card(self, content):
        prompt = """你是一个精通领域驱动设计（DDD）和业务建模的资深架构师。你的核心任务是根据业务描述，生成一个高质量的 Agent-to-Agent (A2A) 协议 JSON。

        ### ⚠ 最重要的设计原则（必须贯穿始终）：

        这个 Agent Card 的 description 会被上游编排器（Orchestrator）用来判断"用户的问题是否属于这个 Agent 的业务领域"。
        因此，description 的首要目标不是列举具体功能，而是**清晰定义这个 Agent 所负责的完整语义域（Semantic Domain）**。

        **你必须遵循"语义域优先"原则：**
        1. **整体系统 = 一个Agent**：用户提供的业务描述描述了一个完整系统。无论该系统内部划分了多少个子领域/限界上下文/模块，你必须生成**一个**Agent Card来覆盖该系统的**全部**子领域。绝对不可以只选取其中一个子领域来生成Agent Card。name和description必须体现系统的整体定位，而非某个子领域。
        2. **先定义域，再说能力**：首先用概括性语言说清楚"我负责整个 XXX 领域"，然后再展开细节。
        3. **宽泛包容，而非窄化排斥**：描述要涵盖该领域所有可能的业务问题，包括查询、统计、分析、对比、趋势、预测等各种操作。不要只列举当前已知的具体功能点。
        4. **同义词与关联概念全覆盖**：对于每个核心业务概念，必须同时提及其同义词、近义词、上位词、口语化表达。例如"贷款"同时提及"借款、放款、信贷、授信"。
        5. **避免排他性表述**：绝对不要写"只处理XXX"、"仅限于XXX"、"不负责XXX"这类限定性语句。只要问题与该语义域相关，即使是边缘场景，也应被覆盖。

        ### 输出规则：
        1. **只输出JSON**：不要任何额外文本、解释、Markdown代码块标记。
        2. **严格遵循结构**：必须使用下方提供的完整JSON结构模板。
        3. **确保可解析**：输出的JSON必须能被 `json.loads()` 直接解析。
        4. **引号必须使用ASCII标准双引号**：JSON中的所有引号必须使用ASCII标准双引号(U+0022)，绝对不能使用中文引号、排版引号或其他任何Unicode引号变体。这一点非常关键，使用非标准引号会导致JSON解析失败。

        ### 字段填充指南：

        **一定不能替换的字段**：url, provider, version, documentationUrl, capabilities部分, authentication部分, defaultInputModes部分, defaultOutputModes部分, skill的inputModes, skill的outputModes。

        **1. name 字段**：
        - 格式：驼峰命名法，如 `BankFinancialDataAgent`
        - 要求：体现所负责的**整个系统**的业务领域名称（不要只用某一个子领域命名）
        - 示例：若系统是电商交易平台，应命名为 `EcommerceTransactionAgent`，而非 `EcommerceUserManagementAgent`

        **2. description 字段（核心，约800-1200字）**：
        【请严格按照以下三层结构书写，形成从宏观到微观的完整描述】

        **第一层：语义域声明（最关键，约200字）**
        用2-3句话，清晰、概括地声明本 Agent 负责的完整业务领域。这段话的目的是让编排器一眼就能判断"这个领域涵盖了哪些类型的业务问题"。

        要求：
        - 明确说出所属的**行业**和**业务大类**
        - 列出该领域涉及的**所有核心业务主题词**（含同义词、近义词、口语表达）
        - 使用"涵盖……等一切相关问题"这类包容性语句

        示例：
        > "本Agent是银行业分支机构财务数据领域的全能专家，负责处理与银行网点/支行/分行的财务状况相关的一切问题。覆盖的核心主题包括但不限于：资产负债表、总资产、总负债、净资产、存款（储蓄、定期、活期、对公存款、个人存款、零售存款）、贷款（放款、授信、信贷、按揭、消费贷、对公贷款、零售贷款）、客户规模、员工规模，以及围绕这些数据的查询、统计、分析、对比、排名、趋势等各类操作。"

        **第二层：子领域与业务概念展开（约400-600字）**
        按业务子领域分组，展开描述每个子领域包含的业务概念和典型问题类型。每个子领域都应该：
        - 说明其核心职责
        - 列出涉及的全部业务术语和数据实体（含同义词）
        - 说明该子领域下用户可能提出的问题方向（用"包括XXX类问题"的方式概括，不要举过于具体的例子）

        示例：
        > "【存款业务】管理各分支机构的存款数据，涉及的概念包括：存款结构、存款分布、对公存款与零售存款的区分、活期存款与定期存款的比例、存款总额与趋势变化等。用户可能围绕存款提出查询、汇总、排名、对比、趋势分析等各类问题。"

        **第三层：协作声明（约100-200字）**
        简要说明本 Agent 在多智能体协作中的定位：
        - 当其他 Agent 或用户遇到与本领域相关的任何问题时，都应路由到本 Agent
        - 本 Agent 具备对该领域数据进行多维度分析的能力
        - 如果用户的问题涉及的数据实体属于本领域，无论具体操作方式如何（查询、统计、可视化、导出等），本 Agent 都能处理

        **3. skills 数组**：
        每个 skill 代表该语义域下的一个子领域或核心业务能力：
        - `id`: 如 `deposit-data-analysis`
        - `name`: 如 `存款业务数据服务`
        - `description`: 应包含：
          1. **子领域范围**：这个 skill 覆盖的业务范围
          2. **核心数据实体**：涉及的业务名词和概念（含同义词）
          3. **支持的问题类型**：可以处理哪些类型的业务问题
        - `tags`: 业务标签，要包含同义词和关联词，如 `["deposit", "savings", "存款", "储蓄"]`
        - `examples`: 该子领域下的典型自然语言问题示例

        ### 完整JSON模板（必须严格使用此结构）：
        {
            "name": "根据业务领域填写，如BankFinancialDataAgent",
            "description": "【请严格按照三层结构填充：语义域声明 + 子领域展开 + 协作声明】",
            "url": "http://192.168.xxx.xxx:20002/",
            "provider": null,
            "version": "1.0.0",
            "documentationUrl": null,
            "capabilities": {
                "streaming": "True",
                "pushNotifications": "True",
                "stateTransitionHistory": "False"
            },
            "authentication": {
                "credentials": null,
                "schemes": ["public"]
            },
            "defaultInputModes": ["text", "text/plain"],
            "defaultOutputModes": ["text", "text/plain"],
            "skills": [
                {
                    "id": "子领域标识，如deposit-data-analysis",
                    "name": "子领域名称，如存款业务数据服务",
                    "description": "必须包含：子领域范围、核心数据实体（含同义词）、支持的问题类型",
                    "tags": ["业务标签，含同义词和关联词"],
                    "examples": ["该子领域下的典型自然语言问题示例"],
                    "inputModes": null,
                    "outputModes": null
                }
            ]
        }

        ### 关键检查清单（生成后请自查）：
        1. ✅ description 第一层是否用概括性语言声明了完整的语义域？
        2. ✅ 是否覆盖了所有核心业务名词的同义词和口语表达？
        3. ✅ 是否避免了"只处理"、"仅限于"等排他性表述？
        4. ✅ 是否说明了"任何与该领域相关的问题都能处理"？
        5. ✅ skills 是否按子领域划分，而非按具体操作划分？
        6. ✅ tags 是否包含了足够的同义词和关联词？
        7. ✅ 当输入里已经包含「语义组旧的 description / agent_card」或与成员域语义高度重叠时，输出的 description 必须是**重新归纳后的单一去重正文**，禁止把旧 description 整段保留再在文末追加「补充」造成同一子领域写两遍。

        ### 最终要求：
        1. 基于用户提供的业务描述，生成完整的JSON
        2. description 务必做到"领域覆盖最大化"——宁可多覆盖，不可漏掉相关问题
        3. 确保 skills 真实、具体、可调用
        4. 不要偏离提供的JSON结构
        """

        system_message = SystemMessage(content=prompt)
        human_message = HumanMessage(content=f"{content}")

        MAX_RETRIES = 3
        
        for attempt in range(MAX_RETRIES):
            try:
                response = self.llm.invoke([system_message, human_message])

                llm_result = self.format_llm_output(response)

                agent_card = AgentCard(**llm_result)

                logger.info(f"========== agent_card : {agent_card}")

                return llm_result

            except (TypeError, ValueError, KeyError) as e:
                logging.error(f"AgentCard instantiation failed on attempt {attempt + 1}: {e}")

                if attempt + 1 == MAX_RETRIES:
                    raise RuntimeError(f"Failed to generate valid AgentCard after {MAX_RETRIES} attempts.") from e

        raise RuntimeError("Unexpected failure in AgentCard generation loop.")


    def consolidate_for_decremental_semantic_group(
        self, 
        semantic_domains: List[Dict[str, Any]],
        max_retries: int = 3,
        retry_delay: float = 1.0,
        exponential_backoff: bool = True
    ) -> Dict[str, Any]:
        """
        Consolidate multiple semantic domains using LLM with retry support
        
        This function uses LLM to consolidate multiple semantic domains.
        It includes retry logic to handle transient failures.
        
        Args:
            semantic_domains: List of dictionaries containing semantic domain information
                Each dictionary should have keys: semantic_domain_id, semantic_domain, agent_card, dd_name, dd_namespace
            max_retries: Maximum number of retry attempts (default: 3)
            retry_delay: Initial delay between retries in seconds (default: 1.0)
            exponential_backoff: Whether to use exponential backoff for retries (default: True)
            
        Returns:
            Dictionary containing consolidated result with 'summary' key
            
        Raises:
            ValueError: If semantic_domains is invalid
            RuntimeError: If all retry attempts fail
        """
        # Validate input
        if not isinstance(semantic_domains, list):
            raise ValueError("semantic_domains must be a list")
        
        if len(semantic_domains) == 0:
            raise ValueError("semantic_domains list cannot be empty")
        
        for i, domain in enumerate(semantic_domains):
            if not isinstance(domain, dict):
                raise ValueError(f"semantic_domains[{i}] must be a dictionary")
            if 'semantic_domain' not in domain:
                raise ValueError(f"semantic_domains[{i}] must contain 'semantic_domain' key")

        prompt = """
        你是一个精通领域驱动设计（DDD）和业务建模的资深架构师，特别擅长用业务语言描述技术能力。你的核心任务是根据业务描述，生成一个高质量、健壮的 Agent-to-Agent (A2A) 协议 JSON。

        ### 核心理念（请严格遵循）：
        1. **业务服务导向**：Agent描述应该像“专业服务专家介绍”，而不是技术实现文档。
        2. **价值清晰**：说明“我能为其他Agent解决什么业务问题”, 要完整的包含所有的业务范围，特别是要完整包括所有的业务名称/名词。
        3. **边界明确**：让其他Agent清楚知道什么时候该找你，什么不该找你。
        4. **可操作性**：提供的skills必须真实可调用，示例必须具体可行。

        ### 输出规则：
        1. **只输出JSON**：不要任何额外文本、解释、Markdown代码块标记。
        2. **严格遵循结构**：必须使用下方提供的完整JSON结构模板。
        3. **确保可解析**：输出的JSON必须能被 `json.loads()` 直接解析。

        ### 字段填充指南：

        **1. name 字段**：
        - 格式：驼峰命名法，如 `InvoiceProcessingAgent`
        - 要求：代表核心业务能力，如“支付”、“订单”、“库存”

        **2. description 字段（核心，约1000字）**：
        【请严格按照以下四部分结构书写】

        **第一部分：我的业务身份**
        用1-2句话定义你的专业角色。示例：
        > "我是财务结算流程的『合规专家』，专注于确保所有交易记录准确、完整且符合会计准则。"

        **第二部分：我能为你解决的问题（列出全部的能力）**
        这是最重要的部分！使用这种格式：
        1. **[核心能力1]**：[具体解决什么业务痛点]。例如："**多币种结算处理**：帮你处理跨境交易中的货币转换、汇率锁定和本地化税务计算。"
        2. **[核心能力2]**：[具体解决什么业务痛点]。例如："**复杂折扣计算**：处理组合促销、阶梯折扣、优惠券叠加等复杂定价逻辑。"
        
        **第三部分：何时找我 & 我的服务承诺**
        - **找我时机**：当需要...[具体业务场景]时
        - **我能保证**：我确保...[提供的价值保证]
        - **协作方式**：通过调用我的...技能

        **第四部分：典型业务场景演示**
        用1-2个具体例子展示你的价值。示例：
        > "当企业客户需要进行月度统一结算时，我会：1) 汇总所有待结算订单，2) 验证每笔交易的合规性，3) 计算应返佣金和税费，4) 生成标准化的结算单。"

        **3. skills 数组**：
        每个skill必须是真实可调用的业务能力，包含：
        - `id`: 如 `validate-invoice`
        - `name`: 如 `Validate Invoice`
        - `description`: **必须包含四个要素**：
          1. **业务目的**：这个技能解决什么具体问题？
          2. **典型输入**：需要提供什么业务信息？
          3. **预期输出**：会返回什么业务结果？
          4. **主要调用者**：哪些Agent最常用这个技能？
        - `tags`: 至少一个业务标签，如 `billing`, `compliance`
        - `examples`: 具体的调用示例，如 `{"customer_id": "C001", "invoice_no": "INV-2023-001"}`
        -  一定不能替换的字段包括**: url, provider, version, documentationUrl, capabilities部分, authentication部分, defaultInputModes部分, defaultOutputModes部分, skill的inputModes, skill的outputModes。


        ### 完整JSON模板（必须严格使用此结构）：
        {
            "name": "根据业务领域填写，如InvoiceAgent",
            "description": "【请严格按照四部分结构填充】",
            "url": "http://192.168.xxx.xxx:20002/",
            "provider": null,
            "version": "1.0.0",
            "documentationUrl": null,
            "capabilities": {
                "streaming": "True",
                "pushNotifications": "True",
                "stateTransitionHistory": "False"
            },
            "authentication": {
                "credentials": null,
                "schemes": ["public"]
            },
            "defaultInputModes": ["text", "text/plain"],
            "defaultOutputModes": ["text", "text/plain"],
            "skills": [
                {
                    "id": "具体技能标识，如validate-invoice",
                    "name": "技能名称，如Validate Invoice",
                    "description": "必须包含：业务目的、输入、输出、调用者",
                    "tags": ["业务标签"],
                    "examples": ["具体调用示例"],
                    "inputModes": null,
                    "outputModes": null
                }
            ]
        }

        ### 业务示例（供参考理解）：
        如果业务领域是"发票处理"，那么：

        **描述示例**：
        "我是企业财务系统的『发票合规专家』，专注于确保所有进项和销项发票的合法性、完整性和可抵扣性..."
        
        **技能示例**：
        {
            "id": "validate-vat-invoice",
            "name": "Validate VAT Invoice",
            "description": "验证增值税专用发票的合规性。业务目的：确保发票可正常抵扣，避免税务风险。输入：发票基础信息、交易明细、买卖双方税号。输出：验证结果（通过/拒绝）、拒绝原因、建议修正项。主要被财务审核Agent和报销Agent调用。",
            "tags": ["invoice", "tax", "compliance"],
            "examples": ["请验证这张金额为￥10,000的增值税专用发票，购买方税号：91310000100012345X，销售方税号：91320000200067890Y"]
        }

        ### 最终要求：
        1. 基于用户提供的业务描述，生成完整的JSON
        2. 保持专业性和业务价值导向
        3. 确保skills真实、具体、可调用
        4. 不要偏离提供的JSON结构
        """

        # 循环遍历所有语义域，拼接成字符串
        semantic_domain_parts = []
        for i, domain in enumerate(semantic_domains, 1):
            semantic_domain_text = domain.get('semantic_domain', '')
            dd_name = domain.get('dd_name', '')
            dd_namespace = domain.get('dd_namespace', '')
            
            # 构建每个语义域的标识
            domain_identifier = f"{dd_namespace}.{dd_name}" if dd_namespace and dd_name else f"语义域 {i}"
            
            # 拼接语义域内容
            domain_content = f"## 语义域 {i}: {domain_identifier}\n\n{semantic_domain_text}"
            semantic_domain_parts.append(domain_content)
        
        # 将所有语义域内容拼接在一起
        all_semantic_domains = "\n\n---\n\n".join(semantic_domain_parts)
        
        content = f"以下是需要合并的 {len(semantic_domains)} 个语义域：\n\n{all_semantic_domains}"

        system_message = SystemMessage(content=prompt)
        human_message = HumanMessage(content=content)
        
        last_exception = None
        
        for attempt in range(max_retries):
            try:
                logger.info(f"Attempting LLM consolidation (attempt {attempt + 1}/{max_retries})")
                
                # Call LLM
                response = self.llm.invoke([system_message, human_message])
                
                # Format output
                llm_result = self.format_llm_output(response)
                
                if llm_result is not None:
                    logger.info(f"LLM consolidation successful on attempt {attempt + 1}")
                    return llm_result
                else:
                    logger.warning(f"LLM returned None result on attempt {attempt + 1}")
                    # Treat None result as a failure and retry
                    last_exception = ValueError("LLM returned None result")
                    
            except Exception as e:
                last_exception = e
                logger.warning(f"LLM consolidation failed on attempt {attempt + 1}/{max_retries}: {e}")
                
                # Don't retry on the last attempt
                if attempt < max_retries - 1:
                    # Calculate delay
                    if exponential_backoff:
                        delay = retry_delay * (2 ** attempt)
                    else:
                        delay = retry_delay
                    
                    logger.info(f"Retrying in {delay} seconds...")
                    time.sleep(delay)
                else:
                    logger.error(f"All {max_retries} attempts failed. Last error: {e}")
        
        # All retries failed
        logger.error(f"Failed to consolidate semantic domain after {max_retries} attempts")
        if last_exception:
            raise RuntimeError(f"Failed to consolidate semantic domain after {max_retries} attempts: {last_exception}") from last_exception
        else:
            raise RuntimeError(f"Failed to consolidate semantic domain after {max_retries} attempts")


    def decremental_semantic_group_analyse(
        self,
        semantic_domain_id: str
    ) -> Dict[str, Any]:
        """
        减量式语义域分组分析（移除语义域）
        
        核心策略：减量式处理 (Decremental Processing)
        - Step 1: UnbindDB - 移除关系表记录
        - Step 2: Check Empty - 检查组是否为空（注意：组不会被自动删除，只能在页面上手动删除，因为组可能被agent使用）
        - Step 3: Re-Induct - LLM任务，同步执行，重新聚合剩余成员的语义，更新描述
        - Step 4: Vector Update - Embedding同步执行，确保检索到的候选组依然准确
        
        Args:
            semantic_domain_id: 要移除的语义域ID
            
        Returns:
            处理结果，格式：
            {
                "status": "success" | "error",
                "action": "REMOVED" | "REINDUCT_SCHEDULED",
                "group_id": str,
                "group_name": str,
                "remaining_member_count": int,
                "message": str
            }
            
        注意：
        - 组不会被自动删除（即使为空），只能在页面上手动删除，因为组可能被agent使用
        - 当组为空时，会返回 "REMOVED" action，并提示需要在页面上手动删除组
        """
        if not semantic_domain_id:
            logger.warning("语义域ID为空")
            return {
                "status": "error",
                "action": "REMOVED",
                "message": "语义域ID为空"
            }
        
        logger.info(f"开始处理移除语义域: {semantic_domain_id}")
        
        try:
            # Step 1: UnbindDB - 获取关系并删除
            if not self.semantic_group_client:
                logger.warning("SemanticGroupClient 未配置，无法执行移除操作")
                return {
                    "status": "error",
                    "action": "REMOVED",
                    "message": "SemanticGroupClient 未配置"
                }
            
            # 获取语义域所属的组关系
            relations_response = self.semantic_group_client.get_relations_by_sd_id(semantic_domain_id)
            relations_data = relations_response.get('data', [])
            
            if not isinstance(relations_data, list) or len(relations_data) == 0:
                logger.warning(f"语义域 {semantic_domain_id} 没有关联的语义组")
                return {
                    "status": "success",
                    "action": "REMOVED",
                    "message": "语义域没有关联的语义组",
                    "remaining_member_count": 0
                }
            
            # 检查：如果该 semantic domain 所属的任何一个组中只有它这一个 semantic domain，不允许删除
            for relation in relations_data:
                group_id = relation.get('group_id')
                
                if not group_id:
                    logger.warning(f"关系记录缺少 group_id: {relation}")
                    continue
                
                # 获取组成员数量
                current_relations_response = self.semantic_group_client.get_relations_by_group_id(group_id)
                current_relations_data = current_relations_response.get('data', [])
                if not isinstance(current_relations_data, list):
                    current_relations_data = []
                current_member_count = len(current_relations_data)
                
                # 如果组中只有这一个 semantic domain，不允许删除
                if current_member_count == 1:
                    # 获取组信息用于错误消息
                    group_response = self.semantic_group_client.get_semantic_group_by_id(group_id)
                    group_data = group_response.get('data', {})
                    group_name = group_data.get('group_name', group_id)
                    
                    logger.warning(f"不允许删除语义域 {semantic_domain_id}：它所属的组 '{group_name}' (group_id: {group_id}) 中只有它这一个语义域")
                    return {
                        "status": "error",
                        "action": "REMOVED",
                        "group_id": group_id,
                        "group_name": group_name,
                        "remaining_member_count": current_member_count,
                        "message": f"不允许删除：该语义域（dd）所属的组 '{group_name}' 中只有它这一个语义域，不允许删除"
                    }
            
            # 获取第一个关系用于后续删除操作（通常一个语义域只属于一个组）
            relation = relations_data[0]
            group_id = relation.get('group_id')
            relation_id = relation.get('id')
            
            if not group_id:
                logger.warning(f"关系记录缺少 group_id: {relation}")
                return {
                    "status": "error",
                    "action": "REMOVED",
                    "message": "关系记录缺少 group_id"
                }
            
            # 获取组信息
            group_response = self.semantic_group_client.get_semantic_group_by_id(group_id)
            group_data = group_response.get('data', {})
            group_name = group_data.get('group_name', '')
            
            logger.info(f"语义域 {semantic_domain_id} 当前属于组 {group_name} (group_id: {group_id})")
            
            # 删除关系
            if relation_id:
                try:
                    self.semantic_group_client.delete_dd_group_relation(relation_id)
                    logger.info(f"已删除关系记录: relation_id={relation_id}")
                except Exception as e:
                    logger.error(f"删除关系记录失败: {str(e)}", exc_info=True)
                    # 尝试使用 sd_id 删除
                    try:
                        self.semantic_group_client.delete_relations_by_sd_id(semantic_domain_id)
                        logger.info(f"已通过 sd_id 删除关系记录: {semantic_domain_id}")
                    except Exception as e2:
                        logger.error(f"通过 sd_id 删除关系记录也失败: {str(e2)}", exc_info=True)
                        return {
                            "status": "error",
                            "action": "REMOVED",
                            "group_id": group_id,
                            "group_name": group_name,
                            "message": f"删除关系记录失败: {str(e2)}"
                        }
            else:
                # 如果没有 relation_id，使用 sd_id 删除
                try:
                    self.semantic_group_client.delete_relations_by_sd_id(semantic_domain_id)
                    logger.info(f"已通过 sd_id 删除关系记录: {semantic_domain_id}")
                except Exception as e:
                    logger.error(f"通过 sd_id 删除关系记录失败: {str(e)}", exc_info=True)
                    return {
                        "status": "error",
                        "action": "REMOVED",
                        "group_id": group_id,
                        "group_name": group_name,
                        "message": f"删除关系记录失败: {str(e)}"
                    }
            
            # Step 2: Check Empty - 检查组是否为空
            # 注意：组不会被自动删除，只能在页面上手动删除，因为组可能被agent使用
            remaining_relations_response = self.semantic_group_client.get_relations_by_group_id(group_id)
            remaining_relations_data = remaining_relations_response.get('data', [])
            if not isinstance(remaining_relations_data, list):
                remaining_relations_data = []
            remaining_member_count = len(remaining_relations_data)
            
            if remaining_member_count == 0:
                # 组为空，但不会自动删除（组可能被agent使用，只能在页面上手动删除）
                logger.info(f"组 {group_name} (group_id: {group_id}) 已为空，但不会自动删除（组可能被agent使用，只能在页面上手动删除）")
                
                return {
                    "status": "success",
                    "action": "REMOVED",
                    "group_id": group_id,
                    "group_name": group_name,
                    "remaining_member_count": 0,
                    "message": "组已为空，但未自动删除（组可能被agent使用，请在页面上手动删除）"
                }
            
            # 优化：如果只剩1个成员，直接将该成员的语义作为组语义，不需要LLM重新Induct
            if remaining_member_count == 1:
                logger.info(f"组 {group_name} (group_id: {group_id}) 只剩1个成员，执行优化处理：直接使用该成员的语义作为组语义")
                
                # 获取剩余成员的信息
                remaining_relation = remaining_relations_data[0]
                remaining_sd_id = remaining_relation.get('sd_id')
                
                if not remaining_sd_id:
                    logger.warning(f"剩余成员缺少 sd_id，无法获取语义域信息")
                    return {
                        "status": "error",
                        "action": "REMOVED",
                        "group_id": group_id,
                        "group_name": group_name,
                        "remaining_member_count": 1,
                        "message": "只剩1个成员但无法获取成员信息（缺少 sd_id）"
                    }
                
                # 尝试获取剩余成员的完整语义域数据
                remaining_domain = None
                if self.semantic_domain_client:
                    try:
                        logger.info(f"尝试获取剩余成员 {remaining_sd_id} 的完整语义域数据，使用 base_url: {self.semantic_domain_client.base_url}")
                        # 直接通过 semantic_domain_id 获取语义域数据
                        domain_response = self.semantic_domain_client.get_semantic_domain_by_id(remaining_sd_id)
                        logger.debug(f"get_semantic_domain_by_id 返回响应类型: {type(domain_response)}, 内容: {domain_response}")
                        
                        if isinstance(domain_response, dict):
                            if 'data' in domain_response:
                                remaining_domain = domain_response.get('data')
                                logger.debug(f"从响应中提取 data 字段: {remaining_domain is not None}")
                            else:
                                remaining_domain = domain_response
                                logger.debug(f"直接使用响应作为 remaining_domain")
                            
                            if remaining_domain:
                                logger.info(f"成功通过 get_semantic_domain_by_id 获取剩余成员的语义域数据: sd_id={remaining_sd_id}, 包含字段: {list(remaining_domain.keys()) if isinstance(remaining_domain, dict) else 'N/A'}")
                            else:
                                logger.warning(f"get_semantic_domain_by_id 返回的数据为空: domain_response={domain_response}")
                        else:
                            logger.warning(f"get_semantic_domain_by_id 返回格式异常: 期望 dict，实际 {type(domain_response)}, 值: {domain_response}")
                    except Exception as e:
                        logger.error(f"通过 get_semantic_domain_by_id 获取语义域数据失败: sd_id={remaining_sd_id}, base_url={self.semantic_domain_client.base_url}, 错误: {str(e)}", exc_info=True)
                else:
                    logger.warning(f"semantic_domain_client 未配置，无法获取剩余成员 {remaining_sd_id} 的完整语义域数据")
                
                if remaining_domain:
                    # 使用该成员的语义域数据更新组
                    try:
                        # 提取语义域信息
                        new_agent_card = remaining_domain.get('agent_card', '')
                        # 从 agent_card 中提取 description
                        new_description = self._extract_description_from_agent_card(new_agent_card)
                        
                        # 从 agent_card 提取 name 作为新的 group_name
                        new_group_name = group_name  # 默认使用原组名
                        if new_agent_card:
                            if isinstance(new_agent_card, dict):
                                new_group_name = new_agent_card.get('name', group_name)
                            elif isinstance(new_agent_card, str):
                                try:
                                    agent_card_dict = json.loads(new_agent_card)
                                    new_group_name = agent_card_dict.get('name', group_name)
                                except:
                                    # 如果解析失败，保持原组名
                                    pass
                        new_group_name = self._normalize_group_name(new_group_name, fallback=group_name)
                        
                        # 确保 agent_card 是字符串格式
                        if isinstance(new_agent_card, dict):
                            new_agent_card = json.dumps(new_agent_card, ensure_ascii=False)
                        elif not isinstance(new_agent_card, str):
                            new_agent_card = str(new_agent_card) if new_agent_card else ''
                        
                        # 更新组数据
                        next_version = self._version_for_semantic_group_update(
                            group_data,
                            new_group_name=new_group_name,
                            new_description=new_description,
                            new_agent_card=new_agent_card,
                        )
                        updated_group_data = SemanticGroupData(
                            id=group_id,
                            group_name=new_group_name,
                            description=new_description,
                            agent_card=new_agent_card,
                            version=next_version,
                        )
                        self.semantic_group_client.update_semantic_group(
                            group_id=group_id,
                            semantic_group=updated_group_data
                        )
                        logger.info(
                            "已使用剩余成员的语义更新组 %s，group_name: %s version=%s",
                            group_id,
                            new_group_name,
                            next_version,
                        )
                        
                        # 更新向量数据
                        if self.vector_client:
                            # 构建成员域列表（只包含 agent_card，_build_semantic_group_text 只使用 agent_card）
                            member_domain = {
                                "semantic_domain_id": remaining_sd_id,
                                "agent_card": remaining_domain.get('agent_card', '')
                            }
                            member_domains = [member_domain]
                            
                            # 构建新的组文本
                            group_text = self._build_semantic_group_text(
                                group_name=new_group_name,
                                description=new_description,
                                member_domains=member_domains
                            )
                            
                            # 删除旧的向量数据
                            self._delete_group_from_pgvector(group_id)
                            
                            # 添加新的向量数据
                            metadata = {
                                "group_id": group_id,
                                "group_name": new_group_name
                            }
                            
                            document = VectorDocument(
                                page_content=group_text,
                                metadata=metadata
                            )
                            self.vector_client.add_documents(
                                collection_name=self.collection_name,
                                documents=[document]
                            )
                            logger.info(f"已更新组 {group_id} 在 pgvector 中的向量数据")
                        
                        return {
                            "status": "success",
                            "action": "REMOVED",
                            "group_id": group_id,
                            "group_name": new_group_name,
                            "remaining_member_count": 1,
                            "message": f"只剩1个成员，已直接使用该成员的语义作为组语义（无需LLM重新Induct）"
                        }
                        
                    except Exception as e:
                        logger.error(f"使用剩余成员语义更新组失败: {str(e)}", exc_info=True)
                        return {
                            "status": "error",
                            "action": "REMOVED",
                            "group_id": group_id,
                            "group_name": group_name,
                            "remaining_member_count": 1,
                            "message": f"使用剩余成员语义更新组失败: {str(e)}"
                        }
                else:
                    # 无法获取语义域数据，记录警告但继续执行后续流程（让 Re-Induct 处理）
                    logger.warning(f"无法获取剩余成员 {remaining_sd_id} 的完整语义域数据（semantic_domain_client 未配置或获取失败），将执行正常的 Re-Induct 流程")
                    # 继续执行后续的 Step 3-4 流程

            logger.info(f"组 {group_name} (group_id: {group_id}) 仍有 {remaining_member_count} 个成员，需要重新聚合")
            
            # Step 3 & 4: Re-Induct 和 Vector Update
            # 同步执行 Re-Induct
            try:
                # 获取剩余成员的所有语义域数据
                    remaining_member_domains = []
                    if not self.semantic_domain_client:
                        logger.warning(f"semantic_domain_client 未配置，无法获取剩余成员的完整语义域数据，跳过重新聚合")
                    else:
                        logger.info(f"开始获取剩余成员的完整语义域数据，剩余成员数: {len(remaining_relations_data)}, base_url: {self.semantic_domain_client.base_url}")
                        for rel in remaining_relations_data:
                            sd_id = rel.get('sd_id')
                            if not sd_id:
                                logger.warning(f"关系记录缺少 sd_id: {rel}")
                                continue
                            
                            domain_data = None
                            
                            # 直接通过 semantic_domain_id 获取语义域数据
                            try:
                                logger.debug(f"尝试获取语义域数据: sd_id={sd_id}")
                                domain_response = self.semantic_domain_client.get_semantic_domain_by_id(sd_id)
                                logger.debug(f"get_semantic_domain_by_id 返回响应类型: {type(domain_response)}, 内容: {domain_response}")
                                
                                if isinstance(domain_response, dict):
                                    if 'data' in domain_response:
                                        domain_data = domain_response.get('data')
                                        logger.debug(f"从响应中提取 data 字段: {domain_data is not None}")
                                    else:
                                        domain_data = domain_response
                                        logger.debug(f"直接使用响应作为 domain_data")
                                    
                                    if domain_data:
                                        logger.info(f"通过 get_semantic_domain_by_id 成功获取语义域数据: sd_id={sd_id}, 包含字段: {list(domain_data.keys()) if isinstance(domain_data, dict) else 'N/A'}")
                                    else:
                                        logger.warning(f"get_semantic_domain_by_id 返回的数据为空: sd_id={sd_id}, domain_response={domain_response}")
                                else:
                                    logger.warning(f"get_semantic_domain_by_id 返回格式异常: 期望 dict，实际 {type(domain_response)}, sd_id={sd_id}")
                            except Exception as e:
                                logger.error(f"get_semantic_domain_by_id 失败: sd_id={sd_id}, base_url={self.semantic_domain_client.base_url}, 错误: {str(e)}", exc_info=True)
                            
                            # 如果成功获取到语义域数据，添加到列表中
                            if domain_data:
                                remaining_member_domains.append({
                                    "semantic_domain_id": domain_data.get('semantic_domain_id', sd_id),
                                    "semantic_domain": domain_data.get('semantic_domain', ''),
                                    "agent_card": domain_data.get('agent_card', ''),
                                    "dd_name": domain_data.get('dd_name', ''),
                                    "dd_namespace": domain_data.get('dd_namespace', '')
                                })
                                logger.debug(f"已添加语义域到列表: sd_id={sd_id}, 当前列表长度: {len(remaining_member_domains)}")
                            else:
                                logger.warning(f"无法获取语义域 {sd_id} 的完整数据，跳过该成员")
                    
                    # 如果能够获取到剩余成员的完整数据，执行重新聚合
                    if remaining_member_domains and all(d.get('semantic_domain') for d in remaining_member_domains):
                        # 重新聚合剩余成员的语义
                        logger.info(f"开始重新聚合组 {group_name} 的剩余成员语义，成员数: {len(remaining_member_domains)}")
                        try:
                            consolidated_result = self.consolidate_for_decremental_semantic_group(
                                semantic_domains=remaining_member_domains,
                                max_retries=3,
                                retry_delay=1.0
                            )
                            
                            # consolidate_for_decremental_semantic_group 返回的是完整的 agent_card
                            if consolidated_result:
                                # 直接使用返回的 agent_card，不需要再生成
                                try:
                                    logger.info(f"使用重新聚合后的 agent_card 更新组 {group_id}")
                                    # consolidated_result 就是 agent_card（字典格式）
                                    new_agent_card_result = consolidated_result
                                    # agent_card 转换为 JSON 字符串
                                    new_agent_card = json.dumps(new_agent_card_result, ensure_ascii=False) if isinstance(new_agent_card_result, dict) else str(new_agent_card_result)
                                    
                                    # 从 agent_card 中提取 name 作为新的 group_name
                                    if isinstance(new_agent_card_result, dict):
                                        new_group_name = new_agent_card_result.get('name', group_name)
                                    else:
                                        # 如果 agent_card_result 不是字典，尝试解析 JSON
                                        try:
                                            agent_card_dict = json.loads(new_agent_card) if isinstance(new_agent_card, str) else {}
                                            new_group_name = agent_card_dict.get('name', group_name)
                                        except:
                                            new_group_name = group_name
                                    
                                    logger.info(f"使用重新聚合后的 agent_card，group_name 更新为 agent_card.name: {new_group_name}")
                                    new_group_name = self._normalize_group_name(new_group_name, fallback=group_name)
                                    # 从 agent_card 中提取 description
                                    new_description = self._extract_description_from_agent_card(new_agent_card_result)
                                except Exception as e:
                                    logger.warning(f"处理重新聚合后的 agent_card 失败: {str(e)}，使用原组的 agent_card 和 group_name", exc_info=True)
                                    # 如果处理失败，使用原组的 agent_card 和 group_name
                                    new_agent_card = group_data.get('agent_card', '')
                                    new_group_name = group_name
                                    # 从原组的 agent_card 中提取 description
                                    new_description = self._extract_description_from_agent_card(new_agent_card)
                                
                                # 更新组的描述、group_name 和 agent_card
                                next_version = self._version_for_semantic_group_update(
                                    group_data,
                                    new_group_name=new_group_name,
                                    new_description=new_description,
                                    new_agent_card=new_agent_card,
                                )
                                updated_group_data = SemanticGroupData(
                                    id=group_id,
                                    group_name=new_group_name,
                                    description=new_description,
                                    agent_card=new_agent_card,
                                    version=next_version,
                                )
                                self.semantic_group_client.update_semantic_group(
                                    group_id=group_id,
                                    semantic_group=updated_group_data
                                )
                                logger.info(
                                    "已更新组 %s 的描述、group_name 和 agent_card（重新聚合后的语义） version=%s",
                                    group_id,
                                    next_version,
                                )
                                
                                # 更新向量数据（如果 vector_client 可用，会在 Vector Update 步骤处理）
                                # 但这里已经获取了 remaining_member_domains，可以直接更新
                                if self.vector_client:
                                    try:
                                        # 构建新的组文本
                                        group_text = self._build_semantic_group_text(
                                            group_name=new_group_name,
                                            description=new_description,
                                            member_domains=remaining_member_domains
                                        )
                                        
                                        # 删除旧的向量数据
                                        self._delete_group_from_pgvector(group_id)
                                        
                                        # 添加新的向量数据
                                        metadata = {
                                            "group_id": group_id,
                                            "group_name": new_group_name
                                        }
                                        
                                        document = VectorDocument(
                                            page_content=group_text,
                                            metadata=metadata
                                        )
                                        self.vector_client.add_documents(
                                            collection_name=self.collection_name,
                                            documents=[document]
                                        )
                                        logger.info(f"已更新组 {group_id} 在 pgvector 中的向量数据（重新聚合后）")
                                    except Exception as e:
                                        logger.warning(f"更新向量数据失败: {str(e)}", exc_info=True)
                            else:
                                logger.warning(f"consolidate_for_decremental_semantic_group 返回的 summary 为空，跳过更新描述")
                        except Exception as e:
                            logger.error(f"重新聚合语义失败: {str(e)}", exc_info=True)
                    else:
                        logger.warning(f"无法获取剩余成员的完整语义域数据，跳过重新聚合（已获取 {len(remaining_member_domains)} 个成员的完整数据）")
                        
            except Exception as e:
                logger.error(f"重新聚合语义失败: {str(e)}", exc_info=True)
            
            # 同步执行 Vector Update
            if self.vector_client:
                try:
                    # 获取更新后的组信息
                    updated_group_response = self.semantic_group_client.get_semantic_group_by_id(group_id)
                    updated_group_data = updated_group_response.get('data', {})
                    updated_description = updated_group_data.get('description', '')
                    updated_group_name = updated_group_data.get('group_name', group_name)
                    
                    # 获取剩余成员信息用于构建向量文本
                    member_domains_for_vector = []
                    if self.semantic_domain_client:
                        logger.info(f"Vector Update: 开始获取剩余成员的完整语义域数据，剩余成员数: {len(remaining_relations_data)}, base_url: {self.semantic_domain_client.base_url}")
                        for rel in remaining_relations_data:
                            sd_id = rel.get('sd_id')
                            if not sd_id:
                                logger.warning(f"Vector Update: 关系记录缺少 sd_id: {rel}")
                                continue
                            
                            domain_data = None
                            
                            # 直接通过 semantic_domain_id 获取语义域数据
                            try:
                                logger.debug(f"Vector Update: 尝试获取语义域数据: sd_id={sd_id}")
                                domain_response = self.semantic_domain_client.get_semantic_domain_by_id(sd_id)
                                logger.debug(f"Vector Update: get_semantic_domain_by_id 返回响应类型: {type(domain_response)}, 内容: {domain_response}")
                                
                                if isinstance(domain_response, dict):
                                    if 'data' in domain_response:
                                        domain_data = domain_response.get('data')
                                        logger.debug(f"Vector Update: 从响应中提取 data 字段: {domain_data is not None}")
                                    else:
                                        domain_data = domain_response
                                        logger.debug(f"Vector Update: 直接使用响应作为 domain_data")
                                    
                                    if domain_data:
                                        logger.info(f"Vector Update: 通过 get_semantic_domain_by_id 成功获取语义域数据: sd_id={sd_id}, 包含字段: {list(domain_data.keys()) if isinstance(domain_data, dict) else 'N/A'}")
                                    else:
                                        logger.warning(f"Vector Update: get_semantic_domain_by_id 返回的数据为空: sd_id={sd_id}, domain_response={domain_response}")
                                else:
                                    logger.warning(f"Vector Update: get_semantic_domain_by_id 返回格式异常: 期望 dict，实际 {type(domain_response)}, sd_id={sd_id}")
                            except Exception as e:
                                logger.error(f"Vector Update: get_semantic_domain_by_id 失败: sd_id={sd_id}, base_url={self.semantic_domain_client.base_url}, 错误: {str(e)}", exc_info=True)
                            
                            # 如果成功获取到语义域数据，添加到列表中
                            if domain_data:
                                member_domains_for_vector.append({
                                    "semantic_domain_id": domain_data.get('semantic_domain_id', sd_id),
                                    "semantic_domain": domain_data.get('semantic_domain', ''),
                                    "agent_card": domain_data.get('agent_card', ''),
                                    "dd_name": domain_data.get('dd_name', ''),
                                    "dd_namespace": domain_data.get('dd_namespace', '')
                                })
                                logger.debug(f"Vector Update: 已添加语义域到列表: sd_id={sd_id}, 当前列表长度: {len(member_domains_for_vector)}")
                            else:
                                logger.warning(f"Vector Update: 无法获取语义域 {sd_id} 的完整数据，跳过该成员")
                    else:
                        logger.warning(f"semantic_domain_client 未配置，无法获取成员数据，跳过向量更新（使用空的 member_domains 构建向量文本没有意义）")
                        # 跳过向量更新，因为无法获取成员数据
                        # 即使有 description，没有成员数据的向量文本也是不完整的
                        # 等待 semantic_domain_client 配置后，可以通过 Re-Induct 重新生成向量
                    
                    # 只有当成功获取到成员数据时才更新向量
                    # 如果无法获取成员数据，跳过向量更新，避免生成无意义的 embedding
                    if member_domains_for_vector:
                        # 使用获取到的成员数据构建向量文本
                        group_text = self._build_semantic_group_text(
                            group_name=updated_group_name,
                            description=updated_description,
                            member_domains=member_domains_for_vector
                        )
                        
                        # 删除旧的向量数据
                        self._delete_group_from_pgvector(group_id)
                        
                        # 添加新的向量数据
                        metadata = {
                            "group_id": group_id,
                            "group_name": updated_group_name
                        }
                        
                        document = VectorDocument(
                            page_content=group_text,
                            metadata=metadata
                        )
                        self.vector_client.add_documents(
                            collection_name=self.collection_name,
                            documents=[document]
                        )
                        logger.info(f"已更新组 {group_id} 在 pgvector 中的向量数据，包含 {len(member_domains_for_vector)} 个成员的信息")
                    else:
                        logger.warning(f"无法获取剩余成员的完整语义域数据，跳过向量更新（已获取 {len(member_domains_for_vector)} 个成员的完整数据）。请配置 semantic_domain_client 后重新执行 Re-Induct 以更新向量数据")
                    
                except Exception as e:
                    logger.error(f"更新向量数据失败: {str(e)}", exc_info=True)
            
            return {
                "status": "success",
                "action": "REINDUCT_SCHEDULED",
                "group_id": group_id,
                "group_name": group_name,
                "remaining_member_count": remaining_member_count,
                "message": f"语义域已移除，组剩余 {remaining_member_count} 个成员，Re-Induct 和 Vector Update 已同步执行"
            }
            
        except Exception as e:
            logger.error(f"移除语义域 {semantic_domain_id} 时出错: {str(e)}", exc_info=True)
            return {
                "status": "error",
                "action": "REMOVED",
                "message": f"处理失败: {str(e)}"
            }

