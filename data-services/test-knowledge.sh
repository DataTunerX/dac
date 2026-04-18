# 1. Create Collection

curl -X POST "http://192.168.xxx.xxx:22000/knowledge_pyramid/create_collection" \
-H "Content-Type: application/json" \
-d '{
    "collection_name": "test_knowledge_pyramid112",
    "documents": [
        {
            "page_content": "Python is a popular programming language",
            "metadata": {"author": "Guido van Rossum", "year": 1991}
        }
    ]
}' | jq .

# output

{
  "status": "success",
  "message": "Collection test_knowledge_pyramid123 created successfully"
}


# 2. Delete Collection

curl -X DELETE "http://192.168.xxx.xxx:22000/knowledge_pyramid/delete_collection" \
-H "Content-Type: application/json" \
-d '{
    "collection_name": "test_knowledge_pyramid123"
}' | jq .

# output

{
  "status": "success",
  "message": "Collection 'test_knowledge_pyramid123' deleted successfully"
}



# 3. Add Documents

curl -X POST "http://192.168.xxx.xxx:22000/knowledge_pyramid/test_knowledge_pyramid112/add_documents" \
  -H "Content-Type: application/json" \
  -d '{
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
  }' | jq .

# output

{
  "status": "success",
  "message": "Document added successfully",
  "vector_results": [
    "0047594f-58b3-4665-a2ca-fb7b5467bb59",
    "32856b7b-c527-49d0-824a-32f95007a835"
  ]
}



# 4. Search Documents (vector score: higher is more similar, memory score: lower is more similar)

# hybrid_threshold: Retrieve data greater than hybrid_threshold, limited by limit. The higher the hybrid_threshold, the easier it is to get similar data.

#vector:

curl -X POST "http://192.168.3.212:22000/knowledge_pyramid/dac_dd_aa06/search" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "订单",
    "search_type": "vector",
    "limit": 100,
    "hybrid_threshold": 0.1,
    "vector_weight": 0.5,
    "fulltext_weight": 0.5
  }' | jq .


# output

# {
#   "status": "success",
#   "collection": "test_knowledge_pyramid123",
#   "search_type": "vector",
#   "vector_result": [
#     {
#       "content": "Machine learning is one of the core technologies of artificial intelligence",
#       "metadata": {
#         "source": "Technical Documentation",
#         "category": "AI",
#         "created_at": "2024-01-15",
#         "score": 0.613215822375299
#       },
#       "score": 0.613215822375299,
#       "search_type": "vector",
#       "hybrid_score": 0.0
#     },
#     {
#       "content": "Machine learning is one of the core technologies of artificial intelligence",
#       "metadata": {
#         "source": "Technical Documentation",
#         "category": "AI",
#         "created_at": "2024-01-15",
#         "score": 0.613215822375299
#       },
#       "score": 0.613215822375299,
#       "search_type": "vector",
#       "hybrid_score": 0.0
#     }
#   ]
# }


#fulltext:

curl -X POST "http://192.168.xxx.xxx:22000/knowledge_pyramid/test_knowledge_pyramid123/search" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Java",
    "search_type": "fulltext",
    "limit": 5,
    "hybrid_threshold": 0.1,
    "vector_weight": 0.5,
    "fulltext_weight": 0.5
  }' | jq .


# outout:

# {
#   "status": "success",
#   "collection": "test_knowledge_pyramid123",
#   "search_type": "fulltext",
#   "vector_result": [
#     {
#       "content": "Java is a high-level, object-oriented, cross-platform programming language",
#       "metadata": {
#         "source": "Technical Documentation",
#         "category": "code",
#         "created_at": "2024-01-15",
#         "score": 0.0607927106320858
#       },
#       "score": 0.0607927106320858,
#       "search_type": "fulltext",
#       "hybrid_score": 0.0
#     }
#   ]
# }


# hybrid:

curl -X POST "http://192.168.xxx.xxx:22000/knowledge_pyramid/test_knowledge_pyramid123/search" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "java",
    "search_type": "hybrid",
    "limit": 5,
    "hybrid_threshold": 0.1,
    "vector_weight": 0.5,
    "fulltext_weight": 0.5
  }' | jq .

# output

# {
#   "status": "success",
#   "collection": "test_knowledge_pyramid123",
#   "search_type": "hybrid",
#   "vector_result": [
#     {
#       "content": "Java is a high-level, object-oriented, cross-platform programming language",
#       "metadata": {
#         "source": "Technical Documentation",
#         "category": "code",
#         "created_at": "2024-01-15",
#         "score": 0.5465256301477937
#       },
#       "score": 0.5465256301477937,
#       "search_type": "vector",
#       "hybrid_score": 0.38256794110345554
#     },
#     {
#       "content": "Java is a high-level, object-oriented, cross-platform programming language",
#       "metadata": {
#         "source": "Technical Documentation",
#         "category": "code",
#         "created_at": "2024-01-15",
#         "score": 0.0607927106320858
#       },
#       "score": 0.0607927106320858,
#       "search_type": "fulltext",
#       "hybrid_score": 0.01823781318962574
#     }
#   ]
# }


# 5. Get all Documents

curl -X POST "http://192.168.3.212:22000/knowledge_pyramid/dac_dd_aa06/get_all" \
  -H "Content-Type: application/json" \
  -d '{}' | jq .


# output

# {
#   "status": "success",
#   "collection": "dac_dd_aa06",
#   "vector_result": [
#     {
#       "page_content": "[{'📁 DDD语义域概述': {'语义域名称': '商品管理 (Product Management)', '包含表': ['categories', 'products'], '业务定位': '管理商品分类体系和商品基本信息，包括价格、库存等。'}, '🧩 DDD语义域详情': {'核心职责': '管理商品分类体系和商品基本信息，包括价格、库存等。', d`与`category_id`的关联，形成父子分类的层级关系。 |\n| 一对多   | orders.order_id → order_items.order_id | 一个分类下可以有多个产品，每个产品通过`category_id`确定所属分类。 |\n\nKey Information:\n\n\nFewshots:\n\n\n",
#       "vector": null,
#       "metadata": {
#         "dd_name": null,
#         "module_name": "商品管理 + 订单管理 + 用户管理",
#         "source_type": "mysql",
#         "dd_namespace": null
#       },
#       "provider": "",
#       "children": null
#     },
#     {
#       "page_content": "[{'📁 DDD语义域概述': {'语义域名称': '用户管理 (User Management)', '包含表': ['users'], '业务定位': '管理用户的基本信息和认证。'}, '🧩 DDD语义域详情': {'核心职责': '管理用户的基本信息和认证。', '领域语言与术语': [{'类型': '术语', '术语 (Domain 格，十进制数，整数位8位小数位2位，不能为空 |\n| `stock_quantity` | `int` | YES |  | 库存数量，默认为0 |\n| `category_id` | `int` | NO | MUL n| 一对多   | categories.category_id → products.category_id | 一个分类下可以有多个产品，每个产品通过`category_id`确定所属分类。 |\n\nKey Information:\n\n\nFewshots:\n\n\n",
#       "vector": null,
#       "metadata": {
#         "dd_name": null,
#         "module_name": "用户管理 + 商品分类管理 + 商品管理 + 订单管理 + 订单项管理",
#         "source_type": "mysql",
#         "dd_namespace": null
#       },
#       "provider": "",
#       "children": null
#     },
#     ........
#   ]
# }


# 5. Get metadata data

curl -X POST "http://192.168.3.7:22000/knowledge_pyramid/find_metadata_values_in_collections" \
  -H "Content-Type: application/json" \
  -d '{
    "collection_names": ["dac_bank"]
  }' | jq .




# 6. Delete Documents by ID

# Prepare test data


curl -X POST "http://192.168.xxx.xxx:22000/knowledge_pyramid/test_knowledge_pyramid123/add_documents" \
  -H "Content-Type: application/json" \
  -d '{
    "documents": [
      {
        "page_content": "Ruby is a good development language",
        "metadata": {
          "category": "code",
          "source": "Technical Documentation",
          "created_at": "2024-01-15"
        }
      },
      {
        "page_content": "Rust is a high-performance development language",
        "metadata": {
          "category": "code",
          "source": "Research Paper",
          "created_at": "2024-01-16"
        }
      }
    ]
  }' | jq .


# output

# {
#   "status": "success",
#   "message": "Document added successfully",
#   "vector_results": [
#     "fa268a37-1b1e-4296-bd8f-3aeacb11c0bd",
#     "b19a2053-e00a-4d52-8077-b9b20c7dc161"
#   ]
# }



curl -X DELETE "http://192.168.xxx.xxx:22000/knowledge_pyramid/test_knowledge_pyramid123/delete_by_ids" \
  -H "Content-Type: application/json" \
  -d '{
    "documents": [
      "6bc5327c-a431-4c3f-87fe-69d85ce9922d",
      "228c61b1-1fd6-45f3-9a34-71c9b0b01eaa"
    ]
  }' | jq .



# output


# 7. Delete Documents by metadata field

# Deletes all chunks whose metadata has the given key-value (same semantics as vector delete_by_metadata_field).

curl -X DELETE "http://192.168.xxx.xxx:22000/knowledge_pyramid/test_knowledge_pyramid123/delete_by_metadata_field" \
  -H "Content-Type: application/json" \
  -d '{
    "key": "category",
    "value": "AI"
  }' | jq .

# output

# {
#   "status": "success",
#   "message": "Delete operation completed",
#   "collection": "test_knowledge_pyramid123"
# }


# 8. Delete All Documents and Memories in a Collection

curl -X DELETE "http://192.168.xxx.xxx:22000/knowledge_pyramid/test_knowledge_pyramid123/delete_all" \
  -H "Content-Type: application/json" \
  -d '{}' | jq .

