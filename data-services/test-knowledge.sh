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
  ],
  "memory_result": [
    {
      "id": "3cd39d9b-de1a-45d3-82a4-1a372e6ce7b2",
      "memory": "Machine learning is one of the core technologies of artificial intelligence",
      "event": "ADD"
    },
    {
      "id": "674390fc-88d0-4909-ab85-4ba65cbb87e6",
      "memory": "Deep learning has made breakthrough progress in the field of image recognition",
      "event": "ADD"
    }
  ]
}



# 4. Search Documents (vector score: higher is more similar, memory score: lower is more similar)

# hybrid_threshold: Retrieve data greater than hybrid_threshold, limited by limit. The higher the hybrid_threshold, the easier it is to get similar data.

# memory_threshold: Retrieve data greater than memory_threshold, limited by limit. The lower the memory_threshold, the easier it is to get similar data.


#vector:

curl -X POST "http://192.168.xxx.xxx:22000/knowledge_pyramid/test_knowledge_pyramid123/search" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What is Java",
    "search_type": "vector",
    "limit": 100,
    "hybrid_threshold": 0.1,
    "memory_threshold": 0.1,
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
#   ],
#   "memory_result": [
#     {
#       "id": "5f70514f-53bc-407c-96eb-8a6f6fd32a0f",
#       "memory": "Go (also known as Golang) is an open-source, statically typed, compiled programming language developed by Google",
#       "hash": "7bce3e0d89b03dd0652fbaffab7dfe3d",
#       "metadata": null,
#       "score": 0.7888018419500868,
#       "created_at": "2025-08-27T06:59:46.727515-07:00",
#       "updated_at": null,
#       "user_id": "test_knowledge_pyramid123"
#     },
#     {
#       "id": "50826ca1-3572-4d4d-9c26-f92d26c820e2",
#       "memory": "Java is a high-level, object-oriented, cross-platform programming language",
#       "hash": "abe2a5d48b38fe030ff4694eaceafd24",
#       "metadata": null,
#       "score": 0.7469372900165738,
#       "created_at": "2025-08-27T06:59:46.727368-07:00",
#       "updated_at": null,
#       "user_id": "test_knowledge_pyramid123"
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
    "memory_threshold": 0.1,
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
#   ],
#   "memory_result": [
#     {
#       "id": "15996afb-1dd9-4373-8e0b-06d9aefb5496",
#       "memory": "Deep learning has made breakthrough progress in the field of image recognition",
#       "hash": "049053e6f6389412ee557af602b1dd82",
#       "metadata": null,
#       "score": 0.8201412176917481,
#       "created_at": "2025-08-27T06:59:22.126114-07:00",
#       "updated_at": null,
#       "user_id": "test_knowledge_pyramid123"
#     },
#     {
#       "id": "09e03cfa-d0dc-45ae-be6e-96862a543984",
#       "memory": "Machine learning is one of the core technologies of artificial intelligence",
#       "hash": "beac27403bffdf9bfb6effd487cfeb3c",
#       "metadata": null,
#       "score": 0.784772095795288,
#       "created_at": "2025-08-27T06:59:22.125977-07:00",
#       "updated_at": null,
#       "user_id": "test_knowledge_pyramid123"
#     },
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
    "memory_threshold": 0.1,
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
#   ],
#   "memory_result": [
#     {
#       "id": "645e3cbc-3b9b-448c-a819-8de18468c0ce",
#       "memory": "Deep learning has made breakthrough progress in the field of image recognition",
#       "hash": "049053e6f6389412ee557af602b1dd82",
#       "metadata": null,
#       "score": 0.8201412176917481,
#       "created_at": "2025-08-26T02:39:01.260463-07:00",
#       "updated_at": null,
#       "user_id": "test_knowledge_pyramid123"
#     },
#     {
#       "id": "3cd39d9b-de1a-45d3-82a4-1a372e6ce7b2",
#       "memory": "Java is a high-level, object-oriented, cross-platform programming language",
#       "hash": "abe2a5d48b38fe030ff4694eaceafd24",
#       "metadata": null,
#       "score": 0.45347436985220635,
#       "created_at": "2025-08-26T19:55:14.290165-07:00",
#       "updated_at": null,
#       "user_id": "test_knowledge_pyramid123"
#     }
#   ]
# }


#memory: Lower score indicates higher similarity.

curl -X POST "http://192.168.xxx.xxx:22000/knowledge_pyramid/test_knowledge_pyramid123/search" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What is Java",
    "search_type": "memory",
    "limit": 100,
    "hybrid_threshold": 0.1,
    "memory_threshold": 0.1,
    "vector_weight": 0.5,
    "fulltext_weight": 0.5
  }' | jq .

# output

# {
#   "status": "success",
#   "collection": "test_knowledge_pyramid123",
#   "search_type": "memory",
#   "vector_result": [],
#   "memory_result": [
#     {
#       "id": "e64f81c7-b969-4575-9cd9-3ee91ef541fe",
#       "memory": "Java is a widely used development language",
#       "hash": "756f77c0a8c66056fa37a638f844a6d5",
#       "metadata": null,
#       "score": 0.3371868532057656,
#       "created_at": "2025-08-27T22:57:33.500377-07:00",
#       "updated_at": null,
#       "user_id": "test_knowledge_pyramid123"
#     },
#     {
#       "id": "d778a97a-2121-45dd-82ec-21624b1687b4",
#       "memory": "To learn English well, one must persist in daily immersive learning and practice, listening, speaking, reading, and writing more, creating a language environment and maintaining long-term accumulation.",
#       "hash": "b123f4a12e18f6b7c9c4596801479cb6",
#       "metadata": null,
#       "score": 0.8112151920795441,
#       "created_at": "2025-08-28T00:12:14.124664-07:00",
#       "updated_at": null,
#       "user_id": "test_knowledge_pyramid123"
#     }
#   ]
# }


curl -X POST "http://192.168.xxx.xxx:22000/knowledge_pyramid/test_knowledge_pyramid123/search" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What is Java",
    "search_type": "memory",
    "limit": 5,
    "hybrid_threshold": 0.1,
    "memory_threshold": 0.1,
    "vector_weight": 0.5,
    "fulltext_weight": 0.5
  }' | jq .

# output

# {
#   "status": "success",
#   "collection": "test_knowledge_pyramid123",
#   "search_type": "memory",
#   "vector_result": [],
#   "memory_result": [
#     {
#       "id": "e64f81c7-b969-4575-9cd9-3ee91ef541fe",
#       "memory": "Java is a widely used development language",
#       "hash": "756f77c0a8c66056fa37a638f844a6d5",
#       "metadata": null,
#       "score": 0.3371868532057656,
#       "created_at": "2025-08-27T22:57:33.500377-07:00",
#       "updated_at": null,
#       "user_id": "test_knowledge_pyramid123"
#     },
#     {
#       "id": "dd21f0dc-d48d-4874-af3a-9439cacfb7c7",
#       "memory": "Go (also known as Golang) is an open-source, statically typed, compiled programming language developed by Google",
#       "hash": "7bce3e0d89b03dd0652fbaffab7dfe3d",
#       "metadata": null,
#       "score": 0.6128919288048802,
#       "created_at": "2025-08-27T22:41:50.058989-07:00",
#       "updated_at": null,
#       "user_id": "test_knowledge_pyramid123"
#     }
#   ]
# }


# 5. search all memory Documents with collection name


curl -X POST "http://192.168.xxx.xxx:22000/knowledge_pyramid/test_knowledge_pyramid8/memories_get_all" \
  -H "Content-Type: application/json" \
  -d '{}' | jq .

# output


{
  "status": "success",
  "collection": "test_knowledge_pyramid8",
  "search_type": "memory",
  "vector_result": [],
  "memory_result": [
    {
      "id": "a0e2ab30-2bc0-4f5f-9e60-7653c916ce18",
      "memory": "机器学习是人工智能的一个子领域，它使计算机能够在没有明确编程的情况下学习和改进。",
      "hash": "0fc847201ec7e99ddeb5e725e03f76d1",
      "metadata": null,
      "created_at": "2025-09-23T23:04:40.222531-07:00",
      "updated_at": null,
      "user_id": "test_knowledge_pyramid8"
    },
    {
      "id": "2f31bcbd-9f45-4216-a7be-eebd1e8c3894",
      "memory": "`balance_sheet` 表记录了各分行在特定日期的财务状况，包括总资产、客户贷款、同业资产、其他资产、总负债、客户存款、同业负债、其他负债、客户总数、个人客户数、企业客户数、同业客户数及员工总数。",
      "hash": "5b56955bbf557db32f5a5141cbc12bde",
      "metadata": null,
      "created_at": "2025-09-23T23:49:25.377014-07:00",
      "updated_at": null,
      "user_id": "test_knowledge_pyramid8"
    },
    {
      "id": "d39eeda8-ac64-489a-8c61-cbea5d9c910f",
      "memory": "`deposit_data` 表详细列出了各分行在特定日期的存款情况，涵盖客户存款总额、企业存款总额、企业活期存款、企业定期存款、零售存款总额、零售活期存款及零售定期存款。",
      "hash": "dee3e4c7acd4b9900a1aecbc4c6a3ec1",
      "metadata": null,
      "created_at": "2025-09-23T23:49:25.377356-07:00",
      "updated_at": null,
      "user_id": "test_knowledge_pyramid8"
    },
    {
      "id": "5d897262-81b5-421f-892d-499b82029b4e",
      "memory": "`loan_data` 表提供了各分行在特定日期的贷款详情，包括客户贷款总额、实质性贷款总额、企业贷款总额、普惠小微企业贷款、零售贷款总额、信用卡贷款、中型企业贷款、大型企业贷款、中型及小型企业贷款、大型企业贷款、总贴现额、直接贴现及转贴现。",
      "hash": "d7a2604ab6351ed197df1dc614afe926",
      "metadata": null,
      "created_at": "2025-09-23T23:49:25.377417-07:00",
      "updated_at": null,
      "user_id": "test_knowledge_pyramid8"
    },
    {
      "id": "f6a37b31-426f-44fe-83c2-6c3760a927a4",
      "memory": "`retail_loan_detail` 表则进一步细分了零售贷款的具体构成，如零售贷款总额、抵押贷款总额、一手房抵押贷款、二手房抵押贷款及消费贷款总额。",
      "hash": "7d9bb0afbfc5b8b8c1054851489b8557",
      "metadata": null,
      "created_at": "2025-09-23T23:49:25.377452-07:00",
      "updated_at": null,
      "user_id": "test_knowledge_pyramid8"
    }
  ]
}



# 6. Delete Documents and Memories by ID

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
#   ],
#   "memory_result": [
#     {
#       "id": "f4248cb2-b2a0-4989-8423-d747bf43462a",
#       "memory": "Ruby is a good development language",
#       "event": "ADD"
#     },
#     {
#       "id": "13e0dd58-d96d-43a6-9ed5-51ba437bbcfa",
#       "memory": "Rust is a high-performance development language",
#       "event": "ADD"
#     }
#   ]
# }



curl -X DELETE "http://192.168.xxx.xxx:22000/knowledge_pyramid/test_knowledge_pyramid123/delete_by_ids" \
  -H "Content-Type: application/json" \
  -d '{
    "documents": [
      "6bc5327c-a431-4c3f-87fe-69d85ce9922d",
      "228c61b1-1fd6-45f3-9a34-71c9b0b01eaa"
    ],
    "memorys": [
      "95ecae8f-aaee-4f96-9ff3-3d8da284a992",
      "88011361-5185-4660-bcf1-44fa5f25b6e0"
    ]
  }' | jq .



curl -X DELETE "http://192.168.xxx.xxx:22000/knowledge_pyramid/test_knowledge_pyramid123/delete_by_ids" \
  -H "Content-Type: application/json" \
  -d '{
    "documents": [
    ],
    "memorys": [
      "88fe0f04-7b7e-4bb9-ac97-77517216a2a8"
    ]
  }' | jq .




# output


# 7. Delete All Documents and Memories in a Collection

curl -X DELETE "http://192.168.xxx.xxx:22000/knowledge_pyramid/test_knowledge_pyramid123/delete_all" \
  -H "Content-Type: application/json" \
  -d '{}' | jq .

