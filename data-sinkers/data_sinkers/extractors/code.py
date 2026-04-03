import os
import json
import re
import subprocess
from typing import Dict, Any, Optional, List, Union
from pydantic import BaseModel, Field
from ..api.base import DocumentModel
from .base import CodeAnalyzer
from .code_caller import CodebaseIndexer, convert_to_code_analyzer_format
from ..readers.code.github_reader import GitHubReader
from ..readers.code.gitlab_reader import GitLabReader
from model_sdk import ModelManager
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("code_extractor")


def _local_git_head_sha(repo_dir: str) -> Optional[str]:
    if not repo_dir or not os.path.isdir(repo_dir):
        return None
    try:
        r = subprocess.run(
            ["git", "-C", repo_dir, "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if r.returncode == 0:
            return r.stdout.strip()
    except Exception as e:
        logger.debug("rev-parse HEAD failed for %s: %s", repo_dir, e)
    return None


manager = ModelManager()

llm = manager.get_llm(
    provider=os.getenv("PROVIDER","openai_compatible"),
    api_key=os.getenv("API_KEY"),
    base_url=os.getenv("BASE_URL"),
    model=os.getenv("Model"),
    temperature=0.01,
    extra_body={
        "enable_thinking": False
    },
)

def extract_code(reader, descriptor, repo_type) -> List[DocumentModel]:
    documents: List[DocumentModel] = []
    
    local_repo_dir = reader.query_inner()
    logger.info(f"===========local_repo_dir = {local_repo_dir}")
    
    # 只执行一次代码分析：使用 CodebaseIndexer（更详细的分析）
    codebase_indexer = CodebaseIndexer(llm, max_workers=50, batch_size=50)

    try:
        codebase_index_result = codebase_indexer.index_codebase(local_repo_dir)
        logger.info("Codebase Index completed successfully.")
    except Exception as e:
        logger.error(f"Error during codebase index: {e}")
        codebase_index_result = []  # 失败时使用空列表，继续执行后续逻辑

    # 将 CodebaseIndexer 结果转换为 CodeAnalyzer 格式
    analysis_results = convert_to_code_analyzer_format(codebase_index_result)
    logger.info(f"Converted {len(analysis_results)} files to CodeAnalyzer format")

    # 使用转换后的结果进行 DDD 分析和模块分组
    code_analyzer = CodeAnalyzer(llm, max_workers=50, batch_size=50)
    # 直接使用转换后的 analysis_results，跳过第一阶段分析
    code_analyzer.analysis_results = analysis_results
    
    # 执行分组和 DDD 摘要（不再重复分析文件）
    code_ddd_summary, _, module_files_group_result = code_analyzer.analyze_code_with_existing_results(local_repo_dir)
    
    code_ddd = code_ddd_summary.get("summary") if code_ddd_summary else ""

    logger.info(f"code_extractor, code_ddd = {code_ddd}")

    agent_card = code_analyzer.agent_card(code_ddd)

    fingerprint_associated_info = {
        "ddd": code_ddd,
        "agent_card": agent_card,
        "resolved_head_sha": _local_git_head_sha(local_repo_dir),
    }

    # 为每个模块组创建独立的文档
    if module_files_group_result and "group_with_files" in module_files_group_result:
        for module_group in module_files_group_result["group_with_files"]:
            module_name = module_group.get("module_name", "")
            business_description = module_group.get("business_description", "")
            files = module_group.get("files", [])
            
            # 构建page_content：首先添加模块基本信息
            page_content_parts = [f"模块名称: {module_name}", f"模块业务描述: {business_description}", "\n"]
            summary_parts = [f"模块名称: {module_name}", f"模块业务描述: {business_description}", "\n"]
            
            # 处理每个文件，从analysis_results中查找并提取信息
            for file_path in files:
                # 从analysis_results中查找对应文件的分析结果
                file_analysis = None
                for result in analysis_results:
                    if result.get("file_path") == file_path and result.get("status") == "success":
                        file_analysis = result.get("analysis_result")
                        break
                
                if file_analysis:
                    # 添加文件标题
                    page_content_parts.append(f"=== 文件: {file_path} ===\n\n")
                    summary_parts.append(f"=== 文件: {file_path} ===\n\n")
                    
                    # 添加file_summary
                    if file_summary := file_analysis.get("file_summary"):
                        page_content_parts.append(f"文件摘要: {file_summary}\n\n")
                        summary_parts.append(f"文件摘要: {file_summary}\n\n")
                    
                    # 添加key_functions
                    if key_functions := file_analysis.get("key_functions"):
                        functions_str = "\n".join([f"- {func}" for func in key_functions])
                        page_content_parts.append(f"关键功能:\n{functions_str}")

                    # 添加business_concepts
                    # todo
                    
                    page_content_parts.append("")  # 添加空行分隔不同文件
            
            # 将所有部分拼接成最终的page_content
            page_content = "\n".join(page_content_parts)
            summary = "\n".join(summary_parts)

            module_document = DocumentModel(
                page_content=page_content,
                metadata={
                    "source_type": repo_type,
                    "dd_namespace": descriptor.get('namespace') if descriptor else None,
                    "dd_name": descriptor.get('name') if descriptor else None,
                    "module_name": module_name,
                    "summary": summary,
                    "content_type": "code",
                    "files": files,
                    "file_count": module_group.get("file_count", 0)
                }
            )
            documents.append(module_document)

    return documents, fingerprint_associated_info, codebase_index_result
