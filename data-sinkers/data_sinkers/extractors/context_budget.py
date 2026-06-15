"""module_files_group / semantic_domains_analyse 分批处理的字符预算与切分工具。

本模块为 ``CodeAnalyzer`` 的 Map-Reduce 分批逻辑提供无 LLM 依赖的纯函数能力：

1. **module_files_group Map**：将 ``[{file_path, file_summary}, ...]`` 按字符数与文件数切批。
2. **module_files_group Reduce**：合并各批 ``group_with_files`` 元数据（不含 summary）。
3. **semantic_domains_analyse Map**：按文件路径列表切批（每文件富文本摘要单独估算字符）。
4. **semantic_domains_analyse Reduce**：合并各批语义域 JSON 结果。
5. **辅助**：解析旧版字符串格式、同名组/域确定性预合并。

环境变量（均有默认值，见各 accessor 函数文档）::

    MODULE_FILES_GROUP_MAX_INPUT_CHARS       # 默认 60000
    MODULE_FILES_GROUP_MAX_FILES_PER_BATCH   # 默认 30
    MODULE_FILES_GROUP_SYSTEM_PROMPT_RESERVE # 默认 8000（预留 system prompt 估算）
    SEMANTIC_DOMAINS_MAX_INPUT_CHARS         # 默认 60000
    SEMANTIC_DOMAINS_MAX_FILES_PER_BATCH     # 默认 30
    BUCKET_SUMMARY_MAX_INPUT_CHARS           # 默认 60000（MinIO 桶级 Map-Reduce）
    BUCKET_SUMMARY_MAX_FILES_PER_BATCH       # 默认 30
    BUCKET_SUMMARY_MAP_MAX_WORKERS           # 默认 10（Map 批并行度）
    LLM_JSON_PARSE_MAX_RETRIES               # 默认 3（JSON 解析失败时 LLM 重试次数）
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List

logger = logging.getLogger("context_budget")

# 单次 LLM human 消息（文件 summary 或组合并 JSON）的默认字符上限。
DEFAULT_MAX_INPUT_CHARS = 60000

# 单批最多包含的文件数，与 module_files_group 的 batch_size=30 对齐。
DEFAULT_MAX_FILES_PER_BATCH = 30

# semantic_domains_analyse 单次 LLM human 消息的默认字符上限。
DEFAULT_SEMANTIC_DOMAINS_MAX_INPUT_CHARS = 60000

# semantic_domains_analyse 单批最多包含的文件数。
DEFAULT_SEMANTIC_DOMAINS_MAX_FILES_PER_BATCH = 30

# MinIO 桶级 file_summary Map-Reduce：单批 human 消息字符上限。
DEFAULT_BUCKET_SUMMARY_MAX_INPUT_CHARS = 60000

# MinIO 桶级 Map 阶段单批最多文件数。
DEFAULT_BUCKET_SUMMARY_MAX_FILES_PER_BATCH = 30

# 桶级 Map 批次的 LLM 并行调用线程数。
DEFAULT_BUCKET_SUMMARY_MAP_MAX_WORKERS = 10

# 预留给 system prompt 的字符估算（当前主要用于配置常量，切分以 MAX_INPUT_CHARS 为准）。
DEFAULT_SYSTEM_PROMPT_RESERVE = 8000

# 解析 ``format_file_analysis_with_file_summary`` 产出的 legacy 字符串。
# 格式: ``File {N}. {path}，{summary}``，块之间以空行分隔。
_FILE_ENTRY_LINE_RE = re.compile(
    r"^File\s+(\d+)\.\s*(.+?)，(.*)$",
    re.DOTALL,
)

# 解析 ``format_file_analysis_with_summary_functions_business_concepts`` 产出的富文本。
# 块首行: ``File {N}. {path}``，块之间以空行分隔。
_SEMANTIC_FILE_BLOCK_RE = re.compile(
    r"^File\s+\d+\.\s*(.+)$",
    re.MULTILINE,
)


def _env_int(name: str, default: int) -> int:
    """从环境变量读取正整数；未设置或非法时回退到 default。"""
    raw = os.getenv(name, "").strip()
    if not raw:
        return max(1, default)
    try:
        return max(1, int(raw))
    except ValueError:
        logger.warning("Invalid %s=%r; using %d", name, raw, default)
        return max(1, default)


def module_files_group_max_input_chars() -> int:
    """单次分组/合并 LLM 调用中 human 内容的字符预算上限。

    环境变量: ``MODULE_FILES_GROUP_MAX_INPUT_CHARS``，默认 ``60000``。

    注意: 此为字符数而非 token 数；中文与代码路径混排时实际 token 可能更高，
    部署时可酌情下调。
    """
    return _env_int("MODULE_FILES_GROUP_MAX_INPUT_CHARS", DEFAULT_MAX_INPUT_CHARS)


def module_files_group_max_files_per_batch() -> int:
    """Map 阶段单批最多包含的文件条目数。

    环境变量: ``MODULE_FILES_GROUP_MAX_FILES_PER_BATCH``，默认 ``30``。

    与 ``module_files_group(batch_size=30)`` 的输出约束一致：即使字符未触顶，
    文件数达到此值也会开启新一批。
    """
    return _env_int("MODULE_FILES_GROUP_MAX_FILES_PER_BATCH", DEFAULT_MAX_FILES_PER_BATCH)


def semantic_domains_max_input_chars() -> int:
    """semantic_domains_analyse 单次 LLM human 内容的字符预算上限。

    环境变量: ``SEMANTIC_DOMAINS_MAX_INPUT_CHARS``，默认 ``60000``。
    """
    return _env_int(
        "SEMANTIC_DOMAINS_MAX_INPUT_CHARS",
        DEFAULT_SEMANTIC_DOMAINS_MAX_INPUT_CHARS,
    )


def semantic_domains_max_files_per_batch() -> int:
    """semantic_domains_analyse Map 阶段单批最多包含的文件数。

    环境变量: ``SEMANTIC_DOMAINS_MAX_FILES_PER_BATCH``，默认 ``30``。
    """
    return _env_int(
        "SEMANTIC_DOMAINS_MAX_FILES_PER_BATCH",
        DEFAULT_SEMANTIC_DOMAINS_MAX_FILES_PER_BATCH,
    )


def bucket_summary_max_input_chars() -> int:
    """MinIO 桶级 ``bucket_file_summary_map_reduce`` Map/Reduce 单批字符预算。

    环境变量: ``BUCKET_SUMMARY_MAX_INPUT_CHARS``，默认 ``60000``。
    """
    return _env_int(
        "BUCKET_SUMMARY_MAX_INPUT_CHARS",
        DEFAULT_BUCKET_SUMMARY_MAX_INPUT_CHARS,
    )


def bucket_summary_max_files_per_batch() -> int:
    """桶级 Map 阶段单批最多包含的 per-file 摘要条数。

    环境变量: ``BUCKET_SUMMARY_MAX_FILES_PER_BATCH``，默认 ``30``。
    """
    return _env_int(
        "BUCKET_SUMMARY_MAX_FILES_PER_BATCH",
        DEFAULT_BUCKET_SUMMARY_MAX_FILES_PER_BATCH,
    )


def bucket_summary_map_max_workers() -> int:
    """桶级 Map 阶段并行调用 LLM 的最大线程数。

    环境变量: ``BUCKET_SUMMARY_MAP_MAX_WORKERS``，默认 ``10``。
    """
    return _env_int(
        "BUCKET_SUMMARY_MAP_MAX_WORKERS",
        DEFAULT_BUCKET_SUMMARY_MAP_MAX_WORKERS,
    )


def module_files_group_system_prompt_reserve() -> int:
    """预留给 system prompt 的字符估算值。

    环境变量: ``MODULE_FILES_GROUP_SYSTEM_PROMPT_RESERVE``，默认 ``8000``。

    当前切分逻辑主要依据 ``module_files_group_max_input_chars`` 约束 human 内容；
    本常量供后续若要做「system + human 总预算」时扩展使用。
    """
    return _env_int(
        "MODULE_FILES_GROUP_SYSTEM_PROMPT_RESERVE",
        DEFAULT_SYSTEM_PROMPT_RESERVE,
    )


def format_file_entry_for_group(entry: Dict[str, str], index: int) -> str:
    """将单条文件条目格式化为分组 LLM 可识别的文本行。

    Args:
        entry: 必须含 ``file_path``、``file_summary``。
        index: 行首序号（从 1 开始），与历史 ``File N. path，summary`` 格式一致。

    Returns:
        例如 ``File 3. pkg/order/handler.go，本文件负责订单 API...``
    """
    return f"File {index}. {entry['file_path']}，{entry['file_summary']}"


def estimate_file_entry_chars(entry: Dict[str, str], index: int) -> int:
    """估算单条文件条目在分组 prompt 中占用的字符数。

    用于 ``chunk_entries_by_budget`` 贪心装箱；序号随批内位置变化会影响长度，
    因此必须传入该条目在**当前批内**的 index。
    """
    return len(format_file_entry_for_group(entry, index))


def format_entries_for_group_llm(entries: List[Dict[str, str]]) -> str:
    """将多条文件条目拼接为分组 LLM 的 human 消息正文。

    块之间以 ``\\n\\n`` 分隔，与 ``format_file_analysis_with_file_summary`` 输出兼容。
    """
    parts = [
        format_file_entry_for_group(entry, i + 1)
        for i, entry in enumerate(entries)
    ]
    return "\n\n".join(parts)


def total_entries_chars(entries: List[Dict[str, str]]) -> int:
    """估算全量文件条目列表的总字符数（按全局序号 1..N 计算）。

    用于日志 ``[文件分组|ModuleFilesGroup] summary字符=...`` 与单批短路判断。
    """
    return sum(estimate_file_entry_chars(entry, i + 1) for i, entry in enumerate(entries))


def chunk_entries_by_budget(
    entries: List[Dict[str, str]],
    max_chars: int,
    max_files: int,
) -> List[List[Dict[str, str]]]:
    """Map 阶段：将文件条目贪心装箱为多个批次。

    约束（**同时**满足，先触顶者开新批）:

    - 每批格式化后的字符数不超过 ``max_chars``
    - 每批文件数不超过 ``max_files``

    策略:

    - 先按 ``file_path`` 排序，使同目录/前缀的文件尽量落在同一批，
      降低跨批语义割裂概率（不能保证消除，靠后续 Merge 阶段弥补）。
    - 贪心累加；装不下时封存当前批并开始新批。

    Args:
        entries: ``[{file_path, file_summary}, ...]``
        max_chars: 通常取 ``module_files_group_max_input_chars()``
        max_files: 通常取 ``module_files_group_max_files_per_batch()``

    Returns:
        二维列表，外层每个元素是一批文件条目，例如 ``[[e1,e2],[e3]]``。
    """
    if not entries:
        return []

    sorted_entries = sorted(entries, key=lambda e: e.get("file_path", ""))
    chunks: List[List[Dict[str, str]]] = []
    current: List[Dict[str, str]] = []
    current_chars = 0

    for entry in sorted_entries:
        next_index = len(current) + 1
        entry_chars = estimate_file_entry_chars(entry, next_index)
        # 批内第二条起，条目之间有 ``\n\n`` 分隔符（2 字符）
        separator = 2 if current else 0
        would_exceed_chars = bool(
            current and current_chars + separator + entry_chars > max_chars
        )
        would_exceed_files = len(current) >= max_files

        if current and (would_exceed_chars or would_exceed_files):
            chunks.append(current)
            current = []
            current_chars = 0
            # 新批第一条的序号为 1
            entry_chars = estimate_file_entry_chars(entry, 1)

        current.append(entry)
        current_chars += (2 if len(current) > 1 else 0) + entry_chars

    if current:
        chunks.append(current)

    return chunks


def chunk_file_paths_by_budget(
    file_paths: List[str],
    path_chars: Dict[str, int],
    max_chars: int,
    max_files: int,
) -> List[List[str]]:
    """semantic_domains_analyse Map 阶段：按文件路径贪心装箱。

    Args:
        file_paths: 待分析的文件路径列表。
        path_chars: 每个路径格式化后的字符数（由调用方预计算）。
        max_chars: 单批 human 消息字符预算。
        max_files: 单批最多文件数。

    Returns:
        二维列表，每内层列表是一批文件路径。
    """
    if not file_paths:
        return []

    sorted_paths = sorted(file_paths)
    chunks: List[List[str]] = []
    current: List[str] = []
    current_chars = 0

    for path in sorted_paths:
        entry_chars = path_chars.get(path, len(path))
        separator = 2 if current else 0
        would_exceed_chars = bool(
            current and current_chars + separator + entry_chars > max_chars
        )
        would_exceed_files = len(current) >= max_files

        if current and (would_exceed_chars or would_exceed_files):
            chunks.append(current)
            current = []
            current_chars = 0

        current.append(path)
        current_chars += (2 if len(current) > 1 else 0) + entry_chars

    if current:
        chunks.append(current)

    return chunks


def total_file_paths_chars(file_paths: List[str], path_chars: Dict[str, int]) -> int:
    """估算文件路径列表格式化后的总字符数（块间 ``\\n\\n`` 分隔）。"""
    if not file_paths:
        return 0
    total = sum(path_chars.get(p, len(p)) for p in file_paths)
    if len(file_paths) > 1:
        total += 2 * (len(file_paths) - 1)
    return total


def normalize_semantic_domain_name(name: str) -> str:
    """语义域名称归一化，用于确定性同名合并。"""
    return re.sub(r"\s+", "", (name or "").strip().lower())


def format_semantic_domain_for_merge(domain: Dict[str, Any]) -> Dict[str, Any]:
    """清洗单个 semantic_domains 元素，供合并 LLM 输入。"""
    concepts = []
    for concept in domain.get("core_concepts") or []:
        if not isinstance(concept, dict):
            continue
        files = concept.get("supporting_files") or []
        if not isinstance(files, list):
            files = [str(files)] if files else []
        clean_files = [str(f).strip() for f in files if str(f).strip()]
        concepts.append({
            "name": concept.get("name", ""),
            "description": concept.get("description", ""),
            "supporting_files": clean_files,
        })
    return {
        "domain_name": domain.get("domain_name", ""),
        "domain_tag": domain.get("domain_tag", ""),
        "domain_description": domain.get("domain_description", ""),
        "core_concepts": concepts,
    }


def format_semantic_domains_result_for_merge(result: Dict[str, Any]) -> Dict[str, Any]:
    """将单次 semantic_domains_analyse 产出清洗为合并 LLM 输入对象。"""
    domains = result.get("semantic_domains") or []
    if not isinstance(domains, list):
        domains = []
    relations = result.get("inter_domain_relations") or []
    if not isinstance(relations, list):
        relations = []
    return {
        "domain_model_summary": result.get("domain_model_summary", ""),
        "semantic_domains": [
            format_semantic_domain_for_merge(d)
            for d in domains
            if isinstance(d, dict)
        ],
        "inter_domain_relations": relations,
    }


def format_semantic_domains_for_merge_llm(results: List[Dict[str, Any]]) -> str:
    """将多份 partial semantic_domains 结果序列化为合并 LLM human 消息 JSON。"""
    payload = [format_semantic_domains_result_for_merge(r) for r in results]
    return json.dumps(payload, ensure_ascii=False, indent=2)


def estimate_semantic_domains_merge_chars(results: List[Dict[str, Any]]) -> int:
    """估算合并阶段 human 消息的字符数。"""
    return len(format_semantic_domains_for_merge_llm(results))


def chunk_semantic_results_by_budget(
    results: List[Dict[str, Any]],
    max_chars: int,
) -> List[List[Dict[str, Any]]]:
    """Reduce 阶段：partial 结果列表超预算时切分为多片。"""
    if not results:
        return []

    chunks: List[List[Dict[str, Any]]] = []
    current: List[Dict[str, Any]] = []
    current_chars = 0

    for result in results:
        result_chars = len(
            json.dumps(
                format_semantic_domains_result_for_merge(result),
                ensure_ascii=False,
            )
        )
        separator = 2 if current else 0
        if current and current_chars + separator + result_chars > max_chars:
            chunks.append(current)
            current = []
            current_chars = 0
            result_chars = len(
                json.dumps(
                    format_semantic_domains_result_for_merge(result),
                    ensure_ascii=False,
                )
            )

        current.append(result)
        current_chars += (2 if len(current) > 1 else 0) + result_chars

    if current:
        chunks.append(current)

    return chunks


def premerge_semantic_domains_results(
    results: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Reduce 之前：将 domain_name 归一化后相同的语义域确定性合并（无 LLM）。

    合并同一域下的 core_concepts（按 name 去重，合并 supporting_files），
    拼接 domain_model_summary，去重 inter_domain_relations。
    """
    if not results:
        return {
            "domain_model_summary": "",
            "semantic_domains": [],
            "inter_domain_relations": [],
        }
    if len(results) == 1:
        return format_semantic_domains_result_for_merge(results[0])

    merged_domains: Dict[str, Dict[str, Any]] = {}
    domain_order: List[str] = []
    summaries: List[str] = []
    relations: List[Dict[str, Any]] = []
    seen_relations: set[str] = set()

    for result in results:
        formatted = format_semantic_domains_result_for_merge(result)
        summary = (formatted.get("domain_model_summary") or "").strip()
        if summary:
            summaries.append(summary)

        for rel in formatted.get("inter_domain_relations") or []:
            if not isinstance(rel, dict):
                continue
            rel_key = json.dumps(rel, ensure_ascii=False, sort_keys=True)
            if rel_key not in seen_relations:
                seen_relations.add(rel_key)
                relations.append(rel)

        for domain in formatted.get("semantic_domains") or []:
            key = (
                normalize_semantic_domain_name(domain.get("domain_name"))
                or normalize_semantic_domain_name(domain.get("domain_tag"))
                or "__unnamed__"
            )
            if key not in merged_domains:
                merged_domains[key] = {
                    "domain_name": domain.get("domain_name") or "未命名语义域",
                    "domain_tag": domain.get("domain_tag", ""),
                    "domain_description": domain.get("domain_description", ""),
                    "core_concepts": [],
                }
                domain_order.append(key)
                concept_index: Dict[str, Dict[str, Any]] = {}
            else:
                existing = merged_domains[key]
                if domain.get("domain_description") and not existing["domain_description"]:
                    existing["domain_description"] = domain["domain_description"]
                concept_index = {
                    normalize_semantic_domain_name(c.get("name", "")): c
                    for c in existing["core_concepts"]
                    if c.get("name")
                }

            for concept in domain.get("core_concepts") or []:
                cname = concept.get("name", "")
                ckey = normalize_semantic_domain_name(cname) or f"__concept_{len(concept_index)}"
                files = concept.get("supporting_files") or []
                if ckey not in concept_index:
                    concept_index[ckey] = {
                        "name": cname or "未命名概念",
                        "description": concept.get("description", ""),
                        "supporting_files": list(files),
                    }
                    merged_domains[key]["core_concepts"].append(concept_index[ckey])
                else:
                    existing_concept = concept_index[ckey]
                    if concept.get("description") and not existing_concept.get("description"):
                        existing_concept["description"] = concept["description"]
                    seen_files = set(existing_concept.get("supporting_files") or [])
                    for f in files:
                        if f and f not in seen_files:
                            existing_concept.setdefault("supporting_files", []).append(f)
                            seen_files.add(f)

    return {
        "domain_model_summary": "；".join(summaries),
        "semantic_domains": [merged_domains[k] for k in domain_order],
        "inter_domain_relations": relations,
    }


def normalize_module_group_name(name: str) -> str:
    """组名归一化：去空白、转小写，用于确定性同名合并的 key。

    例如 ``「订单管理」`` 与 ``订单 管理`` 归一化后相同。
    """
    return re.sub(r"\s+", "", (name or "").strip().lower())


def format_group_for_merge_json(group: Dict[str, Any]) -> Dict[str, Any]:
    """将单个 ``group_with_files`` 元素清洗为合并 LLM 输入 JSON 对象。

    - 剥离 ``files`` 中 LLM 可能误带的 ``File N. `` 前缀
    - 重算 ``file_count`` 与清洗后路径列表一致

    合并阶段**故意不包含** ``file_summary``，避免 Reduce 输入再次膨胀。
    """
    files = group.get("files") or []
    if not isinstance(files, list):
        files = [str(files)] if files else []
    clean_files = []
    for f in files:
        path = re.sub(r"^File\s+\d+\.\s*", "", str(f).strip())
        if path:
            clean_files.append(path)
    return {
        "module_name": group.get("module_name", ""),
        "business_description": group.get("business_description", ""),
        "files": clean_files,
        "file_count": len(clean_files),
    }


def format_groups_for_merge_llm(groups: List[Dict[str, Any]]) -> str:
    """将多组 ``group_with_files`` 序列化为合并 LLM 的 human 消息 JSON 字符串。"""
    payload = [format_group_for_merge_json(g) for g in groups]
    return json.dumps(payload, ensure_ascii=False, indent=2)


def estimate_groups_merge_chars(groups: List[Dict[str, Any]]) -> int:
    """估算合并阶段 human 消息的字符数，用于判断是否需继续切分组列表。"""
    return len(format_groups_for_merge_llm(groups))


def chunk_groups_by_budget(
    groups: List[Dict[str, Any]],
    max_chars: int,
) -> List[List[Dict[str, Any]]]:
    """Reduce 阶段：当组列表 JSON 超过预算时，切分为多片分别调用合并 LLM。

    与 ``chunk_entries_by_budget`` 类似，采用贪心装箱；每个元素是一个
    ``group_with_files`` 字典（含 module_name、files 等）。

    Args:
        groups: 各 Map 批次产出的组列表摊平后的结果
        max_chars: 与 Map 阶段相同的字符预算

    Returns:
        二维列表，每片将独立调用一次 ``_invoke_merge_groups_llm``，
        多片结果再递归合并。
    """
    if not groups:
        return []

    chunks: List[List[Dict[str, Any]]] = []
    current: List[Dict[str, Any]] = []
    current_chars = 0

    for group in groups:
        group_chars = len(
            json.dumps(format_group_for_merge_json(group), ensure_ascii=False)
        )
        separator = 2 if current else 0
        if current and current_chars + separator + group_chars > max_chars:
            chunks.append(current)
            current = []
            current_chars = 0
            group_chars = len(
                json.dumps(format_group_for_merge_json(group), ensure_ascii=False)
            )

        current.append(group)
        current_chars += (2 if len(current) > 1 else 0) + group_chars

    if current:
        chunks.append(current)

    return chunks


def parse_semantic_files_content(content: str) -> List[str]:
    """从富文本 files_summary 中解析文件路径列表（legacy 字符串入参）。"""
    if not content or not content.strip():
        return []

    paths: List[str] = []
    seen: set[str] = set()
    for block in re.split(r"\n\n+", content.strip()):
        first_line = block.strip().split("\n", 1)[0].strip()
        match = _SEMANTIC_FILE_BLOCK_RE.match(first_line)
        if not match:
            continue
        path = match.group(1).strip()
        if path and path not in seen:
            seen.add(path)
            paths.append(path)
    return paths


def parse_file_summary_content(content: str) -> List[Dict[str, str]]:
    """解析 ``format_file_analysis_with_file_summary`` 生成的 legacy 字符串。

    期望格式（块间 ``\\n\\n`` 分隔）::

        File 1. pkg/a.go，文件摘要文本
        File 2. pkg/b.go，另一段摘要

    Args:
        content: 历史 ``module_files_group(content)`` 接口的入参

    Returns:
        结构化条目列表；解析失败或重复路径的条目会被跳过。
        若 content 无法解析出任何条目，返回 ``[]``（调用方会走 fallback 单批逻辑）。
    """
    if not content or not content.strip():
        return []

    entries: List[Dict[str, str]] = []
    seen_paths: set[str] = set()

    for block in re.split(r"\n\n+", content.strip()):
        line = block.strip().replace("\n", " ")
        if not line:
            continue
        match = _FILE_ENTRY_LINE_RE.match(line)
        if not match:
            continue
        file_path = match.group(2).strip()
        file_summary = match.group(3).strip()
        if not file_path or file_path in seen_paths:
            continue
        seen_paths.add(file_path)
        entries.append({"file_path": file_path, "file_summary": file_summary})

    return entries


def premerge_groups_by_exact_name(groups: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Reduce 之前：将 ``module_name`` 归一化后完全相同的组合并（无 LLM）。

    场景: 不同 Map 批次若恰好产出相同组名（如都叫「订单管理」），
    在调用合并 LLM 前先拼接 ``files``，减少合并 LLM 负担与 token 消耗。

    注意: 仅处理**组名完全相同**的情况；「订单管理」与「订单服务」仍交给合并 LLM。

    Args:
        groups: 多个 Map 批次 ``group_with_files`` 摊平后的列表

    Returns:
        去重合并后的组列表，保持首次出现组的顺序。
    """
    merged: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []

    for group in groups:
        formatted = format_group_for_merge_json(group)
        key = normalize_module_group_name(formatted["module_name"]) or "__unnamed__"
        if key not in merged:
            merged[key] = {
                "module_name": formatted["module_name"] or "未命名模块",
                "business_description": formatted["business_description"],
                "files": list(formatted["files"]),
                "file_count": len(formatted["files"]),
            }
            order.append(key)
            continue

        existing = merged[key]
        existing_files = existing["files"]
        seen = set(existing_files)
        for path in formatted["files"]:
            if path not in seen:
                existing_files.append(path)
                seen.add(path)
        if formatted["business_description"] and not existing["business_description"]:
            existing["business_description"] = formatted["business_description"]
        existing["file_count"] = len(existing_files)

    return [merged[key] for key in order]
