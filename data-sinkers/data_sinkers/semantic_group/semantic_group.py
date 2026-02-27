import os
from pathlib import Path
from typing import List, Dict, Optional, Any, Tuple
from model_sdk import ModelManager
from langchain_core.messages import SystemMessage, HumanMessage
from datetime import datetime
import json
import re
import time
import concurrent.futures
from concurrent.futures import ThreadPoolExecutor, as_completed
import ast
import logging
import uuid
from a2a.types import AgentCard, AgentSkill
from ..client.vector_client import VectorClient, Document as VectorDocument
from ..client.semantic_group_client import SemanticGroupClient, SemanticGroupData, DDGroupRelationData
from ..client.semantic_domain_client import SemanticDomainClient
from ..api.base import DocumentModel

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("semantic_group")

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
        self.llm = llm
        self.vector_client = vector_client
        self.semantic_group_client = semantic_group_client
        self.semantic_domain_client = semantic_domain_client
        self.collection_name = collection_name
        self.max_workers = max_workers
        self.batch_size = batch_size


    def format_llm_output(self, answer) -> dict:
        """
        格式化 LLM 输出，将 LLM 返回的文本解析为字典
        
        LLM 可能返回多种格式：
        1. 纯 JSON 字符串
        2. 包含 Markdown 代码块的 JSON（如 ```json {...} ```）
        3. Python 字典格式的字符串（使用单引号）
        
        本方法采用多层容错策略，逐步尝试不同的解析方式。
        
        Args:
            answer: LLM 返回的响应对象，包含 content 属性
            
        Returns:
            解析后的字典，如果解析失败则返回 None
        """
        data_dict = None
        
        logger.info(f"code -> format_llm_output, answer: {answer}")
        
        try:
            # 策略1：直接尝试 JSON 解析（最常见的情况）
            data_dict = json.loads(answer.content)
        except json.JSONDecodeError as e:
            # 策略2：清理 Markdown 代码块标记后重试
            cleaned_content = answer.content.strip()

            # 移除开头的代码块标记
            if cleaned_content.startswith('```json'):
                cleaned_content = cleaned_content[7:]  # 移除 '```json'
            elif cleaned_content.startswith('```'):
                cleaned_content = cleaned_content[3:]  # 移除 '```'
            
            # 移除结尾的代码块标记
            if cleaned_content.endswith('```'):
                cleaned_content = cleaned_content[:-3]  # 移除 '```'
            
            cleaned_content = cleaned_content.strip()

            # Normalize Unicode smart quotes to ASCII quotes (LLM may produce these)
            cleaned_content = cleaned_content.replace('\u201c', '"').replace('\u201d', '"')
            cleaned_content = cleaned_content.replace('\u2018', "'").replace('\u2019', "'")
            
            try:
                # 策略3：清理后再次尝试 JSON 解析
                data_dict = json.loads(cleaned_content)
            except json.JSONDecodeError as e2:
                logger.error(f" === format_llm_output, Parsing failed after cleanup.: {e2}")
                try:
                    # 策略4：尝试使用 ast.literal_eval 解析 Python 字典格式（单引号）
                    import ast
                    data_dict = ast.literal_eval(cleaned_content)
                except (ValueError, SyntaxError) as e3:
                    logger.error(f" === format_llm_output, ast parsing fail: {e3}")
                    try:
                        # 策略5：将单引号替换为双引号后重试 JSON 解析
                        cleaned_content = cleaned_content.replace("'", '"')
                        data_dict = json.loads(cleaned_content)
                    except json.JSONDecodeError as e4:
                        logger.error(f" === format_llm_output, secondary parsing failed: {e4}, using default value")
                except Exception as e5:
                    logger.error(f" === format_llm_output, exception occurred during parsing: {e5}, using default value")

        return data_dict

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
                    
                    candidate_groups.append({
                        'group_id': group_id,  # 优先使用 UUID，最可靠的标识符
                        'group_name': group_data.get('group_name', ''),
                        'reason': group_data.get('description', ''),
                        'member_dd_ids': member_dd_ids,
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


        ### 输出格式：
        请严格按以下 JSON 格式返回，**禁止包含任何 Markdown 代码块标签（如 ```json）、注释或解释性文字**：
        {{
            "action": "JOIN" | "CREATE",
            "target_group_index": 0,  // JOIN 时指定要加入的组索引（从0开始），CREATE 时设为 -1
            "new_group_name": "新组名",  // CREATE 时的新组名，其他情况为空字符串
            "reason": "决策理由：说明为什么做出这个决策",
            "confidence": 0.95  // 置信度 0-1
        }}
        """
        
        system_message = SystemMessage(content=prompt)
        human_message = HumanMessage(content="请做出决策")
        
        # 重试逻辑
        last_exception = None
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

    def incremental_semantic_group_analyse(
        self,
        new_domain: Dict[str, Any],
        max_retries: int = 3,
        retry_delay: float = 1.0
    ) -> Dict[str, Any]:
        """
        增量式语义域分组分析（处理单个语义域）
        
        核心策略：增量式归纳 (Incremental Induction)
        - 向量初筛：检索与新 DD 最相似的 Top-3 现有 SemanticGroup
        - LLM 判定：决定 JOIN 或 CREATE
        
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
            decision = self._incremental_decision(new_domain, candidate_groups, max_retries, retry_delay)
            action = decision.get('action', '').upper()
            
            if action == 'JOIN':
                # 加入现有组
                candidate_index = decision.get('target_group_index', -1)
                if 0 <= candidate_index < len(candidate_groups):
                    candidate_group = candidate_groups[candidate_index]
                    target_group_id = candidate_group.get('group_id')
                    
                    if target_group_id:
                        # 检查是否已存在（避免重复添加）
                        if new_domain_id not in candidate_group.get('member_dd_ids', []):
                            # 先获取当前组的完整信息（用于语义合并）
                            group_response_before = self.semantic_group_client.get_semantic_group_by_id(
                                target_group_id
                            )
                            group_data_before = group_response_before.get('data', {})
                            
                            # 同步添加到 MySQL
                            success = self._add_member_to_group(
                                group_id=target_group_id,
                                new_domain=new_domain,
                                association_reason=decision.get('reason', '通过语义相似性分析加入组')
                            )
                            
                            if success:
                                # 使用 consolidate_semantic_domain_into_semantic_group 合并语义
                                try:
                                    # 确保 group_data_before 包含必要的字段
                                    if 'description' not in group_data_before:
                                        logger.warning(f"组 {target_group_id} 缺少 description 字段，使用默认值")
                                        group_data_before['description'] = group_data_before.get('group_name', '') or ''
                                    
                                    logger.info(f"开始合并语义域 {new_domain_id} 到组 {target_group_id} 的语义")
                                    consolidated_result = self.consolidate_semantic_domain_into_semantic_group(
                                        semantic_domain=new_domain,
                                        semantic_group=group_data_before,
                                        max_retries=3,
                                        retry_delay=1.0
                                    )
                                    
                                    # consolidate_semantic_domain_into_semantic_group 返回的是完整的 agent_card
                                    if consolidated_result:
                                        # JOIN 操作：直接使用返回的 agent_card，不需要再生成
                                        try:
                                            logger.info(f"使用合并后的 agent_card 更新组 {target_group_id}")
                                            # consolidated_result 就是 agent_card（字典格式）
                                            new_agent_card_result = consolidated_result
                                            # agent_card 转换为 JSON 字符串
                                            new_agent_card = json.dumps(new_agent_card_result, ensure_ascii=False) if isinstance(new_agent_card_result, dict) else str(new_agent_card_result)
                                            
                                            # 从 agent_card 中提取 name 作为新的 group_name
                                            if isinstance(new_agent_card_result, dict):
                                                new_group_name = new_agent_card_result.get('name', group_data_before.get('group_name', ''))
                                            else:
                                                # 如果 agent_card_result 不是字典，尝试解析 JSON
                                                try:
                                                    agent_card_dict = json.loads(new_agent_card) if isinstance(new_agent_card, str) else {}
                                                    new_group_name = agent_card_dict.get('name', group_data_before.get('group_name', ''))
                                                except:
                                                    new_group_name = group_data_before.get('group_name', '')
                                            
                                            logger.info(f"使用合并后的 agent_card，group_name 更新为 agent_card.name: {new_group_name}")
                                            # 从 agent_card 中提取 description
                                            new_description = self._extract_description_from_agent_card(new_agent_card_result)
                                        except Exception as e:
                                            logger.warning(f"处理合并后的 agent_card 失败: {str(e)}，使用原组的 agent_card 和 group_name", exc_info=True)
                                            # 如果处理失败，使用原组的 agent_card 和 group_name
                                            new_agent_card = group_data_before.get('agent_card', '')
                                            new_group_name = group_data_before.get('group_name', '')
                                            # 从原组的 agent_card 中提取 description
                                            new_description = self._extract_description_from_agent_card(new_agent_card)
                                        
                                        # 更新组的描述、group_name 和 agent_card
                                        updated_group_data = SemanticGroupData(
                                            id=target_group_id,
                                            group_name=new_group_name,
                                            description=new_description,
                                            agent_card=new_agent_card,
                                            version=group_data_before.get('version')
                                        )
                                        self.semantic_group_client.update_semantic_group(
                                            group_id=target_group_id,
                                            semantic_group=updated_group_data
                                        )
                                        logger.info(f"已更新组 {target_group_id} 的 group_name、描述和 agent_card（合并后的语义）")
                                        
                                        # 更新 pgvector 中的向量数据（因为描述改变了）
                                        if self.vector_client:
                                            # 构建成员域列表（使用新成员，description 已包含合并后的完整语义）
                                            member_domains = [new_domain]
                                            
                                            # 构建新的组文本（使用更新后的 group_name）
                                            group_text = self._build_semantic_group_text(
                                                group_name=new_group_name,
                                                description=new_description,
                                                member_domains=member_domains
                                            )
                                            
                                            # 删除旧的向量数据
                                            self._delete_group_from_pgvector(target_group_id)
                                            
                                            # 添加新的向量数据（使用更新后的 group_name）
                                            metadata = {
                                                "group_id": target_group_id,
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
                                            logger.info(f"已更新组 {target_group_id} 在 pgvector 中的向量数据")
                                    else:
                                        logger.warning(f"consolidate_semantic_domain_into_semantic_group 返回的 summary 为空，跳过更新描述")
                                        
                                except Exception as e:
                                    logger.warning(f"合并语义域到组时出错: {str(e)}，继续使用原有描述", exc_info=True)
                                
                                # 重新获取组信息（包含新成员和可能的更新后的描述）
                                group_response = self.semantic_group_client.get_semantic_group_by_id(
                                    target_group_id
                                )
                                group_data = group_response.get('data', {})
                                
                                relations_response = self.semantic_group_client.get_relations_by_group_id(
                                    target_group_id
                                )
                                relations_data = relations_response.get('data', [])
                                if not isinstance(relations_data, list):
                                    relations_data = []
                                
                                member_dd_ids = [rel.get('sd_id') for rel in relations_data if rel.get('sd_id')]
                                
                                logger.info(f"语义域 {new_domain_id} 加入组: {group_data.get('group_name')} (group_id: {target_group_id})")
                                
                                return {
                                    "status": "success",
                                    "action": "JOIN",
                                    "group_id": target_group_id,
                                    "group_name": group_data.get('group_name', ''),
                                    "reason": decision.get('reason', '通过语义相似性分析加入组'),
                                    "member_dd_ids": member_dd_ids,
                                    "confidence": decision.get('confidence', 0.9),
                                    "message": f"成功将语义域加入组: {group_data.get('group_name', '')}"
                                }
                            else:
                                logger.error(f"添加语义域 {new_domain_id} 到组 {target_group_id} 失败")
                                action = 'CREATE'
                        else:
                            logger.warning(f"语义域 {new_domain_id} 已存在于组中")
                            # 返回现有组信息
                            group_response = self.semantic_group_client.get_semantic_group_by_id(
                                target_group_id
                            )
                            group_data = group_response.get('data', {})
                            
                            relations_response = self.semantic_group_client.get_relations_by_group_id(
                                target_group_id
                            )
                            relations_data = relations_response.get('data', [])
                            if not isinstance(relations_data, list):
                                relations_data = []
                            
                            member_dd_ids = [rel.get('sd_id') for rel in relations_data if rel.get('sd_id')]
                            
                            return {
                                "status": "success",
                                "action": "JOIN",
                                "group_id": target_group_id,
                                "group_name": group_data.get('group_name', ''),
                                "reason": "语义域已存在于语义组中",
                                "member_dd_ids": member_dd_ids,
                                "confidence": 1.0,
                                "message": f"语义域已存在于语义组中: {group_data.get('group_name', '')}"
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
            member_domains: 组成员语义域列表（此参数保留用于未来扩展，当前不使用）
            
        Returns:
            构建的文本内容
        """
        text_parts = [f"语义组名称: {group_name}"]
        
        if description:
            text_parts.append(f"描述: {description}")
        
        # 不再列出成员域的描述，因为组的 description 已经包含了所有成员域的信息
        # 这样可以避免重复，并缩短向量数据库中的内容长度
        
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
            # 1. 创建到 MySQL
            if self.semantic_group_client:
                semantic_group_data = SemanticGroupData(
                    id=group_id,
                    group_name=group_name,
                    description=description,
                    agent_card=agent_card
                )
                self.semantic_group_client.create_semantic_group(
                    semantic_group_data
                )
                logger.info(f"已创建语义组到 MySQL: {group_name} (group_id: {group_id})")
                
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
                group_text = self._build_semantic_group_text(group_name, description, member_domains)
                
                # 构建 metadata（包含 group_id，用于后续搜索时识别）
                metadata = {
                    "group_id": group_id,
                    "group_name": group_name
                }
                
                document = VectorDocument(
                    page_content=group_text,
                    metadata=metadata
                )
                
                self.vector_client.add_documents(
                    collection_name=self.collection_name,
                    documents=[document]
                )
                logger.info(f"已创建语义组到 pgvector: {group_name} (group_id: {group_id})")
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

        一定不能替换的字段包括**: url, provider, version, documentationUrl, capabilities部分, authentication部分, defaultInputModes部分, defaultOutputModes部分, skill的inputModes, skill的outputModes。

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

        content = f"将semantic domain和semantic group 进行合并。 semantic domain is: {semantic_domain.get('semantic_domain', '')} \n\n semantic group is: {semantic_group.get('description', '')}"

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
                        
                        # 确保 agent_card 是字符串格式
                        if isinstance(new_agent_card, dict):
                            new_agent_card = json.dumps(new_agent_card, ensure_ascii=False)
                        elif not isinstance(new_agent_card, str):
                            new_agent_card = str(new_agent_card) if new_agent_card else ''
                        
                        # 更新组数据
                        updated_group_data = SemanticGroupData(
                            id=group_id,
                            group_name=new_group_name,
                            description=new_description,
                            agent_card=new_agent_card,
                            version=group_data.get('version')
                        )
                        self.semantic_group_client.update_semantic_group(
                            group_id=group_id,
                            semantic_group=updated_group_data
                        )
                        logger.info(f"已使用剩余成员的语义更新组 {group_id}，group_name: {new_group_name}")
                        
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
                                updated_group_data = SemanticGroupData(
                                    id=group_id,
                                    group_name=new_group_name,
                                    description=new_description,
                                    agent_card=new_agent_card,
                                    version=group_data.get('version')
                                )
                                self.semantic_group_client.update_semantic_group(
                                    group_id=group_id,
                                    semantic_group=updated_group_data
                                )
                                logger.info(f"已更新组 {group_id} 的描述、group_name 和 agent_card（重新聚合后的语义）")
                                
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



