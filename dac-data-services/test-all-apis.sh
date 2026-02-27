#!/bin/bash

export DATA_SERVICES="http://192.168.3.7:22000"

# 测试所有 API 端点
# 服务器地址（可以从环境变量 DATA_SERVICES 读取，或使用默认值）

BASE_URL="http://192.168.3.7:26000"

# 测试统计
TOTAL_TESTS=0
PASSED_TESTS=0
FAILED_TESTS=0

# 存储测试中创建的 ID，用于后续测试
MEMORY_ID=""
SIG_ID=""
SEMANTIC_DOMAIN_ID=""
SEMANTIC_GROUP_ID=""
HISTORY_ID=""
VECTOR_COLLECTION="test_vector_$(date +%s)"
KNOWLEDGE_PYRAMID_COLLECTION="test_knowledge_pyramid_$(date +%s)"

echo "=========================================="
echo "Testing Data Services APIs"
echo "Server: $BASE_URL"
echo "=========================================="
echo ""

# 颜色定义
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# 检查服务器是否可达
echo -e "${BLUE}Checking server connectivity...${NC}"
if curl -s --connect-timeout 5 "$BASE_URL/" > /dev/null 2>&1; then
    echo -e "${GREEN}✓ Server is reachable${NC}"
else
    echo -e "${RED}✗ Cannot reach server at $BASE_URL${NC}"
    echo "Please ensure the server is running and accessible."
    exit 1
fi
echo ""

# 测试函数
test_api() {
    local method=$1
    local endpoint=$2
    local data=$3
    local description=$4
    local extract_id=$5  # 可选：从响应中提取 ID 的 JSON 路径，如 ".data.sig_id"
    
    TOTAL_TESTS=$((TOTAL_TESTS + 1))
    
    echo -e "${CYAN}[$TOTAL_TESTS]${NC} ${YELLOW}Testing: $description${NC}"
    echo "  Method: $method | Endpoint: $endpoint"
    
    local response
    local http_code
    local body
    
    if [ -z "$data" ]; then
        response=$(curl -s -w "\nHTTP_CODE:%{http_code}" --connect-timeout 10 -X "$method" "$BASE_URL$endpoint" 2>&1)
    else
        response=$(curl -s -w "\nHTTP_CODE:%{http_code}" --connect-timeout 10 -X "$method" "$BASE_URL$endpoint" \
            -H "Content-Type: application/json" \
            -d "$data" 2>&1)
    fi
    
    # 检查 curl 错误
    if echo "$response" | grep -q "curl:"; then
        echo -e "${RED}✗ Connection Error${NC}"
        echo "  $response"
        echo ""
        FAILED_TESTS=$((FAILED_TESTS + 1))
        return 1
    fi
    
    http_code=$(echo "$response" | grep "HTTP_CODE" | cut -d: -f2)
    body=$(echo "$response" | sed '/HTTP_CODE/d')
    
    if [ -z "$http_code" ]; then
        echo -e "${RED}✗ No HTTP response code received${NC}"
        echo "  Response: $body"
        echo ""
        FAILED_TESTS=$((FAILED_TESTS + 1))
        return 1
    fi
    
    # 提取 ID（如果指定）
    # extract_id 应该是变量名，如 "SIG_ID"，而不是 JSON 路径
    if [ -n "$extract_id" ] && [ -n "$body" ]; then
        if command -v jq > /dev/null 2>&1; then
            # 根据变量名确定 JSON 路径
            case "$extract_id" in
                "MEMORY_ID")
                    json_path=".data.results[0].id"
                    ;;
                "SIG_ID")
                    json_path=".data.sig_id"
                    ;;
                "SEMANTIC_DOMAIN_ID")
                    json_path=".data.semantic_domain_id"
                    ;;
                "SEMANTIC_GROUP_ID")
                    json_path=".data.id"
                    ;;
                "HISTORY_ID")
                    json_path=".hid"
                    ;;
                *)
                    json_path="$extract_id"
                    ;;
            esac
            extracted_id=$(echo "$body" | jq -r "$json_path" 2>/dev/null)
            if [ -n "$extracted_id" ] && [ "$extracted_id" != "null" ] && [ "$extracted_id" != "" ]; then
                eval "$extract_id=\"$extracted_id\""
                echo -e "${BLUE}  Extracted ID ($extract_id): $extracted_id${NC}"
            fi
        fi
    fi
    
    if [ "$http_code" -ge 200 ] && [ "$http_code" -lt 300 ]; then
        echo -e "${GREEN}✓ Success (HTTP $http_code)${NC}"
        if command -v jq > /dev/null 2>&1 && [ -n "$body" ]; then
            echo "$body" | jq . 2>/dev/null | head -20
            if [ $(echo "$body" | jq . 2>/dev/null | wc -l) -gt 20 ]; then
                echo "  ... (truncated)"
            fi
        else
            echo "  $body" | head -5
        fi
        PASSED_TESTS=$((PASSED_TESTS + 1))
    elif [ "$http_code" -ge 400 ] && [ "$http_code" -lt 500 ]; then
        echo -e "${YELLOW}⚠ Client Error (HTTP $http_code)${NC}"
        if command -v jq > /dev/null 2>&1 && [ -n "$body" ]; then
            echo "$body" | jq . 2>/dev/null
        else
            echo "  $body"
        fi
        # 某些 4xx 错误可能是预期的（如验证错误），不算失败
        FAILED_TESTS=$((FAILED_TESTS + 1))
    elif [ "$http_code" -ge 500 ]; then
        echo -e "${RED}✗ Server Error (HTTP $http_code)${NC}"
        if command -v jq > /dev/null 2>&1 && [ -n "$body" ]; then
            echo "$body" | jq . 2>/dev/null
        else
            echo "  $body"
        fi
        FAILED_TESTS=$((FAILED_TESTS + 1))
    else
        echo -e "${RED}✗ Unexpected Status (HTTP $http_code)${NC}"
        echo "  $body"
        FAILED_TESTS=$((FAILED_TESTS + 1))
    fi
    echo ""
}

# ==========================================
# 1. Basic Endpoints
# ==========================================
echo -e "${BLUE}==========================================${NC}"
echo -e "${BLUE}1. Basic Endpoints${NC}"
echo -e "${BLUE}==========================================${NC}"
test_api "GET" "/" "" "Root endpoint"
test_api "GET" "/info" "" "Info endpoint"
echo ""

# ==========================================
# 2. Memory APIs
# ==========================================
echo -e "${BLUE}==========================================${NC}"
echo -e "${BLUE}2. Memory APIs${NC}"
echo -e "${BLUE}==========================================${NC}"

# 2.1 Add Memory (user_id only)
test_api "POST" "/memories" '{
    "user_id": "test_user_1",
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
}' "Add memory (user_id only)" "MEMORY_ID"

# 2.2 Add another memory for same user
test_api "POST" "/memories" '{
    "user_id": "test_user_1",
    "messages": [
        {
            "role": "user",
            "content": "I like basketball and table tennis"
        },
        {
            "role": "assistant",
            "content": "Okay, your preferences have been remembered"
        }
    ],
    "metadata": {
        "conversation_id": "conv_456",
        "timestamp": "2023-10-01T10:00:00Z"
    }
}' "Add memory (basketball)" "MEMORY_ID"

# 2.3 Add memory with agent_id
test_api "POST" "/memories" '{
    "agent_id": "test_agent_1",
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
        "conversation_id": "conv_789",
        "timestamp": "2023-10-01T11:00:00Z"
    }
}' "Add memory (agent_id)" "MEMORY_ID"

# 2.4 Get all memories by user_id
test_api "POST" "/memories/get_all" '{
    "user_id": "test_user_1",
    "limit": 10
}' "Get all memories by user_id"

# 2.5 Get all memories by agent_id
test_api "POST" "/memories/get_all" '{
    "agent_id": "test_agent_1",
    "limit": 10
}' "Get all memories by agent_id"

# 2.6 Search memories
test_api "POST" "/memories/search" '{
    "user_id": "test_user_1",
    "query": "pizza",
    "limit": 5
}' "Search memories by query"

# 2.7 Get memory by ID (if we have one)
if [ -n "$MEMORY_ID" ]; then
    test_api "GET" "/memories/$MEMORY_ID" "" "Get memory by ID"
fi

# 2.8 Get memory history
if [ -n "$MEMORY_ID" ]; then
    test_api "GET" "/memories/$MEMORY_ID/history" "" "Get memory history"
fi

echo ""

# ==========================================
# 3. Signature APIs
# ==========================================
echo -e "${BLUE}==========================================${NC}"
echo -e "${BLUE}3. Signature APIs${NC}"
echo -e "${BLUE}==========================================${NC}"

# 3.1 Create Signature
test_api "POST" "/signatures" '{
    "sig_type": "application",
    "discovery_mode": "auto",
    "fingerprint": "fp_test_001",
    "location_info": {
        "ip": "192.168.1.100",
        "url": "https://example.com"
    },
    "metadata_content": {
        "summary": "Test signature summary",
        "type": "test"
    },
    "dd_namespace": "test_namespace",
    "dd_name": "test_name"
}' "Create signature" "SIG_ID"

# 3.2 Batch Create Signatures
test_api "POST" "/signatures/batch" '[
    {
        "sig_type": "database",
        "discovery_mode": "manual",
        "fingerprint": "fp_test_002",
        "location_info": {
            "ip": "192.168.1.101"
        },
        "metadata_content": {
            "summary": "Signature summary 2"
        },
        "dd_namespace": "namespace2",
        "dd_name": "name2"
    },
    {
        "sig_type": "api",
        "discovery_mode": "auto",
        "fingerprint": "fp_test_003",
        "location_info": {
            "url": "https://api.example.com"
        },
        "metadata_content": {
            "summary": "Signature summary 3"
        },
        "dd_namespace": "namespace3",
        "dd_name": "name3"
    }
]' "Batch create signatures"

# 3.3 Get signature by sig_id
if [ -n "$SIG_ID" ]; then
    test_api "GET" "/signatures/$SIG_ID" "" "Get signature by sig_id"
fi

# 3.4 Get signature by fingerprint
test_api "GET" "/signatures/fingerprint/fp_test_001" "" "Get signature by fingerprint"

# 3.5 Search by DD Info
test_api "POST" "/signatures/search/by-dd" '{
    "dd_namespace": "test_namespace",
    "dd_name": "test_name"
}' "Search signatures by DD info"

# 3.6 Update signature
if [ -n "$SIG_ID" ]; then
    test_api "PUT" "/signatures/$SIG_ID" '{
        "fingerprint": "fp_test_001_updated",
        "metadata_content": {
            "summary": "Updated signature summary"
        }
    }' "Update signature"
fi

# 3.7 Check signature exists
if [ -n "$SIG_ID" ]; then
    test_api "GET" "/signatures/$SIG_ID/exists" "" "Check signature exists"
fi

# 3.8 Get signature status count
test_api "GET" "/signatures/status/count" "" "Get signature status count"

echo ""

# ==========================================
# 4. Semantic Domain APIs
# ==========================================
echo -e "${BLUE}==========================================${NC}"
echo -e "${BLUE}4. Semantic Domain APIs${NC}"
echo -e "${BLUE}==========================================${NC}"

# 4.1 Create Semantic Domain
test_api "POST" "/semantic_domains" '{
    "semantic_domain": "This is a test semantic domain for application services",
    "agent_card": "{\"name\": \"test_agent\", \"description\": \"Test agent for semantic domain\"}",
    "dd_namespace": "test_namespace",
    "dd_name": "test_name"
}' "Create semantic domain" "SEMANTIC_DOMAIN_ID"

# 4.2 Batch Create Semantic Domains
test_api "POST" "/semantic_domains/batch" '[
    {
        "semantic_domain": "Semantic domain for database services",
        "agent_card": "{\"name\": \"db_agent\", \"type\": \"database\"}",
        "dd_namespace": "namespace2",
        "dd_name": "name2"
    },
    {
        "semantic_domain": "Semantic domain for API services",
        "agent_card": "{\"name\": \"api_agent\", \"type\": \"api\"}",
        "dd_namespace": "namespace3",
        "dd_name": "name3"
    }
]' "Batch create semantic domains"

# 4.3 Get semantic domain by ID
if [ -n "$SEMANTIC_DOMAIN_ID" ]; then
    test_api "GET" "/semantic_domains/$SEMANTIC_DOMAIN_ID" "" "Get semantic domain by ID"
fi

# 4.4 Search by DD Info
test_api "POST" "/semantic_domains/search/by-dd" '{
    "dd_namespace": "test_namespace",
    "dd_name": "test_name"
}' "Search semantic domains by DD info"

# 4.5 Update semantic domain
if [ -n "$SEMANTIC_DOMAIN_ID" ]; then
    test_api "PUT" "/semantic_domains/$SEMANTIC_DOMAIN_ID" '{
        "semantic_domain": "Updated semantic domain",
        "agent_card": "{\"name\": \"updated_agent\"}"
    }' "Update semantic domain"
fi

# 4.6 Check semantic domain exists
if [ -n "$SEMANTIC_DOMAIN_ID" ]; then
    test_api "GET" "/semantic_domains/$SEMANTIC_DOMAIN_ID/exists" "" "Check semantic domain exists"
fi

# 4.7 Get semantic domain status count
test_api "GET" "/semantic_domains/status/count" "" "Get semantic domain status count"

echo ""

# ==========================================
# 5. Semantic Group APIs
# ==========================================
echo -e "${BLUE}==========================================${NC}"
echo -e "${BLUE}5. Semantic Group APIs${NC}"
echo -e "${BLUE}==========================================${NC}"

# 5.1 Create Semantic Group
test_api "POST" "/semantic_groups" '{
    "group_name": "AI模型应用与服务管理平台",
    "description": "这是一个用于管理AI模型应用和服务的平台组",
    "agent_card": "Agent card information",
    "version": "v1.0"
}' "Create semantic group" "SEMANTIC_GROUP_ID"

# 5.2 Batch Create Semantic Groups
test_api "POST" "/semantic_groups/batch" '[
    {
        "group_name": "数据库服务组",
        "description": "管理所有数据库相关的服务",
        "agent_card": "Database service agent card",
        "version": "v1.0"
    },
    {
        "group_name": "API服务组",
        "description": "管理所有API相关的服务",
        "agent_card": "API service agent card",
        "version": "v1.0"
    }
]' "Batch create semantic groups"

# 5.3 Get semantic group by ID
if [ -n "$SEMANTIC_GROUP_ID" ]; then
    test_api "GET" "/semantic_groups/$SEMANTIC_GROUP_ID" "" "Get semantic group by ID"
fi

# 5.3.1 Get semantic group with members (group + member semantic domain details)
if [ -n "$SEMANTIC_GROUP_ID" ]; then
    test_api "GET" "/semantic_groups/$SEMANTIC_GROUP_ID/with_members" "" "Get semantic group with members"
fi

# 5.4 Get all semantic groups
test_api "GET" "/semantic_groups" "" "Get all semantic groups"

# 5.5 Get all semantic groups with pagination
test_api "GET" "/semantic_groups?page=1&page_size=2" "" "Get all semantic groups (paginated)"

# 5.6 Update semantic group
if [ -n "$SEMANTIC_GROUP_ID" ]; then
    test_api "PUT" "/semantic_groups/$SEMANTIC_GROUP_ID" '{
        "group_name": "更新后的AI模型应用与服务管理平台",
        "description": "这是更新后的描述",
        "version": "v2.0"
    }' "Update semantic group"
fi

# 5.7 Check semantic group exists
if [ -n "$SEMANTIC_GROUP_ID" ]; then
    test_api "GET" "/semantic_groups/$SEMANTIC_GROUP_ID/exists" "" "Check semantic group exists"
fi

# 5.8 Get semantic group status count
test_api "GET" "/semantic_groups/status/count" "" "Get semantic group status count"

# 5.9 Create DD Group Relation
if [ -n "$SEMANTIC_DOMAIN_ID" ] && [ -n "$SEMANTIC_GROUP_ID" ]; then
    test_api "POST" "/dd_group_relations" "{
        \"sd_id\": \"$SEMANTIC_DOMAIN_ID\",
        \"group_id\": \"$SEMANTIC_GROUP_ID\",
        \"association_reason\": \"语义相似性分析：两个DD在业务领域和功能上高度相关\"
    }" "Create DD group relation"
fi

# 5.10 Get relations by group_id
if [ -n "$SEMANTIC_GROUP_ID" ]; then
    test_api "GET" "/dd_group_relations/group/$SEMANTIC_GROUP_ID" "" "Get relations by group_id"
fi

# 5.11 Get relations by sd_id
if [ -n "$SEMANTIC_DOMAIN_ID" ]; then
    test_api "GET" "/dd_group_relations/sd/$SEMANTIC_DOMAIN_ID" "" "Get relations by sd_id"
fi

echo ""

# ==========================================
# 6. History APIs
# ==========================================
echo -e "${BLUE}==========================================${NC}"
echo -e "${BLUE}6. History APIs${NC}"
echo -e "${BLUE}==========================================${NC}"

# 6.1 Create history record
test_api "POST" "/history/create" '{
    "user_id": "test_user_001",
    "agent_id": "test_agent_001",
    "run_id": "test_run_001",
    "messages": [
        {
            "role": "user",
            "content": "I like pizza and pasta"
        },
        {
            "role": "assistant",
            "content": "Okay, I have remembered your dietary preferences",
            "think": "this is knowledge"
        }
    ]
}' "Create history record" "HISTORY_ID"

# 6.2 Create another history record
test_api "POST" "/history/create" '{
    "user_id": "test_user_001",
    "agent_id": "test_agent_001",
    "run_id": "test_run_001",
    "messages": [
        {
            "role": "user",
            "content": "I like playing basketball"
        },
        {
            "role": "assistant",
            "content": "Okay, I have remembered your preferences"
        }
    ]
}' "Create another history record" ".hid"

# 6.3 Search history
test_api "POST" "/history/search" '{
    "user_id": "test_user_001",
    "agent_id": "test_agent_001",
    "run_id": "test_run_001",
    "limit": 3
}' "Search history records"

# 6.4 Search history by user and run
test_api "POST" "/history/search_user_run" '{
    "user_id": "test_user_001",
    "run_id": "test_run_001",
    "limit": 10
}' "Search history by user and run"

echo ""

# ==========================================
# 7. Knowledge Graph APIs
# ==========================================
echo -e "${BLUE}==========================================${NC}"
echo -e "${BLUE}7. Knowledge Graph APIs${NC}"
echo -e "${BLUE}==========================================${NC}"

# 7.1 Add knowledge graph with source
test_api "POST" "/knowledge_graph/add_with_source" '{
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
}' "Add knowledge graph with source"

# 7.2 Search knowledge graph with source
test_api "POST" "/knowledge_graph/search_with_source" '{
    "source": "test_source_1",
    "query": "张三",
    "limit": 10
}' "Search knowledge graph with source"

# 7.2.1 Get graph by source (all nodes + all relationships)
test_api "POST" "/knowledge_graph/get_graph_by_source" '{
    "source": "test_source_1",
    "node_limit": 1000,
    "rel_limit": 1000
}' "Get graph by source"

# 7.3 Delete knowledge graph with source
test_api "DELETE" "/knowledge_graph/delete_with_source" '{
    "source": "test_source_1"
}' "Delete knowledge graph with source"

# 7.4 Create vector index
test_api "POST" "/knowledge_graph/create_vector_index" '' "Create vector index"

echo ""

# ==========================================
# 8. Vector APIs
# ==========================================
echo -e "${BLUE}==========================================${NC}"
echo -e "${BLUE}8. Vector APIs${NC}"
echo -e "${BLUE}==========================================${NC}"

# 8.1 Create vector collection
test_api "POST" "/vector/create_collection" "{
    \"collection_name\": \"$VECTOR_COLLECTION\",
    \"documents\": [
        {
            \"page_content\": \"Python is a popular programming language\",
            \"metadata\": {\"author\": \"Guido van Rossum\", \"year\": 1991}
        }
    ]
}" "Create vector collection"

# 8.2 Add documents to vector collection
test_api "POST" "/vector/$VECTOR_COLLECTION/add_documents" '{
    "documents": [
        {
            "page_content": "Machine learning is one of the core technologies of artificial intelligence",
            "metadata": {
                "category": "AI",
                "source": "Technical Documentation",
                "created_at": "2024-01-15"
            }
        },
        {
            "page_content": "Deep learning has made breakthrough progress in the field of image recognition",
            "metadata": {
                "category": "Deep Learning",
                "source": "Research Paper",
                "created_at": "2024-01-16"
            }
        }
    ]
}' "Add documents to vector collection"

# 8.3 Search vector collection
test_api "POST" "/vector/$VECTOR_COLLECTION/search" '{
    "query": "artificial intelligence",
    "search_type": "vector",
    "limit": 10,
    "hybrid_threshold": 0.1
}' "Search vector collection"

# 8.4 Delete vector collection
test_api "DELETE" "/vector/delete_collection" "{
    \"collection_name\": \"$VECTOR_COLLECTION\"
}" "Delete vector collection"

echo ""

# ==========================================
# 9. Knowledge Pyramid APIs
# ==========================================
echo -e "${BLUE}==========================================${NC}"
echo -e "${BLUE}9. Knowledge Pyramid APIs${NC}"
echo -e "${BLUE}==========================================${NC}"

# 9.1 Create knowledge pyramid collection
test_api "POST" "/knowledge_pyramid/create_collection" "{
    \"collection_name\": \"$KNOWLEDGE_PYRAMID_COLLECTION\",
    \"documents\": [
        {
            \"page_content\": \"Python is a popular programming language\",
            \"metadata\": {\"author\": \"Guido van Rossum\", \"year\": 1991}
        }
    ]
}" "Create knowledge pyramid collection"

# 9.2 Add documents to knowledge pyramid
test_api "POST" "/knowledge_pyramid/$KNOWLEDGE_PYRAMID_COLLECTION/add_documents" '{
    "documents": [
        {
            "page_content": "Machine learning is one of the core technologies of artificial intelligence",
            "metadata": {
                "category": "AI",
                "source": "Technical Documentation",
                "created_at": "2024-01-15"
            }
        },
        {
            "page_content": "Deep learning has made breakthrough progress in the field of image recognition",
            "metadata": {
                "category": "Deep Learning",
                "source": "Research Paper",
                "created_at": "2024-01-16"
            }
        }
    ]
}' "Add documents to knowledge pyramid"

# 9.3 Get all documents from knowledge pyramid
test_api "POST" "/knowledge_pyramid/$KNOWLEDGE_PYRAMID_COLLECTION/get_all" '{
    "limit": 10
}' "Get all documents from knowledge pyramid"

# 9.4 Search knowledge pyramid
test_api "POST" "/knowledge_pyramid/$KNOWLEDGE_PYRAMID_COLLECTION/search" '{
    "query": "machine learning",
    "search_type": "vector",
    "limit": 10,
    "hybrid_threshold": 0.1,
    "vector_weight": 0.5,
    "fulltext_weight": 0.5
}' "Search knowledge pyramid"

# 9.5 Delete knowledge pyramid collection
test_api "DELETE" "/knowledge_pyramid/delete_collection" "{
    \"collection_name\": \"$KNOWLEDGE_PYRAMID_COLLECTION\"
}" "Delete knowledge pyramid collection"

echo ""

# ==========================================
# Test Summary
# ==========================================
echo -e "${BLUE}==========================================${NC}"
echo -e "${BLUE}Test Summary${NC}"
echo -e "${BLUE}==========================================${NC}"
echo -e "Total Tests: ${CYAN}$TOTAL_TESTS${NC}"
echo -e "${GREEN}Passed: $PASSED_TESTS${NC}"
echo -e "${RED}Failed: $FAILED_TESTS${NC}"

if [ $FAILED_TESTS -eq 0 ]; then
    echo -e "${GREEN}All tests passed!${NC}"
    exit 0
else
    echo -e "${RED}Some tests failed.${NC}"
    exit 1
fi
