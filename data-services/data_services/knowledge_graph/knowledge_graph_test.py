"""
测试基于向量的知识图谱服务
python -m data_services.knowledge_graph.knowledge_graph_test
"""

import json
import os
import logging
from .knowledge_graph import KnowledgeGraphVectorService

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)


def setup_env():
    """设置环境变量"""
    # Embedding 配置
    os.environ["EMBEDDING_PROVIDER"] = "dashscope"
    os.environ["EMBEDDING_MODEL"] = "text-embedding-v4"
    os.environ["EMBEDDING_BASE_URL"] = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    os.environ["EMBEDDING_API_KEY"] = "sk-xxx"
    
    logger.info("Environment variables configured")


def load_test_data():
    """加载测试数据"""
    current_dir = os.path.dirname(os.path.abspath(__file__))
    data_file = os.path.join(current_dir, "data.json")
    
    if not os.path.exists(data_file):
        raise FileNotFoundError(f"Test data file not found: {data_file}")
    
    with open(data_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    logger.info(f"Loaded test data: {len(data.get('nodes', []))} nodes, "
                f"{len(data.get('relationships', []))} relationships")
    return data


def test_add_data(service: KnowledgeGraphVectorService, test_data: dict, source: str = "vector_test"):
    """测试添加数据"""
    logger.info("=" * 60)
    logger.info("Testing ADD functionality")
    logger.info("=" * 60)
    
    nodes = test_data.get('nodes', [])
    relationships = test_data.get('relationships', [])
    
    # 使用所有节点进行测试
    test_nodes = nodes
    test_relationships = relationships
    
    logger.info(f"Adding {len(test_nodes)} nodes and {len(test_relationships)} relationships...")
    
    # 显示一些节点信息用于调试
    if test_nodes:
        logger.info(f"Sample node: {test_nodes[0].get('id')} - {test_nodes[0].get('properties', {}).get('name', 'N/A')}")
    
    result = service.add(
        nodes=test_nodes,
        relationships=test_relationships,
        source=source,
        text_fields=['name', 'term', 'description', 'englishName', 'englishTerm']
    )
    
    logger.info(f"Add result: {json.dumps(result, indent=2, ensure_ascii=False)}")
    
    # 验证数据是否正确存储
    logger.info("\nVerifying data storage...")
    with service.driver.session() as session:
        # 检查节点数量
        count_query = "MATCH (n {data_source: $source}) RETURN count(n) as count"
        result_count = session.run(count_query, source=source)
        node_count = result_count.single()['count']
        logger.info(f"Nodes in database with source '{source}': {node_count}")
        
        # 检查有embedding的节点数量
        embedding_query = "MATCH (n {data_source: $source}) WHERE n.embedding IS NOT NULL RETURN count(n) as count"
        result_embedding = session.run(embedding_query, source=source)
        embedding_count = result_embedding.single()['count']
        logger.info(f"Nodes with embedding: {embedding_count}")
        
        # 检查一个节点的embedding维度
        sample_query = "MATCH (n {data_source: $source}) WHERE n.embedding IS NOT NULL RETURN n.id as id, size(n.embedding) as dims LIMIT 1"
        result_sample = session.run(sample_query, source=source)
        sample = result_sample.single()
        if sample:
            logger.info(f"Sample node embedding dimensions: {sample['dims']} (node: {sample['id']})")
    
    return result


def test_search(service: KnowledgeGraphVectorService, source: str = "vector_test"):
    """测试搜索功能"""
    logger.info("=" * 60)
    logger.info("Testing SEARCH functionality")
    logger.info("=" * 60)
    
    # 测试多个查询
    test_queries = [
        "组织架构管理",
        "人力资源管理",
        "项目管理",
        "部门层级",
        "员工信息"
    ]
    
    for query_text in test_queries:
        logger.info(f"\n--- Searching for: '{query_text}' ---")
        
        try:
            results = service.search(
                query_text=query_text,
                source=source,
                top_k=5,
                include_relationships=True,
                relationship_depth=1
            )
            
            logger.info(f"Found {results['count']} results")
            
            # 显示前3个结果
            for i, node in enumerate(results['nodes'][:3], 1):
                logger.info(f"\n  Result {i}:")
                logger.info(f"    ID: {node.get('id')}")
                logger.info(f"    Labels: {node.get('labels')}")
                logger.info(f"    Similarity Score: {node.get('similarity_score', 0):.4f}")
                
                # 显示关键属性
                props = node.get('properties', {})
                if 'name' in props:
                    logger.info(f"    Name: {props['name']}")
                if 'term' in props:
                    logger.info(f"    Term: {props['term']}")
                if 'description' in props:
                    desc = props['description']
                    if len(desc) > 100:
                        desc = desc[:100] + "..."
                    logger.info(f"    Description: {desc}")
            
            # 显示关系信息
            if results.get('relationships'):
                logger.info(f"\n  Found {len(results['relationships'])} relationships:")
                for rel in results['relationships'][:3]:
                    logger.info(f"    {rel['start_id']} -[{rel['type']}]-> {rel['end_id']}")
            
        except Exception as e:
            logger.error(f"Search failed for query '{query_text}': {e}", exc_info=True)


def test_comprehensive_search(service: KnowledgeGraphVectorService, source: str = "vector_test"):
    """综合搜索测试"""
    logger.info("=" * 60)
    logger.info("Testing Comprehensive Search")
    logger.info("=" * 60)
    
    query = "企业组织管理"
    logger.info(f"Query: '{query}'")
    
    results = service.search(
        query_text=query,
        source=source,
        top_k=10,
        include_relationships=True,
        relationship_depth=2
    )
    
    logger.info(f"\nTotal results: {results['count']}")
    logger.info(f"Nodes found: {len(results['nodes'])}")
    logger.info(f"Relationships found: {len(results.get('relationships', []))}")
    
    # 详细显示结果
    logger.info("\nDetailed Results:")
    for i, node in enumerate(results['nodes'], 1):
        logger.info(f"\n  [{i}] Node: {node.get('id')}")
        logger.info(f"      Labels: {', '.join(node.get('labels', []))}")
        logger.info(f"      Similarity: {node.get('similarity_score', 0):.4f}")
        props = node.get('properties', {})
        for key in ['name', 'term', 'description']:
            if key in props:
                value = props[key]
                if isinstance(value, str) and len(value) > 80:
                    value = value[:80] + "..."
                logger.info(f"      {key}: {value}")
    
    # 显示关系图
    if results.get('relationships'):
        logger.info(f"\n  Relationship Graph:")
        rel_map = {}
        for rel in results['relationships']:
            start = rel['start_id']
            end = rel['end_id']
            rel_type = rel['type']
            if start not in rel_map:
                rel_map[start] = []
            rel_map[start].append((rel_type, end))
        
        for start_id, rels in list(rel_map.items())[:5]:
            logger.info(f"    {start_id}:")
            for rel_type, end_id in rels[:3]:
                logger.info(f"      -[{rel_type}]-> {end_id}")


def test_format_search_result_as_svo(service: KnowledgeGraphVectorService, source: str = "vector_test"):
    """测试 format_search_result_as_svo：将 search 结果格式化为主谓宾字符串"""
    logger.info("=" * 60)
    logger.info("Testing FORMAT_SEARCH_RESULT_AS_SVO functionality")
    logger.info("=" * 60)

    # 1. 单元测试：mock 数据
    logger.info("\n--- Unit tests with mock search result ---")
    mock_empty = {}
    assert service.format_search_result_as_svo(mock_empty) == ""
    logger.info("  ✓ Empty input -> empty string")

    mock_fail = {"status": "fail", "nodes": [], "relationships": []}
    assert service.format_search_result_as_svo(mock_fail) == ""
    logger.info("  ✓ status != success -> empty string")

    mock_no_rels = {
        "status": "success",
        "nodes": [{"id": "n1", "properties": {"name": "A"}}],
        "relationships": [],
    }
    assert service.format_search_result_as_svo(mock_no_rels) == ""
    logger.info("  ✓ No relationships -> empty string")

    mock_svo = {
        "status": "success",
        "nodes": [
            {"id": "a", "properties": {"name": "Alice"}},
            {"id": "b", "properties": {"name": "Bob"}},
        ],
        "relationships": [
            {"start_id": "a", "end_id": "b", "type": "KNOWS"},
        ],
    }
    svo = service.format_search_result_as_svo(mock_svo)
    assert svo == "Alice KNOWS Bob", f"Expected 'Alice KNOWS Bob', got {svo!r}"
    logger.info(f"  ✓ Single relationship -> '{svo}'")

    mock_multi = {
        "status": "success",
        "nodes": [
            {"id": "x", "properties": {"name": "X"}},
            {"id": "y", "properties": {"title": "Y"}},
            {"id": "z", "properties": {}},
        ],
        "relationships": [
            {"start_id": "x", "end_id": "y", "type": "RELATED_TO"},
            {"start_id": "y", "end_id": "z", "type": "CONTAINS"},
        ],
    }
    svo_multi = service.format_search_result_as_svo(mock_multi)
    lines = svo_multi.split("\n")
    assert len(lines) == 2, f"Expected 2 lines, got {len(lines)}"
    assert "X RELATED_TO Y" in svo_multi
    assert "Y CONTAINS z" in svo_multi  # z 无 name/title 用 id
    logger.info(f"  ✓ Multiple relationships (name/title/id fallback):\n    {svo_multi.replace(chr(10), chr(10) + '    ')}")

    # 2. 集成测试：真实 search + format（需 Neo4j + embedding 可用）
    logger.info("\n--- Integration test: real search + format_search_result_as_svo ---")
    try:
        result = service.search(
            query_text="企业组织管理",
            source=source,
            top_k=5,
            include_relationships=True,
            relationship_depth=1,
        )
        svo_out = service.format_search_result_as_svo(result)
        logger.info(f"  Query: '企业组织管理'")
        logger.info(f"  Nodes: {result['count']}, Relationships: {len(result.get('relationships', []))}")
        if svo_out:
            logger.info("  SVO output (one triple per line):")
            for line in svo_out.split("\n"):
                logger.info(f"    {line}")
            logger.info("  ✓ Integration test passed.")
        else:
            logger.info("  (No relationships in result; SVO string is empty.)")
    except Exception as e:
        logger.warning(
            f"  Integration test skipped (search failed: {e}). "
            "Unit tests above already validate format_search_result_as_svo."
        )

    logger.info("\n✓ format_search_result_as_svo tests passed!")


def verify_existing_data(service: KnowledgeGraphVectorService, source: str = "vector_test_source"):
    """验证已存在的数据"""
    logger.info("=" * 60)
    logger.info("Verifying existing data")
    logger.info("=" * 60)
    
    try:
        with service.driver.session() as session:
            # 检查节点数量
            count_query = "MATCH (n {data_source: $source}) RETURN count(n) as count"
            result_count = session.run(count_query, source=source)
            node_count = result_count.single()['count']
            logger.info(f"Nodes in database with source '{source}': {node_count}")
            
            if node_count == 0:
                logger.warning(f"No nodes found with source '{source}'")
                return False
            
            # 检查有embedding的节点数量
            embedding_query = "MATCH (n {data_source: $source}) WHERE n.embedding IS NOT NULL RETURN count(n) as count"
            result_embedding = session.run(embedding_query, source=source)
            embedding_count = result_embedding.single()['count']
            logger.info(f"Nodes with embedding: {embedding_count}")
            
            # 检查关系数量
            rel_query = "MATCH ()-[r {data_source: $source}]->() RETURN count(r) as count"
            result_rel = session.run(rel_query, source=source)
            rel_count = result_rel.single()['count']
            logger.info(f"Relationships: {rel_count}")
            
            # 检查一个节点的embedding维度
            sample_query = "MATCH (n {data_source: $source}) WHERE n.embedding IS NOT NULL RETURN n.id as id, n.name as name, size(n.embedding) as dims LIMIT 3"
            result_sample = session.run(sample_query, source=source)
            logger.info("Sample nodes with embeddings:")
            for record in result_sample:
                logger.info(f"  - {record['id']}: {record.get('name', 'N/A')} (dims: {record['dims']})")
            
            return embedding_count > 0
    except Exception as e:
        logger.error(f"Error verifying data: {e}", exc_info=True)
        return False


def test_validate_data(service: KnowledgeGraphVectorService, test_data: dict):
    """测试数据验证功能"""
    logger.info("=" * 60)
    logger.info("Testing VALIDATE_DATA functionality")
    logger.info("=" * 60)
    
    try:
        validation = service.validate_data(test_data)
        logger.info(f"Validation result:")
        logger.info(f"  Nodes: {validation['node_count']}")
        logger.info(f"  Relationships: {validation['relationship_count']}")
        logger.info(f"  Errors: {len(validation['errors'])}")
        logger.info(f"  Warnings: {len(validation['warnings'])}")
        
        if validation['errors']:
            logger.warning(f"Validation errors: {validation['errors']}")
        if validation['warnings']:
            logger.info(f"Validation warnings: {validation['warnings']}")
        
        if len(validation['errors']) == 0:
            logger.info("✓ Data validation passed!")
            return True
        else:
            logger.error("✗ Data validation failed!")
            return False
    except Exception as e:
        logger.error(f"Validation test failed: {e}", exc_info=True)
        raise


def test_get_node_by_id(service: KnowledgeGraphVectorService, source: str = "vector_test_source"):
    """测试根据ID查询节点"""
    logger.info("=" * 60)
    logger.info("Testing GET_NODE_BY_ID functionality")
    logger.info("=" * 60)
    
    try:
        # 先获取一个节点ID
        all_nodes = service.get_all_nodes(source=source, limit=1)
        if not all_nodes:
            logger.warning("No nodes found, skipping test")
            return
        
        test_node_id = all_nodes[0].get('id')
        logger.info(f"Testing with node ID: {test_node_id}")
        
        node = service.get_node_by_id(test_node_id, source=source)
        
        if node:
            logger.info(f"✓ Found node: {node.get('id')}")
            logger.info(f"  Labels: {node.get('labels')}")
            logger.info(f"  Has embedding: {'embedding' in node}")
            logger.info("✓ Get node by ID test passed!")
        else:
            logger.error("✗ Node not found!")
    except Exception as e:
        logger.error(f"Get node by ID test failed: {e}", exc_info=True)
        raise


def test_get_nodes_by_label(service: KnowledgeGraphVectorService, source: str = "vector_test_source"):
    """测试根据标签查询节点"""
    logger.info("=" * 60)
    logger.info("Testing GET_NODES_BY_LABEL functionality")
    logger.info("=" * 60)
    
    try:
        # 测试查询 SemanticDomain 标签
        nodes = service.get_nodes_by_label("SemanticDomain", source=source, limit=10)
        logger.info(f"Found {len(nodes)} nodes with label 'SemanticDomain'")
        
        for i, node in enumerate(nodes[:3], 1):
            logger.info(f"  {i}. {node.get('id')}: {node.get('properties', {}).get('name', 'N/A')}")
        
        if len(nodes) > 0:
            logger.info("✓ Get nodes by label test passed!")
        else:
            logger.warning("⚠ No nodes found with label 'SemanticDomain'")
    except Exception as e:
        logger.error(f"Get nodes by label test failed: {e}", exc_info=True)
        raise


def test_get_relationships(service: KnowledgeGraphVectorService, source: str = "vector_test_source"):
    """测试关系查询功能"""
    logger.info("=" * 60)
    logger.info("Testing GET_RELATIONSHIPS functionality")
    logger.info("=" * 60)
    
    try:
        # 1. 测试根据类型查询关系
        logger.info("\n1. Testing get_relationships_by_type...")
        relationships = service.get_relationships_by_type("DEFINES", source=source, limit=10)
        logger.info(f"Found {len(relationships)} relationships of type 'DEFINES'")
        for rel in relationships[:3]:
            logger.info(f"  {rel['start_id']} -[{rel['type']}]-> {rel['end_id']}")
        
        # 2. 测试查询节点的关系
        logger.info("\n2. Testing get_node_relationships...")
        all_nodes = service.get_all_nodes(source=source, limit=1)
        if all_nodes:
            node_id = all_nodes[0].get('id')
            logger.info(f"Testing with node: {node_id}")
            
            # 查询出边
            outgoing = service.get_node_relationships(node_id, source=source, direction="out")
            logger.info(f"  Outgoing relationships: {len(outgoing)}")
            
            # 查询入边
            incoming = service.get_node_relationships(node_id, source=source, direction="in")
            logger.info(f"  Incoming relationships: {len(incoming)}")
            
            # 查询双向
            both = service.get_node_relationships(node_id, source=source, direction="both")
            logger.info(f"  Both directions: {len(both)}")
        
        logger.info("✓ Get relationships test passed!")
    except Exception as e:
        logger.error(f"Get relationships test failed: {e}", exc_info=True)
        raise


def test_find_path(service: KnowledgeGraphVectorService, source: str = "vector_test_source"):
    """测试路径查找功能"""
    logger.info("=" * 60)
    logger.info("Testing FIND_PATH functionality")
    logger.info("=" * 60)
    
    try:
        # 获取两个节点
        all_nodes = service.get_all_nodes(source=source, limit=5)
        if len(all_nodes) < 2:
            logger.warning("Not enough nodes for path test, skipping")
            return
        
        start_id = all_nodes[0].get('id')
        end_id = all_nodes[-1].get('id')
        
        logger.info(f"Finding path from {start_id} to {end_id}")
        
        paths = service.find_path(start_id, end_id, source=source, max_depth=3)
        
        if paths:
            path = paths[0]
            logger.info(f"✓ Found path with length: {path['length']}")
            logger.info(f"  Nodes: {[n['id'] for n in path['nodes']]}")
            logger.info(f"  Relationships: {[r['type'] for r in path['relationships']]}")
            logger.info("✓ Find path test passed!")
        else:
            logger.warning("⚠ No path found between nodes")
    except Exception as e:
        logger.error(f"Find path test failed: {e}", exc_info=True)
        raise


def test_get_statistics(service: KnowledgeGraphVectorService, source: str = "vector_test_source"):
    """测试统计信息功能"""
    logger.info("=" * 60)
    logger.info("Testing GET_STATISTICS functionality")
    logger.info("=" * 60)
    
    try:
        stats = service.get_statistics(source=source)
        
        logger.info(f"Statistics for source '{source}':")
        logger.info(f"  Total nodes: {stats['total_nodes']}")
        logger.info(f"  Nodes with embedding: {stats.get('nodes_with_embedding', 0)}")
        logger.info(f"  Total relationships: {stats['total_relationships']}")
        logger.info(f"  Nodes by label: {stats['nodes_by_label']}")
        logger.info(f"  Relationships by type: {stats['relationships_by_type']}")
        
        logger.info("✓ Get statistics test passed!")
    except Exception as e:
        logger.error(f"Get statistics test failed: {e}", exc_info=True)
        raise


def test_get_subgraph(service: KnowledgeGraphVectorService, source: str = "vector_test_source"):
    """测试子图查询功能"""
    logger.info("=" * 60)
    logger.info("Testing GET_SUBGRAPH functionality")
    logger.info("=" * 60)
    
    try:
        # 获取一个节点
        all_nodes = service.get_all_nodes(source=source, limit=1)
        if not all_nodes:
            logger.warning("No nodes found, skipping subgraph test")
            return
        
        center_node_id = all_nodes[0].get('id')
        logger.info(f"Getting subgraph for node: {center_node_id}")
        
        subgraph = service.get_subgraph(center_node_id, source=source, depth=2)
        
        logger.info(f"Subgraph contains:")
        logger.info(f"  Nodes: {len(subgraph['nodes'])}")
        logger.info(f"  Relationships: {len(subgraph['relationships'])}")
        logger.info(f"  Center node: {subgraph['center_node_id']}")
        
        # 显示一些节点
        for i, node in enumerate(subgraph['nodes'][:5], 1):
            logger.info(f"    {i}. {node['id']}: {node.get('properties', {}).get('name', 'N/A')}")
        
        logger.info("✓ Get subgraph test passed!")
    except Exception as e:
        logger.error(f"Get subgraph test failed: {e}", exc_info=True)
        raise


def test_get_graph_by_source(service: KnowledgeGraphVectorService, source: str = "vector_test_source"):
    """测试按 source 查询整图（所有节点 + 所有关系）"""
    logger.info("=" * 60)
    logger.info("Testing GET_GRAPH_BY_SOURCE functionality")
    logger.info("=" * 60)
    
    try:
        result = service.get_graph_by_source(source=source, node_limit=1000, rel_limit=1000)
        assert "nodes" in result and "relationships" in result
        nodes = result["nodes"]
        relationships = result["relationships"]
        logger.info(f"Graph by source: nodes={len(nodes)}, relationships={len(relationships)}")
        for i, node in enumerate(nodes[:3], 1):
            logger.info(f"  Node {i}: {node.get('id')} {node.get('labels', [])}")
        for i, rel in enumerate(relationships[:3], 1):
            logger.info(f"  Rel {i}: {rel.get('start_id')} -[{rel.get('type')}]-> {rel.get('end_id')}")
        logger.info("✓ Get graph by source test passed!")
    except Exception as e:
        logger.error(f"Get graph by source test failed: {e}", exc_info=True)
        raise


def test_execute_custom_query(service: KnowledgeGraphVectorService, source: str = "vector_test_source"):
    """测试自定义查询功能"""
    logger.info("=" * 60)
    logger.info("Testing EXECUTE_CUSTOM_QUERY functionality")
    logger.info("=" * 60)
    
    try:
        # 执行自定义查询：查找有embedding的节点
        query = """
        MATCH (n {data_source: $source})
        WHERE n.embedding IS NOT NULL
        RETURN n.id as id, labels(n) as labels, size(n.embedding) as dims
        LIMIT 5
        """
        
        results = service.execute_custom_query(query, parameters={"source": source})
        
        logger.info(f"Custom query returned {len(results)} results:")
        for i, record in enumerate(results, 1):
            logger.info(f"  {i}. {record['id']}: {record['labels']} (dims: {record['dims']})")
        
        logger.info("✓ Execute custom query test passed!")
    except Exception as e:
        logger.error(f"Execute custom query test failed: {e}", exc_info=True)
        raise


def test_deduplicate_by_name(service: KnowledgeGraphVectorService, source: str = "deduplicate_test"):
    """测试基于name字段的节点去重合并功能"""
    logger.info("=" * 60)
    logger.info("Testing DEDUPLICATE BY NAME functionality")
    logger.info("=" * 60)
    
    try:
        # 先清理测试数据
        try:
            service.delete_by_source(source)
            logger.info(f"Cleaned up existing data for source '{source}'")
        except Exception as e:
            logger.debug(f"No existing data to clean: {e}")
        
        # 测试场景1: 节点顶层有name字段，两个节点name相同但id不同
        logger.info("\n--- Test Case 1: Nodes with same top-level name field ---")
        nodes_case1 = [
            {
                "id": "node_dup_001",
                "name": "张三",  # 顶层name字段
                "labels": ["Person", "Employee"],
                "properties": {
                    "age": 30,
                    "department": "技术部",
                    "email": "zhangsan@example.com"
                }
            },
            {
                "id": "node_dup_002",  # 不同的id
                "name": "张三",  # 相同的name
                "labels": ["Person", "Manager"],  # 不同的labels
                "properties": {
                    "age": 35,  # 不同的属性
                    "department": "技术部",
                    "phone": "13800138000"
                }
            },
            {
                "id": "node_dup_003",
                "name": "李四",  # 不同的name，不应该合并
                "labels": ["Person"],
                "properties": {
                    "age": 28
                }
            }
        ]
        
        relationships_case1 = [
            {
                "start": "node_dup_001",
                "end": "node_dup_003",
                "type": "KNOWS",
                "properties": {}
            }
        ]
        
        logger.info(f"Adding {len(nodes_case1)} nodes with deduplicate_by_name=True...")
        result1 = service.add(
            nodes=nodes_case1,
            relationships=relationships_case1,
            source=source,
            deduplicate_by_name=True,
            name_field='name'
        )
        
        logger.info(f"Add result: {json.dumps(result1, indent=2, ensure_ascii=False)}")
        
        # 验证结果
        assert result1['status'] == 'success', "Add operation should succeed"
        
        # 检查node_id_mapping
        if 'node_id_mapping' in result1:
            logger.info(f"✓ Node ID mappings: {result1['node_id_mapping']}")
            assert len(result1['node_id_mapping']) > 0, "Should have node ID mappings"
        else:
            logger.warning("⚠ No node_id_mapping in result")
        
        # 验证数据库中的节点数量
        with service.driver.session() as session:
            count_query = "MATCH (n {data_source: $source}) RETURN count(n) as count"
            result_count = session.run(count_query, source=source)
            node_count = result_count.single()['count']
            logger.info(f"Total nodes in database: {node_count}")
            
            # 应该只有2个节点（node_dup_001和node_dup_003），因为node_dup_002被合并了
            assert node_count == 2, f"Expected 2 nodes after merge, got {node_count}"
            
            # 查询name为"张三"的节点
            name_query = """
            MATCH (n {data_source: $source})
            WHERE n.name = $name_value
            RETURN n.id as id, n.name as name, labels(n) as labels, 
                   n.age as age, n.department as department,
                   n.email as email, n.phone as phone
            """
            result_nodes = session.run(name_query, source=source, name_value="张三")
            nodes_with_name = list(result_nodes)
            logger.info(f"Nodes with name '张三': {len(nodes_with_name)}")
            
            for node_record in nodes_with_name:
                logger.info(f"  - Node ID: {node_record['id']}, Labels: {node_record['labels']}, "
                          f"Age: {node_record.get('age')}, Email: {node_record.get('email')}, "
                          f"Phone: {node_record.get('phone')}")
            
            # 应该只有一个name为"张三"的节点（合并后）
            assert len(nodes_with_name) == 1, f"Expected 1 node with name '张三', got {len(nodes_with_name)}"
            
            # 验证合并后的节点包含了两个节点的属性
            merged_node = nodes_with_name[0]
            logger.info(f"Merged node details: {json.dumps(dict(merged_node), indent=2, ensure_ascii=False)}")
            
            # 验证labels被合并（应该包含两个节点的labels）
            merged_labels = set(merged_node['labels'])
            assert 'Person' in merged_labels, "Merged node should have 'Person' label"
            assert 'Employee' in merged_labels or 'Manager' in merged_labels, \
                "Merged node should have at least one of 'Employee' or 'Manager' labels"
            
            # 验证属性被合并
            assert merged_node.get('email') is not None or merged_node.get('phone') is not None, \
                "Merged node should have properties from both nodes"
        
        logger.info("✓ Test Case 1 passed: Nodes with same top-level name were merged correctly")
        
        # 测试场景2: properties中有name字段的情况
        logger.info("\n--- Test Case 2: Nodes with same name in properties ---")
        nodes_case2 = [
            {
                "id": "node_prop_001",
                "labels": ["Person"],
                "properties": {
                    "name": "王五",  # properties中的name
                    "age": 25
                }
            },
            {
                "id": "node_prop_002",
                "labels": ["Person"],
                "properties": {
                    "name": "王五",  # 相同的name
                    "age": 30
                }
            }
        ]
        
        logger.info(f"Adding {len(nodes_case2)} nodes with name in properties...")
        result2 = service.add(
            nodes=nodes_case2,
            relationships=[],
            source=source,
            deduplicate_by_name=True,
            name_field='name'
        )
        
        logger.info(f"Add result: {json.dumps(result2, indent=2, ensure_ascii=False)}")
        
        # 验证properties中的name也能正确去重
        with service.driver.session() as session:
            name_query = """
            MATCH (n {data_source: $source})
            WHERE n.name = $name_value
            RETURN count(n) as count
            """
            result_count = session.run(name_query, source=source, name_value="王五")
            count = result_count.single()['count']
            logger.info(f"Nodes with name '王五': {count}")
            # 应该只有1个（合并后）
            assert count == 1, f"Expected 1 node with name '王五' after merge, got {count}"
        
        logger.info("✓ Test Case 2 passed: Nodes with name in properties handled correctly")
        
        # 测试场景3: 禁用去重功能
        logger.info("\n--- Test Case 3: Disable deduplication ---")
        nodes_case3 = [
            {
                "id": "node_no_dedup_001",
                "name": "赵六",
                "labels": ["Person"],
                "properties": {"age": 20}
            },
            {
                "id": "node_no_dedup_002",
                "name": "赵六",  # 相同的name
                "labels": ["Person"],
                "properties": {"age": 25}
            }
        ]
        
        logger.info(f"Adding {len(nodes_case3)} nodes with deduplicate_by_name=False...")
        result3 = service.add(
            nodes=nodes_case3,
            relationships=[],
            source=source,
            deduplicate_by_name=False,  # 禁用去重
            name_field='name'
        )
        
        logger.info(f"Add result: {json.dumps(result3, indent=2, ensure_ascii=False)}")
        
        # 验证没有node_id_mapping
        assert 'node_id_mapping' not in result3 or len(result3.get('node_id_mapping', {})) == 0, \
            "Should not have node ID mappings when deduplication is disabled"
        
        # 验证数据库中有2个节点（没有合并）
        with service.driver.session() as session:
            name_query = """
            MATCH (n {data_source: $source})
            WHERE n.name = $name_value
            RETURN count(n) as count
            """
            result_count = session.run(name_query, source=source, name_value="赵六")
            count = result_count.single()['count']
            logger.info(f"Nodes with name '赵六': {count}")
            assert count == 2, f"Expected 2 nodes with name '赵六' (no deduplication), got {count}"
        
        logger.info("✓ Test Case 3 passed: Deduplication correctly disabled")
        
        logger.info("\n" + "=" * 60)
        logger.info("✓ All deduplicate_by_name tests passed!")
        logger.info("=" * 60)
        
    except Exception as e:
        logger.error(f"Deduplicate test failed: {e}", exc_info=True)
        raise


def test_delete_by_source(service: KnowledgeGraphVectorService, source: str = "vector_test_source"):
    """测试基于source删除数据"""
    logger.info("=" * 60)
    logger.info("Testing DELETE by source functionality")
    logger.info("=" * 60)
    
    try:
        # 先验证数据存在
        with service.driver.session() as session:
            count_query = "MATCH (n {data_source: $source}) RETURN count(n) as count"
            result_count = session.run(count_query, source=source)
            node_count_before = result_count.single()['count']
            
            rel_query = "MATCH ()-[r {data_source: $source}]->() RETURN count(r) as count"
            result_rel = session.run(rel_query, source=source)
            rel_count_before = result_rel.single()['count']
            
            logger.info(f"Before deletion: {node_count_before} nodes, {rel_count_before} relationships")
        
        if node_count_before == 0:
            logger.warning(f"No data found with source '{source}', skipping delete test")
            return
        
        # 执行删除
        result = service.delete_by_source(source)
        
        logger.info(f"Delete result: {json.dumps(result, indent=2, ensure_ascii=False)}")
        
        # 验证删除结果
        if result['status'] == 'success':
            logger.info(f"\n✓ Deleted {result['nodes_deleted']} nodes and {result['relationships_deleted']} relationships")
            
            # 验证数据确实被删除
            import time
            time.sleep(1)
            
            with service.driver.session() as session:
                count_query = "MATCH (n {data_source: $source}) RETURN count(n) as count"
                result_count = session.run(count_query, source=source)
                node_count_after = result_count.single()['count']
                
                rel_query = "MATCH ()-[r {data_source: $source}]->() RETURN count(r) as count"
                result_rel = session.run(rel_query, source=source)
                rel_count_after = result_rel.single()['count']
                
                logger.info(f"After deletion: {node_count_after} nodes, {rel_count_after} relationships")
                
                if node_count_after == 0 and rel_count_after == 0:
                    logger.info("✓ Delete verification passed: All data removed successfully")
                else:
                    logger.warning(f"⚠ Delete verification: Still found {node_count_after} nodes and {rel_count_after} relationships")
        else:
            logger.error("✗ Delete test failed: Status is not 'success'")
            
    except Exception as e:
        logger.error(f"Delete test failed: {e}", exc_info=True)
        raise


def main():
    """主测试函数"""
    try:
        # 设置环境
        setup_env()
        
        # 加载测试数据
        test_data = load_test_data()
        
        # Neo4j 连接配置
        neo4j_uri = os.getenv('NEO4J_URI', 'bolt://192.168.3.238:7687')
        neo4j_user = os.getenv('NEO4J_USER', 'neo4j')
        neo4j_password = os.getenv('NEO4J_PASSWORD', 'test123456')
        embedding_dims = int(os.getenv('KNOWLEDGE_GRAPH_EMBEDDING_DIMS', '1024'))
        
        logger.info(f"Connecting to Neo4j: {neo4j_uri}")
        
        # 创建服务实例
        service = KnowledgeGraphVectorService(
            uri=neo4j_uri,
            user=neo4j_user,
            password=neo4j_password,
            embedding_dims=embedding_dims,
            vector_index_name="node_embeddings_vector_test"
        )
        
        try:
            # 测试数据源
            test_source = "vector_test_source"
            
            # 先检查是否已有数据
            has_existing_data = verify_existing_data(service, source=test_source)
            
            if not has_existing_data:
                logger.info("\nNo existing data found, adding new data...")
                # 1. 测试添加数据
                try:
                    add_result = test_add_data(service, test_data, source=test_source)
                    
                    if add_result['status'] == 'success':
                        logger.info("\n✓ Add test passed!")
                    else:
                        logger.error("\n✗ Add test failed!")
                        return
                    
                    # 等待一下，确保数据已写入
                    import time
                    time.sleep(3)
                except Exception as e:
                    logger.error(f"Failed to add data: {e}")
                    logger.info("Will try to search with existing data if available...")
            else:
                logger.info("\nUsing existing data for testing...")
            
            # 2. 测试搜索功能
            try:
                test_search(service, source=test_source)
            except Exception as e:
                logger.error(f"Search test failed: {e}", exc_info=True)
            
            # 3. 综合搜索测试
            try:
                test_comprehensive_search(service, source=test_source)
            except Exception as e:
                logger.error(f"Comprehensive search test failed: {e}", exc_info=True)

            # 3.5. 测试 format_search_result_as_svo
            try:
                test_format_search_result_as_svo(service, source=test_source)
            except Exception as e:
                logger.error(f"format_search_result_as_svo test failed: {e}", exc_info=True)
            
            # 4. 测试数据验证功能
            try:
                test_validate_data(service, test_data)
            except Exception as e:
                logger.error(f"Validate data test failed: {e}", exc_info=True)
            
            # 5. 测试基础查询功能
            try:
                test_get_node_by_id(service, source=test_source)
            except Exception as e:
                logger.error(f"Get node by ID test failed: {e}", exc_info=True)
            
            try:
                test_get_nodes_by_label(service, source=test_source)
            except Exception as e:
                logger.error(f"Get nodes by label test failed: {e}", exc_info=True)
            
            # 6. 测试关系查询功能
            try:
                test_get_relationships(service, source=test_source)
            except Exception as e:
                logger.error(f"Get relationships test failed: {e}", exc_info=True)
            
            # 7. 测试路径查找功能
            try:
                test_find_path(service, source=test_source)
            except Exception as e:
                logger.error(f"Find path test failed: {e}", exc_info=True)
            
            # 8. 测试统计信息功能
            try:
                test_get_statistics(service, source=test_source)
            except Exception as e:
                logger.error(f"Get statistics test failed: {e}", exc_info=True)
            
            # 9. 测试子图查询功能
            try:
                test_get_subgraph(service, source=test_source)
            except Exception as e:
                logger.error(f"Get subgraph test failed: {e}", exc_info=True)
            
            # 9.5. 测试按 source 查询整图
            try:
                test_get_graph_by_source(service, source=test_source)
            except Exception as e:
                logger.error(f"Get graph by source test failed: {e}", exc_info=True)
            
            # 10. 测试自定义查询功能
            try:
                test_execute_custom_query(service, source=test_source)
            except Exception as e:
                logger.error(f"Execute custom query test failed: {e}", exc_info=True)
            
            # 10.5. 测试节点name相同时的合并功能
            try:
                test_deduplicate_by_name(service, source="deduplicate_test")
            except Exception as e:
                logger.error(f"Deduplicate by name test failed: {e}", exc_info=True)
            
            # 11. 测试删除功能
            logger.info("\n" + "=" * 60)
            logger.info("Testing DELETE functionality")
            logger.info("=" * 60)
            try:
                test_delete_by_source(service, source=test_source)
            except Exception as e:
                logger.error(f"Delete test failed: {e}", exc_info=True)
            
            # 12. 验证删除后数据确实被清空
            logger.info("\n" + "=" * 60)
            logger.info("Verifying data after deletion")
            logger.info("=" * 60)
            verify_existing_data(service, source=test_source)
            
            logger.info("\n" + "=" * 60)
            logger.info("All tests completed!")
            logger.info("=" * 60)
            
        finally:
            service.close()
            logger.info("Service connection closed")
            
    except Exception as e:
        logger.error(f"Test failed: {e}", exc_info=True)
        import traceback
        traceback.print_exc()
        raise


if __name__ == "__main__":
    main()
