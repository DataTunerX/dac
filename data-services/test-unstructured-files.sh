
# unstructured-files API 手工测试（每条 curl 可直接复制执行）。
# data-services 示例地址: http://10.17.0.41:31337
# MinIO 对象 dactest/dianshang.docx 的 file_size 请用 HeadObject 的 ContentLength（示例为 48146，MinIO 示例: http://10.17.0.41:30389，密钥 minioadmin/minioadmin）。
#
# 默认只做到「写入 + 查询」，不在库里删数据，便于核对。若要清理，再自行取消第 7、8 步里 curl 的注释执行。

# 1. Upsert one file (POST /unstructured-files)

curl -X POST "http://10.17.0.41:31337/unstructured-files" \
-H "Content-Type: application/json" \
-d '{
    "dd_namespace": "test_namespace",
    "dd_name": "test_unstructured_dd",
    "file_name": "dianshang.docx",
    "bucket": "dactest",
    "minio_path": "minio://dactest/dianshang.docx",
    "file_size": 48146
}' | jq .

# output

# {
#   "status": "success",
#   "message": "unstructured-files upsert success",
#   "data": {
#     "id": 1,
#     "dd_namespace": "test_namespace",
#     "dd_name": "test_unstructured_dd",
#     "file_name": "dianshang.docx",
#     "bucket": "dactest",
#     "minio_path": "minio://dactest/dianshang.docx",
#     "file_size": 48146,
#     "created_at": "2026-04-15T12:00:00"
#   },
#   "count": null
# }


# 2. Batch upsert (POST /unstructured-files/batch)

curl -X POST "http://10.17.0.41:31337/unstructured-files/batch" \
-H "Content-Type: application/json" \
-d '{
    "files": [
        {
            "dd_namespace": "test_namespace",
            "dd_name": "test_unstructured_dd",
            "file_name": "dianshang.docx",
            "bucket": "dactest",
            "minio_path": "minio://dactest/dianshang.docx",
            "file_size": 48146
        },
        {
            "dd_namespace": "test_namespace",
            "dd_name": "test_unstructured_dd",
            "file_name": "notes.txt",
            "bucket": "dactest",
            "minio_path": "minio://dactest/notes.txt",
            "file_size": 512
        }
    ]
}' | jq .

# output

# {
#   "status": "success",
#   "message": "unstructured-files batch upsert success (2 rows)",
#   "data": { "upserted": 2 },
#   "count": 2
# }


# 3. Get by row id (GET /unstructured-files/{id}，请按步骤 1 返回的 id 修改 URL)

curl -X GET "http://10.17.0.41:31337/unstructured-files/1" | jq .

# output

# {
#   "status": "success",
#   "data": {
#     "id": 1,
#     "dd_namespace": "test_namespace",
#     "dd_name": "test_unstructured_dd",
#     "file_name": "dianshang.docx",
#     "bucket": "dactest",
#     "minio_path": "minio://dactest/dianshang.docx",
#     "file_size": 48146,
#     "created_at": "2026-04-15T12:00:00"
#   },
#   "message": null,
#   "count": null
# }


# 4. List by bucket + DataDescriptor (GET /unstructured-files?bucket&dd_namespace&dd_name)

curl -X GET "http://10.17.0.41:31337/unstructured-files?bucket=dactest&dd_namespace=test_namespace&dd_name=test_unstructured_dd&limit=50&offset=0" | jq .

# output

# {
#   "status": "success",
#   "data": [
#     {
#       "id": 1,
#       "dd_namespace": "test_namespace",
#       "dd_name": "test_unstructured_dd",
#       "file_name": "dianshang.docx",
#       "bucket": "dactest",
#       "minio_path": "minio://dactest/dianshang.docx",
#       "file_size": 48146,
#       "created_at": "..."
#     },
#     {
#       "id": 2,
#       "dd_namespace": "test_namespace",
#       "dd_name": "test_unstructured_dd",
#       "file_name": "notes.txt",
#       "bucket": "dactest",
#       "minio_path": "minio://dactest/notes.txt",
#       "file_size": 1024,
#       "created_at": "..."
#     }
#   ],
#   "count": 2
# }


# 5. List by DataDescriptor only (GET /unstructured-files?dd_namespace&dd_name)

curl -X GET "http://10.17.0.41:31337/unstructured-files?dd_namespace=test_namespace&dd_name=test_unstructured_dd&limit=50&offset=0" | jq .

# output

# {
#   "status": "success",
#   "data": [ ... ],
#   "count": 2
# }


# 6. List first page without bucket / dd filter (GET /unstructured-files?limit&offset)

curl -X GET "http://10.17.0.41:31337/unstructured-files?limit=10&offset=0" | jq .

# output

# {
#   "status": "success",
#   "data": [ ... ],
#   "count": 10
# }


# 7. Delete by object (POST /unstructured-files/delete-by-object)

curl -X POST "http://10.17.0.41:31337/unstructured-files/delete-by-object" \
-H "Content-Type: application/json" \
-d '{
    "dd_namespace": "test_namespace",
    "dd_name": "test_unstructured_dd",
    "bucket": "dactest",
    "minio_path": "minio://dactest/notes.txt"
}' | jq .

# output

# {
#   "status": "success",
#   "message": "unstructured-files deleted by bucket and path",
#   "data": null,
#   "count": null
# }


# 8. Delete by row id (DELETE /unstructured-files/{id}，请按实际 id 修改 URL)

curl -X DELETE "http://10.17.0.41:31337/unstructured-files/1" | jq .

# output

# {
#   "status": "success",
#   "message": "unstructured-files deleted",
#   "data": { "id": 1 },
#   "count": null
# }


# 9. Delete all rows in a MinIO bucket for every DataDescriptor (DELETE /unstructured-files/bucket/{bucket}) — 慎用

# curl -X DELETE "http://10.17.0.41:31337/unstructured-files/bucket/dactest" | jq .

# output

# {
#   "status": "success",
#   "message": "unstructured-files deleted N row(s) for bucket",
#   "data": { "deleted": N },
#   "count": N
# }


# 10. Delete all rows for one DataDescriptor only (POST /unstructured-files/delete-by-dd)
#     仅需 dd_namespace + dd_name，会删掉该 DD 下全部 unstructured_files 记录（与 bucket/minio_path 无关）— 慎用

curl -X POST "http://10.17.0.41:31337/unstructured-files/delete-by-dd" -H "Content-Type: application/json" -d '{"dd_namespace":"test_namespace","dd_name":"test_unstructured_dd"}' | jq .

# output

# {
#   "status": "success",
#   "message": "unstructured-files deleted 2 row(s) for dd_namespace='test_namespace' dd_name='test_unstructured_dd'",
#   "data": { "deleted": 2 },
#   "count": 2
# }

# 若无匹配行：

# {
#   "status": "success",
#   "message": "no unstructured-files rows matched this DataDescriptor",
#   "data": { "deleted": 0 },
#   "count": 0
# }
