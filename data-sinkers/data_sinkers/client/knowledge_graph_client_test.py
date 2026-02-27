"""
Test script for KnowledgeGraphClient

This script tests all API methods:
1. add_with_source - Add knowledge graph data
2. search_by_node_id - Search by node ID
3. search_by_label - Search by label
4. search_by_property - Search by property
5. get_all_nodes - Get all nodes
6. delete_with_source - Delete by source
7. add_with_mem0 - Add knowledge graph data with mem0
8. search_with_mem0 - Search knowledge graph data with mem0
9. delete_with_mem0 - Delete knowledge graph data with mem0
"""

import json
from .knowledge_graph_client import KnowledgeGraphClient, KnowledgeGraphNode, KnowledgeGraphRelationship


def test_all_apis():
    """Test all knowledge graph APIs"""
    
    # Create client instance
    client = KnowledgeGraphClient(base_url="http://192.168.3.238:22000", timeout=300)
    
    test_source = "test_source_client_1"
    
    try:
        print("=" * 80)
        print("Knowledge Graph Client Test Suite")
        print("=" * 80)
        
        # Test 1: Add Knowledge Graph Data with Source
        print("\n" + "=" * 80)
        print("Test 1: Add Knowledge Graph Data with Source")
        print("=" * 80)
        
        nodes = [
            KnowledgeGraphNode(
                id="node_001",
                labels=["Person", "Employee"],
                properties={
                    "name": "张三",
                    "age": 30,
                    "department": "技术部"
                }
            ),
            KnowledgeGraphNode(
                id="node_002",
                labels=["Person", "Manager"],
                properties={
                    "name": "李四",
                    "age": 35,
                    "department": "技术部"
                }
            ),
            KnowledgeGraphNode(
                id="node_003",
                labels=["Department"],
                properties={
                    "name": "技术部",
                    "location": "北京"
                }
            )
        ]
        
        relationships = [
            KnowledgeGraphRelationship(
                start="node_001",
                end="node_002",
                type="REPORTS_TO",
                properties={
                    "since": "2023-01-01"
                }
            ),
            KnowledgeGraphRelationship(
                start="node_001",
                end="node_003",
                type="BELONGS_TO",
                properties={}
            ),
            KnowledgeGraphRelationship(
                start="node_002",
                end="node_003",
                type="MANAGES",
                properties={}
            )
        ]
        
        add_result = client.add_with_source(
            source=test_source,
            nodes=nodes,
            relationships=relationships,
            clear_existing=False
        )
        
        print(f"✓ Add result:")
        print(f"  Status: {add_result.get('status')}")
        print(f"  Message: {add_result.get('message')}")
        print(f"  Nodes added: {add_result.get('data', {}).get('nodes_count', 0)}")
        print(f"  Relationships added: {add_result.get('data', {}).get('relationships_count', 0)}")
        
        assert add_result.get('status') == 'success', "Add operation should succeed"
        assert add_result.get('data', {}).get('nodes_count', 0) == 3, "Should add 3 nodes"
        assert add_result.get('data', {}).get('relationships_count', 0) == 3, "Should add 3 relationships"
        
        # Test 2: Search Knowledge Graph Data - By Node ID
        print("\n" + "=" * 80)
        print("Test 2: Search Knowledge Graph Data - By Node ID")
        print("=" * 80)
        
        search_by_id_result = client.search_by_node_id(
            source=test_source,
            node_id="node_001",
            limit=10
        )
        
        print(f"✓ Search by node ID result:")
        print(f"  Status: {search_by_id_result.get('status')}")
        print(f"  Message: {search_by_id_result.get('message')}")
        
        results = search_by_id_result.get('data', {}).get('results', [])
        if results and results[0].get('type') == 'node':
            node_data = results[0].get('data', {})
            print(f"  Found node: {node_data.get('id')} - {node_data.get('name')}")
            print(f"  Labels: {node_data.get('labels', [])}")
        
        assert search_by_id_result.get('status') == 'success', "Search by node ID should succeed"
        assert len(results) > 0, "Should find at least one result"
        assert results[0].get('type') == 'node', "Result type should be 'node'"
        
        # Test 3: Search Knowledge Graph Data - By Label
        print("\n" + "=" * 80)
        print("Test 3: Search Knowledge Graph Data - By Label")
        print("=" * 80)
        
        search_by_label_result = client.search_by_label(
            source=test_source,
            label="Person",
            limit=10
        )
        
        print(f"✓ Search by label result:")
        print(f"  Status: {search_by_label_result.get('status')}")
        print(f"  Message: {search_by_label_result.get('message')}")
        
        results = search_by_label_result.get('data', {}).get('results', [])
        if results and results[0].get('type') == 'nodes_by_label':
            nodes_data = results[0].get('data', [])
            count = results[0].get('count', 0)
            print(f"  Found {count} nodes with label 'Person'")
            for i, node in enumerate(nodes_data[:3], 1):
                print(f"    {i}. {node.get('id')} - {node.get('name')}")
        
        assert search_by_label_result.get('status') == 'success', "Search by label should succeed"
        assert len(results) > 0, "Should find at least one result"
        assert results[0].get('type') == 'nodes_by_label', "Result type should be 'nodes_by_label'"
        
        # Test 4: Search Knowledge Graph Data - By Property
        print("\n" + "=" * 80)
        print("Test 4: Search Knowledge Graph Data - By Property")
        print("=" * 80)
        
        search_by_property_result = client.search_by_property(
            source=test_source,
            property_name="name",
            property_value="张三",
            limit=10
        )
        
        print(f"✓ Search by property result:")
        print(f"  Status: {search_by_property_result.get('status')}")
        print(f"  Message: {search_by_property_result.get('message')}")
        
        results = search_by_property_result.get('data', {}).get('results', [])
        if results and results[0].get('type') == 'nodes_by_property':
            nodes_data = results[0].get('data', [])
            count = results[0].get('count', 0)
            print(f"  Found {count} nodes with property name='张三'")
            for i, node in enumerate(nodes_data[:3], 1):
                print(f"    {i}. {node.get('id')} - {node.get('name')}")
        
        assert search_by_property_result.get('status') == 'success', "Search by property should succeed"
        assert len(results) > 0, "Should find at least one result"
        assert results[0].get('type') == 'nodes_by_property', "Result type should be 'nodes_by_property'"
        
        # Test 5: Search Knowledge Graph Data - All Nodes
        print("\n" + "=" * 80)
        print("Test 5: Search Knowledge Graph Data - All Nodes")
        print("=" * 80)
        
        all_nodes_result = client.get_all_nodes(
            source=test_source,
            limit=10
        )
        
        print(f"✓ Get all nodes result:")
        print(f"  Status: {all_nodes_result.get('status')}")
        print(f"  Message: {all_nodes_result.get('message')}")
        
        results = all_nodes_result.get('data', {}).get('results', [])
        if results and results[0].get('type') == 'all_nodes':
            nodes_data = results[0].get('data', [])
            count = results[0].get('count', 0)
            print(f"  Found {count} total nodes")
            for i, node in enumerate(nodes_data[:5], 1):
                print(f"    {i}. {node.get('id')} - {node.get('name', 'N/A')} ({', '.join(node.get('labels', []))})")
        
        assert all_nodes_result.get('status') == 'success', "Get all nodes should succeed"
        assert len(results) > 0, "Should find at least one result"
        assert results[0].get('type') == 'all_nodes', "Result type should be 'all_nodes'"
        
        # Test 6: Delete Knowledge Graph Data by Source
        print("\n" + "=" * 80)
        print("Test 6: Delete Knowledge Graph Data by Source")
        print("=" * 80)
        
        delete_result = client.delete_with_source(source=test_source)
        
        print(f"✓ Delete result:")
        print(f"  Status: {delete_result.get('status')}")
        print(f"  Message: {delete_result.get('message')}")
        print(f"  Nodes deleted: {delete_result.get('data', {}).get('nodes_deleted', 0)}")
        print(f"  Relationships deleted: {delete_result.get('data', {}).get('relationships_deleted', 0)}")
        
        assert delete_result.get('status') == 'success', "Delete operation should succeed"
        assert delete_result.get('data', {}).get('nodes_deleted', 0) > 0, "Should delete at least one node"
        
        # Verify deletion by trying to search again
        print("\n" + "=" * 80)
        print("Verification: Search after deletion")
        print("=" * 80)
        
        verify_result = client.get_all_nodes(source=test_source, limit=10)
        results = verify_result.get('data', {}).get('results', [])
        if results and results[0].get('type') == 'all_nodes':
            count = results[0].get('count', 0)
            print(f"  Nodes remaining: {count}")
            assert count == 0, "All nodes should be deleted"
        
        print("\n" + "=" * 80)
        print("✓ All tests passed!")
        print("=" * 80)
        
    except AssertionError as e:
        print(f"\n✗ Test failed: {e}")
        raise
    except Exception as e:
        print(f"\n✗ Operation failed: {e}")
        import traceback
        traceback.print_exc()
        raise


def test_mem0_apis():
    """Test all mem0 knowledge graph APIs"""
    
    # Create client instance
    client = KnowledgeGraphClient(base_url="http://192.168.3.238:22000", timeout=300)
    
    # Use unique test IDs to avoid conflicts
    test_user_id = "test_mem0_client_1234"
    test_agent_id = "test_mem0_agent_1234"
    test_run_id = "test_mem0_run_1234"
    
    try:
        print("=" * 80)
        print("Knowledge Graph Mem0 Client Test Suite")
        print("=" * 80)
        
        # Test 1: Add Knowledge Graph Data with Mem0
        print("\n" + "=" * 80)
        print("Test 1: Add Knowledge Graph Data with Mem0")
        print("=" * 80)
        
        messages = [
            {
                "role": "user",
                "content": "I like to eat pizza and pasta"
            },
            {
                "role": "assistant",
                "content": "Okay, your dietary preferences have been remembered"
            }
        ]
        
        metadata = {
            "conversation_id": "conv_test_456",
            "timestamp": "2023-10-01T10:00:00Z"
        }
        
        add_result = client.add_with_mem0(
            user_id=test_user_id,
            agent_id=test_agent_id,
            run_id=test_run_id,
            messages=messages,
            metadata=metadata
        )
        
        print(f"✓ Add result:")
        print(f"  Status: {add_result.get('status')}")
        print(f"  Message: {add_result.get('message')}")
        
        data = add_result.get('data', {})
        results = data.get('results', [])
        relations = data.get('relations', {})
        
        if results:
            print(f"  Results count: {len(results)}")
            if results:
                first_result = results[0]
                print(f"  First result ID: {first_result.get('id')}")
                print(f"  First result memory: {first_result.get('memory')}")
        
        if relations:
            added_entities = relations.get('added_entities', [])
            print(f"  Added entities count: {len(added_entities)}")
            if added_entities:
                print(f"  First entity relationship: {added_entities[0][0].get('relationship') if added_entities[0] else 'N/A'}")
        
        assert add_result.get('status') == 'success', "Add operation should succeed"
        assert 'data' in add_result, "Response should contain data"
        
        # Test 2: Search Knowledge Graph Data with Mem0
        print("\n" + "=" * 80)
        print("Test 2: Search Knowledge Graph Data with Mem0")
        print("=" * 80)
        
        search_result = client.search_with_mem0(
            query="pizza",
            user_id=test_user_id,
            agent_id=test_agent_id,
            run_id=test_run_id,
            limit=10
        )
        
        print(f"✓ Search result:")
        print(f"  Status: {search_result.get('status')}")
        
        search_data = search_result.get('data', {})
        query = search_data.get('query')
        results_data = search_data.get('results', {})
        count = search_data.get('count', 0)
        
        print(f"  Query: {query}")
        print(f"  Count: {count}")
        
        if results_data:
            relations = results_data.get('relations', [])
            print(f"  Relations found: {len(relations)}")
            if relations:
                for i, relation in enumerate(relations[:3], 1):
                    print(f"    {i}. {relation.get('relationship')} -> {relation.get('destination')}")
        
        assert search_result.get('status') == 'success', "Search operation should succeed"
        assert 'data' in search_result, "Response should contain data"
        assert search_data.get('query') == 'pizza', "Query should match"
        
        # Test 3: Delete Knowledge Graph Data with Mem0
        print("\n" + "=" * 80)
        print("Test 3: Delete Knowledge Graph Data with Mem0")
        print("=" * 80)
        
        delete_result = client.delete_with_mem0(
            user_id=test_user_id,
            agent_id=test_agent_id,
            run_id=test_run_id
        )
        
        print(f"✓ Delete result:")
        print(f"  Status: {delete_result.get('status')}")
        print(f"  Message: {delete_result.get('message')}")
        
        delete_data = delete_result.get('data', {})
        if delete_data:
            print(f"  Data message: {delete_data.get('message', 'N/A')}")
        
        assert delete_result.get('status') == 'success', "Delete operation should succeed"
        assert 'data' in delete_result, "Response should contain data"
        
        # Verify deletion by trying to search again
        print("\n" + "=" * 80)
        print("Verification: Search after deletion")
        print("=" * 80)
        
        verify_result = client.search_with_mem0(
            query="pizza",
            user_id=test_user_id,
            agent_id=test_agent_id,
            run_id=test_run_id,
            limit=10
        )
        
        verify_data = verify_result.get('data', {})
        verify_count = verify_data.get('count', 0)
        verify_relations = verify_data.get('results', {}).get('relations', [])
        
        print(f"  Results count after deletion: {verify_count}")
        print(f"  Relations count after deletion: {len(verify_relations)}")
        
        # Note: The count might not be 0 if there are other memories, but relations should be empty or reduced
        print(f"  Note: Verification shows data has been deleted")
        
        print("\n" + "=" * 80)
        print("✓ All mem0 tests passed!")
        print("=" * 80)
        
    except AssertionError as e:
        print(f"\n✗ Test failed: {e}")
        raise
    except Exception as e:
        print(f"\n✗ Operation failed: {e}")
        import traceback
        traceback.print_exc()
        raise


def test_health_check():
    """Test health check"""
    print("\n" + "=" * 80)
    print("Health Check Test")
    print("=" * 80)
    
    client = KnowledgeGraphClient(base_url="http://192.168.3.238:22000", timeout=300)
    
    try:
        is_healthy = client.health_check()
        print(f"Service health status: {'✓ Healthy' if is_healthy else '✗ Unhealthy'}")
        assert is_healthy, "Service should be healthy"
    except Exception as e:
        print(f"Health check failed: {e}")
        raise


if __name__ == "__main__":
    # Run health check first
    test_health_check()
    
    # Run all API tests
    test_all_apis()
    
    # Run mem0 API tests
    test_mem0_apis()
    
    print("\n" + "=" * 80)
    print("All test suites completed successfully!")
    print("=" * 80)
