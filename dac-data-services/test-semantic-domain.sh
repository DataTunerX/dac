#!/bin/bash

# Semantic Domain API 手测（与 data-services 路由与模型一致；含 descriptor_type、version）
#
# dac-data-services 为代理：若进程设置了 DATA_DESCRIPTOR 且非空，每条请求需带校验头，例如：
#   -H "Data-Descriptor: <与 DATA_DESCRIPTOR 环境变量相同的字符串>"
# 未设置 DATA_DESCRIPTOR 时服务端跳过该校验。

# 1. Create Semantic Domain

curl -X POST "http://192.168.3.238:22000/semantic_domains" \
-H "Content-Type: application/json" \
-d '{
    "semantic_domain": "This is a test semantic domain for application services",
    "agent_card": "{\"name\": \"test_agent\", \"description\": \"Test agent for semantic domain\"}",
    "dd_namespace": "test_namespace",
    "dd_name": "test_name",
    "descriptor_type": "structured",
    "version": "1"
}' | jq .

# output
# {
#   "status": "success",
#   "data": {
#     "semantic_domain_id": "86353825-902f-4403-b721-989e76859342",
#     "semantic_domain": "This is a test semantic domain for application services",
#     "agent_card": "{\"name\": \"test_agent\", \"description\": \"Test agent for semantic domain\"}",
#     "dd_namespace": "test_namespace",
#     "dd_name": "test_name",
#     "descriptor_type": "structured",
#     "version": "1",
#     "created_at": "2024-01-01T00:00:00",
#     "updated_at": "2024-01-01T00:00:00"
#   },
#   "message": "semantic domain create success",
#   "count": null
# }

# 2. Batch Create Semantic Domains

curl -X POST "http://192.168.3.238:22000/semantic_domains/batch" \
-H "Content-Type: application/json" \
-d '[
    {
        "semantic_domain": "Semantic domain for database services",
        "agent_card": "{\"name\": \"db_agent\", \"type\": \"database\"}",
        "dd_namespace": "namespace2",
        "dd_name": "name2",
        "descriptor_type": "structured",
        "version": "1"
    },
    {
        "semantic_domain": "Semantic domain for API services",
        "agent_card": "{\"name\": \"api_agent\", \"type\": \"api\"}",
        "dd_namespace": "namespace3",
        "dd_name": "name3",
        "descriptor_type": "code",
        "version": "1"
    }
]' | jq .

# output
# {
#   "status": "success",
#   "data": {
#     "count": 2
#   },
#   "message": "batch create 2 semantic domains success",
#   "count": null
# }

# 3. Get by semantic_domain_id

curl -X GET "http://192.168.3.238:22000/semantic_domains/c94af930-ad5b-4ab6-9930-3f178d732570" | jq .

# output
# {
#   "status": "success",
#   "data": {
#     "semantic_domain_id": "86353825-902f-4403-b721-989e76859342",
#     "semantic_domain": "This is a test semantic domain for application services",
#     "agent_card": "{\"name\": \"test_agent\", \"description\": \"Test agent for semantic domain\"}",
#     "dd_namespace": "test_namespace",
#     "dd_name": "test_name",
#     "descriptor_type": "structured",
#     "version": "1",
#     "created_at": "2024-01-01T00:00:00",
#     "updated_at": "2024-01-01T00:00:00"
#   },
#   "message": null,
#   "count": null
# }

# 4. Search by DD Info

curl -X POST "http://192.168.3.238:22000/semantic_domains/search/by-dd" \
-H "Content-Type: application/json" \
-d '{
    "dd_namespace": "test_namespace",
    "dd_name": "test_name"
}' | jq .

# output
# {
#   "status": "success",
#   "data": [
#     {
#       "semantic_domain_id": "86353825-902f-4403-b721-989e76859342",
#       "semantic_domain": "This is a test semantic domain for application services",
#       "agent_card": "{\"name\": \"test_agent\", \"description\": \"Test agent for semantic domain\"}",
#       "dd_namespace": "test_namespace",
#       "dd_name": "test_name",
#       "descriptor_type": "structured",
#       "version": "1",
#       "created_at": "2024-01-01T00:00:00",
#       "updated_at": "2024-01-01T00:00:00"
#     }
#   ],
#   "count": 1
# }

# 5. Update Semantic Domain（可显式传 version / descriptor_type；未传则服务端保留原值）

curl -X PUT "http://192.168.3.238:22000/semantic_domains/c94af930-ad5b-4ab6-9930-3f178d732570" \
-H "Content-Type: application/json" \
-d '{
    "semantic_domain": "Updated semantic domain content",
    "agent_card": "{\"name\": \"updated_agent\", \"description\": \"Updated agent card\"}",
    "dd_namespace": "updated_namespace",
    "dd_name": "updated_name",
    "descriptor_type": "unstructured",
    "version": "2"
}' | jq .

# output
# {
#   "status": "success",
#   "data": {
#     "semantic_domain_id": "86353825-902f-4403-b721-989e76859342",
#     "semantic_domain": "Updated semantic domain content",
#     "agent_card": "{\"name\": \"updated_agent\", \"description\": \"Updated agent card\"}",
#     "dd_namespace": "updated_namespace",
#     "dd_name": "updated_name",
#     "descriptor_type": "unstructured",
#     "version": "2",
#     "created_at": "2024-01-01T00:00:00",
#     "updated_at": "2024-01-01T00:01:00"
#   },
#   "message": "semantic domain updated success",
#   "count": null
# }

# 6. Delete Semantic Domain

curl -X DELETE "http://192.168.3.238:22000/semantic_domains/c94af930-ad5b-4ab6-9930-3f178d732570" | jq .

# output
# {
#   "status": "success",
#   "data": null,
#   "message": "semantic domain deleted success",
#   "count": null
# }

# 7. Delete by DD Info

curl -X DELETE "http://192.168.3.238:22000/semantic_domains/dd_info/test_namespace/test_name" | jq .

# output
# {
#   "status": "success",
#   "data": null,
#   "message": "the semantic domain of DD namespace 'namespace2', DD name 'name2' is deleted success",
#   "count": null
# }

# 8. Check Existence by semantic_domain_id

curl -X GET "http://192.168.3.238:22000/semantic_domains/58564420-67ec-4e6a-b2f8-8dff6fdbda03/exists" | jq .

# output
# {
#   "status": "success",
#   "data": {
#     "exists": true
#   },
#   "message": null,
#   "count": null
# }

# 9. Check Existence by DD Info

curl -X GET "http://192.168.3.238:22000/semantic_domains/dd_info/test_namespace/test_name/exists" | jq .

# output
# {
#   "status": "success",
#   "data": {
#     "exists": true
#   },
#   "message": null,
#   "count": null
# }

# 10. Get Semantic Domain Count

curl -X GET "http://192.168.3.238:22000/semantic_domains/status/count" | jq .

# output
# {
#   "status": "success",
#   "data": {
#     "total_count": 1
#   },
#   "message": null,
#   "count": null
# }
