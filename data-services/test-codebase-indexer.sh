#!/bin/bash

echo "=========================================="
echo "1. Create Codebase Indexer"
echo "=========================================="

curl -X POST "http://192.168.3.238:22000/codebase_indexers" \
-H "Content-Type: application/json" \
-d '{
    "filepath": "/src/main/app.py",
    "code_deep_analysis": "这是一个Flask应用入口文件，包含应用初始化、路由配置和数据库连接设置。主要功能：1. Flask应用初始化 2. 蓝图注册 3. 中间件配置",
    "dd_namespace": "test_namespace",
    "dd_name": "test_app"
}' | jq .

# output
# {
#   "status": "success",
#   "data": {
#     "codebase_indexer_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
#     "filepath": "/src/main/app.py",
#     "code_deep_analysis": "这是一个Flask应用入口文件...",
#     "dd_namespace": "test_namespace",
#     "dd_name": "test_app",
#     "created_at": null,
#     "updated_at": null
#   },
#   "message": "codebase indexer create success",
#   "count": null
# }

echo ""
echo "=========================================="
echo "2. Batch Create Codebase Indexers"
echo "=========================================="

curl -X POST "http://192.168.3.238:22000/codebase_indexers/batch" \
-H "Content-Type: application/json" \
-d '[
    {
        "filepath": "/src/utils/helper.py",
        "code_deep_analysis": "工具函数模块，包含字符串处理、日期格式化、数据验证等常用工具函数",
        "dd_namespace": "test_namespace",
        "dd_name": "test_app"
    },
    {
        "filepath": "/src/models/user.py",
        "code_deep_analysis": "用户模型定义，包含User类、用户认证方法和数据库ORM映射",
        "dd_namespace": "test_namespace",
        "dd_name": "test_app"
    },
    {
        "filepath": "/src/api/routes.py",
        "code_deep_analysis": "API路由配置，定义了RESTful接口端点、请求验证和响应处理逻辑",
        "dd_namespace": "test_namespace",
        "dd_name": "test_app"
    }
]' | jq .

# output
# {
#   "status": "success",
#   "data": {
#     "count": 3
#   },
#   "message": "batch create 3 codebase indexers success",
#   "count": null
# }

echo ""
echo "=========================================="
echo "3. Get Codebase Indexer Count"
echo "=========================================="

curl -X GET "http://192.168.3.238:22000/codebase_indexers/status/count" | jq .

# output
# {
#   "status": "success",
#   "data": {
#     "total_count": 4
#   },
#   "message": null,
#   "count": null
# }

echo ""
echo "=========================================="
echo "4. Search by DD Info"
echo "=========================================="

curl -X POST "http://192.168.3.238:22000/codebase_indexers/search/by-dd" \
-H "Content-Type: application/json" \
-d '{
    "dd_namespace": "test_namespace",
    "dd_name": "test_app"
}' | jq .

# output
# {
#   "status": "success",
#   "data": [
#     {
#       "codebase_indexer_id": "...",
#       "filepath": "/src/main/app.py",
#       "code_deep_analysis": "...",
#       "dd_namespace": "test_namespace",
#       "dd_name": "test_app",
#       "created_at": "2024-01-01T00:00:00",
#       "updated_at": "2024-01-01T00:00:00"
#     },
#     ...
#   ],
#   "count": 4
# }

echo ""
echo "=========================================="
echo "5. Search by Filepath (Exact Match)"
echo "=========================================="

curl -X POST "http://192.168.3.238:22000/codebase_indexers/search/by-filepath" \
-H "Content-Type: application/json" \
-d '{
    "filepath": "/src/main/app.py"
}' | jq .

# output
# {
#   "status": "success",
#   "data": [
#     {
#       "codebase_indexer_id": "...",
#       "filepath": "/src/main/app.py",
#       "code_deep_analysis": "这是一个Flask应用入口文件...",
#       "dd_namespace": "test_namespace",
#       "dd_name": "test_app",
#       "created_at": "2024-01-01T00:00:00",
#       "updated_at": "2024-01-01T00:00:00"
#     }
#   ],
#   "count": 1
# }

echo ""
echo "=========================================="
echo "6. Search by Filepath (Prefix Match)"
echo "=========================================="

curl -X POST "http://192.168.3.238:22000/codebase_indexers/search/by-filepath" \
-H "Content-Type: application/json" \
-d '{
    "filepath": "/src/",
    "prefix_match": true
}' | jq .

# output
# {
#   "status": "success",
#   "data": [
#     {
#       "codebase_indexer_id": "...",
#       "filepath": "/src/api/routes.py",
#       ...
#     },
#     {
#       "codebase_indexer_id": "...",
#       "filepath": "/src/main/app.py",
#       ...
#     },
#     ...
#   ],
#   "count": 4
# }

echo ""
echo "=========================================="
echo "7. Search by Filepath with DD Filter"
echo "=========================================="

curl -X POST "http://192.168.3.238:22000/codebase_indexers/search/by-filepath" \
-H "Content-Type: application/json" \
-d '{
    "filepath": "/src/",
    "dd_namespace": "test_namespace",
    "dd_name": "test_app",
    "prefix_match": true
}' | jq .

# output
# {
#   "status": "success",
#   "data": [
#     {
#       "codebase_indexer_id": "...",
#       "filepath": "/src/api/routes.py",
#       "code_deep_analysis": "API路由配置...",
#       "dd_namespace": "test_namespace",
#       "dd_name": "test_app",
#       ...
#     },
#     ...
#   ],
#   "count": 4
# }

echo ""
echo "=========================================="
echo "8. Get by codebase_indexer_id"
echo "=========================================="
echo "(Replace with actual ID from step 1)"

# Replace <CODEBASE_INDEXER_ID> with actual ID
# curl -X GET "http://192.168.3.238:22000/codebase_indexers/<CODEBASE_INDEXER_ID>" | jq .

# output
# {
#   "status": "success",
#   "data": {
#     "codebase_indexer_id": "...",
#     "filepath": "/src/main/app.py",
#     "code_deep_analysis": "...",
#     "dd_namespace": "test_namespace",
#     "dd_name": "test_app",
#     "created_at": "2024-01-01T00:00:00",
#     "updated_at": "2024-01-01T00:00:00"
#   },
#   "message": null,
#   "count": null
# }

echo ""
echo "=========================================="
echo "9. Update Codebase Indexer"
echo "=========================================="
echo "(Replace with actual ID)"

# Replace <CODEBASE_INDEXER_ID> with actual ID
# curl -X PUT "http://192.168.3.238:22000/codebase_indexers/<CODEBASE_INDEXER_ID>" \
# -H "Content-Type: application/json" \
# -d '{
#     "filepath": "/src/main/updated_app.py",
#     "code_deep_analysis": "更新后的代码分析内容：这是一个重构后的Flask应用入口"
# }' | jq .

# output
# {
#   "status": "success",
#   "data": {
#     "codebase_indexer_id": "...",
#     "filepath": "/src/main/updated_app.py",
#     "code_deep_analysis": "更新后的代码分析内容...",
#     "dd_namespace": "test_namespace",
#     "dd_name": "test_app",
#     "created_at": null,
#     "updated_at": null
#   },
#   "message": "codebase indexer updated success",
#   "count": null
# }

echo ""
echo "=========================================="
echo "10. Check Existence by codebase_indexer_id"
echo "=========================================="
echo "(Replace with actual ID)"

# Replace <CODEBASE_INDEXER_ID> with actual ID
# curl -X GET "http://192.168.3.238:22000/codebase_indexers/<CODEBASE_INDEXER_ID>/exists" | jq .

# output
# {
#   "status": "success",
#   "data": {
#     "exists": true
#   },
#   "message": null,
#   "count": null
# }

echo ""
echo "=========================================="
echo "11. Check Existence by DD Info"
echo "=========================================="

curl -X GET "http://192.168.3.238:22000/codebase_indexers/dd_info/test_namespace/test_app/exists" | jq .

# output
# {
#   "status": "success",
#   "data": {
#     "exists": true
#   },
#   "message": null,
#   "count": null
# }

echo ""
echo "=========================================="
echo "12. Delete Codebase Indexer by ID"
echo "=========================================="
echo "(Replace with actual ID)"

# Replace <CODEBASE_INDEXER_ID> with actual ID
# curl -X DELETE "http://192.168.3.238:22000/codebase_indexers/<CODEBASE_INDEXER_ID>" | jq .

# output
# {
#   "status": "success",
#   "data": null,
#   "message": "codebase indexer deleted success",
#   "count": null
# }

echo ""
echo "=========================================="
echo "13. Delete by DD Info"
echo "=========================================="

curl -X DELETE "http://192.168.3.238:22000/codebase_indexers/dd_info/test_namespace/test_app" | jq .

# output
# {
#   "status": "success",
#   "data": null,
#   "message": "the codebase indexer of DD namespace 'test_namespace', DD name 'test_app' is deleted success",
#   "count": null
# }

echo ""
echo "=========================================="
echo "Test completed!"
echo "=========================================="
