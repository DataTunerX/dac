from neo4j import GraphDatabase
import json
import re
import heapq
from typing import Dict, List, Any, Optional
import logging
import os
import numpy as np
from model_sdk import ModelManager

class KnowledgeGraphVectorService:
    """
    基于向量的知识图谱服务，支持使用 cosine 相似度进行向量搜索
    """
    
    def __init__(self, uri: str, user: str, password: str, 
                 embedding_model=None,
                 embedding_dims: int = 1024,
                 vector_index_name: str = "node_embeddings",
                 batch_size: int = 50,
                 use_apoc: bool = True):
        """
        初始化向量服务
        
        Args:
            uri: Neo4j连接URI
            user: 用户名
            password: 密码
            embedding_model: Embedding模型实例（可选，如果不提供则从环境变量初始化）
            embedding_dims: 向量维度
            vector_index_name: 向量索引名称
            batch_size: 批量处理大小（用于批量添加节点时的embedding计算）
            use_apoc: 是否使用APOC扩展（如果可用）
        """
        # 配置连接池（提高性能和稳定性）
        self.driver = GraphDatabase.driver(
            uri, 
            auth=(user, password),
            max_connection_pool_size=50,  # 最大连接池大小
            connection_timeout=30,  # 连接超时（秒）
            encrypted=False  # 根据实际情况调整
        )
        self.embedding_dims = embedding_dims
        self.vector_index_name = vector_index_name
        self.batch_size = batch_size
        self.use_apoc = use_apoc
        self.logger = logging.getLogger(__name__)
        
        # 初始化 embedding 模型
        if embedding_model is None:
            self.embedding_model = self._init_embedding_model()
        else:
            self.embedding_model = embedding_model
        
        # 创建向量索引
        self._create_vector_index()
    
    def _init_embedding_model(self):
        """从环境变量初始化 embedding 模型"""
        provider = os.getenv('EMBEDDING_PROVIDER', 'openai')
        model = os.getenv('EMBEDDING_MODEL', 'text-embedding-ada-002')
        api_key = os.getenv('EMBEDDING_API_KEY', '')
        
        model_manager = ModelManager()
        
        if provider == 'azure':
            return model_manager.get_embedding(
                provider=provider,
                model=model,
                azure_endpoint=os.getenv('AZURE_ENDPOINT'),
                api_key=api_key,
                deployment=os.getenv('EMBEDDING_DEPLOYMENT'),
                api_version=os.getenv('API_VERSION', '2023-05-15')
            )
        elif provider == 'dashscope':
            return model_manager.get_embedding(
                provider=provider,
                model=model,
                dashscope_api_key=api_key
            )
        else:
            return model_manager.get_embedding(
                provider=provider,
                model=model,
                base_url=os.getenv('EMBEDDING_BASE_URL'),
                api_key=api_key
            )
    
    def _wait_for_index_ready(self, session, max_wait_seconds: int = 30):
        """
        等待向量索引就绪（Neo4j 向量索引是异步创建的）
        
        Args:
            session: Neo4j会话
            max_wait_seconds: 最大等待时间（秒）
        """
        import time
        start_time = time.time()
        check_interval = 1  # 每秒检查一次
        
        while time.time() - start_time < max_wait_seconds:
            try:
                check_query = """
                CALL db.indexes()
                YIELD name, type, state, populationPercent
                WHERE name = $index_name AND type = 'VECTOR'
                RETURN name, state, populationPercent
                """
                result = session.run(check_query, index_name=self.vector_index_name)
                record = result.single()
                
                if record:
                    state = record.get('state', '').upper()
                    population_percent = record.get('populationPercent', 100)
                    
                    # 索引状态：ONLINE 表示就绪，POPULATING 表示正在构建
                    if state == 'ONLINE':
                        self.logger.info(
                            f"Vector index '{self.vector_index_name}' is ready "
                            f"(state: {state}, population: {population_percent}%)"
                        )
                        return True
                    elif state == 'POPULATING':
                        self.logger.debug(
                            f"Vector index '{self.vector_index_name}' is populating "
                            f"({population_percent}%), waiting..."
                        )
                    else:
                        self.logger.debug(
                            f"Vector index '{self.vector_index_name}' state: {state}, waiting..."
                        )
                else:
                    # 索引不存在，可能还在创建中
                    self.logger.debug(
                        f"Vector index '{self.vector_index_name}' not found in indexes, waiting..."
                    )
                
                time.sleep(check_interval)
            except Exception as e:
                self.logger.debug(f"Error checking index status: {e}, waiting...")
                time.sleep(check_interval)
        
        self.logger.warning(
            f"Vector index '{self.vector_index_name}' did not become ready within {max_wait_seconds} seconds"
        )
        return False
    
    def _list_all_vector_indexes(self, session):
        """
        列出所有向量索引（用于调试）
        
        Args:
            session: Neo4j会话
            
        Returns:
            向量索引列表
        """
        try:
            list_query = """
            CALL db.indexes()
            YIELD name, type, state, entityType, labelsOrTypes, properties, indexProvider
            WHERE type = 'VECTOR'
            RETURN name, state, labelsOrTypes, properties
            ORDER BY name
            """
            result = session.run(list_query)
            indexes = []
            for record in result:
                indexes.append({
                    'name': record.get('name'),
                    'state': record.get('state'),
                    'labels': record.get('labelsOrTypes'),
                    'properties': record.get('properties')
                })
            return indexes
        except Exception as e:
            self.logger.debug(f"Failed to list vector indexes: {e}")
            return []
    
    def _create_vector_index(self):
        """创建向量索引以支持高效的向量搜索（仅支持 Neo4j 5.x）"""
        try:
            with self.driver.session() as session:
                # 列出所有向量索引（用于调试）
                all_indexes = self._list_all_vector_indexes(session)
                if all_indexes:
                    self.logger.info(
                        f"Existing vector indexes in database: {[idx['name'] for idx in all_indexes]}"
                    )
                    # 检查是否有名称不同但配置相同的索引（这会导致创建失败）
                    conflicting_indexes = [idx for idx in all_indexes if idx['name'] != self.vector_index_name]
                    if conflicting_indexes:
                        self.logger.warning(
                            f"Found {len(conflicting_indexes)} vector index(es) with different names: "
                            f"{[idx['name'] for idx in conflicting_indexes]}. "
                            f"Target index name is '{self.vector_index_name}'. "
                            "Neo4j does not allow multiple vector indexes on the same label/property. "
                            "If you want to use the target index name, please drop the conflicting index(es) first: "
                            f"DROP INDEX {' '.join([idx['name'] for idx in conflicting_indexes])} IF EXISTS;"
                        )
                
                # 检查索引是否已存在且就绪（Neo4j 5.x 使用 db.indexes()）
                existing_index = None
                index_ready = False
                try:
                    check_query = """
                    CALL db.indexes()
                    YIELD name, type, state, entityType, labelsOrTypes, properties, indexProvider
                    WHERE name = $index_name AND type = 'VECTOR'
                    RETURN name, state, properties
                    """
                    result = session.run(check_query, index_name=self.vector_index_name)
                    existing_index = result.single()
                    
                    if existing_index:
                        state = existing_index.get('state', '').upper()
                        if state == 'ONLINE':
                            index_ready = True
                            self.logger.info(
                                f"Vector index '{self.vector_index_name}' already exists and is ready"
                            )
                        else:
                            self.logger.info(
                                f"Vector index '{self.vector_index_name}' exists but state is '{state}', "
                                "waiting for it to become ready..."
                            )
                            index_ready = self._wait_for_index_ready(session)
                except Exception as e:
                    self.logger.debug(f"db.indexes() check failed: {e}, will try to create index directly")
                
                if existing_index is None or not index_ready:
                    # Neo4j 5.11+ 向量索引需指定标签；使用 Node，add() 中所有节点带 Node（5.18）
                    create_query = f"""
                    CREATE VECTOR INDEX {self.vector_index_name} IF NOT EXISTS
                    FOR (n:Node)
                    ON n.embedding
                    OPTIONS {{
                        indexConfig: {{
                            `vector.dimensions`: {self.embedding_dims},
                            `vector.similarity_function`: 'cosine'
                        }}
                    }}
                    """
                    try:
                        # 执行创建命令并检查结果
                        result = session.run(create_query)
                        # 消费结果以确保命令执行完成
                        result.consume()
                        
                        # 立即验证索引是否真的被创建（Neo4j 可能因为冲突而不创建，但不会抛出异常）
                        verify_query = """
                        CALL db.indexes()
                        YIELD name, type, state
                        WHERE name = $index_name AND type = 'VECTOR'
                        RETURN name, state
                        """
                        verify_result = session.run(verify_query, index_name=self.vector_index_name)
                        verified_index = verify_result.single()
                        
                        if not verified_index:
                            # 索引没有被创建，可能是因为已存在相同配置的索引
                            self.logger.error(
                                f"Vector index '{self.vector_index_name}' creation command executed, "
                                "but the index does not exist in the database. "
                                "This usually means Neo4j rejected the creation because a different index "
                                "with the same configuration already exists. "
                                f"Please check existing indexes and drop the conflicting one if needed."
                            )
                            # 列出所有向量索引以便用户查看
                            conflicting_indexes = self._list_all_vector_indexes(session)
                            if conflicting_indexes:
                                self.logger.error(
                                    f"Existing vector indexes that may conflict: "
                                    f"{[idx['name'] for idx in conflicting_indexes]}"
                                )
                            index_ready = False
                        else:
                            self.logger.info(
                                f"Vector index '{self.vector_index_name}' creation command executed, "
                                f"index exists with state: {verified_index.get('state', 'unknown')}, "
                                "waiting for index to become ready..."
                            )
                            # 等待索引就绪
                            index_ready = self._wait_for_index_ready(session, max_wait_seconds=60)
                            if index_ready:
                                self.logger.info(
                                    f"Vector index '{self.vector_index_name}' is ready and can be used"
                                )
                            else:
                                self.logger.error(
                                    f"Vector index '{self.vector_index_name}' did not become ready after creation. "
                                    "This may indicate a problem with Neo4j configuration or version. "
                                    "Vector search will fall back to cosine similarity calculation."
                                )
                    except Exception as e:
                        error_msg = str(e)
                        self.logger.error(
                            f"Failed to create vector index '{self.vector_index_name}': {error_msg}. "
                            "Ensure Neo4j 5.11+ and nodes have :Node label. "
                            "Vector search will fall back to cosine similarity calculation."
                        )
                        # 检查是否是索引已存在的通知（Neo4j 可能返回通知而不是异常）
                        if 'already exists' in error_msg.lower() or 'no effect' in error_msg.lower():
                            self.logger.warning(
                                f"Index creation returned 'already exists' or 'no effect'. "
                                f"This may mean a different index with the same configuration exists. "
                                f"Please check existing indexes and consider dropping conflicting ones."
                            )
                            # 再次检查索引是否存在
                            try:
                                check_result = session.run(
                                    "CALL db.indexes() YIELD name, type WHERE name = $index_name AND type = 'VECTOR' RETURN name",
                                    index_name=self.vector_index_name
                                )
                                if check_result.single():
                                    self.logger.info(
                                        f"Index '{self.vector_index_name}' exists, waiting for it to be ready..."
                                    )
                                    self._wait_for_index_ready(session, max_wait_seconds=30)
                            except Exception as check_e:
                                self.logger.debug(f"Error checking index after creation failure: {check_e}")
                    
        except Exception as e:
            self.logger.error(
                f"Could not check/create vector index '{self.vector_index_name}': {e}. "
                "Index may need to be created manually. "
                "Vector search will fall back to cosine similarity calculation.",
                exc_info=True
            )
    
    def create_vector_index(self) -> Dict[str, Any]:
        """
        主动创建向量索引（供 API 或运维调用）。
        若索引已存在则跳过；否则尝试创建。
        
        Returns:
            {status, message, index_name}
        """
        self._create_vector_index()
        return {
            'status': 'success',
            'message': (
                f"Vector index creation attempted for '{self.vector_index_name}'. "
                "Check service logs for details; search will retry index creation on failure."
            ),
            'index_name': self.vector_index_name,
        }
    
    def close(self):
        """关闭连接"""
        if self.driver:
            self.driver.close()
    
    def _remove_embedding_from_node(self, node: Dict[str, Any]) -> Dict[str, Any]:
        """
        从节点数据中移除embedding字段（用于返回给前端时隐藏）
        
        Args:
            node: 节点数据字典
            
        Returns:
            移除embedding后的节点数据
        """
        if not isinstance(node, dict):
            return node
        
        # 创建副本以避免修改原始数据
        cleaned_node = node.copy()
        
        # 如果节点有properties字段，从properties中移除embedding
        if 'properties' in cleaned_node and isinstance(cleaned_node['properties'], dict):
            cleaned_node['properties'] = {k: v for k, v in cleaned_node['properties'].items() if k != 'embedding'}
        
        # 如果节点本身包含embedding字段，也移除
        if 'embedding' in cleaned_node:
            del cleaned_node['embedding']
        
        return cleaned_node
    
    def _remove_embedding_from_nodes(self, nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        从节点列表中移除所有节点的embedding字段
        
        Args:
            nodes: 节点列表
            
        Returns:
            移除embedding后的节点列表
        """
        return [self._remove_embedding_from_node(node) for node in nodes]
    
    def _compute_embedding(self, text: str) -> List[float]:
        """
        计算文本的 embedding
        
        Args:
            text: 输入文本
            
        Returns:
            embedding 向量
            
        Raises:
            ValueError: 如果文本为空或embedding计算失败
        """
        if not text or not text.strip():
            self.logger.warning("Empty text provided for embedding computation, using zero vector")
            # 返回零向量
            return [0.0] * self.embedding_dims
        
        try:
            # 截断过长的文本（避免超出模型限制）
            max_length = 8192  # 根据模型调整，大多数模型支持8K tokens
            original_length = len(text)
            if original_length > max_length:
                text = text[:max_length]
                self.logger.debug(f"Text truncated from {original_length} to {max_length} characters")
            
            # 计算embedding
            if hasattr(self.embedding_model, 'embed_query'):
                embedding = self.embedding_model.embed_query(text)
            elif hasattr(self.embedding_model, 'embed_documents'):
                embedding = self.embedding_model.embed_documents([text])[0]
            elif callable(self.embedding_model):
                embedding = self.embedding_model(text)
                if isinstance(embedding, list) and len(embedding) > 0:
                    if isinstance(embedding[0], list):
                        embedding = embedding[0]
            else:
                raise ValueError("Embedding model is not callable or does not have expected methods")
            
            # 验证embedding维度
            if len(embedding) != self.embedding_dims:
                self.logger.warning(
                    f"Embedding dimension mismatch: expected {self.embedding_dims}, "
                    f"got {len(embedding)}. Adjusting dimension."
                )
                if len(embedding) > self.embedding_dims:
                    # 截断
                    embedding = embedding[:self.embedding_dims]
                else:
                    # 填充零
                    embedding = list(embedding) + [0.0] * (self.embedding_dims - len(embedding))
            
            # 确保返回的是列表格式
            if isinstance(embedding, np.ndarray):
                embedding = embedding.tolist()
            
            return embedding
            
        except Exception as e:
            self.logger.error(f"Error computing embedding for text '{text[:50]}...': {e}", exc_info=True)
            # 返回零向量而不是抛出异常，避免影响整个流程
            self.logger.warning("Returning zero vector due to embedding computation error")
            return [0.0] * self.embedding_dims
    
    def add(self, nodes: List[Dict[str, Any]], relationships: List[Dict[str, Any]] = None,
            source: str = "default", text_fields: List[str] = None,
            deduplicate_by_name: bool = True, name_field: str = 'name') -> Dict[str, Any]:
        """
        添加知识图谱数据，并计算和存储 embedding
        
        Args:
            nodes: 节点列表，每个节点包含 id, labels, properties
            relationships: 关系列表，每个关系包含 start, end, type, properties
            source: 数据源标签
            text_fields: 用于生成 embedding 的文本字段列表，如果为 None 则使用所有字符串字段
            deduplicate_by_name: 是否基于name字段进行去重（如果id不同但name相同，则合并节点）
            name_field: 用于去重的字段名，默认为'name'
            
        Returns:
            添加结果统计，包含节点id映射信息（如果启用了去重）
            
        Note:
            - 去重逻辑基于数据库查询，不依赖内存状态，服务重启不影响去重功能
            - node_id_mapping 仅在返回结果中提供信息，用于告知调用者哪些节点被合并
            - 合并后的节点使用实际ID（已存在的节点ID）存储在数据库中
            - 后续查询和操作应使用实际ID，而不是原始ID
        """
        if not nodes:
            raise ValueError("nodes 不能为空")
        
        if text_fields is None:
            text_fields = ['name', 'title', 'content', 'description', 'text']
        
        try:
            with self.driver.session() as session:
                added_nodes = 0
                updated_nodes = 0
                added_relationships = 0
                node_id_mapping = {}  # 用于记录原始id到实际id的映射（去重时使用）
                
                # 处理节点
                for node in nodes:
                    node_id = node.get('id')
                    if not node_id:
                        self.logger.warning(f"Skipping node without id: {node}")
                        continue
                    
                    labels = node.get('labels', []) or []
                    if 'Node' not in labels:
                        labels = ['Node'] + list(labels)
                    properties = node.get('properties', {})
                    
                    # 如果启用了基于name的去重，先检查是否存在相同name的节点
                    # 支持节点本身的name字段和properties中的name字段
                    actual_node_id = node_id
                    if deduplicate_by_name:
                        # 使用白名单验证name_field（更安全）
                        allowed_dedup_fields = {'name', 'title', 'id', 'key', 'identifier', 'code'}
                        if name_field not in allowed_dedup_fields:
                            self.logger.warning(
                                f"name_field '{name_field}' is not in allowed list {allowed_dedup_fields}, "
                                f"skipping deduplication"
                            )
                        else:
                            # 优先从节点本身获取name，如果没有则从properties中获取
                            name_value = node.get(name_field) or properties.get(name_field)
                            
                            if isinstance(name_value, str) and name_value.strip():
                                # 查询是否存在相同name的节点（同一source下）
                                # 支持查询节点本身的字段（作为节点属性存储）
                                # 使用参数化查询，name_field作为参数传递
                                check_query = """
                                MATCH (n {data_source: $source})
                                WHERE n[$name_field] = $name_value
                                RETURN n.id as existing_id, labels(n) as labels
                                LIMIT 1
                                """
                                existing_result = session.run(
                                    check_query,
                                    source=source,
                                    name_field=name_field,  # 作为参数传递，更安全
                                    name_value=name_value
                                )
                                existing_record = existing_result.single()
                                
                                if existing_record:
                                    # 找到已存在的节点，使用其id
                                    actual_node_id = existing_record['existing_id']
                                    existing_labels = existing_record['labels']
                                    
                                    self.logger.info(
                                        f"Found existing node with {name_field}='{name_value}': "
                                        f"id={actual_node_id}, merging with new node id={node_id}"
                                    )
                                    
                                    # 记录id映射
                                    if actual_node_id != node_id:
                                        node_id_mapping[node_id] = actual_node_id
                                        updated_nodes += 1
                                        
                                        # 合并labels（去重并保留原有labels）
                                        if labels:
                                            combined_labels = list(set(existing_labels + labels))
                                            labels = combined_labels
                    
                    # 构建用于 embedding 的文本
                    # 支持从节点本身和properties中获取文本字段
                    text_parts = []
                    for field in text_fields:
                        # 优先从节点本身获取，如果没有则从properties中获取
                        field_value = node.get(field) or properties.get(field)
                        if isinstance(field_value, str) and field_value.strip():
                            text_parts.append(field_value)
                    
                    # 如果没有找到指定字段，使用所有字符串属性（包括节点本身和properties）
                    if not text_parts:
                        # 先从节点本身获取字符串字段
                        for key, value in node.items():
                            if key not in ['id', 'labels', 'properties'] and isinstance(value, str) and value.strip():
                                text_parts.append(value)
                        # 再从properties中获取
                        for key, value in properties.items():
                            if isinstance(value, str) and value.strip():
                                text_parts.append(value)
                    
                    # 计算 embedding
                    text_for_embedding = ' '.join(text_parts) if text_parts else actual_node_id
                    embedding = self._compute_embedding(text_for_embedding)
                    
                    # 准备节点属性
                    # 首先收集所有需要存储的属性：properties中的字段 + 节点顶层的字段
                    all_properties = properties.copy()
                    # 特殊字段：id, labels, properties 这些不应该作为节点属性
                    special_fields = {'id', 'labels', 'properties'}
                    for key, value in node.items():
                        if key not in special_fields and value is not None:
                            # 如果properties中已经有这个字段，优先使用properties中的值
                            # 否则使用节点顶层的值
                            if key not in all_properties:
                                all_properties[key] = value
                    
                    # 清理所有属性（包括节点顶层的字段）
                    node_properties = self._clean_properties(all_properties)
                    node_properties['id'] = actual_node_id
                    node_properties['data_source'] = source
                    node_properties['embedding'] = embedding
                    
                    # 创建或更新节点
                    labels_str = ':'.join(labels) if labels else 'Node'
                    
                    if actual_node_id != node_id and deduplicate_by_name:
                        # 节点已存在，需要更新而不是创建（合并属性）
                        # 使用 += 操作符合并属性，保留原有属性，新属性会覆盖同名属性
                        update_properties = {k: v for k, v in node_properties.items() 
                                           if k not in ['id', 'data_source']}
                        
                        # 更新节点属性（合并模式）
                        update_query = f"""
                        MATCH (n {{id: $id, data_source: $source}})
                        SET n += $update_properties
                        SET n.embedding = $embedding
                        RETURN n.id as id
                        """
                        result = session.run(
                            update_query,
                            id=actual_node_id,
                            source=source,
                            update_properties=update_properties,
                            embedding=embedding
                        )
                        if result.single():
                            # 节点已更新，尝试添加新标签（如果APOC可用）
                            if labels:
                                try:
                                    add_labels_query = """
                                    MATCH (n {id: $id, data_source: $source})
                                    CALL apoc.create.addLabels(n, $labels) YIELD node
                                    RETURN node.id as id
                                    """
                                    session.run(
                                        add_labels_query,
                                        id=actual_node_id,
                                        source=source,
                                        labels=labels
                                    )
                                except Exception:
                                    # APOC不可用，跳过标签添加（节点已有标签）
                                    self.logger.debug("APOC not available, skipping label addition")
                    else:
                        # 新节点，正常创建
                        query = f"""
                        MERGE (n:{labels_str} {{id: $id, data_source: $source}})
                        SET n = $properties
                        RETURN n.id as id
                        """
                        result = session.run(
                            query, 
                            id=actual_node_id, 
                            source=source,
                            properties=node_properties
                        )
                        if result.single():
                            added_nodes += 1
                
                # 处理关系
                if relationships:
                    for rel in relationships:
                        start_id = rel.get('start')
                        end_id = rel.get('end')
                        rel_type = rel.get('type', 'RELATED_TO')
                        properties = rel.get('properties', {})
                        
                        if not start_id or not end_id:
                            self.logger.warning(f"Skipping relationship without start/end: {rel}")
                            continue
                        
                        # 如果启用了去重，使用映射后的id
                        actual_start_id = node_id_mapping.get(start_id, start_id)
                        actual_end_id = node_id_mapping.get(end_id, end_id)
                        
                        rel_properties = self._clean_properties(properties)
                        rel_properties['data_source'] = source
                        
                        query = f"""
                        MATCH (start {{id: $start_id, data_source: $source}})
                        MATCH (end {{id: $end_id, data_source: $source}})
                        MERGE (start)-[r:{rel_type}]->(end)
                        SET r = $properties
                        RETURN type(r) as type
                        """
                        
                        result = session.run(query, 
                                           start_id=actual_start_id,
                                           end_id=actual_end_id,
                                           source=source,
                                           properties=rel_properties)
                        if result.single():
                            added_relationships += 1
                
                self.logger.info(
                    f"Added {added_nodes} nodes, updated {updated_nodes} nodes, "
                    f"and {added_relationships} relationships"
                )
                
                result = {
                    'status': 'success',
                    'nodes_added': added_nodes,
                    'nodes_updated': updated_nodes,
                    'relationships_added': added_relationships,
                    'source': source
                }
                
                # 如果启用了去重且有id映射，返回映射信息
                if deduplicate_by_name and node_id_mapping:
                    result['node_id_mapping'] = node_id_mapping
                    self.logger.info(f"Node ID mappings due to deduplication: {node_id_mapping}")
                
                return result
                
        except ValueError as e:
            # 参数验证错误，直接抛出
            self.logger.error(f"Validation error in add method: {e}")
            raise
        except Exception as e:
            self.logger.error(f"Error adding knowledge graph data: {e}", exc_info=True)
            raise RuntimeError(f"Failed to add knowledge graph data: {str(e)}") from e
    
    def search(self, query_text: str, source: str = "default", 
               top_k: int = 10, include_relationships: bool = True,
               relationship_depth: int = 1) -> Dict[str, Any]:
        """
        基于向量搜索知识图谱
        
        Args:
            query_text: 查询文本
            source: 数据源标签
            top_k: 返回最相似的节点数量
            include_relationships: 是否包含关系信息
            relationship_depth: 关系查询深度
            
        Returns:
            搜索结果，包含匹配的节点和关系
        """
        try:
            # 计算查询文本的 embedding
            query_embedding = self._compute_embedding(query_text)
            
            with self.driver.session() as session:
                # 首先尝试使用向量索引进行相似度搜索
                # Neo4j 5.x 使用 db.index.vector.queryNodes
                nodes = []
                use_fallback = False
                index_create_attempted = False

                def _run_vector_query():
                    search_query = f"""
                    CALL db.index.vector.queryNodes(
                        '{self.vector_index_name}',
                        {top_k * 2},
                        $query_embedding
                    )
                    YIELD node, score
                    WHERE node.data_source = $source
                    WITH node, score
                    ORDER BY score DESC
                    LIMIT $top_k
                    RETURN node, score, labels(node) as labels
                    """
                    return session.run(
                        search_query,
                        query_embedding=query_embedding,
                        source=source,
                        top_k=top_k,
                    )

                while True:
                    try:
                        result = _run_vector_query()
                        vec_nodes = []
                        for record in result:
                            node_dict = dict(record['node'])
                            vec_nodes.append({
                                'id': node_dict.get('id'),
                                'labels': record['labels'],
                                'properties': node_dict,
                                'similarity_score': float(record['score']),
                            })
                        if not vec_nodes:
                            self.logger.warning("Vector index query returned no results, trying fallback method")
                            use_fallback = True
                        else:
                            self.logger.info(f"Vector index query found {len(vec_nodes)} results")
                            nodes = self._remove_embedding_from_nodes(vec_nodes)
                        break
                    except Exception as e:
                        err_msg = str(e).lower()
                        is_missing_index = (
                            not index_create_attempted
                            and ('no such' in err_msg and 'index' in err_msg)
                        )
                        if is_missing_index:
                            self.logger.info(
                                f"Vector index '{self.vector_index_name}' not found, "
                                "attempting to create it..."
                            )
                            self._create_vector_index()
                            index_create_attempted = True
                            # 创建后等待索引就绪
                            try:
                                with self.driver.session() as wait_session:
                                    if self._wait_for_index_ready(wait_session, max_wait_seconds=10):
                                        continue  # 索引已就绪，重试查询
                                    else:
                                        self.logger.warning(
                                            f"Vector index '{self.vector_index_name}' not ready after creation, "
                                            "using fallback method"
                                        )
                                        use_fallback = True
                                        break
                            except Exception as wait_e:
                                self.logger.warning(
                                    f"Error waiting for index: {wait_e}, using fallback method"
                                )
                                use_fallback = True
                                break
                        else:
                            self.logger.warning(f"Vector index query failed: {e}, using fallback method")
                            use_fallback = True
                            break

                # 如果索引查询失败或返回空结果，使用备选方案
                if use_fallback:
                    nodes = self._search_with_cosine_similarity(
                        session, query_embedding, source, top_k
                    )
                    # 注意：_search_with_cosine_similarity 已经移除了embedding字段
                
                # 获取关系信息
                relationships = []
                node_ids = [node['id'] for node in nodes]
                
                if include_relationships and node_ids:
                    relationships = self._get_node_relationships(
                        session, node_ids, source, relationship_depth
                    )
                
                return {
                    'status': 'success',
                    'query': query_text,
                    'nodes': nodes,
                    'relationships': relationships,
                    'count': len(nodes)
                }
                
        except ValueError as e:
            # 参数验证错误，直接抛出
            self.logger.error(f"Validation error in search method: {e}")
            raise
        except Exception as e:
            self.logger.error(f"Error searching knowledge graph: {e}", exc_info=True)
            raise RuntimeError(f"Failed to search knowledge graph: {str(e)}") from e
    
    def format_search_result_as_svo(self, search_result: Dict[str, Any]) -> str:
        """
        将 search 返回的数据处理成自然语言风格的主谓宾（主-谓-宾）字符串，
        每条关系对应一句，多个字符串之间用换行符分隔。
        
        Args:
            search_result: search 方法的返回值，包含 nodes 和 relationships
            
        Returns:
            主谓宾形式的自然语言字符串，每行一句；若无关系则返回空字符串
        """
        if not search_result or search_result.get('status') != 'success':
            return ''
        
        nodes = search_result.get('nodes', [])
        relationships = search_result.get('relationships', [])
        
        if not relationships:
            return ''
        
        # 构建 node_id -> 展示名 的映射（优先 name/title，否则用 id）
        id_to_name: Dict[str, str] = {}
        for n in nodes:
            nid = n.get('id')
            if nid is None:
                continue
            props = n.get('properties') or {}
            name = props.get('name') or props.get('title') or props.get('content')
            if isinstance(name, str) and name.strip():
                id_to_name[nid] = name.strip()
            else:
                id_to_name[nid] = str(nid)
        
        def _display_name(nid: Any) -> str:
            if nid is None:
                return '未知'
            return id_to_name.get(nid, str(nid))
        
        svo_lines: List[str] = []
        for r in relationships:
            start_id = r.get('start_id')
            end_id = r.get('end_id')
            rel_type = r.get('type') or 'RELATED_TO'
            subj = _display_name(start_id)
            obj = _display_name(end_id)
            svo_lines.append(f'{subj} {rel_type} {obj}')
        
        return '\n'.join(svo_lines)
    
    def _search_with_cosine_similarity(self, session, query_embedding: List[float],
                                       source: str, top_k: int, batch_size: int = 1000) -> List[Dict[str, Any]]:
        """
        使用余弦相似度进行搜索（备选方案，当向量索引不可用时）
        使用批量处理优化内存使用
        
        Args:
            session: Neo4j会话
            query_embedding: 查询向量
            source: 数据源标签
            top_k: 返回最相似的节点数量
            batch_size: 批量处理大小
            
        Returns:
            最相似的top_k个节点列表
        """
        import heapq
        
        query_vec = np.array(query_embedding)
        query_norm = np.linalg.norm(query_vec)
        
        if query_norm == 0:
            self.logger.warning("Query embedding has zero norm, cannot compute similarity")
            return []
        
        # 使用最小堆来保持top_k（堆大小为top_k，堆顶是最小值）
        top_k_heap = []
        node_count = 0
        skip = 0
        max_candidates = top_k * 10  # 最多收集10倍候选，避免处理过多数据
        
        while len(top_k_heap) < max_candidates:
            # 批量获取节点
            query = """
            MATCH (n {data_source: $source})
            WHERE n.embedding IS NOT NULL
            RETURN n, labels(n) as labels
            SKIP $skip
            LIMIT $batch_size
            """
            
            result = session.run(query, source=source, skip=skip, batch_size=batch_size)
            batch_nodes = list(result)
            
            if not batch_nodes:
                break
            
            # 处理当前批次
            for record in batch_nodes:
                node = record['n']
                node_embedding = node.get('embedding')
                if node_embedding:
                    node_count += 1
                    try:
                        node_vec = np.array(node_embedding)
                        node_norm = np.linalg.norm(node_vec)
                        
                        if node_norm > 0:
                            # 计算余弦相似度
                            similarity = float(np.dot(query_vec, node_vec) / (query_norm * node_norm))
                            
                            candidate = {
                                'id': node.get('id'),
                                'labels': record['labels'],
                                'properties': dict(node),
                                'similarity_score': similarity
                            }
                            
                            # 使用最小堆维护top_k
                            if len(top_k_heap) < top_k:
                                heapq.heappush(top_k_heap, (similarity, candidate))
                            else:
                                # 如果当前相似度大于堆顶（最小值），替换堆顶
                                if similarity > top_k_heap[0][0]:
                                    heapq.heapreplace(top_k_heap, (similarity, candidate))
                                    
                    except Exception as e:
                        self.logger.debug(f"Error computing similarity for node {node.get('id')}: {e}")
                        continue
            
            skip += batch_size
            
            # 如果已经收集了足够的候选，可以提前停止
            if len(top_k_heap) >= top_k and skip > max_candidates:
                break
        
        self.logger.info(
            f"Computed cosine similarity for {node_count} nodes, "
            f"found {len(top_k_heap)} candidates in top_k heap"
        )
        if node_count == 0:
            self.logger.warning(
                f"Cosine fallback: 0 nodes with data_source={source!r} and embedding. "
                "Ensure data has been added for this source (e.g. via add/import)."
            )

        # 从堆中提取结果，按相似度降序排序
        candidates = [item[1] for item in sorted(top_k_heap, key=lambda x: x[0], reverse=True)]

        # 移除embedding字段
        return self._remove_embedding_from_nodes(candidates)
    
    def _get_node_relationships(self, session, node_ids: List[str], 
                                source: str, depth: int) -> List[Dict[str, Any]]:
        """
        获取节点的关系信息
        """
        if not node_ids:
            return []
        
        relationships = []
        rel_set = set()
        
        # 查询指定深度的关系
        query = f"""
        MATCH path = (start {{id: $node_id, data_source: $source}})-[*1..{depth}]-(connected {{data_source: $source}})
        WHERE start.id IN $node_ids
        UNWIND relationships(path) as rel
        WITH DISTINCT rel, startNode(rel) as start, endNode(rel) as end
        WHERE rel.data_source = $source
        RETURN 
            start.id as start_id,
            labels(start) as start_labels,
            type(rel) as rel_type,
            rel as relationship,
            end.id as end_id,
            labels(end) as end_labels
        """
        
        for node_id in node_ids:
            result = session.run(query, node_id=node_id, source=source, node_ids=node_ids)
            for record in result:
                rel_key = (record['start_id'], record['rel_type'], record['end_id'])
                if rel_key not in rel_set:
                    rel_set.add(rel_key)
                    relationships.append({
                        'start_id': record['start_id'],
                        'start_labels': record['start_labels'],
                        'end_id': record['end_id'],
                        'end_labels': record['end_labels'],
                        'type': record['rel_type'],
                        'properties': dict(record['relationship'])
                    })
        
        return relationships
    
    def delete_by_source(self, source: str) -> Dict[str, int]:
        """
        删除指定数据源的所有数据（节点和关系）
        
        Args:
            source: 数据源标签（必需）
            
        Returns:
            包含删除的节点数和关系数的字典
        """
        if not source:
            raise ValueError("source参数是必需的，不能为空")
        
        try:
            with self.driver.session() as session:
                # 先统计要删除的数据量
                result = session.run(
                    "MATCH (n {data_source: $source}) RETURN count(n) as node_count",
                    source=source
                )
                node_count = result.single()['node_count']
                
                result = session.run(
                    "MATCH ()-[r {data_source: $source}]->() RETURN count(r) as rel_count",
                    source=source
                )
                rel_count = result.single()['rel_count']
                
                # 删除所有具有指定source的关系
                session.run(
                    "MATCH ()-[r {data_source: $source}]->() DELETE r",
                    source=source
                )
                
                # 删除所有具有指定source的节点（包括embedding）
                session.run(
                    "MATCH (n {data_source: $source}) DETACH DELETE n",
                    source=source
                )
                
                self.logger.info(f"Deleted source '{source}': {node_count} nodes, {rel_count} relationships")
                
                return {
                    'status': 'success',
                    'source': source,
                    'nodes_deleted': node_count,
                    'relationships_deleted': rel_count
                }
        except Exception as e:
            self.logger.error(f"Error deleting data by source: {e}", exc_info=True)
            raise
    
    def validate_data(self, json_data: Dict) -> Dict[str, List[str]]:
        """
        验证数据完整性（参考 UniversalNeo4jImporter）
        
        Args:
            json_data: 要验证的数据
            
        Returns:
            验证结果，包含错误和警告
        """
        errors = []
        warnings = []
        
        nodes = json_data.get('nodes', [])
        relationships = json_data.get('relationships', [])
        
        # 检查节点ID唯一性
        node_ids = {}
        for i, node in enumerate(nodes):
            node_id = node.get('id')
            if not node_id:
                errors.append(f"Node at index {i} has no id")
            elif node_id in node_ids:
                errors.append(f"Duplicate node id: {node_id}")
            else:
                node_ids[node_id] = i
        
        # 检查关系引用的节点是否存在
        for i, rel in enumerate(relationships):
            start_id = rel.get('start')
            end_id = rel.get('end')
            
            if not start_id:
                errors.append(f"Relationship at index {i} has no start node")
            elif start_id not in node_ids:
                errors.append(f"Relationship at index {i} references non-existent start node: {start_id}")
            
            if not end_id:
                errors.append(f"Relationship at index {i} has no end node")
            elif end_id not in node_ids:
                errors.append(f"Relationship at index {i} references non-existent end node: {end_id}")
            
            if not rel.get('type'):
                warnings.append(f"Relationship at index {i} has no type, using default 'RELATED_TO'")
        
        return {
            'errors': errors,
            'warnings': warnings,
            'node_count': len(nodes),
            'relationship_count': len(relationships)
        }
    
    def import_json_file(self, file_path: str, source: str, 
                        text_fields: List[str] = None,
                        clear_existing: bool = False) -> Dict[str, Any]:
        """
        从JSON文件导入数据（参考 UniversalNeo4jImporter）
        
        Args:
            file_path: JSON文件路径
            source: 数据源标签
            text_fields: 用于生成 embedding 的文本字段列表
            clear_existing: 是否先清空现有数据
            
        Returns:
            导入结果
        """
        with open(file_path, 'r', encoding='utf-8') as f:
            json_data = json.load(f)
        
        # 验证数据
        validation = self.validate_data(json_data)
        if validation['errors']:
            raise ValueError(f"Data validation failed: {validation['errors']}")
        
        # 如果设置了清空，先删除
        if clear_existing:
            self.delete_by_source(source)
        
        # 导入数据
        return self.add(
            nodes=json_data.get('nodes', []),
            relationships=json_data.get('relationships', []),
            source=source,
            text_fields=text_fields
        )
    
    def get_node_by_id(self, node_id: str, source: str) -> Optional[Dict[str, Any]]:
        """
        根据ID查询节点（参考 UniversalNeo4jQuerier）
        
        Args:
            node_id: 节点ID
            source: 数据源标签
            
        Returns:
            节点数据字典，如果不存在返回None
        """
        if not source:
            raise ValueError("source参数是必需的，不能为空")
        
        with self.driver.session() as session:
            query = "MATCH (n {id: $node_id, data_source: $source}) RETURN n, labels(n) as labels"
            result = session.run(query, node_id=node_id, source=source)
            record = result.single()
            if record:
                node = dict(record['n'])
                node['labels'] = record['labels']
                # 移除embedding字段
                return self._remove_embedding_from_node(node)
            return None
    
    def get_nodes_by_label(self, label: str, source: str, limit: int = 100) -> List[Dict[str, Any]]:
        """
        根据标签查询节点（参考 UniversalNeo4jQuerier）
        
        Args:
            label: 节点标签
            source: 数据源标签
            limit: 返回数量限制
            
        Returns:
            节点列表
        """
        if not source:
            raise ValueError("source参数是必需的，不能为空")
        
        with self.driver.session() as session:
            query = f"MATCH (n:{label} {{data_source: $source}}) RETURN n, labels(n) as labels LIMIT $limit"
            result = session.run(query, source=source, limit=limit)
            nodes = []
            for record in result:
                node = dict(record['n'])
                node['labels'] = record['labels']
                nodes.append(node)
            # 移除embedding字段
            return self._remove_embedding_from_nodes(nodes)
    
    def get_all_nodes(self, source: str, limit: int = 1000) -> List[Dict[str, Any]]:
        """
        查询所有节点（参考 UniversalNeo4jQuerier）
        
        Args:
            source: 数据源标签
            limit: 返回数量限制
            
        Returns:
            节点列表
        """
        if not source:
            raise ValueError("source参数是必需的，不能为空")
        
        with self.driver.session() as session:
            query = "MATCH (n {data_source: $source}) RETURN n, labels(n) as labels LIMIT $limit"
            result = session.run(query, source=source, limit=limit)
            nodes = []
            for record in result:
                node = dict(record['n'])
                node['labels'] = record['labels']
                nodes.append(node)
            # 移除embedding字段
            return self._remove_embedding_from_nodes(nodes)
    
    def get_all_relationships(self, source: str, limit: int = 10000) -> List[Dict[str, Any]]:
        """
        根据 source 查询该数据源下的所有关系（不区分关系类型）。
        
        Args:
            source: 数据源标签
            limit: 返回数量限制
            
        Returns:
            关系列表，每项包含 start_id, end_id, type, properties, start_labels, end_labels
        """
        if not source:
            raise ValueError("source参数是必需的，不能为空")
        
        with self.driver.session() as session:
            query = (
                "MATCH (a {data_source: $source})-[r]->(b {data_source: $source}) "
                "WHERE r.data_source = $source "
                "RETURN a.id as start_id, type(r) as rel_type, "
                "r as relationship, b.id as end_id, "
                "labels(a) as start_labels, labels(b) as end_labels "
                "LIMIT $limit"
            )
            result = session.run(query, source=source, limit=limit)
            relationships = []
            for record in result:
                rel_data = {
                    'start_id': record['start_id'],
                    'start_labels': record['start_labels'],
                    'end_id': record['end_id'],
                    'end_labels': record['end_labels'],
                    'type': record['rel_type'],
                    'properties': dict(record['relationship'])
                }
                relationships.append(rel_data)
            return relationships
    
    def get_graph_by_source(
        self, source: str, node_limit: int = 10000, rel_limit: int = 10000
    ) -> Dict[str, Any]:
        """
        根据 source 查询整图：该数据源下的所有节点和所有关系。
        
        Args:
            source: 数据源标签
            node_limit: 节点返回数量限制
            rel_limit: 关系返回数量限制
            
        Returns:
            {"nodes": [...], "relationships": [...]}，节点已移除 embedding
        """
        if not source:
            raise ValueError("source参数是必需的，不能为空")
        
        nodes = self.get_all_nodes(source=source, limit=node_limit)
        relationships = self.get_all_relationships(source=source, limit=rel_limit)
        return {"nodes": nodes, "relationships": relationships}
    
    def get_relationships_by_type(self, rel_type: str, source: str, limit: int = 100) -> List[Dict[str, Any]]:
        """
        根据类型查询关系（参考 UniversalNeo4jQuerier）
        
        Args:
            rel_type: 关系类型
            source: 数据源标签
            limit: 返回数量限制
            
        Returns:
            关系列表
        """
        if not source:
            raise ValueError("source参数是必需的，不能为空")
        
        with self.driver.session() as session:
            query = (f"MATCH (a)-[r:{rel_type}]->(b) "
                    "WHERE r.data_source = $source "
                    "RETURN a.id as start_id, type(r) as rel_type, "
                    "r as relationship, b.id as end_id, "
                    "labels(a) as start_labels, labels(b) as end_labels "
                    "LIMIT $limit")
            result = session.run(query, source=source, limit=limit)
            relationships = []
            for record in result:
                rel_data = {
                    'start_id': record['start_id'],
                    'start_labels': record['start_labels'],
                    'end_id': record['end_id'],
                    'end_labels': record['end_labels'],
                    'type': record['rel_type'],
                    'properties': dict(record['relationship'])
                }
                relationships.append(rel_data)
            return relationships
    
    def get_node_relationships(self, node_id: str, source: str, direction: str = "both") -> List[Dict[str, Any]]:
        """
        查询节点的所有关系（参考 UniversalNeo4jQuerier）
        
        Args:
            node_id: 节点ID
            source: 数据源标签
            direction: 关系方向，"out"（出边）、"in"（入边）、"both"（双向）
            
        Returns:
            关系列表
        """
        if not source:
            raise ValueError("source参数是必需的，不能为空")
        
        with self.driver.session() as session:
            if direction == "out":
                query = """
                    MATCH (a {id: $node_id, data_source: $source})-[r {data_source: $source}]->(b {data_source: $source})
                    RETURN a.id as start_id, type(r) as rel_type,
                           r as relationship, b.id as end_id,
                           labels(a) as start_labels, labels(b) as end_labels
                """
            elif direction == "in":
                query = """
                    MATCH (a {data_source: $source})<-[r {data_source: $source}]-(b {id: $node_id, data_source: $source})
                    RETURN b.id as start_id, type(r) as rel_type,
                           r as relationship, a.id as end_id,
                           labels(b) as start_labels, labels(a) as end_labels
                """
            else:  # both
                query = """
                    MATCH (a {id: $node_id, data_source: $source})-[r {data_source: $source}]-(b {data_source: $source})
                    RETURN a.id as start_id, type(r) as rel_type,
                           r as relationship, b.id as end_id,
                           labels(a) as start_labels, labels(b) as end_labels,
                           startNode(r).id = $node_id as is_outgoing
                """
            
            result = session.run(query, node_id=node_id, source=source)
            relationships = []
            for record in result:
                rel_data = {
                    'start_id': record['start_id'],
                    'start_labels': record['start_labels'],
                    'end_id': record['end_id'],
                    'end_labels': record['end_labels'],
                    'type': record['rel_type'],
                    'properties': dict(record['relationship'])
                }
                if direction == "both":
                    rel_data['is_outgoing'] = record.get('is_outgoing', True)
                relationships.append(rel_data)
            return relationships
    
    def find_path(self, start_id: str, end_id: str, source: str, max_depth: int = 5) -> List[Dict[str, Any]]:
        """
        查找两个节点之间的路径（参考 UniversalNeo4jQuerier）
        
        Args:
            start_id: 起始节点ID
            end_id: 结束节点ID
            source: 数据源标签
            max_depth: 最大路径深度
            
        Returns:
            路径列表
        """
        if not source:
            raise ValueError("source参数是必需的，不能为空")
        
        with self.driver.session() as session:
            query = f"""
                MATCH path = shortestPath((a {{id: $start_id, data_source: $source}})-[*1..{max_depth}]-(b {{id: $end_id, data_source: $source}}))
                WHERE ALL(r in relationships(path) WHERE r.data_source = $source)
                RETURN path
            """
            result = session.run(
                query,
                start_id=start_id,
                end_id=end_id,
                source=source
            )
            paths = []
            for record in result:
                path = record['path']
                nodes = []
                relationships = []
                
                for node in path.nodes:
                    nodes.append({
                        'id': node.get('id'),
                        'labels': list(node.labels),
                        'properties': dict(node)
                    })
                
                for rel in path.relationships:
                    relationships.append({
                        'type': rel.type,
                        'start_id': rel.start_node.get('id'),
                        'end_id': rel.end_node.get('id'),
                        'properties': dict(rel)
                    })
                
                paths.append({
                    'nodes': nodes,
                    'relationships': relationships,
                    'length': len(relationships)
                })
            return paths
    
    def get_statistics(self, source: str) -> Dict[str, Any]:
        """
        获取数据库统计信息（参考 UniversalNeo4jQuerier）
        
        Args:
            source: 数据源标签
            
        Returns:
            统计信息字典
        """
        if not source:
            raise ValueError("source参数是必需的，不能为空")
        
        with self.driver.session() as session:
            stats = {}
            
            # 节点总数
            result = session.run("MATCH (n {data_source: $source}) RETURN count(n) as count", source=source)
            stats['total_nodes'] = result.single()['count']
            
            # 关系总数
            result = session.run("MATCH ()-[r {data_source: $source}]->() RETURN count(r) as count", source=source)
            stats['total_relationships'] = result.single()['count']
            
            # 有embedding的节点数
            result = session.run(
                "MATCH (n {data_source: $source}) WHERE n.embedding IS NOT NULL RETURN count(n) as count",
                source=source
            )
            stats['nodes_with_embedding'] = result.single()['count']
            
            # 按标签统计节点
            result = session.run("""
                MATCH (n {data_source: $source})
                UNWIND labels(n) as label
                RETURN label, count(*) as count
                ORDER BY count DESC
            """, source=source)
            stats['nodes_by_label'] = {
                record['label']: record['count'] 
                for record in result
            }
            
            # 按类型统计关系
            result = session.run("""
                MATCH ()-[r {data_source: $source}]->()
                RETURN type(r) as relType, count(*) as count
                ORDER BY count DESC
            """, source=source)
            stats['relationships_by_type'] = {
                record['relType']: record['count']
                for record in result
            }
            
            return stats
    
    def get_subgraph(self, node_id: str, source: str, depth: int = 2) -> Dict[str, Any]:
        """
        获取以指定节点为中心的子图（参考 UniversalNeo4jQuerier）
        
        Args:
            node_id: 中心节点ID
            source: 数据源标签
            depth: 查询深度
            
        Returns:
            包含节点和关系的子图字典
        """
        if not source:
            raise ValueError("source参数是必需的，不能为空")
        
        with self.driver.session() as session:
            result = session.run(
                f"""
                MATCH path = (center {{id: $node_id, data_source: $source}})-[*0..{depth}]-(connected)
                WHERE ALL(r in relationships(path) WHERE r.data_source = $source)
                AND (connected.data_source = $source OR connected = center)
                RETURN DISTINCT center, connected, relationships(path) as rels
                """,
                node_id=node_id,
                source=source
            )
            
            nodes = {}
            relationships = []
            rel_set = set()
            
            for record in result:
                center = record['center']
                connected = record['connected']
                rels = record['rels']
                
                # 添加中心节点
                if center.get('id'):
                    nodes[center.get('id')] = {
                        'id': center.get('id'),
                        'labels': list(center.labels),
                        'properties': dict(center)
                    }
                
                # 添加连接的节点
                if connected.get('id'):
                    nodes[connected.get('id')] = {
                        'id': connected.get('id'),
                        'labels': list(connected.labels),
                        'properties': dict(connected)
                    }
                
                # 添加关系（去重）
                for rel in rels:
                    rel_key = (rel.start_node.get('id'), rel.type, rel.end_node.get('id'))
                    if rel_key not in rel_set:
                        rel_set.add(rel_key)
                        relationships.append({
                            'type': rel.type,
                            'start_id': rel.start_node.get('id'),
                            'end_id': rel.end_node.get('id'),
                            'properties': dict(rel)
                        })
            
            return {
                'nodes': list(nodes.values()),
                'relationships': relationships,
                'center_node_id': node_id
            }
    
    def execute_custom_query(self, cypher_query: str, parameters: Dict[str, Any] = None) -> List[Dict[str, Any]]:
        """
        执行自定义Cypher查询（参考 UniversalNeo4jQuerier）
        
        Args:
            cypher_query: Cypher查询语句
            parameters: 查询参数
            
        Returns:
            查询结果列表
        """
        with self.driver.session() as session:
            if parameters:
                result = session.run(cypher_query, **parameters)
            else:
                result = session.run(cypher_query)
            
            records = []
            for record in result:
                records.append(dict(record))
            return records
    
    def _clean_properties(self, properties: Dict) -> Dict:
        """
        清理属性值，处理特殊字符和类型
        
        Args:
            properties: 原始属性字典
            
        Returns:
            清理后的属性字典
        """
        cleaned = {}
        for key, value in properties.items():
            if value is None:
                continue
            elif isinstance(value, (str, int, float, bool)):
                cleaned[key] = value
            elif isinstance(value, (list, dict)):
                cleaned[f"{key}_json"] = json.dumps(value, ensure_ascii=False)
            else:
                cleaned[key] = str(value)
        return cleaned
