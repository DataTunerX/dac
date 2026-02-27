#!/bin/bash

# 1. Create Semantic Group

curl -X POST "http://192.168.3.238:22000/semantic_groups" \
-H "Content-Type: application/json" \
-d '{
    "group_name": "AI模型应用与服务管理平台",
    "description": "这是一个用于管理AI模型应用和服务的平台组",
    "agent_card": "Agent card information",
    "version": "v1.0"
}' | jq .

# output
# {
#   "status": "success",
#   "data": {
#     "id": "86353825-902f-4403-b721-989e76859342",
#     "group_name": "AI模型应用与服务管理平台",
#     "description": "这是一个用于管理AI模型应用和服务的平台组",
#     "agent_card": "Agent card information",
#     "version": "v1.0",
#     "created_at": "2024-01-01T00:00:00"
#   },
#   "message": "semantic group create success",
#   "count": null
# }

# 2. Batch Create Semantic Groups

curl -X POST "http://192.168.3.238:22000/semantic_groups/batch" \
-H "Content-Type: application/json" \
-d '[
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
]' | jq .

# output
# {
#   "status": "success",
#   "data": {
#     "count": 2
#   },
#   "message": "batch create 2 semantic groups success",
#   "count": null
# }

# 3. Get by group_id

curl -X GET "http://192.168.3.238:22000/semantic_groups/4b979c3a-6e66-42f3-b762-9a12c572ca5c" | jq .

# output
# {
#   "status": "success",
#   "data": {
#     "id": "86353825-902f-4403-b721-989e76859342",
#     "group_name": "AI模型应用与服务管理平台",
#     "description": "这是一个用于管理AI模型应用和服务的平台组",
#     "agent_card": "Agent card information",
#     "version": "v1.0",
#     "created_at": "2024-01-01T00:00:00"
#   },
#   "message": null,
#   "count": null
# }

# 4. Get All Groups

curl -X GET "http://192.168.3.238:22000/semantic_groups" | jq .

# output
# {
#   "status": "success",
#   "data": [
#     {
#       "id": "86353825-902f-4403-b721-989e76859342",
#       "group_name": "AI模型应用与服务管理平台",
#       "description": "这是一个用于管理AI模型应用和服务的平台组",
#       "agent_card": "Agent card information",
#       "version": "v1.0",
#       "created_at": "2024-01-01T00:00:00"
#     }
#   ],
#   "count": 1
# }

# 5. Get All Groups with Pagination

curl -X GET "http://192.168.3.238:22000/semantic_groups?page=1&page_size=2" | jq .

# output
# {
#   "status": "success",
#   "data": [
#     {
#       "id": "86353825-902f-4403-b721-989e76859342",
#       "group_name": "AI模型应用与服务管理平台",
#       "description": "这是一个用于管理AI模型应用和服务的平台组",
#       "agent_card": "Agent card information",
#       "version": "v1.0",
#       "created_at": "2024-01-01T00:00:00"
#     }
#   ],
#   "count": 1
# }

# 6. Update Semantic Group

curl -X PUT "http://192.168.3.238:22000/semantic_groups/4b979c3a-6e66-42f3-b762-9a12c572ca5c" \
-H "Content-Type: application/json" \
-d '{
    "group_name": "更新后的AI模型应用与服务管理平台",
    "description": "这是更新后的描述",
    "agent_card": "Updated agent card information",
    "version": "v2.0"
}' | jq .

# output
# {
#   "status": "success",
#   "data": {
#     "id": "86353825-902f-4403-b721-989e76859342",
#     "group_name": "更新后的AI模型应用与服务管理平台",
#     "description": "这是更新后的描述",
#     "agent_card": "Updated agent card information",
#     "version": "v2.0",
#     "created_at": "2024-01-01T00:00:00"
#   },
#   "message": "semantic group updated success",
#   "count": null
# }

# 7. Delete Semantic Group

curl -X DELETE "http://192.168.3.238:22000/semantic_groups/4b979c3a-6e66-42f3-b762-9a12c572ca5c" | jq .

# output
# {
#   "status": "success",
#   "data": null,
#   "message": "semantic group deleted success",
#   "count": null
# }

# 8. Check Existence by group_id

curl -X GET "http://192.168.3.238:22000/semantic_groups/4b979c3a-6e66-42f3-b762-9a12c572ca5c/exists" | jq .

# output
# {
#   "status": "success",
#   "data": {
#     "exists": true
#   },
#   "message": null,
#   "count": null
# }

# 9. Get Semantic Group Count

curl -X GET "http://192.168.3.238:22000/semantic_groups/status/count" | jq .

# output
# {
#   "status": "success",
#   "data": {
#     "total_count": 1
#   },
#   "message": null,
#   "count": null
# }

# 10. Create DD Group Relation

curl -X POST "http://192.168.3.238:22000/dd_group_relations" \
-H "Content-Type: application/json" \
-d '{
    "sd_id": "86353825-902f-4403-b721-989e76859342",
    "group_id": "378ee90f-ca11-47f2-a1a2-b06285992a1f",
    "association_reason": "语义相似性分析：两个DD在业务领域和功能上高度相关"
}' | jq .

# output
# {
#   "status": "success",
#   "data": {
#     "id": 1,
#     "sd_id": "86353825-902f-4403-b721-989e76859342",
#     "group_id": "c94af930-ad5b-4ab6-9930-3f178d732570",
#     "association_reason": "语义相似性分析：两个DD在业务领域和功能上高度相关"
#   },
#   "message": "dd group relation create success",
#   "count": null
# }

# 11. Batch Create DD Group Relations

curl -X POST "http://192.168.3.238:22000/dd_group_relations/batch" \
-H "Content-Type: application/json" \
-d '[
    {
        "sd_id": "sd_id_1",
        "group_id": "c94af930-ad5b-4ab6-9930-3f178d732570",
        "association_reason": "关联原因1：功能相似"
    },
    {
        "sd_id": "sd_id_2",
        "group_id": "c94af930-ad5b-4ab6-9930-3f178d732570",
        "association_reason": "关联原因2：业务领域相同"
    }
]' | jq .

# output
# {
#   "status": "success",
#   "data": {
#     "count": 2
#   },
#   "message": "batch create 2 dd group relations success",
#   "count": null
# }

# 12. Get Relations by Group ID

curl -X GET "http://192.168.3.238:22000/dd_group_relations/group/378ee90f-ca11-47f2-a1a2-b06285992a1f" | jq .

# output
# {
#   "status": "success",
#   "data": [
#     {
#       "id": 1,
#       "sd_id": "86353825-902f-4403-b721-989e76859342",
#       "group_id": "c94af930-ad5b-4ab6-9930-3f178d732570",
#       "association_reason": "语义相似性分析：两个DD在业务领域和功能上高度相关"
#     }
#   ],
#   "count": 1
# }

# 13. Get Relations by SD ID

curl -X GET "http://192.168.3.238:22000/dd_group_relations/sd/86353825-902f-4403-b721-989e76859342" | jq .

# output
# {
#   "status": "success",
#   "data": [
#     {
#       "id": 1,
#       "sd_id": "86353825-902f-4403-b721-989e76859342",
#       "group_id": "c94af930-ad5b-4ab6-9930-3f178d732570",
#       "association_reason": "语义相似性分析：两个DD在业务领域和功能上高度相关"
#     }
#   ],
#   "count": 1
# }

# 14. Delete Relation by ID

curl -X DELETE "http://192.168.3.238:22000/dd_group_relations/27" | jq .

# output
# {
#   "status": "success",
#   "data": null,
#   "message": "dd group relation deleted success",
#   "count": null
# }

# 15. Delete Relations by Group ID

curl -X DELETE "http://192.168.3.238:22000/dd_group_relations/group/378ee90f-ca11-47f2-a1a2-b06285992a1f" | jq .

# output
# {
#   "status": "success",
#   "data": null,
#   "message": "all dd group relations for group 'c94af930-ad5b-4ab6-9930-3f178d732570' deleted success",
#   "count": null
# }

# 16. Delete Relations by SD ID

curl -X DELETE "http://192.168.3.238:22000/dd_group_relations/sd/86353825-902f-4403-b721-989e76859342" | jq .

# output
# {
#   "status": "success",
#   "data": null,
#   "message": "all dd group relations for sd '86353825-902f-4403-b721-989e76859342' deleted success",
#   "count": null
# }
