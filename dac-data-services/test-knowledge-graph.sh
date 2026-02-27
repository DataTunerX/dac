#!/bin/bash


# clear db all nodes and relationships

## MATCH (n) DETACH DELETE n; 


# 1. Add Knowledge Graph Data with Source

curl -X POST "http://192.168.3.238:22000/knowledge_graph/add_with_source" \
-H "Content-Type: application/json" \
-d '{
    "source": "test_source_1",
    "clear_existing": false,
    "nodes": [
        {
            "id": "node_001",
            "name": "张三",
            "labels": ["Person", "Employee"],
            "properties": {
                "age": 30,
                "department": "技术部"
            }
        },
        {
            "id": "node_002",
            "name": "李四",
            "labels": ["Person", "Manager"],
            "properties": {
                "age": 35,
                "department": "技术部"
            }
        },
        {
            "id": "node_003",
            "name": "技术部",
            "labels": ["Department"],
            "properties": {
                "location": "北京"
            }
        }
    ],
    "relationships": [
        {
            "start": "node_001",
            "end": "node_002",
            "type": "REPORTS_TO",
            "properties": {
                "since": "2023-01-01"
            }
        },
        {
            "start": "node_001",
            "end": "node_003",
            "type": "BELONGS_TO",
            "properties": {}
        },
        {
            "start": "node_002",
            "end": "node_003",
            "type": "MANAGES",
            "properties": {}
        }
    ]
}' | jq .

# output
# {
#   "status": "success",
#   "message": "Knowledge graph data added successfully with source 'test_source_1'",
#   "data": {
#     "source": "test_source_1",
#     "nodes_count": 3,
#     "relationships_count": 3
#   }
# }






curl -X POST "http://192.168.3.238:22000/knowledge_graph/add_with_source" \
-H "Content-Type: application/json" \
-d '{
    "source": "test_source_1",
    "clear_existing": false,
    "nodes": [
        {
            "id": "node_001",
            "labels": ["Person", "Employee"],
            "properties": {
                "name": "张三",
                "age": 30,
                "department": "技术部"
            }
        },
        {
            "id": "node_002",
            "labels": ["Person", "Manager"],
            "properties": {
                "name": "李四",
                "age": 35,
                "department": "技术部"
            }
        },
        {
            "id": "node_003",
            "labels": ["Department"],
            "properties": {
                "name": "技术部",
                "location": "北京"
            }
        }
    ],
    "relationships": [
        {
            "start": "node_001",
            "end": "node_002",
            "type": "REPORTS_TO",
            "properties": {
                "since": "2023-01-01"
            }
        },
        {
            "start": "node_001",
            "end": "node_003",
            "type": "BELONGS_TO",
            "properties": {}
        },
        {
            "start": "node_002",
            "end": "node_003",
            "type": "MANAGES",
            "properties": {}
        }
    ]
}' | jq .


# 2. Search Knowledge Graph Data - By Node ID

curl -X POST "http://192.168.3.238:22000/knowledge_graph/search_with_source" \
-H "Content-Type: application/json" \
-d '{
    "source": "test_source_1",
    "node_id": "node_001",
    "limit": 10
}' | jq .

# output

# {
#   "status": "success",
#   "message": "Knowledge graph search completed for source 'test_source_1'",
#   "data": {
#     "source": "test_source_1",
#     "results": [
#       {
#         "type": "node",
#         "data": {
#           "name": "张三",
#           "id": "node_001",
#           "department": "技术部",
#           "age": 30,
#           "data_source": "test_source_1",
#           "labels": [
#             "Person",
#             "Employee"
#           ]
#         }
#       }
#     ]
#   }
# }


# 3. Search Knowledge Graph Data - By Label

curl -X POST "http://192.168.3.238:22000/knowledge_graph/search_with_source" \
-H "Content-Type: application/json" \
-d '{
    "source": "test_source_1",
    "label": "Person",
    "limit": 10
}' | jq .

# output

# {
#   "status": "success",
#   "message": "Knowledge graph search completed for source 'test_source_1'",
#   "data": {
#     "source": "test_source_1",
#     "results": [
#       {
#         "type": "nodes_by_label",
#         "data": [
#           {
#             "name": "张三",
#             "id": "node_001",
#             "department": "技术部",
#             "age": 30,
#             "data_source": "test_source_1",
#             "labels": [
#               "Person",
#               "Employee"
#             ]
#           },
#           {
#             "name": "李四",
#             "id": "node_002",
#             "department": "技术部",
#             "age": 35,
#             "data_source": "test_source_1",
#             "labels": [
#               "Person",
#               "Manager"
#             ]
#           }
#         ],
#         "count": 2
#       }
#     ]
#   }
# }


# 4. Search Knowledge Graph Data - By Property

curl -X POST "http://192.168.3.238:22000/knowledge_graph/search_with_source" \
-H "Content-Type: application/json" \
-d '{
    "source": "test_source_1",
    "property_name": "name",
    "property_value": "张三",
    "limit": 10
}' | jq .

# output

# {
#   "status": "success",
#   "message": "Knowledge graph search completed for source 'test_source_1'",
#   "data": {
#     "source": "test_source_1",
#     "results": [
#       {
#         "type": "nodes_by_property",
#         "data": [
#           {
#             "name": "张三",
#             "id": "node_001",
#             "department": "技术部",
#             "age": 30,
#             "data_source": "test_source_1",
#             "labels": [
#               "Person",
#               "Employee"
#             ]
#           }
#         ],
#         "count": 1
#       }
#     ]
#   }
# }


# 5. Search Knowledge Graph Data - All Nodes

curl -X POST "http://192.168.3.238:22000/knowledge_graph/search_with_source" \
-H "Content-Type: application/json" \
-d '{
    "source": "test_source_1",
    "limit": 10
}' | jq .

# output

{
  "status": "success",
  "message": "Knowledge graph search completed for source 'test_source_1'",
  "data": {
    "source": "test_source_1",
    "results": [
      {
        "type": "all_nodes",
        "data": [
          {
            "name": "张三",
            "id": "node_001",
            "department": "技术部",
            "age": 30,
            "data_source": "test_source_1",
            "labels": [
              "Person",
              "Employee"
            ]
          },
          {
            "name": "李四",
            "id": "node_002",
            "department": "技术部",
            "age": 35,
            "data_source": "test_source_1",
            "labels": [
              "Person",
              "Manager"
            ]
          },
          {
            "name": "技术部",
            "location": "北京",
            "id": "node_003",
            "data_source": "test_source_1",
            "labels": [
              "Department"
            ]
          }
        ],
        "count": 3
      }
    ]
  }
}


# empty data

# {
#   "status": "success",
#   "message": "Knowledge graph search completed for source 'test_source_1'",
#   "data": {
#     "source": "test_source_1",
#     "results": [
#       {
#         "type": "all_nodes",
#         "data": [],
#         "count": 0
#       }
#     ]
#   }
# }



# 6. Search Knowledge Graph Data - Vector Search (Semantic Search)

echo ""
echo "=========================================="
echo "6. Testing Vector Search (Semantic Search)"
echo "=========================================="
echo ""

# 6.1 Vector search with default parameters
curl -X POST "http://192.168.3.238:22000/knowledge_graph/search_with_source" \
-H "Content-Type: application/json" \
-d '{
    "source": "test_source_1",
    "query_text": "技术部门的管理人员",
    "top_k": 5,
    "include_relationships": true,
    "relationship_depth": 1
}' | jq .

# output example:
# {
#   "status": "success",
#   "message": "Knowledge graph search completed for source 'test_source_1'",
#   "data": {
#     "source": "test_source_1",
#     "results": [
#       {
#         "type": "vector_search",
#         "query": "技术部门的管理人员",
#         "result": "李四是技术部门的管理人员",
#         "nodes": [
#           {
#             "id": "node_002",
#             "labels": ["Person", "Manager"],
#             "properties": {
#               "name": "李四",
#               "age": 35,
#               "department": "技术部",
#               "data_source": "test_source_1",
#               "embedding": [...]
#             },
#             "similarity_score": 0.85
#           }
#         ],
#         "relationships": [
#           {
#             "start_id": "node_002",
#             "start_labels": ["Person", "Manager"],
#             "end_id": "node_003",
#             "end_labels": ["Department"],
#             "type": "MANAGES",
#             "properties": {
#               "data_source": "test_source_1"
#             }
#           }
#         ],
#         "count": 1
#       }
#     ]
#   }
# }

echo ""
echo "---"

# 6.1.1 Vector search with return_svo_only (returns only SVO string format)
echo "Testing Vector Search with return_svo_only=true"
curl -X POST "http://192.168.3.238:22000/knowledge_graph/search_with_source" \
-H "Content-Type: application/json" \
-d '{
    "source": "test_source_1",
    "query_text": "技术部门的管理人员",
    "top_k": 5,
    "include_relationships": true,
    "relationship_depth": 1,
    "return_svo_only": true
}' | jq .

# output example:
# {
#   "status": "success",
#   "message": "Knowledge graph search completed for source 'test_source_1'",
#   "data": {
#     "type": "vector_search",
#     "source": "test_source_1",
#     "result": "李四 MANAGES 技术部\n张三 WORKS_IN 技术部",
#     "query": "技术部门的管理人员",
#     "count": 2
#   }
# }

echo ""
echo "---"

# 6.2 Vector search without relationships
curl -X POST "http://192.168.3.238:22000/knowledge_graph/search_with_source" \
-H "Content-Type: application/json" \
-d '{
    "source": "test_source_1",
    "query_text": "员工信息",
    "top_k": 10,
    "include_relationships": false,
    "relationship_depth": 0
}' | jq .

# output example:
# {
#   "status": "success",
#   "message": "Knowledge graph search completed for source 'test_source_1'",
#   "data": {
#     "source": "test_source_1",
#     "results": [
#       {
#         "type": "vector_search",
#         "query": "员工信息",
#         "nodes": [
#           {
#             "id": "node_001",
#             "labels": ["Person", "Employee"],
#             "properties": {...},
#             "similarity_score": 0.92
#           }
#         ],
#         "relationships": [],
#         "count": 1
#       }
#     ]
#   }
# }

echo ""
echo "---"

# 6.3 Vector search with deeper relationship depth
curl -X POST "http://192.168.3.238:22000/knowledge_graph/search_with_source" \
-H "Content-Type: application/json" \
-d '{
    "source": "test_source_1",
    "query_text": "部门组织结构",
    "top_k": 5,
    "include_relationships": true,
    "relationship_depth": 2
}' | jq .

# output example:
# {
#   "status": "success",
#   "message": "Knowledge graph search completed for source 'test_source_1'",
#   "data": {
#     "source": "test_source_1",
#     "results": [
#       {
#         "type": "vector_search",
#         "query": "部门组织结构",
#         "nodes": [
#           {
#             "id": "node_003",
#             "labels": ["Department"],
#             "properties": {...},
#             "similarity_score": 0.88
#           }
#         ],
#         "relationships": [
#           {
#             "start_id": "node_001",
#             "end_id": "node_003",
#             "type": "BELONGS_TO",
#             ...
#           },
#           {
#             "start_id": "node_002",
#             "end_id": "node_003",
#             "type": "MANAGES",
#             ...
#           }
#         ],
#         "count": 1
#       }
#     ]
#   }
# }

echo ""
echo "=========================================="
echo ""


# 7. Test Deduplication - Add nodes with same name but different IDs

echo ""
echo "=========================================="
echo "7. Testing Deduplication by Name"
echo "=========================================="
echo ""

# 7.1 First, add a node with name "张三"
curl -X POST "http://192.168.3.238:22000/knowledge_graph/add_with_source" \
-H "Content-Type: application/json" \
-d '{
    "source": "test_dedup",
    "clear_existing": true,
    "nodes": [
        {
            "id": "original_zhangsan",
            "labels": ["Person"],
            "properties": {
                "name": "张三",
                "age": 30,
                "department": "技术部"
            }
        }
    ],
    "relationships": []
}' | jq .

echo ""
echo "---"

# 7.2 Then add another node with different ID but same name - should merge
curl -X POST "http://192.168.3.238:22000/knowledge_graph/add_with_source" \
-H "Content-Type: application/json" \
-d '{
    "source": "test_dedup",
    "clear_existing": false,
    "nodes": [
        {
            "id": "duplicate_zhangsan",
            "labels": ["Person", "Employee"],
            "properties": {
                "name": "张三",
                "age": 31,
                "email": "zhangsan@example.com"
            }
        }
    ],
    "relationships": []
}' | jq .

# Expected: The second node should be merged into the first one
# The result should show nodes_updated: 1 and node_id_mapping

echo ""
echo "---"

# 7.3 Verify deduplication - search for nodes with name "张三"
curl -X POST "http://192.168.3.238:22000/knowledge_graph/search_with_source" \
-H "Content-Type: application/json" \
-d '{
    "source": "test_dedup",
    "property_name": "name",
    "property_value": "张三",
    "limit": 10
}' | jq .

# Expected: Should return only ONE node (the merged one), not two

echo ""
echo "---"

# 7.4 Test with relationships - add nodes with same name and relationships
curl -X POST "http://192.168.3.238:22000/knowledge_graph/add_with_source" \
-H "Content-Type: application/json" \
-d '{
    "source": "test_dedup_rel",
    "clear_existing": true,
    "nodes": [
        {
            "id": "person_a",
            "labels": ["Person"],
            "properties": {
                "name": "王五",
                "age": 25
            }
        },
        {
            "id": "person_b",
            "labels": ["Person"],
            "properties": {
                "name": "赵六",
                "age": 28
            }
        }
    ],
    "relationships": [
        {
            "start": "person_a",
            "end": "person_b",
            "type": "KNOWS",
            "properties": {}
        }
    ]
}' | jq .

echo ""
echo "---"

# 7.5 Add duplicate node with same name but different ID, with relationship
curl -X POST "http://192.168.3.238:22000/knowledge_graph/add_with_source" \
-H "Content-Type: application/json" \
-d '{
    "source": "test_dedup_rel",
    "clear_existing": false,
    "nodes": [
        {
            "id": "person_a_duplicate",
            "labels": ["Person", "Employee"],
            "properties": {
                "name": "王五",
                "age": 26,
                "email": "wangwu@example.com"
            }
        },
        {
            "id": "person_c",
            "labels": ["Person"],
            "properties": {
                "name": "孙七",
                "age": 30
            }
        }
    ],
    "relationships": [
        {
            "start": "person_a_duplicate",
            "end": "person_c",
            "type": "KNOWS",
            "properties": {
                "since": "2024-01-01"
            }
        }
    ]
}' | jq .

# Expected: person_a_duplicate should merge into person_a
# The relationship should be created between person_a and person_c

echo ""
echo "---"

# 7.6 Verify relationships are correctly mapped
curl -X POST "http://192.168.3.238:22000/knowledge_graph/search_with_source" \
-H "Content-Type: application/json" \
-d '{
    "source": "test_dedup_rel",
    "property_name": "name",
    "property_value": "王五",
    "limit": 10
}' | jq .

echo ""
echo "=========================================="
echo ""


# 8. Test Node Name Field Support (name at node level vs in properties)

echo ""
echo "=========================================="
echo "8. Testing Node Name Field Support"
echo "=========================================="
echo ""

# 8.1 Add node with name at node level
curl -X POST "http://192.168.3.238:22000/knowledge_graph/add_with_source" \
-H "Content-Type: application/json" \
-d '{
    "source": "test_node_name",
    "clear_existing": true,
    "nodes": [
        {
            "id": "node_name_level",
            "name": "张三",
            "labels": ["Person"],
            "properties": {
                "age": 30,
                "department": "技术部"
            }
        }
    ],
    "relationships": []
}' | jq .

# Expected: Node should be created with name at node level

echo ""
echo "---"

# 8.2 Add duplicate node with same name at node level (should merge)
curl -X POST "http://192.168.3.238:22000/knowledge_graph/add_with_source" \
-H "Content-Type: application/json" \
-d '{
    "source": "test_node_name",
    "clear_existing": false,
    "nodes": [
        {
            "id": "node_name_level_dup",
            "name": "张三",
            "labels": ["Person", "Employee"],
            "properties": {
                "age": 31,
                "email": "zhangsan@example.com"
            }
        }
    ],
    "relationships": []
}' | jq .

# Expected: Should merge into node_name_level, return nodes_updated: 1

echo ""
echo "---"

# 8.3 Verify deduplication - should only have 1 node
curl -X POST "http://192.168.3.238:22000/knowledge_graph/search_with_source" \
-H "Content-Type: application/json" \
-d '{
    "source": "test_node_name",
    "property_name": "name",
    "property_value": "张三",
    "limit": 10
}' | jq .

# Expected: Should return only 1 node (the merged one)

echo ""
echo "---"

# 8.4 Test name in properties (traditional way)
curl -X POST "http://192.168.3.238:22000/knowledge_graph/add_with_source" \
-H "Content-Type: application/json" \
-d '{
    "source": "test_node_name_props",
    "clear_existing": true,
    "nodes": [
        {
            "id": "node_name_props",
            "labels": ["Person"],
            "properties": {
                "name": "李四",
                "age": 35,
                "department": "技术部"
            }
        }
    ],
    "relationships": []
}' | jq .

# Expected: Node should be created with name in properties

echo ""
echo "---"

# 8.5 Test mixed: name in properties can deduplicate with name at node level
curl -X POST "http://192.168.3.238:22000/knowledge_graph/add_with_source" \
-H "Content-Type: application/json" \
-d '{
    "source": "test_node_name_mixed",
    "clear_existing": true,
    "nodes": [
        {
            "id": "node_props_name",
            "labels": ["Person"],
            "properties": {
                "name": "王五",
                "age": 25
            }
        }
    ],
    "relationships": []
}' | jq .

echo ""
echo "---"

# Add node with name at node level, same name (should merge)
curl -X POST "http://192.168.3.238:22000/knowledge_graph/add_with_source" \
-H "Content-Type: application/json" \
-d '{
    "source": "test_node_name_mixed",
    "clear_existing": false,
    "nodes": [
        {
            "id": "node_level_name",
            "name": "王五",
            "labels": ["Person", "Employee"],
            "properties": {
                "age": 26,
                "email": "wangwu@example.com"
            }
        }
    ],
    "relationships": []
}' | jq .

# Expected: Should merge into node_props_name

echo ""
echo "---"

# Verify mixed deduplication
curl -X POST "http://192.168.3.238:22000/knowledge_graph/search_with_source" \
-H "Content-Type: application/json" \
-d '{
    "source": "test_node_name_mixed",
    "property_name": "name",
    "property_value": "王五",
    "limit": 10
}' | jq .

# Expected: Should return only 1 node (the merged one)

echo ""
echo "=========================================="
echo ""


# 9. Delete Knowledge Graph Data by Source

curl -X DELETE "http://192.168.3.238:22000/knowledge_graph/delete_with_source" \
-H "Content-Type: application/json" \
-d '{
    "source": "test_source_1"
}' | jq .

# output

# {
#   "status": "success",
#   "message": "Knowledge graph data deleted successfully for source 'test_source_1'",
#   "data": {
#     "source": "test_source_1",
#     "nodes_deleted": 3,
#     "relationships_deleted": 3
#   }
# }


# 8. Add Another Source Data

curl -X POST "http://192.168.3.238:22000/knowledge_graph/add_with_source" \
-H "Content-Type: application/json" \
-d '{
    "source": "test_source_2",
    "clear_existing": false,
    "nodes": [
        {
            "id": "node_101",
            "labels": ["Product"],
            "properties": {
                "name": "产品A",
                "price": 1000
            }
        },
        {
            "id": "node_102",
            "labels": ["Product"],
            "properties": {
                "name": "产品B",
                "price": 2000
            }
        }
    ],
    "relationships": [
        {
            "start": "node_101",
            "end": "node_102",
            "type": "RELATED_TO",
            "properties": {
                "relation_type": "complementary"
            }
        }
    ]
}' | jq .

# output
# {
#   "status": "success",
#   "message": "Knowledge graph data added successfully with source 'test_source_2'",
#   "data": {
#     "source": "test_source_2",
#     "nodes_count": 2,
#     "relationships_count": 1
#   }
# }

# 9. Verify Source Isolation - Search test_source_2

curl -X POST "http://192.168.3.238:22000/knowledge_graph/search_with_source" \
-H "Content-Type: application/json" \
-d '{
    "source": "test_source_2",
    "label": "Product",
    "limit": 10
}' | jq .

# output

# {
#   "status": "success",
#   "message": "Knowledge graph search completed for source 'test_source_2'",
#   "data": {
#     "source": "test_source_2",
#     "results": [
#       {
#         "type": "nodes_by_label",
#         "data": [
#           {
#             "price": 1000,
#             "name": "产品A",
#             "id": "node_101",
#             "data_source": "test_source_2",
#             "labels": [
#               "Product"
#             ]
#           },
#           {
#             "price": 2000,
#             "name": "产品B",
#             "id": "node_102",
#             "data_source": "test_source_2",
#             "labels": [
#               "Product"
#             ]
#           }
#         ],
#         "count": 2
#       }
#     ]
#   }
# }


# 10. Clean Up - Delete test_source_2

curl -X DELETE "http://192.168.3.238:22000/knowledge_graph/delete_with_source" \
-H "Content-Type: application/json" \
-d '{
    "source": "test_source_2"
}' | jq .

# output
# {
#   "status": "success",
#   "message": "Knowledge graph data deleted successfully for source 'test_source_2'",
#   "data": {
#     "source": "test_source_2",
#     "nodes_deleted": 2,
#     "relationships_deleted": 1
#   }
# }




11. mem0 add 



curl -X POST "http://192.168.3.238:22000/knowledge_graph_mem0" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "test1234",
    "agent_id": "test1234",
    "run_id": "test1234",
    "messages": [
      {
        "role": "user",
        "content": "I like to eat pizza and pasta"
      },
      {
        "role": "assistant",
        "content": "Okay, your dietary preferences have been remembered"
      }
    ],
    "metadata": {
      "conversation_id": "conv_456",
      "timestamp": "2023-10-01T10:00:00Z"
    }
  }' | jq .


# Output:

{
  "status": "success",
  "message": "knowledge graph added successfully",
  "data": {
    "results": [
        {
          "id": "276c397f-90c5-4ca2-8d39-eba0462915b9",
          "memory": "Likes to eat pizza and pasta",
          "hash": "1fa6211ecb07b77eede443e4b82829f0",
          "metadata": {
            "conversation_id": "conv_456"
          },
          "score": 0.2985008181035018,
          "created_at": "2025-09-18T05:38:36.042830-07:00",
          "updated_at": null,
          "user_id": "user1",
          "agent_id": "assistant_001",
          "run_id": "run_123456"
        }
      ]
    "relations": {
      "deleted_entities": [],
      "added_entities": [
        [
          {
            "source": "user_id:_test1234,_agent_id:_test1234,_run_id:_test1234",
            "relationship": "likes_to_eat",
            "target": "pizza"
          }
        ],
        [
          {
            "source": "user_id:_test1234,_agent_id:_test1234,_run_id:_test1234",
            "relationship": "likes_to_eat",
            "target": "pasta"
          }
        ]
      ]
    }
  }
}

12. mem0 search


curl -X POST "http://192.168.3.238:22000/knowledge_graph_mem0/search" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "pizza",
    "user_id": "test1234",
    "agent_id": "test1234",
    "run_id": "test1234",
    "limit": 10
  }' | jq .


# output：

{
  "status": "success",
  "data": {
    "query": "pizza",
    "results": {
      "results": [],
      "relations": [
        {
          "source": "user_id:_test1234,_agent_id:_test1234,_run_id:_test1234",
          "relationship": "likes_to_eat",
          "destination": "pizza"
        }
      ]
    },
    "count": 2
  }
}



13. mem0 delete 

curl -X POST "http://192.168.3.238:22000/knowledge_graph_mem0/delete" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "test1234",
    "agent_id": "test1234",
    "run_id": "test1234"
  }' | jq .

