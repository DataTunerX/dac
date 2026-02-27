import json
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path
import click
import httpx
import uvicorn
from enum import Enum
import os
import re
import asyncio
import atexit
import signal
from datetime import date, datetime, time, timedelta
from decimal import Decimal
import uuid
import numpy as np
from typing import Annotated, Any, AsyncIterable, Dict, Literal, List, Optional, Union
from pydantic import BaseModel, Field, BeforeValidator
from abc import ABC
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.types import AgentCard, AgentSkill
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import Event, EventQueue
from typing_extensions import override
from langchain_core.prompts.chat import ChatPromptTemplate, HumanMessagePromptTemplate, SystemMessagePromptTemplate
from a2a.types import TaskArtifactUpdateEvent, TaskStatusUpdateEvent, TaskState, TaskStatus, TextPart
from a2a.server.tasks import BasePushNotificationSender, InMemoryPushNotificationConfigStore, InMemoryTaskStore
from a2a.server.tasks import TaskUpdater
from a2a.utils import new_agent_text_message, new_task, new_text_artifact
from .client.redis_registry import RedisRegistry, HeartbeatService
from model_sdk import ModelManager
from langchain_core.messages import SystemMessage, HumanMessage
from .client.dataservices_client import DataServicesClient
from .schema import ROLE_TYPE, AgentState, Memory, Message
from .prompts import (  
    REQUERY_PROMPT_ZH,
    OBSERVE_PROMPT_COMMON_ZH,
    LOCATE_FILES,
    OBSERVE_LOCATE_FILES,
    SEARCH_CODE_SEGMENTS_PROMPT,
    ANSWER_WITH_CODE_PROMPT,
    EXTRACT_KEYWORDS_PROMPT,
    QUICK_RELEVANCE_CHECK_PROMPT
)
from .tools.extract_code_by_lines import read_file_from_code_repo, read_file_with_context, smart_read_code
from langfuse import get_client, Langfuse
from langfuse.langchain import CallbackHandler

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)

logger = logging.getLogger(__name__)

# Initialize Langfuse client
langfuse = get_client()

langfuse_auth_check = os.getenv('LANGFUSE_AUTH_CHECK',"disable")
if langfuse_auth_check == "enable":
    # Verify connection
    if langfuse.auth_check():
        logger.info("Langfuse client is authenticated and ready!")
    else:
        logger.error("Authentication failed. Please check your credentials and host.")

# Initialize Langfuse CallbackHandler for Langchain (tracing)
langfuse_handler = CallbackHandler()

class BaseAgent(BaseModel, ABC):
    """Base class for agents."""

    model_config = {
        'arbitrary_types_allowed': True,
        'extra': 'allow',
    }

    agent_name: str = Field(
        description='The name of the agent.',
    )

    description: str = Field(
        description="A brief description of the agent's purpose.",
    )

    content_types: list[str] = Field(description='Supported content types.')

class TaskAnalyze(BaseModel):

    task: Optional[str] = Field(
        description='The name of  current task description.'
    )

    conclusion: Optional[str] = Field(
        description='whether the answer meet your question.'
    )

class LLMResult(BaseModel):

    answer: Optional[str] = Field(
        description='The answer of llm for user question.'
    )

    conclusion: Optional[str] = Field(
        description='whether the answer meet your question.'
    )

    requery: Optional[str] = Field(
        description='The regenerated new user query.'
    )

class RequeryResult(BaseModel):

    requery: Optional[str] = Field(
        description='The new query for user question.'
    )

    conclusion: Optional[str] = Field(
        description='whether the answer meet your question.'
    )

class ObserveResult(BaseModel):

    reason: Optional[str] = Field(
        description='The reason for answer.'
    )

    conclusion: Optional[str] = Field(
        description='whether the answer meet your question.'
    )

class TaskStatus(BaseModel):

    id: int = Field(description='Sequential ID for the task.')

    description: str = Field(
        description='description of subtask'
    )

    agent: str = Field(
        description='agent name of the task to be executed.'
    )

    answer: str = Field(
        description='answer of the task.'
    )

    status: str = Field(
        description='the status of the task to be executed.'
    )

class TaskStatusList(BaseModel):
    """Represents a list of tasks."""
    
    tasks: List[TaskStatus] = Field(description='List of tasks')

class StepStatus(BaseModel):

    id: int = Field(description='Sequential ID for the steps.')

    query: str = Field(
        description='description of subtask'
    )

    answer: str = Field(
        description='answer of the step.'
    )

class StepStatusList(BaseModel):
    """Represents a list of steps."""
    
    steps: List[StepStatus] = Field(description='List of steps')

class FileLocationResult(BaseModel):
    """
    基于业务意图的代码文件定位结果模型
    """
    
    knowledge_files: List['KnowledgeFiles'] = Field(
        default_factory=list,
        description="知识ID与文件的映射列表，清晰展示每个知识文档包含哪些定位到的文件。"
    )

    intent_analysis: str = Field(
        description="对用户真实业务意图的理解及其背后的逻辑链路拆解，阐述‘为什么要找这些文件’。"
    )
    
    reasoning_path: str = Field(
        description="从触发点到执行点的逻辑推演过程，描述文件之间的调用、依赖或数据流转关系。"
    )
    
    def get_all_files(self, unique: bool = True) -> List[str]:
        """获取所有定位到的文件列表
        
        Args:
            unique: 是否去重，默认 True
        
        Returns:
            文件路径列表
        """
        all_files = []
        for kf in self.knowledge_files:
            all_files.extend(kf.files)
        if unique:
            # 去重并保持顺序
            seen = set()
            return [f for f in all_files if not (f in seen or seen.add(f))]
        return all_files
    
    def get_all_knowledge_ids(self, unique: bool = True) -> List[str]:
        """获取所有知识ID列表
        
        Args:
            unique: 是否去重，默认 True
        """
        ids = [kf.knowledge_id for kf in self.knowledge_files]
        if unique:
            seen = set()
            return [i for i in ids if not (i in seen or seen.add(i))]
        return ids

class KnowledgeFiles(BaseModel):
    """知识ID与其关联文件的映射"""
    knowledge_id: str = Field(description="知识文档的ID")
    files: List[str] = Field(default_factory=list, description="该知识ID下定位到的文件列表")


class AuditResult(BaseModel):
    """
    表示对单个文件的审计结果，判断其是否符合业务逻辑层级。
    """
    knowledge_id: str = Field(
        description="知识库中的 ID 或模块标识符"
    )
    file_path: str = Field(
        description="被审核文件的完整路径"
    )
    action: Literal["KEEP", "DISCARD"] = Field(
        description="审计动作：KEEP 表示保留该文件，DISCARD 表示剔除该文件"
    )
    logic_score: int = Field(
        ge=0, le=10, 
        description="逻辑匹配得分 (0-10)，分数越高代表该文件与用户意图的职责层级越契合"
    )
    reasoning: str = Field(
        description="基于职责层级（Orchestrator/Worker）和业务链条解释保留或剔除的深层原因"
    )

class FileAuditResponse(BaseModel):
    """
    针对用户查询意图，对初步筛选文件进行二次审计后的最终结构化输出。
    """
    intent_reconstruction: str = Field(
        description="使用架构语言（如：宏观编排层、底层执行层等）重新描述用户的核心意图及其所处的系统层级"
    )
    audit_results: List[AuditResult] = Field(
        description="对每个候选文件进行逻辑审查的结果列表"
    )
    final_context_summary: str = Field(
        description="说明保留下来的文件集如何协同工作，共同形成解释用户问题的逻辑闭环"
    )
    
    def get_kept_files(self, unique: bool = True) -> List[str]:
        """获取所有保留的文件列表（去重）"""
        files = [ar.file_path for ar in self.audit_results if ar.action == "KEEP"]
        if unique:
            seen = set()
            return [f for f in files if not (f in seen or seen.add(f))]
        return files
    
    def get_discarded_files(self, unique: bool = True) -> List[str]:
        """获取所有剔除的文件列表（去重）"""
        files = [ar.file_path for ar in self.audit_results if ar.action == "DISCARD"]
        if unique:
            seen = set()
            return [f for f in files if not (f in seen or seen.add(f))]
        return files


# ==================== Codebase Indexer 分析结果相关模型 ====================

# line_no 字段的类型：兼容 indexer 返回 int 或 str 的情况
StrLineNo = Annotated[Optional[str], BeforeValidator(lambda v: str(v) if v is not None else None)]


class CodeAttribute(BaseModel):
    """代码属性/字段"""
    name: str = Field(description="属性名")
    type_name: Optional[str] = Field(default=None, alias="type", description="数据类型")
    business_meaning: Optional[str] = Field(default=None, description="属性的业务含义")
    is_identifier: Optional[bool] = Field(default=False, description="是否是唯一标识符")
    constraints: Optional[str] = Field(default=None, description="业务约束")
    line_no: StrLineNo = Field(default=None, description="在文件中的行号")


class CodeFunction(BaseModel):
    """代码函数/方法"""
    name: str = Field(description="方法/函数名")
    purpose: Optional[str] = Field(default=None, description="方法的业务目的")
    input_semantics: Optional[str] = Field(default=None, description="输入参数的业务含义")
    output_semantics: Optional[str] = Field(default=None, description="返回值的业务含义")
    business_action: Optional[str] = Field(default=None, description="执行的核心业务动作")
    line_no: StrLineNo = Field(default=None, description="在文件中的行号范围，如 100-160")
    calls_to: List[str] = Field(default_factory=list, description="该方法内部调用的其他方法/函数名列表")


class CodeEntity(BaseModel):
    """代码实体（类/对象）"""
    name: str = Field(description="对象或类的名称")
    business_meaning: Optional[str] = Field(default=None, description="详细的业务含义解释")
    details: Optional[str] = Field(default=None, description="核心属性的业务含义")
    line_no: StrLineNo = Field(default=None, description="实体在文件中的行号范围")
    attributes: List[CodeAttribute] = Field(default_factory=list, description="属性列表")
    functions: List[CodeFunction] = Field(default_factory=list, description="方法列表")


class ApiEndpoint(BaseModel):
    """API 端点"""
    method: Optional[str] = Field(default=None, description="HTTP 方法，如 GET, POST")
    path: Optional[str] = Field(default=None, description="API 路径")
    request: Optional[str] = Field(default=None, description="请求参数结构体")
    response: Optional[str] = Field(default=None, description="响应结构体")
    business_summary: Optional[str] = Field(default=None, description="接口的业务功能描述")
    file: Optional[str] = Field(default=None, description="API 所在的文件路径")
    line_no: StrLineNo = Field(default=None, description="在文件中的行号范围")


class CodeDeepAnalysis(BaseModel):
    """代码深度分析结果"""
    file_summary: Optional[str] = Field(default=None, description="文件的核心职责概述")
    file_path: Optional[str] = Field(default=None, description="文件全路径")
    dependence: Optional[str] = Field(default=None, description="代码文件中的导入依赖信息")
    has_api_endpoints: Optional[bool] = Field(default=False, description="是否包含 API 端点定义")
    entities: List[CodeEntity] = Field(default_factory=list, description="实体列表")
    global_functions: List[CodeFunction] = Field(default_factory=list, description="全局函数列表")
    api_endpoints: List[ApiEndpoint] = Field(default_factory=list, description="API 端点列表")


class RelevantCodeSegment(BaseModel):
    """与用户问题相关的代码片段"""
    file_path: str = Field(description="文件路径")
    segment_type: str = Field(description="片段类型：entity, function, api_endpoint, global_function")
    name: str = Field(description="代码元素名称")
    line_no: str = Field(description="行号范围，如 100-160")
    relevance_reason: str = Field(description="与用户问题相关的原因")
    business_meaning: Optional[str] = Field(default=None, description="业务含义")


class CodeSearchResult(BaseModel):
    """代码搜索结果"""
    query: str = Field(description="用户查询")
    intent_analysis: str = Field(description="对用户意图的分析")
    relevant_segments: List[RelevantCodeSegment] = Field(default_factory=list, description="相关代码片段列表")
    summary: str = Field(description="搜索结果总结")


class CodebaseIndex:
    """
    代码库索引 - 提供 grep-like 搜索和依赖追踪能力
    
    功能：
    1. 加载整个 repo 的文件分析结果到内存
    2. 提供关键字搜索（类似 grep）
    3. 解析和追踪依赖关系
    4. 提供调用链分析
    """
    
    def __init__(self):
        # 文件路径 -> CodeDeepAnalysis 的映射
        self.file_index: Dict[str, CodeDeepAnalysis] = {}
        # 函数名 -> [(文件路径, 函数对象, 所属实体名)] 的映射
        self.function_index: Dict[str, List[tuple]] = {}
        # 实体名 -> [(文件路径, 实体对象)] 的映射
        self.entity_index: Dict[str, List[tuple]] = {}
        # API 路径 -> [(文件路径, API端点对象)] 的映射
        self.api_index: Dict[str, List[tuple]] = {}
        # 文件依赖关系：文件路径 -> 依赖的文件列表
        self.dependency_graph: Dict[str, List[str]] = {}
        # 反向依赖：文件路径 -> 被哪些文件依赖
        self.reverse_dependency: Dict[str, List[str]] = {}
        # 函数级调用图：(文件路径, 函数名) -> [(目标文件路径, 目标函数名)] 的映射
        self.function_call_graph: Dict[str, List[Dict[str, str]]] = {}
        # 函数级反向调用图：(目标函数全名) -> [(调用方文件路径, 调用方函数名)]
        self.function_reverse_call_graph: Dict[str, List[Dict[str, str]]] = {}
        # 原始记录
        self.raw_records: List[Dict[str, Any]] = []
        
    def load_from_records(self, records: List[Dict[str, Any]]) -> None:
        """
        从 codebase indexer 记录加载数据到索引
        
        Args:
            records: codebase indexer 记录列表
        """
        self.raw_records = records
        self.file_index.clear()
        self.function_index.clear()
        self.entity_index.clear()
        self.api_index.clear()
        self.dependency_graph.clear()
        self.reverse_dependency.clear()
        self.function_call_graph.clear()
        self.function_reverse_call_graph.clear()
        
        for record in records:
            filepath = record.get("filepath", "")
            analysis_str = record.get("code_deep_analysis", "")
            
            if not analysis_str:
                continue
                
            try:
                data = json.loads(analysis_str)
                analysis = CodeDeepAnalysis(**data)
                analysis.file_path = filepath
                
                # 索引文件
                self.file_index[filepath] = analysis
                
                # 解析依赖关系
                if analysis.dependence:
                    self._parse_dependencies(filepath, analysis.dependence)
                
                # 索引实体和函数
                for entity in analysis.entities:
                    entity_name = entity.name
                    if entity_name:
                        if entity_name not in self.entity_index:
                            self.entity_index[entity_name] = []
                        self.entity_index[entity_name].append((filepath, entity))
                        
                        # 索引实体内的方法
                        for func in entity.functions:
                            func_name = func.name
                            if func_name:
                                if func_name not in self.function_index:
                                    self.function_index[func_name] = []
                                self.function_index[func_name].append((filepath, func, entity_name))
                
                # 索引全局函数
                for func in analysis.global_functions:
                    func_name = func.name
                    if func_name:
                        if func_name not in self.function_index:
                            self.function_index[func_name] = []
                        self.function_index[func_name].append((filepath, func, None))
                
                # 索引 API 端点
                for endpoint in analysis.api_endpoints:
                    api_key = f"{endpoint.method} {endpoint.path}" if endpoint.method else endpoint.path
                    if api_key:
                        if api_key not in self.api_index:
                            self.api_index[api_key] = []
                        self.api_index[api_key].append((filepath, endpoint))
                        
            except (json.JSONDecodeError, Exception) as e:
                logger.warning(f"Failed to parse analysis for {filepath}: {e}")
        
        # 构建函数级调用图
        self._build_function_call_graph()
                
        # 统计依赖图连通情况
        total_dep_edges = sum(len(deps) for deps in self.dependency_graph.values())
        files_with_deps = len(self.dependency_graph)
        files_with_callers = len(self.reverse_dependency)
        total_func_call_edges = sum(len(targets) for targets in self.function_call_graph.values())
        
        logger.info(f"CodebaseIndex loaded: {len(self.file_index)} files, "
                   f"{len(self.function_index)} functions, "
                   f"{len(self.entity_index)} entities, "
                   f"{len(self.api_index)} APIs, "
                   f"dependency graph: {files_with_deps} files with deps, "
                   f"{total_dep_edges} edges, "
                   f"{files_with_callers} files with callers, "
                   f"function call graph: {len(self.function_call_graph)} callers, "
                   f"{total_func_call_edges} call edges")
    
    def _parse_dependencies(self, filepath: str, dependence_str: str) -> None:
        """
        解析依赖字符串，建立依赖图（支持多语言）
        
        支持的语言和格式：
        - Python:  "from src.services.payment import PaymentService" / "import src.models.order"
        - Go:      'import "pkg/util/label"' / 'import ("fmt"; "pkg/config")'
        - Java:    "import com.example.service.OrderService;"
        - JS/TS:   "import { xxx } from './services/order'" / "const x = require('./utils')"
        
        解析出的依赖路径会通过模糊匹配关联到 file_index 中的实际文件。
        """
        if not dependence_str:
            return
            
        raw_dep_paths = []
        lines = dependence_str.split('\n') if '\n' in dependence_str else [dependence_str]
        
        # 根据文件后缀确定语言
        ext = os.path.splitext(filepath)[1].lower()
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            parsed = self._parse_single_import(line, ext)
            raw_dep_paths.extend(parsed)
        
        if not raw_dep_paths:
            return
        
        # 将解析出的原始路径模糊匹配到 file_index 中的实际文件
        resolved_deps = []
        for raw_path in raw_dep_paths:
            matched = self._resolve_dep_path(raw_path, filepath)
            if matched:
                resolved_deps.append(matched)
        
        if resolved_deps:
            self.dependency_graph[filepath] = resolved_deps
            # 建立反向依赖
            for dep in resolved_deps:
                if dep not in self.reverse_dependency:
                    self.reverse_dependency[dep] = []
                if filepath not in self.reverse_dependency[dep]:
                    self.reverse_dependency[dep].append(filepath)
    
    def _parse_single_import(self, line: str, ext: str) -> List[str]:
        """
        解析单行 import 语句，返回原始依赖路径列表
        
        Args:
            line: 单行 import 语句
            ext: 文件扩展名（如 .py, .go, .java, .ts）
            
        Returns:
            原始依赖路径列表（尚未匹配到 file_index）
        """
        results = []
        
        # ========== Python ==========
        # from xxx.yyy import zzz
        if line.startswith('from ') and ' import ' in line:
            module = line.split(' import ')[0].replace('from ', '').strip()
            # 相对导入: from .services import xxx -> services
            module = module.lstrip('.')
            if module:
                results.append(module.replace('.', '/'))
            return results
        
        # import xxx, import xxx.yyy, import xxx as yyy
        if ext == '.py' and line.startswith('import '):
            parts = line.replace('import ', '').strip().split(',')
            for part in parts:
                part = part.strip().split(' as ')[0].strip()
                if part:
                    results.append(part.replace('.', '/'))
            return results
        
        # ========== Go ==========
        # import "pkg/util/label"  /  import ( "fmt"\n"pkg/config" )
        if ext == '.go':
            # 提取所有带引号的路径
            import_paths = re.findall(r'"([^"]+)"', line)
            for imp in import_paths:
                # 跳过 Go 标准库（不含 / 的短名称，如 "fmt", "os", "context"）
                # 但保留项目内部路径（如 "pkg/util/label", "internal/controller"）
                if '/' in imp and not imp.startswith('github.com/') and not imp.startswith('golang.org/'):
                    results.append(imp)
                elif '/' in imp:
                    # 外部依赖，取最后一段作为可能的匹配
                    # 如 "github.com/foo/bar/pkg/xxx" -> 尝试 "pkg/xxx"
                    parts = imp.split('/')
                    # 跳过域名部分（github.com, golang.org 等），取剩余
                    for i, p in enumerate(parts):
                        if p in ('pkg', 'internal', 'cmd', 'api', 'app', 'src'):
                            results.append('/'.join(parts[i:]))
                            break
            return results
        
        # ========== Java ==========
        # import com.example.service.OrderService;
        if ext == '.java' and line.startswith('import '):
            path = line.replace('import ', '').replace('static ', '').rstrip(';').strip()
            # 移除通配符 import com.example.service.*
            if path.endswith('.*'):
                path = path[:-2]
            if path:
                results.append(path.replace('.', '/'))
            return results
        
        # ========== JavaScript / TypeScript ==========
        # import { xxx } from './services/order'
        # import xxx from '../utils/helper'
        # import './styles/global.css'  (side-effect)
        # const xxx = require('./config')
        if ext in ('.js', '.ts', '.tsx', '.jsx', '.mjs'):
            # ES module: import ... from 'xxx'
            from_match = re.search(r"""from\s+['"](.+?)['"]""", line)
            if from_match:
                imp = from_match.group(1)
                if imp.startswith('.'):  # 相对路径
                    results.append(re.sub(r'^\./', '', re.sub(r'^\.\./', '', imp)))
                else:  # node_modules，跳过
                    pass
                return results
            
            # Side-effect import: import './styles/global.css'（没有 from 关键字）
            side_effect_match = re.match(r"""^import\s+['"](.+?)['"]""", line)
            if side_effect_match:
                imp = side_effect_match.group(1)
                if imp.startswith('.'):
                    results.append(re.sub(r'^\./', '', re.sub(r'^\.\./', '', imp)))
                return results
            
            # CommonJS: require('xxx')
            require_match = re.search(r"""require\s*\(\s*['"](.+?)['"]\s*\)""", line)
            if require_match:
                imp = require_match.group(1)
                if imp.startswith('.'):
                    results.append(re.sub(r'^\./', '', re.sub(r'^\.\./', '', imp)))
                return results
        
        # ========== Rust ==========
        # use crate::services::payment_service;
        # use crate::models::order::Order;
        # use super::config;
        # mod repository;
        if ext == '.rs':
            # use crate::xxx::yyy  /  use super::xxx
            use_match = re.match(r'^use\s+(crate|super|self)::(.+?)(\s+as\s+\w+)?;', line)
            if use_match:
                path = use_match.group(2)
                # 去掉 {A, B} 多导入部分，取路径前缀
                path = re.sub(r'::\{.*\}', '', path)
                # 去掉末尾的具体类型名（取模块路径）
                parts = path.split('::')
                results.append('/'.join(parts))
                return results
            # mod xxx; -> 本地模块
            mod_match = re.match(r'^(pub\s+)?mod\s+(\w+);', line)
            if mod_match:
                results.append(mod_match.group(2))
                return results
            return results

        # ========== C# ==========
        # using MyApp.Services.PaymentService;
        # using static MyApp.Utils.Helpers;
        if ext == '.cs':
            using_match = re.match(r'^using\s+(static\s+)?([^;=]+);', line)
            if using_match:
                ns = using_match.group(2).strip()
                if not ns.startswith('System') and not ns.startswith('Microsoft'):
                    results.append(ns.replace('.', '/'))
            return results

        # ========== Kotlin ==========
        # import com.shop.service.OrderService
        # import com.shop.model.*
        if ext in ('.kt', '.kts'):
            if line.startswith('import '):
                path = line.replace('import ', '').strip()
                if path.endswith('.*'):
                    path = path[:-2]
                if path and not path.startswith('kotlin.') and not path.startswith('java.'):
                    results.append(path.replace('.', '/'))
            return results

        # ========== Swift ==========
        # import Foundation  (skip system)
        # import MyModule
        # 注意：Swift 的 import 是模块级的，通常只有 import ModuleName
        if ext == '.swift':
            if line.startswith('import '):
                module = line.replace('import ', '').strip()
                # 跳过系统框架
                system_modules = {'Foundation', 'UIKit', 'SwiftUI', 'Combine', 'CoreData',
                                  'CoreGraphics', 'XCTest', 'Darwin', 'Dispatch', 'os'}
                if module and module not in system_modules:
                    results.append(module.replace('.', '/'))
            return results

        # ========== Scala ==========
        # import com.shop.service.OrderService
        # import com.shop.model._
        # import com.shop.{OrderService, PaymentService}
        if ext == '.scala':
            if line.startswith('import '):
                path = line.replace('import ', '').strip()
                # 去掉通配符 / 多导入
                path = re.sub(r'\._$', '', path)
                path = re.sub(r'\.?\{.*\}', '', path)
                if path and not path.startswith('scala.') and not path.startswith('java.'):
                    results.append(path.replace('.', '/'))
            return results

        # ========== PHP ==========
        # use App\Services\PaymentService;
        # require_once 'config/database.php';
        # include 'helpers/utils.php';
        if ext == '.php':
            use_match = re.match(r'^use\s+([^;]+);', line)
            if use_match:
                ns = use_match.group(1).strip().split(' as ')[0].strip()
                if ns and not ns.startswith('Illuminate') and not ns.startswith('Symfony'):
                    results.append(ns.replace('\\', '/'))
                return results
            # require/include
            req_match = re.search(r"""(require|include)(_once)?\s*[\(]?\s*['"](.+?)['"]\s*[\)]?;""", line)
            if req_match:
                path = req_match.group(3)
                results.append(path.lstrip('./'))
                return results
            return results

        # ========== Ruby ==========
        # require 'services/payment_service'
        # require_relative '../models/order'
        if ext == '.rb':
            req_match = re.match(r"""^require(?:_relative)?\s+['"](.+?)['"]""", line)
            if req_match:
                path = req_match.group(1)
                path = re.sub(r'^\./', '', re.sub(r'^\.\./', '', path))
                results.append(path)
            return results

        # ========== C / C++ ==========
        # #include "services/payment_service.h"
        # #include <iostream>  (skip system)
        if ext in ('.c', '.h', '.cpp', '.hpp', '.cc', '.cxx'):
            inc_match = re.match(r'^#\s*include\s+"(.+?)"', line)
            if inc_match:
                results.append(inc_match.group(1))
            return results

        # ========== Dart ==========
        # import 'package:my_app/services/payment_service.dart';
        # import '../models/order.dart';
        if ext == '.dart':
            dart_match = re.match(r"""^import\s+['"](.+?)['"]""", line)
            if dart_match:
                path = dart_match.group(1)
                # package:xxx/yyy.dart -> yyy.dart 部分
                pkg_match = re.match(r'^package:[^/]+/(.+)', path)
                if pkg_match:
                    results.append(pkg_match.group(1))
                elif path.startswith('.'):
                    results.append(re.sub(r'^\./', '', re.sub(r'^\.\./', '', path)))
                else:
                    # 跳过 dart:xxx 系统库
                    if not path.startswith('dart:'):
                        results.append(path)
            return results

        # ========== Vue / Svelte ==========
        # 复用 JS/TS 的解析逻辑
        if ext in ('.vue', '.svelte'):
            from_match = re.search(r"""from\s+['"](.+?)['"]""", line)
            if from_match:
                imp = from_match.group(1)
                if imp.startswith('.'):
                    results.append(re.sub(r'^\./', '', re.sub(r'^\.\./', '', imp)))
                return results
            req_match = re.search(r"""require\s*\(\s*['"](.+?)['"]\s*\)""", line)
            if req_match:
                imp = req_match.group(1)
                if imp.startswith('.'):
                    results.append(re.sub(r'^\./', '', re.sub(r'^\.\./', '', imp)))
                return results
            return results

        # ========== 通用 fallback ==========
        # 对于 from/import 开头但上面没匹配到的，尝试通用提取
        if line.startswith('from ') or line.startswith('import ') or line.startswith('use '):
            # 提取引号内的路径
            quoted = re.findall(r"""['"]([^'"]+)['"]""", line)
            for q in quoted:
                if '/' in q or '.' in q:
                    results.append(q.replace('.', '/'))
            
            # 如果没有引号，尝试提取 from/import/use 后的标识符
            if not results:
                cleaned = line.replace('from ', '').replace('import ', '').replace('use ', '').strip()
                cleaned = cleaned.split(' ')[0].rstrip(';').strip()
                if cleaned and not cleaned.startswith('{') and not cleaned.startswith('('):
                    results.append(cleaned.replace('.', '/'))
        
        return results
    
    def _resolve_dep_path(self, raw_dep: str, source_filepath: str) -> Optional[str]:
        """
        将解析出的原始依赖路径模糊匹配到 file_index 中的实际文件
        
        匹配策略（按优先级）：
        1. 精确匹配：raw_dep 正好是 file_index 中的 key
        2. 后缀匹配：file_index 的 key 以 raw_dep 结尾（加常见后缀）
        3. 文件名匹配：raw_dep 最后一段作为文件名搜索
        
        Args:
            raw_dep: 解析出的原始依赖路径，如 "pkg/util/label", "services/order"
            source_filepath: 发起 import 的源文件路径（用于相对路径解析）
            
        Returns:
            匹配到的 file_index key，未匹配返回 None
        """
        # 常见后缀列表（覆盖所有支持的语言）
        possible_extensions = [
            '', '.py', '.go', '.java', '.js', '.ts', '.tsx', '.jsx',
            '.rs', '.cs', '.kt', '.swift', '.scala', '.php', '.rb',
            '.cpp', '.c', '.h', '.hpp', '.cc', '.cxx',
            '.dart', '.vue', '.svelte',
        ]
        
        # 策略1: 精确匹配（带各种后缀）
        for ext in possible_extensions:
            candidate = raw_dep + ext
            if candidate in self.file_index:
                return candidate
        
        # 策略2: 路径前缀/后缀匹配（要求 raw_dep 包含路径分隔符，避免短名称误匹配）
        # 例如 raw_dep="pkg/util/label" 匹配 "pkg/util/label/label.go"
        # 例如 raw_dep="com/shop/model" 匹配 "src/main/java/com/shop/model/Order.java"
        if '/' in raw_dep:
            for indexed_path in self.file_index:
                # 路径前缀匹配：indexed_path 以 raw_dep 为目录前缀
                if indexed_path.startswith(raw_dep + '/'):
                    return indexed_path
                
                # 路径中间包含匹配：indexed_path 内部包含 /raw_dep/ 目录段
                # 例如 "src/main/java/com/shop/model/Order.java" 包含 "/com/shop/model/"
                if ('/' + raw_dep + '/') in indexed_path:
                    return indexed_path
                
                # 去掉后缀后匹配
                indexed_no_ext = os.path.splitext(indexed_path)[0]
                if indexed_no_ext == raw_dep or indexed_no_ext.endswith('/' + raw_dep):
                    return indexed_path
        
        # 策略3: 从源文件路径推导相对路径
        source_dir = os.path.dirname(source_filepath)
        if source_dir:
            relative = os.path.normpath(os.path.join(source_dir, raw_dep)).replace('\\', '/')
            for ext in possible_extensions:
                candidate = relative + ext
                if candidate in self.file_index:
                    return candidate
            # 相对路径的后缀匹配
            for indexed_path in self.file_index:
                indexed_no_ext = os.path.splitext(indexed_path)[0]
                if indexed_no_ext == relative or indexed_no_ext.endswith('/' + relative):
                    return indexed_path
        
        # 策略4: 最后一段文件名匹配（最宽松，只在其他策略全部失败时使用）
        dep_basename = raw_dep.rstrip('/').split('/')[-1].lower()
        if dep_basename and len(dep_basename) > 2:  # 避免太短的名字造成误匹配
            candidates = []
            for indexed_path in self.file_index:
                indexed_basename = os.path.splitext(os.path.basename(indexed_path))[0].lower()
                if indexed_basename == dep_basename:
                    candidates.append(indexed_path)
            if len(candidates) == 1:
                # 只有唯一匹配时才返回，避免歧义
                return candidates[0]
        
        return None
    
    def _build_function_call_graph(self) -> None:
        """
        根据 CodeFunction.calls_to 数据构建函数级调用图
        
        遍历所有文件中的函数，解析 calls_to 列表，将每个调用关系
        映射到 function_index 中的实际函数，建立：
        - function_call_graph: 调用方 -> 被调用方列表
        - function_reverse_call_graph: 被调用方 -> 调用方列表
        """
        for filepath, analysis in self.file_index.items():
            if analysis is None:
                continue
            
            # 收集当前文件中所有函数
            all_funcs = []
            for entity in analysis.entities:
                for func in entity.functions:
                    all_funcs.append((func, entity.name))
            for func in analysis.global_functions:
                all_funcs.append((func, None))
            
            for func, entity_name in all_funcs:
                if not func.calls_to:
                    continue
                
                caller_key = f"{filepath}::{entity_name}.{func.name}" if entity_name else f"{filepath}::{func.name}"
                
                for call_target in func.calls_to:
                    # 解析调用目标，可能是 "ClassName.method_name" 或 "function_name"
                    resolved = self._resolve_call_target(call_target, filepath)
                    if resolved:
                        if caller_key not in self.function_call_graph:
                            self.function_call_graph[caller_key] = []
                        self.function_call_graph[caller_key].append(resolved)
                        
                        # 构建反向调用图
                        target_key = f"{resolved['file']}::{resolved['entity']}.{resolved['function']}" if resolved.get('entity') else f"{resolved['file']}::{resolved['function']}"
                        if target_key not in self.function_reverse_call_graph:
                            self.function_reverse_call_graph[target_key] = []
                        self.function_reverse_call_graph[target_key].append({
                            "file": filepath,
                            "function": func.name,
                            "entity": entity_name,
                        })
    
    def _resolve_call_target(self, call_target: str, source_file: str) -> Optional[Dict[str, str]]:
        """
        解析函数调用目标，匹配到 function_index 中的实际函数
        
        Args:
            call_target: 调用目标，如 "OrderRepository.save", "validate_order", "self.process"
            source_file: 调用发生的源文件路径
            
        Returns:
            匹配到的函数信息 {"file": filepath, "function": func_name, "entity": entity_name}
            未匹配返回 None
        """
        # 跳过 self 调用的解析（self.xxx -> 在同一文件内查找）
        if call_target.startswith('self.'):
            call_target = call_target[5:]  # 去掉 self. 前缀
        
        # 解析 ClassName.method_name 格式
        if '.' in call_target:
            parts = call_target.rsplit('.', 1)
            entity_name = parts[0]
            method_name = parts[1]
            
            # 先在 function_index 中查找方法名
            if method_name in self.function_index:
                # 优先匹配同一个实体名的
                for fpath, func_obj, ent_name in self.function_index[method_name]:
                    if ent_name and ent_name == entity_name:
                        return {"file": fpath, "function": method_name, "entity": ent_name}
                
                # 其次匹配源文件依赖的文件中的函数
                source_deps = set(self.dependency_graph.get(source_file, []))
                source_deps.add(source_file)  # 包含自身
                for fpath, func_obj, ent_name in self.function_index[method_name]:
                    if fpath in source_deps:
                        return {"file": fpath, "function": method_name, "entity": ent_name}
                
                # 最后返回第一个匹配
                fpath, func_obj, ent_name = self.function_index[method_name][0]
                return {"file": fpath, "function": method_name, "entity": ent_name}
        else:
            # 纯函数名格式
            func_name = call_target
            if func_name in self.function_index:
                # 优先匹配同文件内的函数
                for fpath, func_obj, ent_name in self.function_index[func_name]:
                    if fpath == source_file:
                        return {"file": fpath, "function": func_name, "entity": ent_name}
                
                # 其次匹配源文件依赖的文件中的函数
                source_deps = set(self.dependency_graph.get(source_file, []))
                for fpath, func_obj, ent_name in self.function_index[func_name]:
                    if fpath in source_deps:
                        return {"file": fpath, "function": func_name, "entity": ent_name}
                
                # 最后返回第一个匹配
                fpath, func_obj, ent_name = self.function_index[func_name][0]
                return {"file": fpath, "function": func_name, "entity": ent_name}
        
        return None
    
    def grep(self, pattern: str, case_sensitive: bool = False) -> List[Dict[str, Any]]:
        """
        类似 grep 的关键字搜索（基于 CodeDeepAnalysis 元数据）
        
        搜索范围包括：
        - 文件摘要 (file_summary)
        - 实体名称和业务含义 (entity.name, entity.business_meaning)
        - 函数名称、用途和业务动作 (function.name, function.purpose, function.business_action)
        - API 路径和业务描述 (api.path, api.business_summary)
        
        注意：此方法搜索的是 LLM 生成的结构化元数据，而非原始代码文本。
        
        Args:
            pattern: 搜索模式（支持正则表达式）
            case_sensitive: 是否区分大小写
            
        Returns:
            匹配结果列表，每个结果包含文件路径、匹配类型、匹配内容、行号等
            
        Return Sample:
            # pattern = "订单"
            [
                {
                    'file_path': 'order-service/services/order_service.py',
                    'match_type': 'file_summary',
                    'name': 'order-service/services/order_service.py',
                    'content': '订单服务核心模块，处理订单创建、查询、更新和取消等业务逻辑',
                    'line_no': None
                },
                {
                    'file_path': 'order-service/services/order_service.py',
                    'match_type': 'entity',
                    'name': 'OrderService',
                    'content': '订单服务类，处理所有订单相关业务逻辑',
                    'line_no': '15'
                },
                {
                    'file_path': 'order-service/services/order_service.py',
                    'match_type': 'function',
                    'name': 'create_order',
                    'content': '创建新订单，处理订单创建流程',
                    'line_no': '25'
                },
                {
                    'file_path': 'order-service/controllers/order_controller.py',
                    'match_type': 'api_endpoint',
                    'name': 'POST /api/v1/orders',
                    'content': '创建订单接口',
                    'line_no': '45'
                }
            ]
        """
        results = []
        flags = 0 if case_sensitive else re.IGNORECASE
        
        try:
            regex = re.compile(pattern, flags)
        except re.error:
            # 如果不是有效正则，作为普通文本搜索
            regex = re.compile(re.escape(pattern), flags)
        
        for filepath, analysis in self.file_index.items():
            # 搜索文件摘要
            if analysis.file_summary and regex.search(analysis.file_summary):
                results.append({
                    "file_path": filepath,
                    "match_type": "file_summary",
                    "name": filepath,
                    "content": analysis.file_summary,
                    "line_no": None
                })
            
            # 搜索实体
            for entity in analysis.entities:
                matched = False
                entity_matched_texts = []
                if entity.name and regex.search(entity.name):
                    matched = True
                if entity.business_meaning and regex.search(entity.business_meaning):
                    matched = True
                    entity_matched_texts.append(entity.business_meaning)
                # 修复盲区3: 搜索 entity.details
                if entity.details and regex.search(entity.details):
                    matched = True
                    entity_matched_texts.append(entity.details)
                    
                if matched:
                    # content 优先展示包含匹配词的字段，name 匹配时 fallback
                    entity_content = " | ".join(entity_matched_texts) if entity_matched_texts else (entity.business_meaning or "")
                    results.append({
                        "file_path": filepath,
                        "match_type": "entity",
                        "name": entity.name,
                        "content": entity_content,
                        "line_no": entity.line_no,
                        "entity_obj": entity
                    })
                
                # 修复盲区2: 搜索实体内的属性
                for attr in entity.attributes:
                    attr_matched = False
                    if attr.name and regex.search(attr.name):
                        attr_matched = True
                    if attr.business_meaning and regex.search(attr.business_meaning):
                        attr_matched = True
                        
                    if attr_matched:
                        results.append({
                            "file_path": filepath,
                            "match_type": "attribute",
                            "name": attr.name,
                            "parent_entity": entity.name,
                            "content": attr.business_meaning or "",
                            "line_no": attr.line_no,
                        })
                
                # 搜索实体内的方法
                for func in entity.functions:
                    func_matched = False
                    if func.name and regex.search(func.name):
                        func_matched = True
                    if func.purpose and regex.search(func.purpose):
                        func_matched = True
                    if func.business_action and regex.search(func.business_action):
                        func_matched = True
                    # 修复盲区4: 搜索 input_semantics / output_semantics
                    if func.input_semantics and regex.search(func.input_semantics):
                        func_matched = True
                    if func.output_semantics and regex.search(func.output_semantics):
                        func_matched = True
                        
                    if func_matched:
                        # 修复5: content 优先展示包含匹配关键词的字段
                        matched_texts = []
                        if func.purpose and regex.search(func.purpose):
                            matched_texts.append(func.purpose)
                        if func.business_action and regex.search(func.business_action):
                            matched_texts.append(func.business_action)
                        if func.input_semantics and regex.search(func.input_semantics):
                            matched_texts.append(func.input_semantics)
                        if func.output_semantics and regex.search(func.output_semantics):
                            matched_texts.append(func.output_semantics)
                        # 如果通过 name 匹配, 补上 purpose 作为语义描述
                        if not matched_texts:
                            matched_texts.append(func.purpose or func.business_action or "")
                        content = " | ".join(matched_texts)
                        
                        results.append({
                            "file_path": filepath,
                            "match_type": "function",
                            "name": func.name,
                            "parent_entity": entity.name,
                            "content": content,
                            "line_no": func.line_no,
                            "func_obj": func
                        })
            
            # 搜索全局函数
            for func in analysis.global_functions:
                func_matched = False
                if func.name and regex.search(func.name):
                    func_matched = True
                if func.purpose and regex.search(func.purpose):
                    func_matched = True
                # 修复盲区1: 全局函数增加 business_action 搜索
                if func.business_action and regex.search(func.business_action):
                    func_matched = True
                # 修复盲区4: 全局函数增加 input_semantics / output_semantics 搜索
                if func.input_semantics and regex.search(func.input_semantics):
                    func_matched = True
                if func.output_semantics and regex.search(func.output_semantics):
                    func_matched = True
                    
                if func_matched:
                    # 修复5: content 优先展示包含匹配关键词的字段
                    matched_texts = []
                    if func.purpose and regex.search(func.purpose):
                        matched_texts.append(func.purpose)
                    if func.business_action and regex.search(func.business_action):
                        matched_texts.append(func.business_action)
                    if func.input_semantics and regex.search(func.input_semantics):
                        matched_texts.append(func.input_semantics)
                    if func.output_semantics and regex.search(func.output_semantics):
                        matched_texts.append(func.output_semantics)
                    if not matched_texts:
                        matched_texts.append(func.purpose or func.business_action or "")
                    content = " | ".join(matched_texts)
                    
                    results.append({
                        "file_path": filepath,
                        "match_type": "global_function",
                        "name": func.name,
                        "content": content,
                        "line_no": func.line_no,
                        "func_obj": func
                    })
            
            # 搜索 API 端点
            for endpoint in analysis.api_endpoints:
                api_matched = False
                if endpoint.path and regex.search(endpoint.path):
                    api_matched = True
                if endpoint.business_summary and regex.search(endpoint.business_summary):
                    api_matched = True
                    
                if api_matched:
                    results.append({
                        "file_path": filepath,
                        "match_type": "api_endpoint",
                        "name": f"{endpoint.method} {endpoint.path}",
                        "content": endpoint.business_summary or "",
                        "line_no": endpoint.line_no,
                        "endpoint_obj": endpoint
                    })
        
        return results
    
    def local_file_grep(self, pattern: str, code_paths: List[str], 
                         file_extensions: List[str] = None,
                         max_results_per_file: int = 10) -> List[Dict[str, Any]]:
        """
        在本地文件系统中进行 grep 搜索
        
        优先使用 ripgrep (rg)，如果不可用则使用 Python 实现
        
        Args:
            pattern: 搜索模式
            code_paths: 要搜索的代码路径列表
            file_extensions: 文件扩展名过滤，如 ['.py', '.go', '.java']
            max_results_per_file: 每个文件最多返回的匹配数
            
        Returns:
            匹配结果列表
            
        Return Sample:
            [
                {
                    'file_path': '/code/order-service/services/order_service.py',
                    'line_no': '25',
                    'match_type': 'code_text',
                    'name': 'Line 25',
                    'content': 'def create_order(self, order_data: dict):',
                    'source': 'local_grep'
                },
                {
                    'file_path': '/code/order-service/controllers/order_controller.py',
                    'line_no': '42',
                    'match_type': 'code_text',
                    'name': 'Line 42',
                    'content': '    return self.order_service.create_order(request.json)',
                    'source': 'local_grep'
                }
            ]
        """
        import subprocess
        import json
        import glob
        
        if file_extensions is None:
            file_extensions = [
                '.py', '.go', '.java', '.js', '.ts', '.tsx', '.jsx',
                '.rs', '.cs', '.kt', '.swift', '.scala', '.php', '.rb',
                '.cpp', '.c', '.h', '.hpp', '.dart', '.vue', '.svelte',
            ]
        
        results = []
        
        # 尝试使用 ripgrep
        try:
            for code_path in code_paths:
                if not os.path.exists(code_path):
                    continue
                    
                # 构建 ripgrep 命令
                cmd = [
                    'rg',
                    '--json',
                    '--max-count', str(max_results_per_file),
                    '--ignore-case',
                    '--no-heading',
                ]
                
                # 添加文件类型过滤
                for ext in file_extensions:
                    cmd.extend(['--glob', f'*{ext}'])
                
                cmd.extend([pattern, code_path])
                
                try:
                    result = subprocess.run(
                        cmd, 
                        capture_output=True, 
                        text=True, 
                        timeout=30
                    )
                    
                    for line in result.stdout.strip().split('\n'):
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                            if data.get('type') == 'match':
                                match_data = data['data']
                                results.append({
                                    'file_path': match_data['path']['text'],
                                    'line_no': str(match_data['line_number']),
                                    'match_type': 'code_text',
                                    'name': f"Line {match_data['line_number']}",
                                    'content': match_data['lines']['text'].strip()[:200],
                                    'source': 'local_grep'
                                })
                        except json.JSONDecodeError:
                            continue
                            
                except subprocess.TimeoutExpired:
                    logger.warning(f"ripgrep timeout for {code_path}")
                except FileNotFoundError:
                    # ripgrep 不可用，使用 Python 实现
                    results.extend(self._python_grep(pattern, code_path, file_extensions, max_results_per_file))
                    
        except Exception as e:
            logger.warning(f"ripgrep failed: {e}, falling back to Python grep")
            for code_path in code_paths:
                results.extend(self._python_grep(pattern, code_path, file_extensions, max_results_per_file))
        
        return results
    
    def _python_grep(self, pattern: str, code_path: str, 
                     file_extensions: List[str], max_results_per_file: int) -> List[Dict[str, Any]]:
        """
        Python 实现的 grep（ripgrep 不可用时的备选）
        
        Args:
            pattern: 搜索模式（正则表达式）
            code_path: 代码路径
            file_extensions: 文件扩展名列表
            max_results_per_file: 每个文件最多返回的匹配数
            
        Returns:
            匹配结果列表
            
        Return Sample:
            [
                {
                    'file_path': '/code/payment-service/payment.py',
                    'line_no': '18',
                    'match_type': 'code_text',
                    'name': 'Line 18',
                    'content': 'class PaymentService:',
                    'source': 'local_grep'
                }
            ]
        """
        import glob
        
        results = []
        
        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error:
            regex = re.compile(re.escape(pattern), re.IGNORECASE)
        
        for ext in file_extensions:
            for filepath in glob.glob(os.path.join(code_path, '**', f'*{ext}'), recursive=True):
                try:
                    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                        match_count = 0
                        for line_no, line in enumerate(f, 1):
                            if regex.search(line):
                                results.append({
                                    'file_path': filepath,
                                    'line_no': str(line_no),
                                    'match_type': 'code_text',
                                    'name': f"Line {line_no}",
                                    'content': line.strip()[:200],
                                    'source': 'local_grep'
                                })
                                match_count += 1
                                if match_count >= max_results_per_file:
                                    break
                except Exception as e:
                    logger.debug(f"Failed to read {filepath}: {e}")
                    
        return results
    
    def get_function_by_name(self, func_name: str) -> List[Dict[str, Any]]:
        """根据函数名获取函数信息"""
        results = []
        if func_name in self.function_index:
            for filepath, func, parent_entity in self.function_index[func_name]:
                results.append({
                    "file_path": filepath,
                    "name": func_name,
                    "parent_entity": parent_entity,
                    "line_no": func.line_no,
                    "purpose": func.purpose,
                    "business_action": func.business_action,
                    "func_obj": func
                })
        return results
    
    def get_entity_by_name(self, entity_name: str) -> List[Dict[str, Any]]:
        """根据实体名获取实体信息"""
        results = []
        if entity_name in self.entity_index:
            for filepath, entity in self.entity_index[entity_name]:
                results.append({
                    "file_path": filepath,
                    "name": entity_name,
                    "line_no": entity.line_no,
                    "business_meaning": entity.business_meaning,
                    "functions": [f.name for f in entity.functions],
                    "entity_obj": entity
                })
        return results
    
    def get_callers(self, filepath: str) -> List[str]:
        """获取调用/依赖指定文件的所有文件（谁调用了这个文件）"""
        return self.reverse_dependency.get(filepath, [])
    
    def get_dependencies(self, filepath: str) -> List[str]:
        """获取指定文件依赖的所有文件（这个文件调用了谁）"""
        return self.dependency_graph.get(filepath, [])
    
    def trace_call_chain(self, start_func: str, direction: str = "callees", max_depth: int = 3) -> Dict[str, Any]:
        """
        递归追踪函数级调用链（多级深度，单方向）
        
        优先使用函数级调用图（function_call_graph），当函数级数据不可用时
        自动降级到文件级依赖图（dependency_graph）。
        
        Args:
            start_func: 起始函数名
            direction: "callees" (这个函数调用了谁) 或 "callers" (谁调用了这个函数)
            max_depth: 最大追踪深度
            
        Returns:
            调用链树形结构，每个节点包含函数信息和下一级子节点
        """
        func_info = self.get_function_by_name(start_func)
        if not func_info:
            return {"function": start_func, "not_found": True, "chain": [], "level": "none"}
        
        # 判断是否有函数级调用数据
        has_func_level = len(self.function_call_graph) > 0 or len(self.function_reverse_call_graph) > 0
        
        result = {
            "function": start_func,
            "locations": func_info,
            "level": "function" if has_func_level else "file",
            "chain": []
        }
        
        if has_func_level:
            result["chain"] = self._trace_function_level(start_func, func_info, direction, max_depth)
        else:
            result["chain"] = self._trace_file_level(func_info, direction, max_depth)
        
        return result
    
    def _trace_function_level(self, start_func: str, func_info: List[Dict], 
                               direction: str, max_depth: int) -> List[Dict]:
        """函数级调用链追踪"""
        visited = set()
        
        # 构建起始函数的所有 key
        start_keys = []
        for info in func_info:
            entity = info.get("parent_entity")
            fpath = info["file_path"]
            key = f"{fpath}::{entity}.{start_func}" if entity else f"{fpath}::{start_func}"
            start_keys.append(key)
            visited.add(key)
        
        def _trace_recursive(keys: List[str], depth: int) -> List[Dict]:
            if depth >= max_depth or not keys:
                return []
            
            chain_nodes = []
            for key in keys:
                if direction == "callees":
                    targets = self.function_call_graph.get(key, [])
                else:
                    targets = self.function_reverse_call_graph.get(key, [])
                
                for target in targets:
                    target_file = target["file"]
                    target_func = target["function"]
                    target_entity = target.get("entity")
                    target_key = f"{target_file}::{target_entity}.{target_func}" if target_entity else f"{target_file}::{target_func}"
                    
                    if target_key in visited:
                        continue
                    visited.add(target_key)
                    
                    # 获取目标函数的详细信息
                    func_detail = None
                    if target_func in self.function_index:
                        for fpath, fobj, ent_name in self.function_index[target_func]:
                            if fpath == target_file:
                                func_detail = {
                                    "purpose": fobj.purpose,
                                    "business_action": fobj.business_action,
                                    "line_no": fobj.line_no,
                                    "calls_to": fobj.calls_to,
                                }
                                break
                    
                    node = {
                        "file": target_file,
                        "function": target_func,
                        "entity": target_entity,
                        "depth": depth + 1,
                        "detail": func_detail,
                        "children": _trace_recursive([target_key], depth + 1)
                    }
                    chain_nodes.append(node)
            
            return chain_nodes
        
        return _trace_recursive(start_keys, 0)
    
    def _trace_file_level(self, func_info: List[Dict], direction: str, max_depth: int) -> List[Dict]:
        """文件级调用链追踪（降级方案，当函数级数据不可用时使用）"""
        start_files = set()
        for info in func_info:
            start_files.add(info["file_path"])
        
        visited = set(start_files)
        
        def _trace_recursive(files: set, depth: int) -> List[Dict]:
            if depth >= max_depth or not files:
                return []
            
            chain_nodes = []
            for filepath in files:
                if direction == "callees":
                    next_files_raw = self.get_dependencies(filepath)
                else:
                    next_files_raw = self.get_callers(filepath)
                
                for next_file in next_files_raw:
                    if next_file in visited or next_file not in self.file_index:
                        continue
                    visited.add(next_file)
                    
                    analysis = self.file_index[next_file]
                    related_funcs = []
                    for entity in analysis.entities:
                        for func in entity.functions:
                            related_funcs.append({
                                "name": func.name,
                                "entity": entity.name,
                                "purpose": func.purpose,
                                "line_no": func.line_no
                            })
                    for func in analysis.global_functions:
                        related_funcs.append({
                            "name": func.name,
                            "entity": None,
                            "purpose": func.purpose,
                            "line_no": func.line_no
                        })
                    
                    node = {
                        "file": next_file,
                        "depth": depth + 1,
                        "file_summary": analysis.file_summary,
                        "functions": related_funcs,
                        "children": _trace_recursive({next_file}, depth + 1)
                    }
                    chain_nodes.append(node)
            
            return chain_nodes
        
        return _trace_recursive(start_files, 0)
    
    def search_with_dependencies(self, keywords: List[str], include_deps: bool = True) -> Dict[str, Any]:
        """
        搜索关键字并包含依赖分析
        
        Args:
            keywords: 关键字列表
            include_deps: 是否包含依赖文件
            
        Returns:
            搜索结果，包含直接匹配和依赖关系
        """
        direct_matches = []
        related_files = set()
        
        # 对每个关键字进行搜索
        for keyword in keywords:
            matches = self.grep(keyword)
            for match in matches:
                direct_matches.append(match)
                related_files.add(match["file_path"])
        
        # 获取依赖关系
        dependency_info = {}
        if include_deps:
            for filepath in list(related_files):
                deps = self.get_dependencies(filepath)
                callers = self.get_callers(filepath)
                if deps or callers:
                    dependency_info[filepath] = {
                        "depends_on": deps,
                        "called_by": callers
                    }
                    # 将依赖文件也加入相关文件
                    for dep in deps:
                        if dep in self.file_index:
                            related_files.add(dep)
        
        return {
            "direct_matches": direct_matches,
            "related_files": list(related_files),
            "dependency_info": dependency_info
        }
    
    def extract_search_keywords(self, query: str) -> List[str]:
        """
        从用户查询中提取搜索关键词
        
        提取策略：
        - 中文词提取（连续中文字符，长度>=2）
        - 英文单词提取（连续字母，长度>=2）
        - 驼峰命名拆分（如 createOrder -> create, Order）
        - 下划线命名拆分（如 create_order -> create, order）
        - 过滤常见停用词
        
        Args:
            query: 用户查询字符串
            
        Returns:
            提取的关键词列表（已去重）
        """
        keywords = set()
        
        # 常见停用词（中英文）
        stopwords = {
            # 中文停用词
            '的', '是', '在', '有', '和', '与', '或', '了', '着', '过',
            '这', '那', '什么', '怎么', '如何', '哪里', '哪个', '为什么',
            '可以', '能够', '应该', '需要', '想要', '帮我', '请', '吗',
            '呢', '啊', '吧', '呀', '嘛', '哦', '哈', '啦',
            '代码', '文件', '函数', '方法', '类', '模块', '功能', '实现',
            '查看', '查找', '搜索', '找到', '显示', '获取', '返回',
            # 英文停用词
            'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been',
            'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will',
            'would', 'could', 'should', 'may', 'might', 'must', 'can',
            'this', 'that', 'these', 'those', 'what', 'which', 'who',
            'how', 'where', 'when', 'why', 'if', 'then', 'else',
            'and', 'or', 'but', 'not', 'no', 'yes', 'for', 'to', 'of',
            'in', 'on', 'at', 'by', 'with', 'from', 'as', 'into',
            'code', 'file', 'function', 'method', 'class', 'module',
            'find', 'search', 'show', 'get', 'return', 'please', 'help'
        }
        
        # 1. 提取中文词（连续中文字符，长度>=2）
        chinese_pattern = re.compile(r'[\u4e00-\u9fa5]{2,}')
        chinese_words = chinese_pattern.findall(query)
        for word in chinese_words:
            if word.lower() not in stopwords and len(word) >= 2:
                keywords.add(word)
        
        # 2. 提取英文单词（包括驼峰命名和下划线命名）
        # 先提取完整的英文标识符
        english_pattern = re.compile(r'[a-zA-Z_][a-zA-Z0-9_]*')
        english_words = english_pattern.findall(query)
        
        for word in english_words:
            # 处理下划线命名：create_order -> [create, order]
            if '_' in word:
                parts = word.split('_')
                for part in parts:
                    if part and len(part) >= 2 and part.lower() not in stopwords:
                        keywords.add(part.lower())
                # 同时保留完整词
                if len(word) >= 3 and word.lower() not in stopwords:
                    keywords.add(word.lower())
            else:
                # 处理驼峰命名：createOrder -> [create, Order]
                # 在大写字母前插入分隔符
                camel_parts = re.sub(r'([a-z])([A-Z])', r'\1_\2', word).split('_')
                for part in camel_parts:
                    if part and len(part) >= 2 and part.lower() not in stopwords:
                        keywords.add(part.lower())
                # 同时保留完整词
                if len(word) >= 2 and word.lower() not in stopwords:
                    keywords.add(word.lower())
        
        # 3. 提取数字+字母组合（如 v2, api3）
        alphanumeric_pattern = re.compile(r'[a-zA-Z]+\d+|\d+[a-zA-Z]+')
        alphanumeric_words = alphanumeric_pattern.findall(query)
        for word in alphanumeric_words:
            if len(word) >= 2:
                keywords.add(word.lower())
        
        return list(keywords)
    
    def get_all_files(self) -> List[str]:
        """获取所有索引的文件路径"""
        return list(self.file_index.keys())
    
    def get_file_analysis(self, filepath: str) -> Optional[CodeDeepAnalysis]:
        """获取指定文件的分析结果"""
        return self.file_index.get(filepath)


class AgentState(str, Enum):
    """Agent execution states"""
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    FINISHED = "FINISHED"
    ERROR = "ERROR"

from .code_repo_init import CodeConfig, parse_descriptor_types_json


# ============================================================
# 调用链工具函数
# ============================================================

def _flatten_chain(chain_nodes: list) -> list:
    """
    将调用链树形结构展平为节点列表（广度优先）
    
    Args:
        chain_nodes: trace_call_chain 返回的 chain 列表（树形，每个节点有 children）
    
    Returns:
        展平的节点列表，按深度优先排列
    """
    result = []
    for node in chain_nodes:
        result.append(node)
        children = node.get("children", [])
        if children:
            result.extend(_flatten_chain(children))
    return result


def _format_chain_path(func_name: str, chain_nodes: list, indent: int = 0) -> str:
    """
    将调用链格式化为可读的路径描述
    
    Args:
        func_name: 起始函数名
        chain_nodes: trace_call_chain 返回的 chain 列表
        indent: 缩进层级
        
    Returns:
        格式化的调用路径字符串，如：
        create_order 的调用链:
          -> PaymentService.process_payment (payment_service.py:45-80)
              -> PaymentGateway.charge (gateway.py:20-35)
          -> OrderRepository.save (order_repo.py:15-25)
    """
    if not chain_nodes:
        return ""
    
    lines = []
    if indent == 0:
        lines.append(f"{func_name} 的调用链:")
    
    for node in chain_nodes:
        prefix = "  " * (indent + 1)
        entity = node.get("entity", "")
        func = node.get("function", "")
        fpath = node.get("file", "")
        line_no = (node.get("detail") or {}).get("line_no", "")
        purpose = (node.get("detail") or {}).get("purpose", "")
        
        label = f"{entity}.{func}" if entity else func
        loc = f"{fpath}:{line_no}" if line_no else fpath
        desc = f" - {purpose}" if purpose else ""
        
        lines.append(f"{prefix}-> {label} ({loc}){desc}")
        
        children = node.get("children", [])
        if children:
            child_text = _format_chain_path(func_name, children, indent + 1)
            if child_text:
                # 跳过子级的标题行，只取内容
                for line in child_text.split("\n"):
                    if line.strip().startswith("->"):
                        lines.append("  " + line)
    
    return "\n".join(lines)


class CodeAgent(BaseAgent):
    """Code Agent"""

    def __init__(
        self,
        provider: str = "openai_compatible",
        api_key: str = None,
        base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
        model: str = "qwen2.5-72b-instruct",
        stream: bool = False,
        temperature: float = 0.01,
        data_descriptors:list = None,
        dd_namespace:str = None,
        descriptor_types:list = None,
        data_services_url: str = None,
        query: str = None,
        metadata: dict = None,
        max_steps:int = 5,
        current_tasks_status: TaskStatusList = None,
        current_task_id: int = None,
        code_paths: Dict[str, str] = None,
        codebase_index: 'CodebaseIndex' = None,  # 外部传入的全局索引
        codebase_index_loaded: bool = False  # 索引是否已加载

    ):
        logger.info('Initializing CodeAgent')
        super().__init__(
            agent_name='CodeAgent',
            description='answer user question using yourself knowledge.',
            content_types=['text', 'text/plain'],
        )

        self.manager = ModelManager()
        _extra_body = {"enable_thinking": False} if os.getenv("ENABLE_THINKING_PARAM", "true").strip().lower() not in ("false", "0", "no") else {}
        self.llm = self.manager.get_llm(
            provider=provider,
            api_key=api_key,
            base_url=base_url,
            model=model,
            temperature=temperature,
            stream=stream,
            extra_body=_extra_body,
        )
        self.query=query
        self.original_query=query
        self.data_descriptors = data_descriptors
        self.dd_namespace = dd_namespace
        self.descriptor_types = descriptor_types
        self.data_services_client = DataServicesClient(
            base_url=data_services_url,
            timeout=600,
            use_data_descriptor_header=True,
        )
        self.current_step = 0
        self.state: AgentState = AgentState.IDLE
        self.duplicate_threshold: int = 2
        self.memory = Memory()
        self.old_querys = []
        self.metadata = metadata
        self.max_steps=max_steps
        self.current_tasks_status = current_tasks_status
        self.current_task_id = current_task_id
        self.step_status_list: List[StepStatus] = []
        self.code_paths = code_paths or {}  # 代码仓库的本地路径，key 为配置名称，value 为本地路径
        # 使用外部传入的全局索引，如果没有则创建新的（兼容旧代码）
        self.codebase_index = codebase_index if codebase_index is not None else CodebaseIndex()
        self._codebase_index_loaded = codebase_index_loaded  # 使用外部传入的状态
        logger.info(f"CodeAgent initialized with code_paths: {list(self.code_paths.keys())}, codebase_index_loaded: {self._codebase_index_loaded}")

    @asynccontextmanager
    async def state_context(self, new_state: AgentState):
        """Context manager for safe agent state transitions.

        Args:
            new_state: The state to transition to during the context.

        Yields:
            None: Allows execution within the new state.

        Raises:
            ValueError: If the new_state is invalid.
        """
        if not isinstance(new_state, AgentState):
            raise ValueError(f"Invalid state: {new_state}")

        previous_state = self.state
        self.state = new_state
        try:
            yield
        except Exception as e:
            self.state = AgentState.ERROR
            raise e
        finally:
            self.state = previous_state

    def format_llm_ouput(self, answer) -> dict:
        data_dict = None
    
        try:
            data_dict = json.loads(answer.content)
        except json.JSONDecodeError as e:

            cleaned_content = answer.content.strip()

            if cleaned_content.startswith('```json'):
                cleaned_content = cleaned_content[7:]
            elif cleaned_content.startswith('```'):
                cleaned_content = cleaned_content[3:]
            
            if cleaned_content.endswith('```'):
                cleaned_content = cleaned_content[:-3]
            
            cleaned_content = cleaned_content.strip()
            
            try:
                data_dict = json.loads(cleaned_content)
            except json.JSONDecodeError as e2:
                logger.error(f" === format_llm_ouput, Parsing failed after cleanup.: {e2}")
                try:
                    import ast
                    data_dict = ast.literal_eval(cleaned_content)
                except (ValueError, SyntaxError) as e3:
                    logger.error(f" === format_llm_ouput, ast parsing fail: {e3}")
                    try:
                        cleaned_content = cleaned_content.replace("'", '"')
                        data_dict = json.loads(cleaned_content)
                    except json.JSONDecodeError as e4:
                        logger.error(f" === format_llm_output, secondary parsing failed: {e4}, using default value")
                except Exception as e5:
                    logger.error(f" === format_llm_output, exception occurred during parsing: {e5}, using default value")

        return data_dict


    async def locate_files(self, knowledge: str = ""):
        """
        基于系统全局信息（knowledge）定位与用户查询相关的代码文件
        
        Args:
            knowledge: 系统全局信息，包含模块描述和文件摘要
        
        Returns:
            FileLocationResult: 包含意图分析、推理路径和定位到的文件列表
        """
        system_template = LOCATE_FILES

        human_template = "{query}"

        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        system_prompt = SystemMessagePromptTemplate.from_template(
            template=system_template,
            input_variables=["current_time", "knowledge"],
        )

        human_prompt = HumanMessagePromptTemplate.from_template(human_template)

        chat_prompt = ChatPromptTemplate.from_messages([system_prompt, human_prompt])

        user_id = self.metadata['user_id']
        run_id = self.metadata['run_id']
        trace_id = self.metadata['trace_id']

        answer = None

        chain = chat_prompt | self.llm
        
        with langfuse.start_as_current_span(
            name="codeagent-locate-files",
            trace_context={"trace_id": trace_id}
        ) as span:
            span.update_trace(
                user_id=user_id,
                session_id=run_id,
                input={"query": self.query}
            )

            answer = await chain.ainvoke(
                {"query": self.query, "current_time": current_time, "knowledge": knowledge},
                config={"callbacks": [langfuse_handler]}
            )
         
            span.update_trace(output={"answer": answer})

        langfuse.flush()

        logger.info(f" === CodeAgent.locate_files, answer = {answer}")

        data_dict = self.format_llm_ouput(answer)

        if data_dict is None:
            data_dict = {
                "query": "System error: Unable to process model response",
                "conclusion": "error"
            }

        llm_result = FileLocationResult(**data_dict)

        logger.debug(f" === CodeAgent.locate_files , FileLocationResult.llm_result = {llm_result}")

        return llm_result


    async def observe_locate_files(self, locate_files, knowledge: str = "",):
        """
        审查一次初步选择的块的detail，是不是detail是不是真正的匹配客户的问题，如果匹配就会保留相关的文件，对于不匹配的就去掉第一轮选择的文件。
        
        Args:
            locate_files: 第一轮定位出来的文件信息
            knowledge: 包含了第一轮选择的所有知识块中的detail的连接出来的字符串

        Returns:
            FileLocationResult: 包含意图分析、推理路径和定位到的文件列表
        """
        system_template = OBSERVE_LOCATE_FILES

        human_template = "{query}"

        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        system_prompt = SystemMessagePromptTemplate.from_template(
            template=system_template,
            input_variables=["current_time", "knowledge"],
            partial_variables={"locate_files":locate_files}
        )

        human_prompt = HumanMessagePromptTemplate.from_template(human_template)

        chat_prompt = ChatPromptTemplate.from_messages([system_prompt, human_prompt])

        user_id = self.metadata['user_id']
        run_id = self.metadata['run_id']
        trace_id = self.metadata['trace_id']

        answer = None

        chain = chat_prompt | self.llm
        
        with langfuse.start_as_current_span(
            name="codeagent-observe_locate_files",
            trace_context={"trace_id": trace_id}
        ) as span:
            span.update_trace(
                user_id=user_id,
                session_id=run_id,
                input={"query": self.query}
            )

            answer = await chain.ainvoke(
                {"query": self.query, "current_time": current_time, "knowledge": knowledge},
                config={"callbacks": [langfuse_handler]}
            )
         
            span.update_trace(output={"answer": answer})

        langfuse.flush()

        logger.info(f" === CodeAgent.observe_locate_files, answer = {answer}")

        data_dict = self.format_llm_ouput(answer)

        if data_dict is None:
            data_dict = {
                "query": "System error: Unable to process model response",
                "conclusion": "error"
            }

        llm_result = FileAuditResponse(**data_dict)

        logger.debug(f" === CodeAgent.observe_locate_files , FileAuditResponse.llm_result = {llm_result}")

        return llm_result

    async def invoke_requery(self) -> RequeryResult:

        step_history = self.get_step_history_for_requery()

        system_template = REQUERY_PROMPT_ZH

        human_template = "{query}"

        terminate_json_prompt_instructions_zh: dict = {
            "requery": "新生成的问题...",
            "conclusion": "terminate"
        }

        continue_json_prompt_instructions_zh: dict = {
            "requery": "",
            "conclusion": "continue"
        }

        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        system_prompt = SystemMessagePromptTemplate.from_template(
            template=system_template,
            input_variables=["original_query","history_querys","current_time","step_history"],
            partial_variables={"terminate_fewshots": terminate_json_prompt_instructions_zh, "continue_fewshots": continue_json_prompt_instructions_zh},
        )

        human_prompt = HumanMessagePromptTemplate.from_template(human_template)

        chat_prompt = ChatPromptTemplate.from_messages([system_prompt, human_prompt])

        history_querys = "\n".join([f"query {i+1}: {query}" for i, query in enumerate(self.old_querys)])

        user_id = self.metadata['user_id']
        run_id = self.metadata['run_id']
        trace_id = self.metadata['trace_id']

        answer = None

        chain = chat_prompt | self.llm
        
        with langfuse.start_as_current_span(
            name="code-requery",
            trace_context={"trace_id": trace_id}
        ) as span:
            span.update_trace(
                user_id=user_id,
                session_id=run_id,
                input={"query": self.query}
            )

            answer = await chain.ainvoke(
                {"query": self.query, "original_query": self.original_query,"history_querys": history_querys, "current_time":current_time, "step_history":step_history},
                config={"callbacks": [langfuse_handler]}
            )
         
            span.update_trace(output={"answer": answer})

        langfuse.flush()

        logger.info(f" === CodeAgent.invoke_requery, answer = {answer}")

        data_dict = self.format_llm_ouput(answer)

        if data_dict is None:
            data_dict = {
                "query": "System error: Unable to process model response",
                "conclusion": "error"
            }

        llm_result = RequeryResult(**data_dict)

        logger.debug(f" === CodeAgent.invoke_requery , llm_result = {llm_result}")

        return llm_result

    async def observe_common(self, query, answer, knowledge, skip_llm: bool = True) -> ObserveResult:
        """
        验证回答质量。
        
        Args:
            query: 用户问题
            answer: 生成的回答
            knowledge: 代码相关上下文
            skip_llm: 是否跳过 LLM 验证，默认 True 直接返回通过。
                      设为 False 则走 LLM 判断回答质量。
        """
        if skip_llm:
            logger.info("[observe_common] skip_llm=True, 跳过 LLM 回答质量验证，直接通过")
            return ObserveResult(
                reason="跳过 LLM 验证（skip_llm=True）",
                conclusion="terminate"
            )

        system_template = OBSERVE_PROMPT_COMMON_ZH

        human_template = "question: {query};\n\nanswer:{answer}"

        terminate_json_prompt_instructions_zh: dict = {
            "reason": "满足问题的原因",
            "conclusion": "terminate"
        }

        continue_json_prompt_instructions_zh: dict = {
            "reason": "不满足问题的原因",
            "conclusion": "continue"
        }

        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        system_prompt = SystemMessagePromptTemplate.from_template(
            template=system_template,
            input_variables=["knowledge","current_time"],
            partial_variables={"terminate_fewshots": terminate_json_prompt_instructions_zh, "continue_fewshots": continue_json_prompt_instructions_zh},
        )

        human_prompt = HumanMessagePromptTemplate.from_template(human_template)

        chat_prompt = ChatPromptTemplate.from_messages([system_prompt, human_prompt])

        user_id = self.metadata['user_id']
        run_id = self.metadata['run_id']
        trace_id = self.metadata['trace_id']

        llm_answer = None

        chain = chat_prompt | self.llm
        
        with langfuse.start_as_current_span(
            name="code-observe_common",
            trace_context={"trace_id": trace_id}
        ) as span:
            span.update_trace(
                user_id=user_id,
                session_id=run_id,
                input={"query": query}
            )

            llm_answer = await chain.ainvoke(
                {"query": query, "answer":answer, "knowledge":knowledge, "current_time":current_time},
                config={"callbacks": [langfuse_handler]}
            )
         
            span.update_trace(output={"answer": llm_answer})

        langfuse.flush()

        logger.info(f" === CodeAgent.observe_common, answer = {llm_answer}")

        data_dict = self.format_llm_ouput(llm_answer)

        if data_dict is None:
            data_dict = {
                "reason": "System error: Unable to process model response",
                "conclusion": "error"
            }

        llm_result = ObserveResult(**data_dict)

        logger.debug(f" === CodeAgent.observe_common , llm_result = {llm_result}")

        return llm_result

    def generate_collection_name(self, dd_name: str) -> str:
        """
        Format: namespace_name
        Rule: Replace '-' with '_'
        Returns:
        str: The generated collection_name
        """

        collection_name = f"{self.dd_namespace}_{dd_name}"

        # Replace '-' in namespace with '_'
        collection_name = collection_name.replace('-', '_')
        
        return collection_name

    async def get_all_knowledge_blocks(self):
        """
        从 dataservices 获取所有知识块数据（包含 id, text, metadata_value）。
        用于两阶段知识检索的数据源。

        Return Sample:
            {
              "status": "success",
              "results": {
                "dac_bank": [
                  {
                    "id": "c744cee7-0f5d-4f47-804e-ae385d91afec",
                    "text": "==========系统领域上下文概述==========[领域1: 机构财务状况 (Institutional Financial Position)]业务范围:",
                    "metadata_value": "[领域1: 机构财务状况 "
                  },
                  {
                    "id": "c0f24f66-d0cd-4ace-8fcb-c325dd1657cb",
                    "text": "==========系统领域上下文概述==========[领域1: 机构财务状况 (Institution Financial Status)]业务范围:",
                    "metadata_value": "[领域1: 机构财务状况 "
                  }
                ]
              },
              "errors": null,
              "success_count": 1,
              "failed_count": 0
            }

        """
        logger.info(f"=========get_all_knowledge_blocks, data_descriptors: {self.data_descriptors}")
        try:
            collection_names = [self.generate_collection_name(item) for item in self.data_descriptors]
            logger.info(f"get_all_knowledge_blocks collection_names: {collection_names}")

            await self.data_services_client._create_session()
            result = await self.data_services_client.find_metadata_values_in_collections(
                collection_names=collection_names
            )

            if result.status != "success":
                logger.error(f"find_metadata_values_in_collections failed: {result.errors}")
                return None

            logger.info(f"get_all_knowledge_blocks success, items count: {len(result.get_all_items())}")
            return result

        except Exception as e:
            logger.error(f'An error occurred during get_all_knowledge_blocks: {e}')
            return None
        finally:
            await self.data_services_client.close()

    async def locate_files_with_metadata(self):
        """
        完整的文件定位流程（单阶段，只定位不获取完整知识）：
        1. 从 dataservices 获取 metadata 知识（模块描述和文件摘要）
        2. 调用 locate_files 进行文件定位分析

        Returns:
            FileLocationResult: 包含意图分析、推理路径和定位到的文件列表
        
        Note:
            如需两阶段检索（定位 + 获取完整知识），请使用 two_stage_knowledge_retrieval()
            
        Return Sample:
            # query = "怎么创建订单"
            FileLocationResult(
                knowledge_files=[
                    KnowledgeFiles(
                        knowledge_id="order-service/services/order_service.py",
                        files=[
                            "order-service/services/order_service.py",
                            "order-service/controllers/order_controller.py",
                            "order-service/validators/order_validator.py"
                        ]
                    ),
                    KnowledgeFiles(
                        knowledge_id="order-service/models/order.py",
                        files=[
                            "order-service/models/order.py"
                        ]
                    )
                ],
                intent_analysis="用户想了解订单创建的完整业务流程。订单创建涉及：1) API接口接收请求；2) 服务层处理业务逻辑；3) 数据验证；4) 订单模型定义。需要定位这些环节对应的核心代码文件。",
                reasoning_path="订单创建流程追踪：前端请求 -> order_controller.py (API入口) -> order_service.py (业务逻辑：校验数据、检查库存、计算价格、创建订单) -> order_validator.py (数据校验) -> order.py (订单数据模型)"
            )
            
            # 方法调用示例
            # result = await code_agent.locate_files_with_metadata()
            # all_files = result.get_all_files()  # ['order-service/services/order_service.py', ...]
            # knowledge_ids = result.get_all_knowledge_ids()  # ['order-service/services/order_service.py', 'order-service/models/order.py']
        """
        logger.info(f"=========locate_files_with_metadata, query: {self.query}")
        
        # 获取所有知识块
        knowledge_blocks = await self.get_all_knowledge_blocks()
        
        if not knowledge_blocks:
            logger.warning("No knowledge blocks found, locate_files will run without knowledge")
            return await self.locate_files(knowledge="")
        
        # 提取摘要进行定位
        knowledge = knowledge_blocks.extract_metadata_as_string()
        result = await self.locate_files(knowledge=knowledge)
        
        return result

    async def two_stage_knowledge_retrieval(self):
        """
        两阶段知识检索流程：
        
        第一阶段（粗筛）：
            - 获取所有知识块的 metadata_value（摘要）
            - LLM 根据用户问题定位相关的 knowledge_ids
        
        第二阶段（精取）：
            - 根据第一阶段得到的 knowledge_ids
            - 获取这些 ID 对应的完整知识内容（text 字段）
            - 返回用于后续处理的完整知识

        Returns:
            dict: 包含定位结果、完整知识和原始数据
            
        Return Sample:
            # query = "怎么创建订单"
            {
                'location_result': FileLocationResult(
                    knowledge_files=[
                        KnowledgeFiles(
                            knowledge_id="order-service/services/order_service.py",
                            files=[
                                "order-service/services/order_service.py",
                                "order-service/controllers/order_controller.py"
                            ]
                        ),
                        KnowledgeFiles(
                            knowledge_id="order-service/models/order.py",
                            files=[
                                "order-service/models/order.py",
                                "order-service/validators/order_validator.py"
                            ]
                        )
                    ],
                    intent_analysis="用户想了解订单创建的完整流程，需要定位订单服务的核心方法、API接口、数据模型和验证逻辑",
                    reasoning_path="订单创建流程：API接口(order_controller.py) -> 服务方法(order_service.py) -> 数据验证(order_validator.py) -> 数据模型(order.py)"
                ),
                'full_knowledge': '''
                    === 文件: order-service/services/order_service.py ===
                    文件摘要: 订单服务核心模块，处理订单创建、查询、更新和取消等业务逻辑

                    实体列表:
                      - OrderService (第15行): 订单服务类，处理所有订单相关业务逻辑
                        方法:
                          - create_order (第25行): 创建新订单，处理订单创建流程
                          - get_order_by_id (第78行): 根据ID查询订单详情
                          - update_order_status (第105行): 更新订单状态

                    API 端点:
                      - POST /api/v1/orders (第45行): 创建订单接口
                      - GET /api/v1/orders/{id} (第60行): 查询订单详情接口

                    依赖关系:
                      - imports: order-service/models/order.py, order-service/validators/order_validator.py
                      - calls: PaymentService.process_payment, InventoryService.check_stock

                    === 文件: order-service/models/order.py ===
                    文件摘要: 订单数据模型定义，包含订单实体类和相关枚举

                    实体列表:
                      - Order (第10行): 订单实体，包含订单ID、用户ID、商品列表、金额、状态等核心属性
                      - OrderStatus (第45行): 订单状态枚举：PENDING, PAID, SHIPPED, COMPLETED, CANCELLED
                ''',
                'knowledge_blocks': MetadataValuesResult(
                    status="success",
                    data={
                        "collection_order_service": [
                            {
                                "knowledge_id": "order-service/services/order_service.py",
                                "metadata_value": "订单服务核心模块，处理订单创建、查询、更新和取消等业务逻辑",
                                "text": "完整的代码分析内容..."
                            },
                            {
                                "knowledge_id": "order-service/models/order.py",
                                "metadata_value": "订单数据模型定义，包含订单实体类和相关枚举",
                                "text": "完整的代码分析内容..."
                            },
                            {
                                "knowledge_id": "order-service/controllers/order_controller.py",
                                "metadata_value": "订单API控制器，提供订单相关的REST接口",
                                "text": "完整的代码分析内容..."
                            }
                        ]
                    },
                    errors=None
                )
            }
            
            # 失败场景示例（未找到知识块）
            {
                'location_result': None,
                'full_knowledge': "",
                'knowledge_blocks': None
            }
        """
        logger.info(f"=========two_stage_knowledge_retrieval, query: {self.query}")
        
        # 获取所有知识块数据
        knowledge_blocks = await self.get_all_knowledge_blocks()
        
        if not knowledge_blocks:
            logger.warning("No knowledge blocks found")
            return {
                'location_result': None,
                'full_knowledge': "",
                'knowledge_blocks': None
            }
        
        # 第一阶段：用摘要定位相关知识块（支持分批处理大型代码仓库）
        logger.info("=== Stage 1: Locate relevant knowledge blocks using metadata_value ===")
        
        # 将摘要按字符数分批，避免超出 LLM 上下文窗口
        MAX_CHARS_PER_BATCH = 60000  # 约 15K tokens
        metadata_batches = knowledge_blocks.extract_metadata_as_batches(
            max_chars_per_batch=MAX_CHARS_PER_BATCH
        )
        
        if not metadata_batches:
            logger.warning("No metadata extracted from knowledge blocks")
            return {
                'location_result': None,
                'full_knowledge': "",
                'knowledge_blocks': knowledge_blocks
            }
        
        total_items = len(knowledge_blocks.get_all_items())
        logger.info(f"Stage 1 - Total {total_items} knowledge blocks, split into {len(metadata_batches)} batch(es)")
        
        if len(metadata_batches) == 1:
            # 单批次：直接处理（与原逻辑一致）
            logger.info(f"Stage 1 - Single batch, metadata length: {len(metadata_batches[0])}")
            location_result = await self.locate_files(knowledge=metadata_batches[0])
        else:
            # 多批次：并发调用 LLM 定位文件，合并结果
            logger.info(f"Stage 1 - Multiple batches mode: {len(metadata_batches)} batches in parallel")
            for i, batch in enumerate(metadata_batches):
                logger.info(f"  Batch {i+1}: {len(batch)} chars")
            
            # 并发执行所有批次的 locate_files
            batch_tasks = [
                self.locate_files(knowledge=batch) 
                for batch in metadata_batches
            ]
            batch_results = await asyncio.gather(*batch_tasks, return_exceptions=True)
            
            # 收集结果
            all_knowledge_files = []
            all_intent_parts = []
            all_reasoning_parts = []
            
            for i, result in enumerate(batch_results):
                if isinstance(result, Exception):
                    logger.error(f"Stage 1 - Batch {i+1} failed: {result}")
                    continue
                
                batch_result = result
                if batch_result and batch_result.knowledge_files:
                    all_knowledge_files.extend(batch_result.knowledge_files)
                    logger.info(f"Stage 1 - Batch {i+1} found {len(batch_result.knowledge_files)} knowledge file groups")
                else:
                    logger.info(f"Stage 1 - Batch {i+1} found no relevant files")
                
                if batch_result:
                    if batch_result.intent_analysis:
                        all_intent_parts.append(batch_result.intent_analysis)
                    if batch_result.reasoning_path:
                        all_reasoning_parts.append(batch_result.reasoning_path)
            
            # 合并多批次的结果并去重
            seen_kid = set()
            merged_knowledge_files = []
            for kf in all_knowledge_files:
                if kf.knowledge_id not in seen_kid:
                    seen_kid.add(kf.knowledge_id)
                    merged_knowledge_files.append(kf)
                else:
                    # knowledge_id 重复时合并 files
                    for existing_kf in merged_knowledge_files:
                        if existing_kf.knowledge_id == kf.knowledge_id:
                            existing_files_set = set(existing_kf.files)
                            for f in kf.files:
                                if f not in existing_files_set:
                                    existing_kf.files.append(f)
                            break
            
            location_result = FileLocationResult(
                knowledge_files=merged_knowledge_files,
                intent_analysis=" | ".join(all_intent_parts) if all_intent_parts else "",
                reasoning_path=" | ".join(all_reasoning_parts) if all_reasoning_parts else "",
            )
            logger.info(f"Stage 1 - Merged: {len(merged_knowledge_files)} unique knowledge file groups from {len(metadata_batches)} batches (parallel)")
        
        # 获取定位到的 knowledge_ids
        knowledge_ids = location_result.get_all_knowledge_ids()
        logger.info(f"Stage 1 - located knowledge_ids: {knowledge_ids}")
        
        if not knowledge_ids:
            logger.warning("No knowledge_ids located in stage 1")
            return {
                'location_result': location_result,
                'full_knowledge': "",
                'knowledge_blocks': knowledge_blocks
            }
        
        # 第二阶段：根据 ID 获取完整知识
        logger.info("=== Stage 2: Retrieve page content knowledge by knowledge_ids ===")
        full_knowledge = knowledge_blocks.get_text_by_ids(knowledge_ids)
        logger.info(f"Stage 2 - full page content knowledge length: {len(full_knowledge)}")
        logger.info(f"Stage 2 - full page content knowledge preview: {full_knowledge[:500] if full_knowledge else 'None'}...")
        
        return {
            'location_result': location_result,
            'full_knowledge': full_knowledge,
            'knowledge_blocks': knowledge_blocks
        }

    def parse_code_configs(self) -> List[CodeConfig]:
        """
        解析 descriptor_types 为 CodeConfig 对象列表
        
        descriptor_types 是一个列表，其中第一个元素是 JSON 格式的配置字符串，如:
            '[{"name":"dd-gitee","descriptorType":"code","codeRepoType":"git","codeRepoPath":"https://gitee.com/xxx/test.git","codeRepoBranch":"main","codeRepoToken":"xxx"}]'
        
        Returns:
            CodeConfig 对象列表
        """
        import json
        
        if not self.descriptor_types:
            return []
        
        # descriptor_types 是一个列表，取第一个元素作为配置字符串
        config_str = self.descriptor_types[0] if isinstance(self.descriptor_types, list) else str(self.descriptor_types)
        config_str = config_str.strip()
        
        if not config_str:
            return []
        
        # 尝试解析 JSON 格式
        if config_str.startswith('['):
            try:
                data_list = json.loads(config_str)
                return [CodeConfig.from_dict(item) for item in data_list]
            except json.JSONDecodeError as e:
                raise ValueError(f"JSON 解析错误: {e}, 输入: {config_str}")
        
        # 如果不是 JSON 格式，抛出错误（code 类型必须是 JSON 格式）
        raise ValueError(f"配置字符串格式错误，期望 JSON 数组格式: {config_str}")
    
    def get_first_code_config(self) -> Optional[CodeConfig]:
        """
        获取第一个 code 类型的配置
        
        Returns:
            第一个 CodeConfig 对象，如果没有则返回 None
        """
        configs = self.parse_code_configs()
        for config in configs:
            if config.descriptor_type == "code":
                return config
        return configs[0] if configs else None

    def get_code_path(self, config_name: str = None) -> Optional[str]:
        """
        获取代码仓库的本地路径
        
        Args:
            config_name: 配置名称，如果为 None 则返回第一个代码路径
        
        Returns:
            代码仓库的本地路径，如果不存在返回 None
        """
        if not self.code_paths:
            return None
        
        if config_name:
            return self.code_paths.get(config_name)
        
        # 返回第一个代码路径
        return next(iter(self.code_paths.values()), None)
    
    def get_all_code_paths(self) -> Dict[str, str]:
        """
        获取所有代码仓库的本地路径
        
        Returns:
            字典，key 为配置名称，value 为本地路径
        """
        return self.code_paths

    # ==================== Codebase Indexer 搜索功能 ====================

    async def search_codebase_indexer_by_filepaths(self, filepaths: List[str]) -> List[Dict[str, Any]]:
        """
        通过文件路径列表搜索 codebase indexer 记录
        
        这是推荐的搜索方式，只获取指定文件的分析结果，避免上下文过大。
        从 data-services 获取指定文件的 CodeDeepAnalysis 元数据。
        
        Args:
            filepaths: 文件路径列表（相对路径）
        
        Returns:
            包含 filepath 和 code_deep_analysis 的记录列表
            
        Return Sample:
            # filepaths = ["order-service/services/order_service.py", "order-service/models/order.py"]
            [
                {
                    "codebase_indexer_id": "idx_abc123",
                    "filepath": "order-service/services/order_service.py",
                    "code_deep_analysis": {
                        "file_summary": "订单服务核心模块，处理订单创建、查询、更新和取消等业务逻辑",
                        "entities": [
                            {
                                "name": "OrderService",
                                "line_no": "15",
                                "business_meaning": "订单服务类，处理所有订单相关业务逻辑",
                                "functions": [
                                    {
                                        "name": "create_order",
                                        "line_no": "25",
                                        "purpose": "创建新订单",
                                        "business_action": "处理订单创建流程，包括校验、计算价格、保存订单"
                                    },
                                    {
                                        "name": "get_order_by_id",
                                        "line_no": "78",
                                        "purpose": "根据ID查询订单",
                                        "business_action": "从数据库获取订单详情"
                                    }
                                ]
                            }
                        ],
                        "global_functions": [],
                        "api_endpoints": [
                            {
                                "path": "POST /api/v1/orders",
                                "line_no": "45",
                                "business_summary": "创建订单接口"
                            }
                        ],
                        "dependencies": {
                            "imports": ["order-service/models/order.py", "order-service/validators/order_validator.py"],
                            "calls": ["PaymentService.process_payment", "InventoryService.check_stock"]
                        }
                    },
                    "dd_namespace": "my-project",
                    "dd_name": "order-service"
                },
                {
                    "codebase_indexer_id": "idx_def456",
                    "filepath": "order-service/models/order.py",
                    "code_deep_analysis": {
                        "file_summary": "订单数据模型定义，包含订单实体类和相关枚举",
                        "entities": [
                            {
                                "name": "Order",
                                "line_no": "10",
                                "business_meaning": "订单实体，包含订单ID、用户ID、商品列表、金额、状态等核心属性",
                                "functions": []
                            },
                            {
                                "name": "OrderStatus",
                                "line_no": "45",
                                "business_meaning": "订单状态枚举：PENDING, PAID, SHIPPED, COMPLETED, CANCELLED",
                                "functions": []
                            }
                        ],
                        "global_functions": [],
                        "api_endpoints": [],
                        "dependencies": {
                            "imports": ["common/base_model.py"],
                            "calls": []
                        }
                    },
                    "dd_namespace": "my-project",
                    "dd_name": "order-service"
                }
            ]
        """
        logger.info(f"Searching codebase indexer by filepaths: {filepaths}")
        
        if not filepaths:
            logger.warning("No filepaths provided")
            return []
        
        all_records = []
        
        try:
            await self.data_services_client._create_session()
            
            for filepath in filepaths:
                # 按文件路径精确搜索
                result = await self.data_services_client.search_codebase_indexers_by_filepath(
                    filepath=filepath,
                    dd_namespace=self.dd_namespace,
                    dd_name=self.data_descriptors[0] if self.data_descriptors else None,
                    prefix_match=False  # 精确匹配
                )
                
                if result and result.data:
                    for item in result.data:
                        record = {
                            "codebase_indexer_id": item.codebase_indexer_id,
                            "filepath": item.filepath,
                            "code_deep_analysis": item.code_deep_analysis,
                            "dd_namespace": item.dd_namespace,
                            "dd_name": item.dd_name
                        }
                        all_records.append(record)
                    
                    logger.info(f"Found codebase indexer record for {filepath}")
                else:
                    logger.warning(f"No codebase indexer record found for {filepath}")
        
        except Exception as e:
            logger.error(f"Error searching codebase indexer by filepath: {e}")
        finally:
            await self.data_services_client.close()
        
        logger.info(f"Total codebase indexer records found: {len(all_records)}")
        return all_records

    def parse_code_deep_analysis(self, code_deep_analysis_str: str) -> Optional[CodeDeepAnalysis]:
        """
        解析 code_deep_analysis JSON 字符串为 CodeDeepAnalysis 对象
        
        Args:
            code_deep_analysis_str: JSON 格式的代码分析结果字符串
        
        Returns:
            CodeDeepAnalysis 对象，解析失败返回 None
        """
        if not code_deep_analysis_str:
            return None
        
        try:
            data = json.loads(code_deep_analysis_str)
            return CodeDeepAnalysis(**data)
        except (json.JSONDecodeError, Exception) as e:
            logger.warning(f"Failed to parse code_deep_analysis: {e}")
            return None

    def build_code_analysis_context(self, records: List[Dict[str, Any]]) -> str:
        """
        构建代码分析上下文，用于 LLM 搜索
        
        Args:
            records: codebase indexer 记录列表
        
        Returns:
            格式化的代码分析上下文字符串

            === 文件详细分析 ===

            === 文件: internal/controller/finetune/finetuneexperiment_controller.go ===
            文件摘要: 本文件是Kubernetes Operator控制器，负责管理微调实验（FinetuneExperiment）资源的生命周期。它根据实验规格创建和管理多个微调任务（FinetuneJob），并聚合这些任务的状态来更新实验的整体状态，包括确定最佳版本。
            依赖: context, reflect, sort, time, github.com/DataTunerX/datatunerx/pkg/util, github.com/DataTunerX/datatunerx/pkg/util/handlererr, finetunev1beta1 "github.com/DataTunerX/meta-server/api/finetune/v1beta1", github.com/DataTunerX/utility-server/logging, k8s.io/apimachinery/pkg/api/errors, metav1 "k8s.io/apimachinery/pkg/apis/meta/v1", "k8s.io/apimachinery/pkg/runtime", "k8s.io/apimachinery/pkg/types", ctrl "sigs.k8s.io/controller-runtime", "sigs.k8s.io/controller-runtime/pkg/builder", "sigs.k8s.io/controller-runtime/pkg/client", "sigs.k8s.io/controller-runtime/pkg/controller", "sigs.k8s.io/controller-runtime/pkg/controller/controllerutil", "sigs.k8s.io/controller-runtime/pkg/event", "sigs.k8s.io/controller-runtime/pkg/handler", "sigs.k8s.io/controller-runtime/pkg/predicate"

            实体/类:

            FinetuneExperimentReconciler: 微调实验资源的协调器（Reconciler），是Kubernetes Operator的核心组件。它持续监控FinetuneExperiment资源的状态，并根据期望状态（Spec）与实际状态（Status）的差异，执行相应的操作来驱动系统达到期望状态。 [行号: 45-49]
            方法: Reconcile - 协调循环的核心方法，由控制器运行时框架在检测到FinetuneExperiment资源变化时调用。 [行号: 52-220]
            方法: SetupWithManager - 控制器初始化方法，用于将本协调器注册到控制器管理器，并配置其监视的资源类型和事件过滤规则。 [行号: 223-250]
            === 文件: internal/controller/finetune/finetunejob_controller.go ===
            文件摘要: 本文件是Kubernetes Operator控制器，负责管理FinetuneJob自定义资源的生命周期。它通过Reconcile循环协调FinetuneJob的状态，驱动微调作业的完整流程：包括前置条件检查、创建Finetune资源、监控微调状态、构建模型镜像、部署推理服务、执行评分任务，并在作业完成后清理资源。
            依赖: github.com/DataTunerX/datatunerx/pkg/config, github.com/DataTunerX/datatunerx/pkg/domain/valueobject, github.com/DataTunerX/datatunerx/pkg/util, github.com/DataTunerX/datatunerx/pkg/util/generate, github.com/DataTunerX/datatunerx/pkg/util/handlererr, corev1beta1 "github.com/DataTunerX/meta-server/api/core/v1beta1", extensionv1beta1 "github.com/DataTunerX/meta-server/api/extension/v1beta1", finetunev1beta1 "github.com/DataTunerX/meta-server/api/finetune/v1beta1", github.com/DataTunerX/utility-server/logging, github.com/duke-git/lancet/v2/slice, rayv1 "github.com/ray-project/kuberay/ray-operator/apis/ray/v1", batchv1 "k8s.io/api/batch/v1", "k8s.io/apimachinery/pkg/api/errors", metav1 "k8s.io/apimachinery/pkg/apis/meta/v1", "k8s.io/apimachinery/pkg/runtime", "k8s.io/apimachinery/pkg/types", ctrl "sigs.k8s.io/controller-runtime", "sigs.k8s.io/controller-runtime/pkg/builder", "sigs.k8s.io/controller-runtime/pkg/client", "sigs.k8s.io/controller-runtime/pkg/controller", "sigs.k8s.io/controller-runtime/pkg/controller/controllerutil", "sigs.k8s.io/controller-runtime/pkg/event", "sigs.k8s.io/controller-runtime/pkg/handler", "sigs.k8s.io/controller-runtime/pkg/predicate"

            实体/类:

            FinetuneJobReconciler: 微调作业控制器，负责监听和协调FinetuneJob自定义资源的状态变化，驱动整个微调作业的生命周期管理。 [行号: 55-58]
            方法: Reconcile - 协调FinetuneJob资源的核心循环，根据资源当前状态执行相应的业务操作。 [行号: 73-150]
            方法: SetupWithManager - 设置控制器管理器，定义控制器监听的资源和事件过滤条件。 [行号: 152-222]
            方法: reconcilePreCondition - 检查并更新微调作业所需的前置依赖资源的状态。 [行号: 224-280]
            方法: reconcileFinetuneSend - 创建或获取与微调作业关联的Finetune资源。 [行号: 282-310]
            方法: reconcileByFinetuneStatus - 根据Finetune资源的状态更新微调作业的状态和推进后续流程。 [行号: 312-400]
            方法: reconcileByJobStatus - 根据构建镜像Job的完成状态，推进微调作业到服务部署阶段。 [行号: 402-470]
            方法: reconcileByRayServiceStatus - 根据RayService推理服务的运行状态，启动评分任务。 [行号: 472-530]
            方法: reconcileByScoringStatus - 根据评分任务的结果，完成微调作业并清理推理服务。 [行号: 532-580]
            方法: reconcileCleaner - 在微调作业删除时，清理前置依赖资源中的引用记录。 [行号: 582-640]

        """
        context_parts = []
        
        for record in records:
            filepath = record.get("filepath", "")
            analysis_str = record.get("code_deep_analysis", "")
            
            if not analysis_str:
                continue
            
            analysis = self.parse_code_deep_analysis(analysis_str)
            if not analysis:
                continue
            
            part = f"\n=== 文件: {filepath} ===\n"
            
            if analysis.file_summary:
                part += f"文件摘要: {analysis.file_summary}\n"
            
            # 添加依赖关系信息，这对LLM理解调用链非常重要
            if analysis.dependence:
                part += f"依赖: {analysis.dependence}\n"
            
            if analysis.entities:
                part += "\n实体/类:\n"
                for entity in analysis.entities:
                    part += f"  - {entity.name}"
                    if entity.business_meaning:
                        part += f": {entity.business_meaning}"
                    if entity.line_no:
                        part += f" [行号: {entity.line_no}]"
                    part += "\n"
                    
                    # 添加函数信息
                    for func in entity.functions:
                        part += f"    - 方法: {func.name}"
                        if func.purpose:
                            part += f" - {func.purpose}"
                        if func.line_no:
                            part += f" [行号: {func.line_no}]"
                        part += "\n"
            
            if analysis.global_functions:
                part += "\n全局函数:\n"
                for func in analysis.global_functions:
                    part += f"  - {func.name}"
                    if func.purpose:
                        part += f": {func.purpose}"
                    if func.line_no:
                        part += f" [行号: {func.line_no}]"
                    part += "\n"
            
            if analysis.api_endpoints:
                part += "\nAPI 端点:\n"
                for endpoint in analysis.api_endpoints:
                    part += f"  - {endpoint.method} {endpoint.path}"
                    if endpoint.business_summary:
                        part += f": {endpoint.business_summary}"
                    if endpoint.line_no:
                        part += f" [行号: {endpoint.line_no}]"
                    part += "\n"
            
            context_parts.append(part)
        
        return "\n".join(context_parts)

    async def search_relevant_code_segments(self, code_analysis_context: str) -> CodeSearchResult:
        """
        使用 LLM 从代码分析结果中搜索与用户问题相关的代码片段
        
        LLM 会分析用户问题的意图，从提供的代码分析上下文中筛选出最相关的代码片段，
        并给出每个片段的相关性原因和业务含义。
        
        Args:
            code_analysis_context: 代码分析上下文，包含文件摘要、实体、函数、API 等结构化信息
        
        Returns:
            CodeSearchResult: 包含相关代码片段的搜索结果
            
        Return Sample:
            # query = "怎么创建订单"
            CodeSearchResult(
                query="怎么创建订单",
                intent_analysis="用户想了解订单创建的业务流程和代码实现，需要查找订单创建相关的服务方法、控制器接口和数据模型",
                relevant_segments=[
                    RelevantCodeSegment(
                        file_path="order-service/services/order_service.py",
                        segment_type="function",
                        name="create_order",
                        line_no="45-98",
                        relevance_reason="订单创建的核心业务逻辑入口，处理订单数据验证、库存检查、价格计算等关键步骤",
                        business_meaning="创建新订单的主要业务方法，包含完整的订单创建流程"
                    ),
                    RelevantCodeSegment(
                        file_path="order-service/controllers/order_controller.py",
                        segment_type="api_endpoint",
                        name="POST /api/v1/orders",
                        line_no="25-52",
                        relevance_reason="创建订单的 REST API 接口，接收前端请求并调用订单服务",
                        business_meaning="对外暴露的订单创建接口，处理请求参数校验和响应格式化"
                    ),
                    RelevantCodeSegment(
                        file_path="order-service/models/order.py",
                        segment_type="entity",
                        name="Order",
                        line_no="10-45",
                        relevance_reason="订单数据模型，定义了订单的所有字段和验证规则",
                        business_meaning="订单实体类，包含订单ID、用户ID、商品列表、金额、状态等核心属性"
                    ),
                    RelevantCodeSegment(
                        file_path="order-service/validators/order_validator.py",
                        segment_type="function",
                        name="validate_order_data",
                        line_no="15-38",
                        relevance_reason="订单创建前的数据校验逻辑，确保订单数据的完整性和有效性",
                        business_meaning="校验订单创建请求中的必填字段、数据格式和业务规则"
                    )
                ],
                summary="找到4个与订单创建相关的代码片段：1个核心服务方法(create_order)负责主要业务逻辑，1个API接口(POST /api/v1/orders)处理外部请求，1个数据模型(Order)定义订单结构，1个验证方法(validate_order_data)确保数据有效性。建议从 order_service.py 的 create_order 方法开始阅读，了解完整的订单创建流程。"
            )
        """
        system_template = SEARCH_CODE_SEGMENTS_PROMPT
        human_template = "{query}"
        
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        system_prompt = SystemMessagePromptTemplate.from_template(
            template=system_template,
            input_variables=["current_time", "code_analysis"],
        )
        
        human_prompt = HumanMessagePromptTemplate.from_template(human_template)
        chat_prompt = ChatPromptTemplate.from_messages([system_prompt, human_prompt])
        
        user_id = self.metadata.get('user_id', 'unknown')
        run_id = self.metadata.get('run_id', 'unknown')
        trace_id = self.metadata.get('trace_id', 'unknown')
        
        chain = chat_prompt | self.llm
        
        with langfuse.start_as_current_span(
            name="codeagent-search-code-segments",
            trace_context={"trace_id": trace_id}
        ) as span:
            span.update_trace(
                user_id=user_id,
                session_id=run_id,
                input={"query": self.query}
            )
            
            answer = await chain.ainvoke(
                {"query": self.query, "current_time": current_time, "code_analysis": code_analysis_context},
                config={"callbacks": [langfuse_handler]}
            )
            
            span.update_trace(output={"answer": answer})
        
        langfuse.flush()
        
        logger.info(f"CodeAgent.search_relevant_code_segments, answer = {answer}")
        
        data_dict = self.format_llm_ouput(answer)
        
        if data_dict is None:
            data_dict = {
                "query": self.query,
                "intent_analysis": "无法解析 LLM 响应",
                "relevant_segments": [],
                "summary": "搜索失败"
            }
        
        return CodeSearchResult(**data_dict)

    def extract_code_by_line_range(self, filepath: str, line_no: str, context_lines: int = 5) -> str:
        """
        使用现有的 extract_code_by_lines 工具从本地文件读取指定行号范围的代码
        
        Args:
            filepath: 文件相对路径
            line_no: 行号范围，如 "100-160" 或 "100"
            context_lines: 额外读取的上下文行数（仅当 line_no 为单行时生效）
        
        Returns:
            读取到的代码内容，包含行号标注
            
        Note:
            - 如果 line_no 是范围格式（如 "45-100"），直接读取该范围，不添加上下文
            - 如果 line_no 是单行格式（如 "45"），则前后各添加 context_lines 行
            - 这样避免完整的方法/类代码块被额外的无关代码污染
        """
        # 获取代码仓库的本地路径
        code_path = self.get_code_path()
        if not code_path:
            logger.warning("No code path configured")
            return f"[无法读取文件: 未配置代码路径]"
        
        try:
            # 解析行号范围
            if "-" in line_no:
                # 已经是范围格式（如 "45-100"），说明 LLM 返回的是完整代码块
                # 不需要额外添加上下文，避免引入无关代码
                parts = line_no.split("-")
                start_line = int(parts[0].strip())
                end_line = int(parts[1].strip())
            else:
                # 单行格式（如 "45"），可能只是关键行，需要添加上下文
                start_line = int(line_no.strip())
                end_line = start_line
                # 只有单行时才添加上下文
                start_line = max(1, start_line - context_lines)
                end_line = end_line + context_lines
            
            # 使用现有的 read_file_from_code_repo 工具读取代码
            content, actual_start, actual_end, full_path = read_file_from_code_repo(
                code_base_path=code_path,
                relative_path=filepath,
                start_line=start_line,
                end_line=end_line,
                include_line_numbers=True
            )
            
            logger.info(f"Read code from {filepath}:{actual_start}-{actual_end}")
            return content
        
        except FileNotFoundError:
            logger.warning(f"File not found: {filepath}")
            return f"[文件不存在: {filepath}]"
        except ValueError as e:
            logger.warning(f"Invalid path: {filepath} - {e}")
            return f"[非法路径: {filepath}]"
        except Exception as e:
            logger.error(f"Error reading file {filepath}: {e}")
            return f"[读取文件出错: {e}]"

    async def load_codebase_index(self, force_reload: bool = False) -> bool:
        """
        从 data-services 加载整个 repo 的文件分析结果到内存索引
        
        Args:
            force_reload: 是否强制重新加载（即使已加载）
            
        Returns:
            是否加载成功
        """
        if self._codebase_index_loaded and not force_reload:
            logger.info("Codebase index already loaded, skip")
            return True
        
        try:
            logger.info("Loading codebase index from data-services...")
            
            dd_name = self.data_descriptors[0] if self.data_descriptors else None
            
            # 使用 by_dd 搜索获取整个 repo 的所有文件
            result = await self.data_services_client.search_codebase_indexers_by_dd(
                dd_namespace=self.dd_namespace,
                dd_name=dd_name
            )
            
            records = []
            if result and result.data:
                for item in result.data:
                    record = {
                        "codebase_indexer_id": item.codebase_indexer_id,
                        "filepath": item.filepath,
                        "code_deep_analysis": item.code_deep_analysis,
                        "dd_namespace": item.dd_namespace,
                        "dd_name": item.dd_name
                    }
                    records.append(record)
            
            await self.data_services_client.close()
            
            if records:
                self.codebase_index.load_from_records(records)
                self._codebase_index_loaded = True
                logger.info(f"Codebase index loaded successfully: {len(records)} files")
                return True
            else:
                logger.warning("No codebase indexer records found for DD: {self.dd_namespace}/{dd_name}")
                return False
                
        except Exception as e:
            logger.error(f"Error loading codebase index: {e}")
            return False

    async def search_and_extract_code_enhanced(self, filepaths: List[str] = None) -> Dict[str, Any]:
        """
        增强版代码搜索和提取流程（推荐入口方法）：
        
        结合 two_stage_knowledge_retrieval 文件定位 + observe_locate_files 审查 + 依赖关系分析
        
        流程：
        Stage 1:   使用 two_stage_knowledge_retrieval 定位相关文件（或使用传入的 filepaths）
        Stage 1.5: 使用 observe_locate_files 审查验证，过滤不相关文件
        Stage 2:   加载全量代码分析到内存（CodebaseIndex）
        Stage 3:   基于定位到的文件，分析多级依赖关系（2级深度）
        Stage 4:   扩展文件列表，包含相关依赖文件
        Stage 5:   构建增强上下文（包含依赖关系信息）
        Stage 6:   LLM 精确筛选代码片段
        Stage 7:   从本地文件读取相关代码
        
        Args:
            filepaths: 可选，直接指定文件路径列表，跳过 Stage 1 和 Stage 1.5
            
        Returns:
            Dict[str, Any]: 包含搜索结果和代码片段的字典，结构如下：
            {
                'search_result': CodeSearchResult(
                    query="用户问题",
                    query_type="process | entity | precise",
                    intent_analysis="对用户意图的分析",
                    relevant_segments=[
                        RelevantCodeSegment(
                            file_path="order-service/services/order_service.py",
                            segment_type="function | entity | api_endpoint | global_function",
                            name="create_order",
                            line_no="45-100",
                            relevance_score=10,
                            relevance_reason="订单创建的核心入口方法",
                            business_meaning="处理订单创建的主要业务逻辑"
                        ),
                        # ... 更多片段
                    ],
                    summary="搜索结果总结"
                ),
                'code_snippets': [
                    {
                        "file_path": "order-service/services/order_service.py",
                        "segment_type": "function",
                        "name": "create_order",
                        "line_no": "45-100",
                        "relevance_score": 10,
                        "relevance_reason": "订单创建的核心入口方法",
                        "business_meaning": "处理订单创建的主要业务逻辑",
                        "code_content": "async def create_order(self, ...):\\n    ..."
                    },
                    # ... 更多代码片段
                ],
                'analysis_records': [
                    {"filepath": "...", "code_deep_analysis": "{...}"},
                    # ... code caller的原始分析记录
                ],
                'located_files': ["order-service/services/order_service.py", ...],
                'expanded_files': ["order-service/services/order_service.py", "order-service/models/order.py", ...],
                'dependency_info': {
                    "order-service/services/order_service.py": {
                        "depends_on": ["order-service/models/order.py", ...],
                        "called_by": ["order-service/controllers/order_controller.py", ...],
                        "depth": 0
                    },
                    # ... 更多依赖关系
                }
            }
            
        Note:
            - 如果 CodebaseIndex 加载失败，会回退到 search_and_extract_code() 基础方法
            - search_and_extract_code() 不进行文件定位，只处理已定位的文件
            - code_snippets 可直接传给 answer_with_code() 生成自然语言回答
        """
        logger.info(f"=== search_and_extract_code_enhanced, query: {self.query} ===")
        
        # 步骤1：定位相关文件
        located_files = filepaths or []
        
        if not located_files:
            logger.info("Using two_stage_knowledge_retrieval to locate files")
            retrieval_result = await self.two_stage_knowledge_retrieval()
            
            if retrieval_result.get('location_result'):
                initial_files = retrieval_result['location_result'].get_all_files()
                logger.info(f"Stage 1 - Initial located files: {initial_files}")
                
                # 步骤1.5：使用 observe_locate_files 审查初步定位的文件
                if initial_files and retrieval_result.get('full_knowledge'):
                    logger.info("Stage 1.5 - Observing/auditing located files")
                    audit_result = await self.observe_locate_files(
                        locate_files=retrieval_result['location_result'],
                        knowledge=retrieval_result['full_knowledge']
                    )
                    
                    # 获取审查后保留的文件
                    located_files = audit_result.get_kept_files()
                    logger.info(f"Stage 1.5 - After audit, kept files: {located_files}")
                    logger.info(f"Stage 1.5 - Audit summary: {audit_result.final_context_summary[:200] if audit_result.final_context_summary else 'N/A'}...")
                else:
                    # 如果没有 full_knowledge，直接使用初步定位结果
                    located_files = initial_files
                    logger.info(f"Stage 1.5 skipped - Using initial files: {located_files}")
        
        if not located_files:
            logger.warning("No files located, cannot proceed")
            return {
                'search_result': CodeSearchResult(
                    query=self.query,
                    intent_analysis="未能定位到相关文件",
                    relevant_segments=[],
                    summary="请尝试提供更具体的文件路径或关键词"
                ),
                'code_snippets': [],
                'analysis_records': [],
                'located_files': []
            }
        
        # 步骤2：加载全量代码分析到内存
        if not self._codebase_index_loaded:
            await self.load_codebase_index()
        
        if not self._codebase_index_loaded:
            logger.warning("Codebase index not loaded, falling back to basic search")
            return await self.search_and_extract_code(located_files)
        
        # 步骤3：基于定位到的文件，分析多级依赖关系
        # 扩展策略：
        #   第1级：双向扩展（了解直接上下游，即"谁调用了我"和"我调用了谁"）
        #   第2级：仅向下扩展 depends_on（跟踪被调用的深层实现，避免 callers 导致无关文件爆炸）
        # 扩展上限：避免大项目中依赖过多导致上下文膨胀
        MAX_EXPANDED_FILES = 15  # 扩展文件总数上限（不含原始定位文件）
        
        dependency_info = {}
        expanded_files = set(located_files)
        
        max_depth = 2
        current_level_files = set(located_files)
        
        for depth in range(max_depth):
            next_level_files = set()
            
            for filepath in current_level_files:
                if filepath in dependency_info:
                    continue
                    
                deps = self.codebase_index.get_dependencies(filepath)
                callers = self.codebase_index.get_callers(filepath)
                
                if deps or callers:
                    dependency_info[filepath] = {
                        "depends_on": deps,
                        "called_by": callers,
                        "depth": depth
                    }
                    
                    # 向下扩展：始终跟踪 depends_on（被调用的文件）
                    for dep in deps:
                        if dep in self.codebase_index.file_index and dep not in expanded_files:
                            if len(expanded_files) - len(located_files) < MAX_EXPANDED_FILES:
                                expanded_files.add(dep)
                                next_level_files.add(dep)
                    
                    # 向上扩展：仅第1级收集 callers（直接调用者），不再递归追踪 callers 的 callers
                    if depth == 0:
                        for caller in callers:
                            if caller in self.codebase_index.file_index and caller not in expanded_files:
                                if len(expanded_files) - len(located_files) < MAX_EXPANDED_FILES:
                                    expanded_files.add(caller)
                                    # 注意：callers 不加入 next_level_files，第2级不再向上追踪
            
            current_level_files = next_level_files
            if not current_level_files:
                break
        
        actual_depth = depth + 1 if current_level_files or dependency_info else 0
        logger.info(f"Multi-level dependency expansion: depth={actual_depth}, expanded from {len(located_files)} to {len(expanded_files)} files (limit={MAX_EXPANDED_FILES})")
        
        # 步骤4：构建增强上下文
        context_parts = []
        
        # 添加依赖关系信息（帮助 LLM 理解文件间关系）
        if dependency_info:
            context_parts.append("=== 文件依赖关系（调用链分析）===")
            context_parts.append("【重要】以下是文件间的调用关系，用于帮助理解完整的业务流程。")
            context_parts.append("对于流程查询，请确保返回完整调用链上的所有关键函数。")
            for filepath, deps in dependency_info.items():
                part = f"\n{filepath}:"
                if deps.get('depends_on'):
                    part += f"\n  - 依赖（调用了）: {deps['depends_on']}"
                if deps.get('called_by'):
                    part += f"\n  - 被调用于: {deps['called_by']}"
                context_parts.append(part)
            context_parts.append("")
        
        # 添加完整的文件分析
        context_parts.append("=== 文件详细分析 ===")
        records_for_context = []
        
        # 先添加定位到的文件（优先级高）
        for filepath in located_files:
            analysis = self.codebase_index.get_file_analysis(filepath)
            if analysis:
                records_for_context.append({
                    "filepath": filepath,
                    "code_deep_analysis": json.dumps({
                        "file_summary": analysis.file_summary,
                        "file_path": analysis.file_path,
                        "dependence": analysis.dependence,
                        "entities": [e.model_dump() for e in analysis.entities],
                        "global_functions": [f.model_dump() for f in analysis.global_functions],
                        "api_endpoints": [a.model_dump() for a in analysis.api_endpoints]
                    }, ensure_ascii=False)
                })
        
        # 再添加依赖文件（补充上下文）
        for filepath in expanded_files:
            if filepath not in located_files:
                analysis = self.codebase_index.get_file_analysis(filepath)
                if analysis:
                    records_for_context.append({
                        "filepath": filepath,
                        "code_deep_analysis": json.dumps({
                            "file_summary": analysis.file_summary,
                            "file_path": analysis.file_path,
                            "dependence": analysis.dependence,
                            "entities": [e.model_dump() for e in analysis.entities],
                            "global_functions": [f.model_dump() for f in analysis.global_functions],
                            "api_endpoints": [a.model_dump() for a in analysis.api_endpoints]
                        }, ensure_ascii=False)
                    })
        
        # 构建代码分析上下文
        file_analysis_context = self.build_code_analysis_context(records_for_context)
        context_parts.append(file_analysis_context)
        
        enhanced_context = "\n".join(context_parts)
        logger.info(f"Built enhanced context, length: {len(enhanced_context)}, files: {len(records_for_context)}")
        
        # 步骤5：使用 LLM 精确筛选
        search_result = await self.search_relevant_code_segments(enhanced_context)
        logger.info(f"LLM found {len(search_result.relevant_segments)} relevant code segments")
        
        # 步骤5.5【调用链扩展】：对 LLM 筛选出的关键函数做函数级调用链追踪
        # 只在有函数级调用图数据时才做，否则跳过（降级为无调用链扩展）
        call_chain_snippets = []
        call_chain_info = []
        
        if self.codebase_index and self.codebase_index.function_call_graph:
            # 1) 从 relevant_segments 提取函数名（只取 function/global_function 类型）
            key_func_names = []
            seen_func = set()
            for seg in search_result.relevant_segments:
                if seg.segment_type in ("function", "global_function") and seg.name not in seen_func:
                    key_func_names.append(seg.name)
                    seen_func.add(seg.name)
            
            # 2) 对关键函数做调用链追踪
            MAX_TRACE_FUNCS = 5   # 最多追踪 5 个关键函数
            MAX_CHAIN_NODES = 10  # 每个函数链上最多收集 10 个新节点
            
            # 已被 LLM 覆盖的函数（file_path + name 去重）
            already_covered = set()
            for seg in search_result.relevant_segments:
                already_covered.add((seg.file_path, seg.name))
            
            for func_name in key_func_names[:MAX_TRACE_FUNCS]:
                chain = self.codebase_index.trace_call_chain(func_name, direction="callees", max_depth=2)
                if chain.get("level") != "function" or not chain.get("chain"):
                    continue
                
                # 记录调用路径描述
                chain_path = _format_chain_path(func_name, chain["chain"])
                if chain_path:
                    call_chain_info.append(chain_path)
                
                # 收集链上 LLM 没有覆盖到的节点
                collected = 0
                for node in _flatten_chain(chain["chain"]):
                    if collected >= MAX_CHAIN_NODES:
                        break
                    node_key = (node["file"], node["function"])
                    if node_key in already_covered:
                        continue
                    
                    line_no = (node.get("detail") or {}).get("line_no", "")
                    if not line_no or not node.get("file"):
                        continue
                    
                    code_content = self.extract_code_by_line_range(
                        filepath=node["file"],
                        line_no=line_no,
                        context_lines=3
                    )
                    if code_content:
                        entity_name = node.get("entity", "")
                        display_name = f"{entity_name}.{node['function']}" if entity_name else node["function"]
                        call_chain_snippets.append({
                            "file_path": node["file"],
                            "segment_type": "function",
                            "name": node["function"],
                            "line_no": line_no,
                            "relevance_reason": f"被 {func_name} 调用（调用链追踪）",
                            "business_meaning": (node.get("detail") or {}).get("purpose", ""),
                            "code_content": code_content,
                            "source": "call_chain",
                            "call_chain_role": f"callee of {func_name}",
                        })
                        already_covered.add(node_key)
                        collected += 1
            
            if call_chain_snippets:
                logger.info(f"Call chain expansion: traced {min(len(key_func_names), MAX_TRACE_FUNCS)} functions, "
                           f"added {len(call_chain_snippets)} new code snippets")
        
        # 步骤6：从本地文件读取相关代码
        code_snippets = []
        for segment in search_result.relevant_segments:
            code_content = self.extract_code_by_line_range(
                filepath=segment.file_path,
                line_no=segment.line_no,
                context_lines=3
            )
            code_snippets.append({
                "file_path": segment.file_path,
                "segment_type": segment.segment_type,
                "name": segment.name,
                "line_no": segment.line_no,
                "relevance_reason": segment.relevance_reason,
                "business_meaning": segment.business_meaning,
                "code_content": code_content
            })
        
        # 合并调用链扩展的代码片段
        if call_chain_snippets:
            code_snippets.extend(call_chain_snippets)
            logger.info(f"Total code snippets: {len(code_snippets)} "
                       f"(LLM selected: {len(code_snippets) - len(call_chain_snippets)}, "
                       f"call chain: {len(call_chain_snippets)})")
        
        return {
            'search_result': search_result,
            'code_snippets': code_snippets,
            'analysis_records': records_for_context,
            'located_files': located_files,
            'expanded_files': list(expanded_files),
            'dependency_info': dependency_info,
            'call_chain_info': call_chain_info,
        }

    async def search_and_extract_code(self, filepaths: List[str]) -> Dict[str, Any]:
        """
        基础代码搜索和提取流程（只处理已定位的文件）：
        
        流程：
            1. 按文件路径搜索 codebase indexer 获取 code_deep_analysis
            2. 使用 LLM 分析哪些代码片段与用户问题相关
            3. 从本地文件读取相关代码
        
        注意：此方法不进行文件定位，文件定位应由调用方完成。
        如需自动文件定位，请使用 search_and_extract_code_enhanced()。
        
        Args:
            filepaths: 必须提供，已定位的文件路径列表
        
        Returns:
            包含搜索结果和代码片段的字典
            
        Return Sample:
            # filepaths = ["order-service/services/order_service.py", "order-service/models/order.py"]
            # query = "怎么创建订单"
            {
                'search_result': CodeSearchResult(
                    query="怎么创建订单",
                    intent_analysis="用户想了解订单创建的业务流程和代码实现",
                    relevant_segments=[
                        RelevantCodeSegment(
                            file_path="order-service/services/order_service.py",
                            segment_type="function",
                            name="create_order",
                            line_no="45-98",
                            relevance_reason="订单创建的核心业务逻辑",
                            business_meaning="创建新订单的主要业务方法"
                        ),
                        RelevantCodeSegment(
                            file_path="order-service/models/order.py",
                            segment_type="entity",
                            name="Order",
                            line_no="10-45",
                            relevance_reason="订单数据模型定义",
                            business_meaning="订单实体类，包含订单核心属性"
                        )
                    ],
                    summary="找到2个与订单创建相关的代码片段"
                ),
                'code_snippets': [
                    {
                        'file_path': 'order-service/services/order_service.py',
                        'segment_type': 'function',
                        'name': 'create_order',
                        'line_no': '45-98',
                        'relevance_reason': '订单创建的核心业务逻辑',
                        'business_meaning': '创建新订单的主要业务方法',
                        'code_content': '''40|    
                            41|    # 订单创建方法
                            42|    async def create_order(self, order_data: dict) -> Order:
                            43|        \"\"\"创建新订单\"\"\"
                            44|        # 1. 校验订单数据
                            45|        validated_data = self.validator.validate(order_data)
                            46|        
                            47|        # 2. 检查库存
                            48|        await self.inventory_service.check_stock(validated_data['items'])
                            49|        
                            50|        # 3. 计算价格
                            51|        total_price = self.calculate_total(validated_data['items'])
                            52|        
                            53|        # 4. 创建订单记录
                            54|        order = Order(
                            55|            user_id=validated_data['user_id'],
                            56|            items=validated_data['items'],
                            57|            total_price=total_price,
                            58|            status=OrderStatus.PENDING
                            59|        )
                            60|        
                            61|        # 5. 保存到数据库
                            62|        await self.order_repository.save(order)
                            63|        
                            64|        return order
                            65|'''
                    },
                    {
                        'file_path': 'order-service/models/order.py',
                        'segment_type': 'entity',
                        'name': 'Order',
                        'line_no': '10-45',
                        'relevance_reason': '订单数据模型定义',
                        'business_meaning': '订单实体类，包含订单核心属性',
                        'code_content': '''5|from enum import Enum
                            6|from dataclasses import dataclass
                            7|from typing import List, Optional
                            8|from datetime import datetime
                            9|
                            10|class OrderStatus(Enum):
                            11|    PENDING = "pending"
                            12|    PAID = "paid"
                            13|    SHIPPED = "shipped"
                            14|    COMPLETED = "completed"
                            15|    CANCELLED = "cancelled"
                            16|
                            17|@dataclass
                            18|class Order:
                            19|    \"\"\"订单实体类\"\"\"
                            20|    id: Optional[str] = None
                            21|    user_id: str = ""
                            22|    items: List[dict] = None
                            23|    total_price: float = 0.0
                            24|    status: OrderStatus = OrderStatus.PENDING
                            25|    created_at: datetime = None
                            26|    updated_at: datetime = None
                            27|'''
                    }
                ],
                'analysis_records': [
                    {
                        "codebase_indexer_id": "idx_abc123",
                        "filepath": "order-service/services/order_service.py",
                        "code_deep_analysis": {...},  # 完整的 CodeDeepAnalysis 结构
                        "dd_namespace": "my-project",
                        "dd_name": "order-service"
                    },
                    {
                        "codebase_indexer_id": "idx_def456",
                        "filepath": "order-service/models/order.py",
                        "code_deep_analysis": {...},
                        "dd_namespace": "my-project",
                        "dd_name": "order-service"
                    }
                ],
                'located_files': [
                    "order-service/services/order_service.py",
                    "order-service/models/order.py"
                ]
            }
        """
        logger.info(f"=== search_and_extract_code, query: {self.query} ===")
        
        located_files = filepaths or []
        
        if not located_files:
            logger.warning("No files located")
            return {
                'search_result': CodeSearchResult(
                    query=self.query,
                    intent_analysis="未能定位到相关文件",
                    relevant_segments=[],
                    summary="请尝试提供更具体的文件路径或关键词"
                ),
                'code_snippets': [],
                'analysis_records': [],
                'located_files': []
            }
        
        # 阶段二：按文件路径搜索 codebase indexer
        records = await self.search_codebase_indexer_by_filepaths(located_files)
        
        if not records:
            logger.warning("No codebase indexer records found for located files")
            return {
                'search_result': CodeSearchResult(
                    query=self.query,
                    intent_analysis=f"定位到文件 {located_files}，但未找到代码分析记录",
                    relevant_segments=[],
                    summary="文件可能尚未被索引，请确保代码已完成索引"
                ),
                'code_snippets': [],
                'analysis_records': [],
                'located_files': located_files
            }
        
        # 构建代码分析上下文
        code_analysis_context = self.build_code_analysis_context(records)
        logger.info(f"Built code analysis context, length: {len(code_analysis_context)}")
        
        # 使用 LLM 搜索相关代码片段
        search_result = await self.search_relevant_code_segments(code_analysis_context)
        logger.info(f"Found {len(search_result.relevant_segments)} relevant code segments")
        
        # 从本地文件读取相关代码（使用现有的 extract_code_by_lines 工具）
        code_snippets = []
        for segment in search_result.relevant_segments:
            code_content = self.extract_code_by_line_range(
                filepath=segment.file_path,
                line_no=segment.line_no,
                context_lines=5  # 额外读取前后5行上下文
            )
            
            snippet = {
                'file_path': segment.file_path,
                'segment_type': segment.segment_type,
                'name': segment.name,
                'line_no': segment.line_no,
                'relevance_reason': segment.relevance_reason,
                'business_meaning': segment.business_meaning,
                'code_content': code_content
            }
            code_snippets.append(snippet)
            
            logger.info(f"Extracted code from {segment.file_path}:{segment.line_no}")
        
        return {
            'search_result': search_result,
            'code_snippets': code_snippets,
            'analysis_records': records,
            'located_files': located_files
        }

    def _is_identifier(self, keyword: str) -> bool:
        """
        判断关键词是否像代码标识符
        
        用于决定是否对该关键词使用本地文件 grep：
        - 标识符（如 create_order, OrderService）适合本地 grep
        - 中文业务词（如 "订单"）不适合本地 grep
        
        Args:
            keyword: 待判断的关键词
            
        Returns:
            bool: True 表示是代码标识符，False 表示不是
            
        Return Sample:
            _is_identifier("create_order")     # True - 下划线命名
            _is_identifier("OrderService")     # True - 驼峰命名
            _is_identifier("api/v1/orders")    # True - 路径格式
            _is_identifier("订单")              # False - 中文词
            _is_identifier("ab")               # False - 太短
        """
        if not keyword:
            return False
        
        # 包含下划线的通常是标识符
        if '_' in keyword:
            return True
        
        # 驼峰命名（首字母大写，后面有小写）
        if keyword[0].isupper() and len(keyword) > 1 and any(c.islower() for c in keyword[1:]):
            return True
        
        # 纯 ASCII 字母数字，且长度 >= 3
        if keyword.isascii() and keyword.isalnum() and len(keyword) >= 3:
            return True
        
        # 包含点号的（如 api.v1.orders）
        if '.' in keyword or '/' in keyword:
            return True
        
        return False

    async def extract_keywords_with_llm(self, query: str = None) -> Dict[str, List[str]]:
        """
        使用 LLM 从用户查询中提取分类的搜索关键词
        
        LLM 会将关键词分为两类：
        - entity_keywords: 主体关键词（业务实体、模块名），用于定位相关文件
        - action_keywords: 动作关键词（操作、行为），用于在主体范围内筛选
        
        Args:
            query: 用户查询，默认使用 self.query
            
        Returns:
            Dict[str, List[str]]: 分类后的关键词字典
            
        Return Sample:
            # 查询: "怎么创建订单"
            {
                'entity_keywords': ['订单', 'Order'],
                'action_keywords': ['创建', 'create']
            }
            
            # 查询: "create_order 函数在哪里"
            {
                'entity_keywords': ['create_order'],
                'action_keywords': []
            }
            
            # 查询: "用户登录验证流程"
            {
                'entity_keywords': ['用户', 'User', '登录'],
                'action_keywords': ['验证']
            }
        """
        query = query or self.query
        logger.info(f"=== extract_keywords_with_llm, query: {query} ===")
        
        system_template = EXTRACT_KEYWORDS_PROMPT
        human_template = "{query}"
        
        system_prompt = SystemMessagePromptTemplate.from_template(
            template=system_template,
            input_variables=["query"],
        )
        human_prompt = HumanMessagePromptTemplate.from_template(human_template)
        chat_prompt = ChatPromptTemplate.from_messages([system_prompt, human_prompt])
        
        trace_id = self.metadata.get('trace_id', '')
        user_id = self.metadata.get('user_id', '')
        run_id = self.metadata.get('run_id', '')
        
        chain = chat_prompt | self.llm
        
        fallback_result = {
            'entity_keywords': self.codebase_index.extract_search_keywords(query),
            'action_keywords': []
        }
        
        try:
            with langfuse.start_as_current_span(
                name="codeagent-extract-keywords",
                trace_context={"trace_id": trace_id}
            ) as span:
                span.update_trace(
                    user_id=user_id,
                    session_id=run_id,
                    input={"query": query}
                )
                
                answer = await chain.ainvoke(
                    {"query": query},
                    config={"callbacks": [langfuse_handler]}
                )
                
                span.update_trace(output={"answer": str(answer)})
            
            langfuse.flush()
            
            # 解析 LLM 输出
            data_dict = self.format_llm_ouput(answer)
            
            if data_dict and "entity_keywords" in data_dict:
                entity_keywords = data_dict.get("entity_keywords", [])
                action_keywords = data_dict.get("action_keywords", [])
                logger.info(f"LLM extracted - entity: {entity_keywords}, action: {action_keywords}")
                return {
                    'entity_keywords': entity_keywords,
                    'action_keywords': action_keywords
                }
            elif data_dict and "keywords" in data_dict:
                # 兼容旧格式
                keywords = data_dict["keywords"]
                logger.info(f"LLM extracted keywords (old format): {keywords}")
                return {
                    'entity_keywords': keywords,
                    'action_keywords': []
                }
            else:
                logger.warning("LLM did not return keywords in expected format")
                return fallback_result
                
        except Exception as e:
            logger.error(f"Error extracting keywords with LLM: {e}")
            return fallback_result

    async def quick_relevance_check(self, match: Dict[str, Any], query: str) -> bool:
        """
        使用 LLM 快速判断代码片段是否与查询相关
        
        Args:
            match: grep 匹配结果，包含 file_path, match_type, name, content 等
            query: 用户查询
            
        Returns:
            bool: 是否相关
            
        Return Sample:
            # match = {
            #     'file_path': 'order-service/services/order_service.py',
            #     'match_type': 'function',
            #     'name': 'create_order',
            #     'content': '创建新订单，处理订单创建流程'
            # }
            # query = "怎么创建订单"
            # return: True
            
            # match = {
            #     'file_path': 'user-service/services/user_service.py',
            #     'match_type': 'function',
            #     'name': 'create_user',
            #     'content': '创建新用户'
            # }
            # query = "怎么创建订单"
            # return: False  # 虽然都有"创建"，但不相关
        """
        try:
            prompt = QUICK_RELEVANCE_CHECK_PROMPT.format(
                query=query,
                filepath=match.get("file_path", ""),
                segment_type=match.get("match_type", "unknown"),
                name=match.get("name", ""),
                description=match.get("content", "")[:200]  # 截断以加快判断
            )
            
            # 使用较短的超时，快速判断
            answer = await self.llm.ainvoke(prompt)
            data_dict = self.format_llm_ouput(answer)
            
            if data_dict and "relevant" in data_dict:
                return data_dict["relevant"]
            return True  # 解析失败时默认保留
            
        except Exception as e:
            logger.debug(f"Quick relevance check failed: {e}")
            return True  # 出错时默认保留

    async def grep_recall_code_segments(self, max_results: int = 20, use_llm_filter: bool = True,
                                          use_local_grep: bool = False) -> Dict[str, Any]:
        """
        使用 grep 机制召回代码块（先搜主体，再筛选动作）
        
        搜索策略：
        1. 使用 LLM 提取主体关键词（entity）和动作关键词（action）
        2. 先用主体关键词搜索，找到相关文件/代码段
        3. 在主体搜索结果中，用动作关键词进一步筛选
        4. 可选使用 LLM 快速判断相关性进行过滤
        5. 可选使用本地文件 grep 补充搜索结果（混合搜索）
        
        这种"先主体后动作"的策略能避免通用词（如"创建"）匹配到大量无关文件。
        
        Args:
            max_results: 最多返回的代码块数量
            use_llm_filter: 是否使用 LLM 对每个代码片段进行相关性筛选
            use_local_grep: 是否使用本地文件 grep 补充搜索（混合搜索模式）
            
        Returns:
            Dict[str, Any]: 包含 grep 召回结果
            
        Return Sample:
            # query = "怎么创建订单", use_llm_filter = True, use_local_grep = False
            {
                'code_snippets': [
                    {
                        'file_path': 'order-service/services/order_service.py',
                        'code': 'def create_order(self, order_data: dict):\\n    \"\"\"创建新订单\"\"\"\\n    ...',
                        'start_line': 25,
                        'end_line': 45,
                        'matched_keyword': '订单 + 创建',
                        'match_type': 'function',
                        'score': 9.0,
                        'source': 'metadata'
                    },
                    {
                        'file_path': 'order-service/controllers/order_controller.py',
                        'code': '@post("/api/v1/orders")\\ndef create_order_api(request):\\n    ...',
                        'start_line': 15,
                        'end_line': 30,
                        'matched_keyword': '订单 + 创建',
                        'match_type': 'api_endpoint',
                        'score': 9.0,
                        'source': 'metadata'
                    }
                ],
                'grep_matches': [
                    {
                        'file_path': 'order-service/services/order_service.py',
                        'match_type': 'function',
                        'name': 'create_order',
                        'content': '创建新订单，处理订单创建流程',
                        'line_no': '25',
                        'matched_entity_keyword': '订单',
                        'matched_action_keyword': '创建',
                        'source': 'metadata'
                    }
                ],
                'keywords': {
                    'entity_keywords': ['订单', 'Order'],
                    'action_keywords': ['创建', 'create']
                },
                'files_matched': [
                    'order-service/services/order_service.py',
                    'order-service/controllers/order_controller.py'
                ],
                'filtered_count': 5,  # 被 LLM 筛选过滤掉的数量
                'use_llm_filter': True,
                'local_grep_count': 0  # 本地 grep 找到的额外匹配数（use_local_grep=True 时有值）
            }
        """
        logger.info(f"=== grep_recall_code_segments, query: {self.query}, use_llm_filter: {use_llm_filter}, use_local_grep: {use_local_grep} ===")
        
        # 确保 codebase index 已加载
        if not self._codebase_index_loaded:
            await self.load_codebase_index()
        
        if not self._codebase_index_loaded:
            logger.warning("Codebase index not loaded, grep recall not available")
            return {
                'code_snippets': [],
                'grep_matches': [],
                'keywords': {'entity_keywords': [], 'action_keywords': []},
                'files_matched': [],
                'filtered_count': 0,
                'local_grep_count': 0
            }
        
        # 1. 使用 LLM 提取分类关键词
        keywords_dict = await self.extract_keywords_with_llm(self.query)
        entity_keywords = keywords_dict.get('entity_keywords', [])
        action_keywords = keywords_dict.get('action_keywords', [])
        
        logger.info(f"Grep recall - entity: {entity_keywords}, action: {action_keywords}")
        
        if not entity_keywords:
            logger.info("No entity keywords extracted, grep recall returns empty")
            return {
                'code_snippets': [],
                'grep_matches': [],
                'keywords': keywords_dict,
                'files_matched': [],
                'filtered_count': 0,
                'local_grep_count': 0
            }
        
        # 2. 先用主体关键词在元数据中搜索
        entity_matches = {}  # file_path -> list of matches
        for keyword in entity_keywords:
            matches = self.codebase_index.grep(keyword)
            for match in matches:
                filepath = match["file_path"]
                if filepath not in entity_matches:
                    entity_matches[filepath] = []
                match['matched_entity_keyword'] = keyword
                match['source'] = 'metadata'
                entity_matches[filepath].append(match)
        
        metadata_match_count = sum(len(m) for m in entity_matches.values())
        logger.info(f"Grep recall - metadata search found {metadata_match_count} matches in {len(entity_matches)} files")
        
        # 2.5 如果启用本地文件 grep，补充搜索结果
        local_grep_count = 0
        if use_local_grep and self.code_paths:
            # code_paths 是字典，需要提取值（路径列表）
            code_path_list = list(self.code_paths.values())
            
            for keyword in entity_keywords:
                # 只对像标识符的关键词使用本地 grep
                if self._is_identifier(keyword):
                    local_matches = self.codebase_index.local_file_grep(
                        keyword, 
                        code_path_list,
                        max_results_per_file=5
                    )
                    local_grep_count += len(local_matches)
                    
                    for match in local_matches:
                        filepath = match["file_path"]
                        # 标准化路径
                        for code_path in code_path_list:
                            if filepath.startswith(code_path):
                                filepath = filepath[len(code_path):].lstrip('/')
                                break
                        
                        if filepath not in entity_matches:
                            entity_matches[filepath] = []
                        match['file_path'] = filepath
                        match['matched_entity_keyword'] = keyword
                        match['source'] = 'local_grep'
                        entity_matches[filepath].append(match)
            
            logger.info(f"Grep recall - local grep found {local_grep_count} additional matches")
        
        # 3. 在主体搜索结果中，用动作关键词进一步筛选
        all_matches = []
        file_scores = {}
        
        for filepath, matches in entity_matches.items():
            # 检查这个文件的代码分析中是否包含动作关键词
            action_match_count = 0
            action_matched_keywords = set()
            
            if action_keywords:
                # 检查文件中的匹配项是否同时包含动作关键词
                for match in matches:
                    match_content = f"{match.get('name', '')} {match.get('content', '')}"
                    for action_kw in action_keywords:
                        if action_kw.lower() in match_content.lower():
                            action_match_count += 1
                            action_matched_keywords.add(action_kw)
                            match['matched_action_keyword'] = action_kw
                            break
                
                # 如果有动作关键词但文件中没有匹配，降低优先级但不排除
                if action_match_count == 0:
                    # 仍然保留，但分数较低
                    for match in matches:
                        match['matched_action_keyword'] = None
            
            # 计算文件分数
            base_score = 0
            for match in matches:
                match_type = match.get("match_type", "")
                if match_type == "function":
                    base_score += 3
                elif match_type == "entity":
                    base_score += 2
                elif match_type == "api_endpoint":
                    base_score += 3
                else:
                    base_score += 1
            
            # 动作关键词匹配加成
            if action_keywords:
                if action_match_count > 0:
                    # 同时匹配主体和动作，大幅加分
                    multiplier = 3.0 + len(action_matched_keywords)
                else:
                    # 只匹配主体，轻微降分
                    multiplier = 0.7
            else:
                # 没有动作关键词要求，正常计分
                multiplier = 1.0
            
            file_scores[filepath] = base_score * multiplier
            
            # 添加匹配到结果列表
            for match in matches:
                all_matches.append(match)
        
        # 4. 可选 LLM 筛选
        filtered_count = 0
        if use_llm_filter and all_matches:
            original_count = len(all_matches)
            batch_size = 50
            total_batches = (len(all_matches) + batch_size - 1) // batch_size

            # 为每个批次定义异步处理函数
            async def _filter_batch(batch, batch_idx):
                tasks = [self.quick_relevance_check(m, self.query) for m in batch]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                kept = []
                for match, is_relevant in zip(batch, results):
                    if isinstance(is_relevant, Exception) or is_relevant:
                        kept.append(match)
                logger.info(
                    f"[LLM filter] 批次 {batch_idx}/{total_batches}: "
                    f"本批 {len(batch)} 个片段，{len(kept)} 个相关，{len(batch) - len(kept)} 个无关"
                )
                return kept

            # 所有批次并行执行（批次间无依赖）
            batch_coros = []
            for i in range(0, len(all_matches), batch_size):
                batch = all_matches[i:i + batch_size]
                batch_idx = i // batch_size + 1
                batch_coros.append(_filter_batch(batch, batch_idx))

            batch_results = await asyncio.gather(*batch_coros, return_exceptions=True)

            filtered_matches = []
            for br in batch_results:
                if isinstance(br, Exception):
                    logger.error(f"[LLM filter] batch failed: {br}")
                else:
                    filtered_matches.extend(br)

            filtered_count = original_count - len(filtered_matches)
            all_matches = filtered_matches
            logger.info(f"[LLM filter] 汇总: local grep 共 {original_count} 个片段，LLM 判定相关 {len(filtered_matches)} 个，过滤无关 {filtered_count} 个")
        
        logger.info(f"Grep recall - found {len(all_matches)} matches in {len(file_scores)} files" + 
                   (f", filtered out {filtered_count}" if use_llm_filter else ""))
        
        # 5. 去重并按分数排序匹配结果
        seen = set()
        unique_matches = []
        for match in all_matches:
            # 使用 (文件路径, 名称, 行号) 作为唯一键
            key = (match["file_path"], match.get("name", ""), match.get("line_no", ""))
            if key not in seen:
                seen.add(key)
                unique_matches.append(match)
        
        # 按文件分数排序
        unique_matches.sort(
            key=lambda m: file_scores.get(m["file_path"], 0),
            reverse=True
        )
        
        # 限制结果数量
        unique_matches = unique_matches[:max_results]
        
        # 6. 读取代码内容，构建与语义检索兼容的 code_snippets 格式
        # 使用 seen_code_blocks 去重：local grep 在同一函数内匹配多行时，
        # smart_read_code 会读到相同的完整函数，通过代码首行去重避免重复
        code_snippets = []
        seen_code_blocks = set()
        
        for match in unique_matches:
            filepath = match["file_path"]
            line_no = match.get("line_no")
            
            # 读取代码内容（使用智能读取：code_text 类型会自动扩展到完整函数）
            code_content = ""
            if line_no:
                code_path = self.get_code_path()
                if code_path:
                    code_content = smart_read_code(
                        code_base_path=code_path,
                        filepath=filepath,
                        line_no=str(line_no),
                        match_type=match.get("match_type", "unknown")
                    )
                else:
                    code_content = self.extract_code_by_line_range(
                        filepath=filepath,
                        line_no=str(line_no),
                        context_lines=5
                    )
            
            # 去重：用 (文件路径, 代码内容首行) 作为唯一键
            # 避免 local grep 多行匹配同一函数时返回重复的完整函数代码
            if code_content:
                first_line = code_content.split('\n')[0].strip() if code_content else ""
                dedup_key = (filepath, first_line)
                if dedup_key in seen_code_blocks:
                    continue
                seen_code_blocks.add(dedup_key)
            
            # 记录匹配的关键词
            entity_kw = match.get('matched_entity_keyword', '')
            action_kw = match.get('matched_action_keyword', '')
            matched_info = entity_kw
            if action_kw:
                matched_info = f"{entity_kw} + {action_kw}"
            
            snippet = {
                'file_path': filepath,
                'segment_type': match.get("match_type", "unknown"),
                'name': match.get("name", ""),
                'line_no': str(line_no) if line_no else "",
                'relevance_reason': f"grep 匹配: {match.get('content', '')[:100]}",
                'business_meaning': match.get("content", ""),
                'code_content': code_content,
                'source': match.get('source', 'metadata'),  # 保留原始来源：metadata / local_grep
                'matched_keyword': matched_info
            }
            code_snippets.append(snippet)
        
        files_matched = list(file_scores.keys())
        logger.info(f"Grep recall - returning {len(code_snippets)} code snippets from {len(files_matched)} files")
        
        return {
            'code_snippets': code_snippets,
            'grep_matches': unique_matches,
            'keywords': keywords_dict,  # 返回分类后的关键词
            'files_matched': files_matched,
            'filtered_count': filtered_count,
            'use_llm_filter': use_llm_filter,
            'local_grep_count': local_grep_count if use_local_grep else 0
        }

    async def hybrid_search(self, filepaths: List[str] = None, use_llm_filter: bool = True,
                            use_local_grep: bool = True) -> Dict[str, Any]:
        """
        混合检索：结合语义检索和 grep 召回（并行执行）
        
        **并行**执行 search_and_extract_code_enhanced（语义检索）和 grep_recall_code_segments（grep 召回），
        然后合并两者的代码块结果，去重后返回。
        
        语义检索的结果优先级更高（排在前面），grep 召回的结果作为补充。
        
        Args:
            filepaths: 可选，直接指定文件路径列表传给语义检索
            use_llm_filter: grep 召回时是否使用 LLM 筛选（默认 True）
            use_local_grep: 是否启用本地文件 grep 补充搜索（默认 True，方案二）
            
        Returns:
            Dict[str, Any]: 合并后的结果
            
        Return Sample:
            # query = "怎么创建订单"
            {
                'code_snippets': [
                    # 语义检索结果（优先）
                    {
                        'file_path': 'order-service/services/order_service.py',
                        'segment_type': 'function',
                        'name': 'create_order',
                        'line_no': '25-45',
                        'relevance_score': 10,
                        'code_content': 'async def create_order(self, data):\\n    ...',
                        'source': 'semantic'
                    },
                    # grep 召回补充结果（metadata 元数据匹配 或 local_grep 本地文件搜索）
                    {
                        'file_path': 'order-service/validators/order_validator.py',
                        'code': 'def validate_order_data(data):\\n    ...',
                        'start_line': 10,
                        'end_line': 25,
                        'matched_keyword': '订单 + 创建',
                        'match_type': 'function',
                        'source': 'metadata'
                    }
                ],
                'semantic_result': {
                    'search_result': CodeSearchResult(...),
                    'code_snippets': [...]  # 语义检索完整结果
                },
                'grep_result': {
                    'code_snippets': [...],
                    'grep_matches': [...],
                    'keywords': {'entity_keywords': ['订单'], 'action_keywords': ['创建']},
                    'files_matched': [...],
                    'filtered_count': 3
                },
                'semantic_snippets_count': 5,    # 语义检索返回的代码块数量
                'grep_only_snippets_count': 2,   # grep 独有的代码块数量（去重后）
                'total_snippets_count': 7        # 合并后总数
            }
        """
        logger.info(f"=== hybrid_search (parallel), query: {self.query}, use_local_grep: {use_local_grep} ===")
        
        # **并行**执行语义检索和 grep 召回
        logger.info("Hybrid search - Parallel execution: Semantic + Grep (local_grep={})".format(use_local_grep))
        
        semantic_task = self.search_and_extract_code_enhanced(filepaths)
        grep_task = self.grep_recall_code_segments(max_results=20, use_llm_filter=use_llm_filter, use_local_grep=use_local_grep)
        
        # 并行等待两个任务完成
        results = await asyncio.gather(semantic_task, grep_task, return_exceptions=True)
        
        # 处理语义检索结果
        if isinstance(results[0], Exception):
            logger.error(f"Semantic retrieval failed: {results[0]}")
            semantic_result = {'code_snippets': []}
        else:
            semantic_result = results[0]
        semantic_snippets = semantic_result.get('code_snippets', [])
        logger.info(f"Semantic retrieval returned {len(semantic_snippets)} code snippets")
        
        # 处理 grep 召回结果
        if isinstance(results[1], Exception):
            logger.error(f"Grep recall failed: {results[1]}")
            grep_result = {'code_snippets': [], 'keywords': [], 'files_matched': [], 'filtered_count': 0}
        else:
            grep_result = results[1]
        grep_snippets = grep_result.get('code_snippets', [])
        logger.info(f"Grep recall returned {len(grep_snippets)} code snippets" + 
                   (f", filtered {grep_result.get('filtered_count', 0)}" if use_llm_filter else ""))
        
        # 3. 合并代码块，去重
        # 使用 (file_path, name, line_no) 作为唯一键
        seen_keys = set()
        merged_snippets = []
        
        # 先添加语义检索的结果（优先级高）
        for snippet in semantic_snippets:
            key = (snippet['file_path'], snippet.get('name', ''), snippet.get('line_no', ''))
            if key not in seen_keys:
                seen_keys.add(key)
                snippet['source'] = 'semantic'  # 标记来源
                merged_snippets.append(snippet)
        
        semantic_count = len(merged_snippets)
        
        # 再添加 grep 召回的结果（作为补充）
        # 保留原始来源标记：'metadata'（元数据匹配）或 'local_grep'（本地文件 grep）
        grep_only_count = 0
        for snippet in grep_snippets:
            key = (snippet['file_path'], snippet.get('name', ''), snippet.get('line_no', ''))
            if key not in seen_keys:
                seen_keys.add(key)
                # 保留原始 source（metadata / local_grep），没有标记的兜底为 metadata
                if not snippet.get('source'):
                    snippet['source'] = 'metadata'
                merged_snippets.append(snippet)
                grep_only_count += 1
        
        logger.info(f"Hybrid search - Merged: {semantic_count} semantic + {grep_only_count} grep-only = {len(merged_snippets)} total")
        
        return {
            'code_snippets': merged_snippets,
            'semantic_result': semantic_result,
            'grep_result': grep_result,
            'semantic_snippets_count': semantic_count,
            'grep_only_snippets_count': grep_only_count,
            'total_snippets_count': len(merged_snippets),
            # 保留语义检索的其他字段
            'search_result': semantic_result.get('search_result'),
            'located_files': semantic_result.get('located_files', []),
            'expanded_files': semantic_result.get('expanded_files', []),
            'dependency_info': semantic_result.get('dependency_info', {}),
            'call_chain_info': semantic_result.get('call_chain_info', []),
        }

    def format_code_snippets_for_answer(self, code_snippets: List[Dict[str, Any]]) -> str:
        """
        将代码片段格式化为可用于回答的字符串
        
        将搜索到的代码片段转换为 Markdown 格式的字符串，便于在回答中展示。
        每个代码片段会包含文件路径、代码元素名称、行号、相关原因、业务含义和代码内容。
        
        Args:
            code_snippets: 代码片段列表，每个元素包含 file_path, name, segment_type, 
                           line_no, relevance_reason, business_meaning, code_content
        
        Returns:
            格式化的代码片段字符串（Markdown 格式）
            
        Return Sample:
            # 输入:
            # code_snippets = [
            #     {
            #         'file_path': 'order-service/services/order_service.py',
            #         'name': 'create_order',
            #         'segment_type': 'function',
            #         'line_no': '45-98',
            #         'relevance_reason': '订单创建的核心业务逻辑',
            #         'business_meaning': '创建新订单的主要业务方法',
            #         'code_content': 'async def create_order(self, data):\\n    ...'
            #     },
            #     {
            #         'file_path': 'order-service/models/order.py',
            #         'name': 'Order',
            #         'segment_type': 'entity',
            #         'line_no': '10-45',
            #         'relevance_reason': '订单数据模型定义',
            #         'business_meaning': '订单实体类',
            #         'code_content': 'class Order:\\n    ...'
            #     }
            # ]
            
            # 输出:
            '''
            ### 文件: order-service/services/order_service.py
            **代码元素**: create_order (function)
            **行号**: 45-98
            **相关原因**: 订单创建的核心业务逻辑
            **业务含义**: 创建新订单的主要业务方法

            ```
            async def create_order(self, data):
                ...
            ```

            ### 文件: order-service/models/order.py
            **代码元素**: Order (entity)
            **行号**: 10-45
            **相关原因**: 订单数据模型定义
            **业务含义**: 订单实体类

            ```
            class Order:
                ...
            ```
            '''
        """
        parts = []
        
        for snippet in code_snippets:
            # 根据来源添加标注
            source = snippet.get('source', 'unknown')
            source_tag = ""
            if source == 'call_chain':
                chain_role = snippet.get('call_chain_role', '')
                source_tag = f" [调用链: {chain_role}]" if chain_role else " [调用链扩展]"
            elif source == 'metadata':
                source_tag = " [元数据检索]"
            elif source == 'local_grep':
                source_tag = " [本地grep]"
            elif source == 'semantic':
                source_tag = " [语义检索]"
            
            part = f"\n### 文件: {snippet['file_path']}{source_tag}\n"
            part += f"**代码元素**: {snippet['name']} ({snippet['segment_type']})\n"
            part += f"**行号**: {snippet['line_no']}\n"
            part += f"**相关原因**: {snippet['relevance_reason']}\n"
            if snippet.get('business_meaning'):
                part += f"**业务含义**: {snippet['business_meaning']}\n"
            part += f"\n```\n{snippet['code_content']}\n```\n"
            parts.append(part)
        
        return "\n".join(parts)

    def _log_code_snippets_info(self, code_snippets: List[Dict[str, Any]]) -> None:
        """
        友好地打印找到的代码片段信息
        
        Args:
            code_snippets: 代码片段列表
        """
        if not code_snippets:
            logger.info("=" * 60)
            logger.info("[CODE SEARCH] 未找到相关代码片段")
            logger.info("=" * 60)
            return
        
        # 统计各来源的数量
        source_counts = {}
        for s in code_snippets:
            src = s.get('source', 'unknown')
            source_counts[src] = source_counts.get(src, 0) + 1
        source_summary = ", ".join(f"{k}: {v}" for k, v in source_counts.items())
        
        logger.info("=" * 80)
        logger.info(f"[CODE SEARCH] 找到 {len(code_snippets)} 个相关代码片段 ({source_summary})")
        logger.info("=" * 80)
        
        for i, snippet in enumerate(code_snippets, 1):
            file_path = snippet.get('file_path', 'unknown')
            segment_type = snippet.get('segment_type', 'unknown')
            name = snippet.get('name', 'unknown')
            line_no = snippet.get('line_no', 'N/A')
            relevance_reason = snippet.get('relevance_reason', '')
            business_meaning = snippet.get('business_meaning', '')
            code_content = snippet.get('code_content', '')
            source = snippet.get('source', 'unknown')
            
            # 来源标签
            source_label = {
                'semantic': 'SEMANTIC',
                'metadata': 'METADATA_GREP',
                'call_chain': 'CALL_CHAIN',
                'local_grep': 'LOCAL_GREP',
            }.get(source, source.upper())
            
            logger.info("-" * 80)
            logger.info(f"[{i}/{len(code_snippets)}] {name} [{source_label}]")
            logger.info(f"    File: {file_path}")
            logger.info(f"    Line: {line_no}")
            logger.info(f"    Type: {segment_type}")
            logger.info(f"    Source: {source_label}")
            if relevance_reason:
                logger.info(f"    Relevance: {relevance_reason}")
            if business_meaning:
                logger.info(f"    Business: {business_meaning}")
            
            # 打印代码内容（限制长度，避免日志过长）
            if code_content:
                code_lines = code_content.split('\n')
                max_lines = 30  # 最多显示30行
                
                logger.info(f"    Code ({len(code_lines)} lines):")
                logger.info("    " + "-" * 50)
                
                # 检查代码是否已经包含行号前缀（格式如 "  18|"）
                has_line_prefix = len(code_lines) > 0 and '|' in code_lines[0][:10] if code_lines[0] else False
                
                for j, line in enumerate(code_lines[:max_lines]):
                    if has_line_prefix:
                        # 代码已包含行号，直接打印
                        logger.info(f"    {line}")
                    else:
                        # 计算实际行号（如果 line_no 是范围格式如 "45-100"）
                        try:
                            if "-" in str(line_no):
                                start_line = int(str(line_no).split("-")[0].strip())
                                actual_line_no = start_line + j
                            else:
                                actual_line_no = int(line_no) + j if line_no != 'N/A' else j + 1
                        except (ValueError, TypeError):
                            actual_line_no = j + 1
                        
                        # 格式化输出，行号右对齐
                        logger.info(f"    {actual_line_no:>6} | {line}")
                
                if len(code_lines) > max_lines:
                    logger.info(f"    ... ({len(code_lines) - max_lines} more lines omitted) ...")
                
                logger.info("    " + "-" * 50)
        
        logger.info("=" * 80)
        logger.info("[CODE SEARCH] Code snippets logged, starting to generate answer...")
        logger.info("=" * 80)

    async def answer_with_code(self, code_snippets: List[Dict[str, Any]], 
                               call_chain_info: List[str] = None) -> str:
        """
        基于代码片段回答用户问题
        
        Args:
            code_snippets: 代码片段列表，每个片段包含:
                - file_path: 文件路径
                - segment_type: 代码类型 (function/entity/api_endpoint/global_function)
                - name: 代码名称
                - line_no: 行号范围
                - relevance_score: 相关性评分
                - relevance_reason: 相关性说明
                - business_meaning: 业务含义
                - code_content: 实际代码内容
            call_chain_info: 可选的调用链路径描述列表
        
        Returns:
            回答字符串
        """
        system_template = ANSWER_WITH_CODE_PROMPT
        
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        code_snippets_str = self.format_code_snippets_for_answer(code_snippets)
        
        # 如果有调用链信息，附加到代码片段上下文中
        if call_chain_info:
            chain_section = "\n\n=== 函数调用链路径 ===\n"
            chain_section += "\n\n".join(call_chain_info)
            chain_section += "\n"
            code_snippets_str = code_snippets_str + chain_section
        
        system_prompt = SystemMessagePromptTemplate.from_template(
            template=system_template,
            input_variables=["current_time", "code_snippets", "query"],
        )
        
        chat_prompt = ChatPromptTemplate.from_messages([system_prompt])
        
        user_id = self.metadata.get('user_id', 'unknown')
        run_id = self.metadata.get('run_id', 'unknown')
        trace_id = self.metadata.get('trace_id', 'unknown')
        
        chain = chat_prompt | self.llm
        
        with langfuse.start_as_current_span(
            name="codeagent-answer-with-code",
            trace_context={"trace_id": trace_id}
        ) as span:
            span.update_trace(
                user_id=user_id,
                session_id=run_id,
                input={"query": self.query}
            )
            
            answer = await chain.ainvoke(
                {
                    "query": self.query,
                    "current_time": current_time,
                    "code_snippets": code_snippets_str
                },
                config={"callbacks": [langfuse_handler]}
            )
            
            span.update_trace(output={"answer": answer})
        
        langfuse.flush()
        
        return answer.content if hasattr(answer, 'content') else str(answer)

    async def step(self) -> str:
        """
        Execute a single step with streaming support.
        
        完整流程:
        1. hybrid_search() - 混合检索相关代码（并行执行语义检索 + grep 召回）
           │
           ├── [并行分支1] search_and_extract_code_enhanced() - 语义检索
           │   ├── two_stage_knowledge_retrieval() - 两阶段知识检索
           │   │   ├── get_all_knowledge_blocks() - 获取所有知识块
           │   │   ├── locate_files() - LLM 定位相关文件
           │   │   └── 获取完整知识内容
           │   ├── observe_locate_files() - LLM 审查验证文件
           │   ├── load_codebase_index() - 加载代码库索引到内存
           │   ├── 依赖分析 - 扩展调用链（2级深度）
           │   ├── search_relevant_code_segments() - LLM 精确筛选代码片段
           │   └── extract_code_by_line_range() - 从本地文件读取代码
           │
           └── [并行分支2] grep_recall_code_segments() - grep 召回
               ├── extract_keywords_with_llm() - LLM 提取分类关键词
               │   └── 返回 entity_keywords（主体）+ action_keywords（动作）
               ├── codebase_index.grep() - 元数据关键词搜索
               │   └── 搜索 file_summary、entity、function、api_endpoint
               ├── local_file_grep() - 本地文件 grep（可选，默认启用）
               │   └── _is_identifier() 判断：仅对标识符命名执行
               │       ├── create_order, OrderService → ✅ 执行 local grep
               │       └── 订单, 创建 → ❌ 跳过（中文词不适合搜代码）
               ├── 动作关键词二次筛选 - 在主体结果中匹配动作词
               └── quick_relevance_check() - LLM 快速相关性过滤（并行）
           
        2. answer_with_code() - 基于代码片段生成自然语言回答
        3. observe_common() - LLM 验证回答质量
        4. 返回结果或触发 requery 重新查询
        """
        # 获取第一个 code 类型的配置
        code_config = self.get_first_code_config()
        
        if not code_config or code_config.descriptor_type != "code":
            raise ValueError(f"Unsupported or missing descriptor type. Expected 'code', got: {code_config.descriptor_type if code_config else 'None'}")

        llm_result = None
        
        try:
            # ========== Step 1: 混合检索相关代码（语义检索 + grep 召回 并行执行） ==========
            logger.info(f"[step] 开始混合检索相关代码，query: {self.query}")
            
            search_result = await self.hybrid_search()
            
            code_snippets = search_result.get('code_snippets', [])
            search_info = search_result.get('search_result')
            call_chain_info = search_result.get('call_chain_info', [])
            
            logger.info(f"[step] 搜索完成，找到 {len(code_snippets)} 个代码片段"
                       + (f"（含 {len(call_chain_info)} 条调用链路径）" if call_chain_info else ""))
            
            # ========== answer_model=original: 直接返回代码片段，跳过 LLM 回答和验证 ==========
            answer_model = self.metadata.get('answer_model', '') if self.metadata else ''
            logger.info(f"[step] 检查 answer_model: '{answer_model}', metadata keys: {list(self.metadata.keys()) if self.metadata else 'None'}")
            if answer_model == "original":
                logger.info(f">>>>>> [answer_model=original] CodeAgent.step() 直接返回代码片段，跳过 answer_with_code 和 observe_common，共 {len(code_snippets)} 个代码片段 <<<<<<")
                if code_snippets:
                    self._log_code_snippets_info(code_snippets)
                    # 将代码片段格式化为可读文本直接返回
                    parts = []
                    for snippet in code_snippets:
                        file_path = snippet.get('file_path', '')
                        code_content = snippet.get('code_content', snippet.get('code', ''))
                        line_no = snippet.get('line_no', snippet.get('start_line', ''))
                        name = snippet.get('name', '')
                        header = f"=== {file_path}"
                        if name:
                            header += f" :: {name}"
                        if line_no:
                            header += f" (line {line_no})"
                        header += " ==="
                        parts.append(f"{header}\n{code_content}")
                    raw_code = "\n\n".join(parts)
                    self.state = AgentState.FINISHED
                    self.save_step_status(self.query, raw_code)
                    return raw_code
                else:
                    self.state = AgentState.FINISHED
                    no_code_msg = f"未找到与问题 '{self.query}' 相关的代码"
                    self.save_step_status(self.query, no_code_msg)
                    return no_code_msg

            # ========== Step 2: 基于代码生成回答 ==========
            if code_snippets:
                # 打印找到的代码信息（友好格式）
                self._log_code_snippets_info(code_snippets)
                
                logger.info(f"[step] 开始生成回答")
                answer = await self.answer_with_code(code_snippets, call_chain_info=call_chain_info)
                
                # 构建 LLMResult
                llm_result = LLMResult(
                    answer=answer,
                    conclusion="terminate",
                    requery=""
                )
                logger.info(f"[step] 回答生成完成")
            else:
                # 未找到相关代码，尝试重新查询
                logger.warning(f"[step] 未找到相关代码片段，尝试重新生成问题")
                self.state = AgentState.IDLE
                
                # 调用 requery 生成新问题
                requery = await self.invoke_requery()
                requery_text = ""
                if requery.conclusion == "terminate" and requery.requery:
                    requery_text = requery.requery
                
                llm_result = LLMResult(
                    answer=f"未找到与问题 '{self.query}' 相关的代码，将尝试重新提问",
                    conclusion="continue",
                    requery=requery_text
                )
            
            # ========== Step 3: 验证回答质量 ==========
            if llm_result and llm_result.conclusion == "terminate":
                # 构建代码相关的上下文，帮助 LLM 更好地判断回答质量
                observe_context = self._build_observe_context(code_snippets, search_info)
                
                logger.info(f"[step] 开始验证回答质量")
                observe_result = await self.observe_common(self.query, llm_result.answer, observe_context)
                
                if observe_result.conclusion == "continue":
                    # 回答质量不佳，需要重新查询
                    logger.info(f"[step] 回答质量验证未通过: {observe_result.reason}")
                    llm_result.conclusion = "continue"
                    self.state = AgentState.IDLE
                    
                    requery = await self.invoke_requery()
                    if requery.conclusion == "terminate" and requery.requery:
                        llm_result.requery = requery.requery
                    llm_result.answer = f"当前回答未能充分解决问题，原因: {observe_result.reason}"
                else:
                    # 回答质量通过，添加成功标记用于外部判断任务完成状态
                    logger.info(f"[step] 回答质量验证通过")
                    step_status_llm_check_success = "The current answer addresses the question very well."
                    llm_result.answer = f"reason:{step_status_llm_check_success}\n\n{llm_result.answer}"
                    
        except Exception as e:
            logger.error(f"[step] 执行出错: {e}", exc_info=True)
            self.state = AgentState.IDLE
            self.save_step_status(self.query, f"step error: {e}")
            
            requery = await self.invoke_requery()
            if requery.conclusion == "terminate":
                self.query = requery.requery
                self._update_task_description(requery.requery)
            return f"执行出错: {e}，将尝试其他方式回答问题: {self.original_query}"

        # ========== Step 4: 处理结果 ==========
        if llm_result:
            if llm_result.conclusion == "terminate":
                # 成功完成，结束 Agent
                self.state = AgentState.FINISHED
                self.memory.add_message(Message.assistant_message(llm_result.answer))
                self.save_step_status(self.query, llm_result.answer)

            elif llm_result.conclusion == "continue":
                # 需要重新查询
                self.save_step_status(self.query, llm_result.answer)
                if llm_result.requery:
                    self.query = llm_result.requery
                    self._update_task_description(llm_result.requery)

            if not llm_result.answer:
                answer = f"未能找到相关知识回答问题: {self.original_query}，将尝试其他方式!"
                return answer
            else:
                return llm_result.answer
        else:
            raise ValueError("step 执行异常: llm_result 为空")

    def save_step_status(self, query:str, answer: str):
        step_status = StepStatus(
            id=self.current_step,
            query=query,
            answer=answer
        )
        self.step_status_list.append(step_status)
        logger.info(f"Saved step {self.current_step} status: query='{query}'")

    def get_step_history_for_requery(self) -> str:
        if not self.step_status_list:
            return "No historical step records"
        
        history_lines = []
        for step in self.step_status_list:
            history_lines.append(f"Step {step.id}:")
            history_lines.append(f"  Query: {step.query}")
            history_lines.append(f"  Answer: {step.answer}")
            history_lines.append("")
        
        return "\n".join(history_lines)

    def format_tasks_status(self, tasks):
        if not tasks:
            return "No tasks available"
        
        lines = []
        for task in tasks:
            lines.append(f"Task {task.id}: {task.description}")
            lines.append(f"  Agent: {task.agent}")
            lines.append(f"  Status: {task.status}")
            lines.append(f"  Answer: {task.answer}\n")
        
        return "\n".join(lines)

    def _build_observe_context(self, code_snippets: List[Dict[str, Any]], search_info: Optional[CodeSearchResult]) -> str:
        """
        构建用于 observe_common 的代码上下文
        
        Args:
            code_snippets: 代码片段列表
            search_info: 搜索结果信息
        
        Returns:
            格式化的上下文字符串
        """
        context_parts = []
        
        # 1. 搜索结果摘要
        if search_info:
            context_parts.append("=== 代码搜索结果 ===")
            context_parts.append(f"意图分析: {search_info.intent_analysis}")
            context_parts.append(f"搜索摘要: {search_info.summary}")
            context_parts.append("")
        
        # 2. 找到的代码片段摘要
        if code_snippets:
            context_parts.append("=== 相关代码片段 ===")
            for i, snippet in enumerate(code_snippets, 1):
                context_parts.append(f"{i}. {snippet.get('file_path', 'unknown')}")
                context_parts.append(f"   - 类型: {snippet.get('segment_type', 'unknown')}")
                context_parts.append(f"   - 名称: {snippet.get('name', 'unknown')}")
                context_parts.append(f"   - 业务含义: {snippet.get('business_meaning', '无')}")
                context_parts.append(f"   - 相关原因: {snippet.get('relevance_reason', '无')}")
            context_parts.append("")
            context_parts.append(f"共找到 {len(code_snippets)} 个相关代码片段")
        else:
            context_parts.append("未找到相关代码片段")
        
        return "\n".join(context_parts)

    def _update_task_description(self, new_task_description: str):
        if self.current_tasks_status and self.current_tasks_status.tasks and self.current_task_id is not None:
            for task in self.current_tasks_status.tasks:
                if task.id == self.current_task_id:
                    task.description = new_task_description
                    logger.info(f"Updated task {self.current_task_id} description to: {new_task_description}")
                    break

    def is_stuck(self) -> bool:
        """Check if the agent is stuck in a loop by detecting duplicate content"""
        if len(self.memory.messages) < 2:
            return False

        last_message = self.memory.messages[-1]
        if not last_message.content:
            return False

        # Count identical content occurrences
        duplicate_count = sum(
            1
            for msg in reversed(self.memory.messages[:-1])
            if msg.role == "assistant" and msg.content == last_message.content
        )

        return duplicate_count >= self.duplicate_threshold

    def update_memory(
        self,
        role: ROLE_TYPE,  # type: ignore
        content: str,
        **kwargs,
    ) -> None:
        """Add a message to the agent's memory.

        Args:
            role: The role of the message sender (user, system, assistant, tool).
            content: The message content.
            **kwargs: Additional arguments (e.g., tool_call_id for tool messages).

        Raises:
            ValueError: If the role is unsupported.
        """
        message_map = {
            "user": Message.user_message,
            "system": Message.system_message,
            "assistant": Message.assistant_message,
            "tool": lambda content, **kw: Message.tool_message(content, **kw),
        }

        if role not in message_map:
            raise ValueError(f"Unsupported message role: {role}")

        # Create message with appropriate parameters based on role
        kwargs = {**(kwargs if role == "tool" else {})}
        self.memory.add_message(message_map[role](content, **kwargs))

    async def run(self) -> AsyncIterable[str]:
        """Run the agent with streaming support."""
        logger.debug(f"************** agent run, query: {self.query}, data_descriptors: {self.data_descriptors} **************")
        if self.state != AgentState.IDLE:
            raise RuntimeError(f"Cannot run agent from state: {self.state}")

        if self.query:
            self.update_memory("user", self.query)

        async with self.state_context(AgentState.RUNNING):
            while (
                self.current_step < self.max_steps and self.state != AgentState.FINISHED
            ):
                self.current_step += 1

                current_task = self.metadata.get('current_task', '')

                logger.info(f"******************** {current_task}, current query: {self.query}, Executing step {self.current_step}/{self.max_steps}")

                step_result_str = f"step {self.current_step}/{self.max_steps}: query: {self.query}"

                step_result = await self.step()

                steps_status = self.get_step_history_for_requery()

                logger.debug(f"******************** steps status: \n\n {steps_status}")
                
                step_result = f"{step_result_str}\n\nanswer: {step_result}\n"

                yield step_result

            if self.current_step >= self.max_steps:
                self.current_step = 0
                self.state = AgentState.FINISHED


class CodeAgentExecutor(AgentExecutor):
    """
    A Code Agent answer user question.
    """

    def __init__(
        self,
        provider: str = "openai_compatible",
        api_key: str = None,
        base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
        model: str = "qwen2.5-72b-instruct",
        stream: bool = True,
        temperature: float = 0.01,
        data_descriptors:list = None,
        dd_namespace:str = None,
        descriptor_types:list = None,
        data_services_url: str = None,
        max_steps:int = 5,
        code_paths: Dict[str, str] = None

    ):
        self.provider=provider
        self.api_key=api_key
        self.base_url=base_url
        self.model=model
        self.stream=stream
        self.temperature=temperature
        self.data_descriptors=data_descriptors
        self.dd_namespace=dd_namespace
        self.descriptor_types=descriptor_types
        self.data_services_url=data_services_url
        self.stream_enabled = stream
        self.max_steps = max_steps
        self.code_paths = code_paths or {}  # 存储 clone 后的代码路径，key 为配置名称，value 为本地路径
        
        # 全局 codebase index，服务级别单例，只加载一次
        self._codebase_index = CodebaseIndex()
        self._codebase_index_loaded = False
        self._codebase_index_lock = asyncio.Lock()  # 防止并发加载
        
        # 服务启动时预加载 codebase index
        self._preload_codebase_index()
    
    def _preload_codebase_index(self) -> None:
        """
        服务启动时预加载 codebase index（同步方法，在 __init__ 中调用）
        """
        logger.info("[STARTUP] Preloading codebase index...")
        try:
            # 尝试获取当前事件循环
            try:
                loop = asyncio.get_running_loop()
                # 如果已有运行中的事件循环，创建任务稍后执行
                loop.create_task(self._ensure_codebase_index_loaded())
                logger.info("[STARTUP] Codebase index preload task scheduled")
            except RuntimeError:
                # 没有运行中的事件循环，创建新的来执行
                asyncio.run(self._ensure_codebase_index_loaded())
        except Exception as e:
            logger.error(f"[STARTUP] Failed to preload codebase index: {e}")
            logger.info("[STARTUP] Will try to load on first request")
    
    async def _ensure_codebase_index_loaded(self) -> bool:
        """
        确保 codebase index 已加载（懒加载，只加载一次）
        
        Returns:
            是否加载成功
        """
        if self._codebase_index_loaded:
            return True
        
        async with self._codebase_index_lock:
            # 双重检查，防止并发时重复加载
            if self._codebase_index_loaded:
                return True
            
            try:
                logger.info("Loading global codebase index from data-services (one-time)...")
                
                dd_name = self.data_descriptors[0] if self.data_descriptors else None
                
                data_services_client = DataServicesClient(
                    base_url=self.data_services_url,
                    timeout=600,
                    use_data_descriptor_header=True
                )
                
                # 使用 by_dd 搜索获取整个 repo 的所有文件
                result = await data_services_client.search_codebase_indexers_by_dd(
                    dd_namespace=self.dd_namespace,
                    dd_name=dd_name
                )
                
                records = []
                if result and result.data:
                    for item in result.data:
                        record = {
                            "codebase_indexer_id": item.codebase_indexer_id,
                            "filepath": item.filepath,
                            "code_deep_analysis": item.code_deep_analysis,
                            "dd_namespace": item.dd_namespace,
                            "dd_name": item.dd_name
                        }
                        records.append(record)
                
                await data_services_client.close()
                
                if records:
                    self._codebase_index.load_from_records(records)
                    self._codebase_index_loaded = True
                    
                    # 打印加载完成的详细信息
                    self._log_codebase_index_loaded(records, dd_name)
                    return True
                else:
                    logger.warning(f"No codebase indexer records found for DD: {self.dd_namespace}/{dd_name}")
                    return False
                    
            except Exception as e:
                logger.error(f"Error loading global codebase index: {e}")
                return False
    
    def _log_codebase_index_loaded(self, records: List[Dict], dd_name: str) -> None:
        """
        打印 codebase index 加载完成的详细信息
        
        Args:
            records: 加载的记录列表
            dd_name: 数据描述符名称
        """
        logger.info("=" * 80)
        logger.info("[CODEBASE INDEX] Global codebase index loaded successfully!")
        logger.info("=" * 80)
        logger.info(f"    Namespace: {self.dd_namespace}")
        logger.info(f"    Descriptor: {dd_name}")
        logger.info(f"    Total Files: {len(records)}")
        logger.info("-" * 80)
        logger.info("    Indexed Files:")
        
        # 按目录分组显示文件
        files_by_dir = {}
        for record in records:
            filepath = record.get('filepath', 'unknown')
            # 提取目录路径
            if '/' in filepath:
                dir_path = '/'.join(filepath.split('/')[:-1])
            else:
                dir_path = '.'
            
            if dir_path not in files_by_dir:
                files_by_dir[dir_path] = []
            files_by_dir[dir_path].append(filepath.split('/')[-1] if '/' in filepath else filepath)
        
        # 按目录排序并打印
        for dir_path in sorted(files_by_dir.keys()):
            files = files_by_dir[dir_path]
            logger.info(f"    [{dir_path}/] ({len(files)} files)")
            for filename in sorted(files)[:10]:  # 每个目录最多显示10个文件
                logger.info(f"        - {filename}")
            if len(files) > 10:
                logger.info(f"        ... and {len(files) - 10} more files")
        
        # 打印索引统计信息
        logger.info("-" * 80)
        logger.info("    Index Statistics:")
        logger.info(f"        - Files indexed: {len(self._codebase_index.file_index)}")
        logger.info(f"        - Functions indexed: {len(self._codebase_index.function_index)}")
        logger.info(f"        - Entities indexed: {len(self._codebase_index.entity_index)}")
        logger.info(f"        - API endpoints indexed: {len(self._codebase_index.api_index)}")
        logger.info(f"        - Dependencies tracked: {len(self._codebase_index.dependency_graph)}")
        logger.info("=" * 80)
        logger.info("[CODEBASE INDEX] Ready to serve requests!")
        logger.info("=" * 80)

    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:

        query = context.get_user_input()

        metadata = context.metadata
        logger.info(f"=====CodeAgent.execute() received metadata keys: {list(metadata.keys()) if metadata else 'None'}, answer_model={metadata.get('answer_model', '(not set)') if metadata else '(no metadata)'}")

        current_tasks_status = None
        current_tasks_status_str = metadata.get('current_tasks_status', '')
        if current_tasks_status_str:
            current_tasks_status_json = json.loads(current_tasks_status_str)
            current_tasks_status = TaskStatusList(tasks=current_tasks_status_json)
        else:
            current_tasks_status = TaskStatusList(tasks=[])
        
        current_task_id = None
        current_task_id_str = metadata.get('current_task_id')
        if current_task_id_str:
            current_task_id = int(current_task_id_str)

        # 确保全局 codebase index 已加载（懒加载，只加载一次）
        await self._ensure_codebase_index_loaded()

        agent = CodeAgent(
            provider=self.provider,
            api_key=self.api_key,
            base_url=self.base_url,
            model=self.model,
            stream=self.stream,
            temperature=self.temperature,
            data_descriptors=self.data_descriptors,
            dd_namespace=self.dd_namespace,
            descriptor_types=self.descriptor_types,
            data_services_url=self.data_services_url,
            query=query,
            metadata=metadata,
            max_steps=self.max_steps,
            current_tasks_status=current_tasks_status,
            current_task_id=current_task_id,
            code_paths=self.code_paths,
            codebase_index=self._codebase_index,  # 传入全局索引
            codebase_index_loaded=self._codebase_index_loaded  # 传入加载状态
        )

        task = context.current_task
        if not task:
            task = new_task(context.message)
            await event_queue.enqueue_event(task)

        updater = TaskUpdater(event_queue, task.id, task.context_id)

        if self.stream_enabled:
                async for chunk in agent.run():
                    if chunk:
                        part = TextPart(text=chunk)
                        await updater.add_artifact(
                            [part],
                            name=f'{agent.agent_name}-result',
                        )
                            
                await updater.complete(
                    message=new_agent_text_message(
                        "", context_id=task.context_id
                    )
                )

    async def cancel(
        self, context: RequestContext, event_queue: EventQueue
    ) -> None:
        raise Exception('cancel not supported')