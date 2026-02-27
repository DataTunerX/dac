
# 1. Create Collection

curl -X POST "http://192.168.xxx.xxx:22000/vector/create_collection" \
-H "Content-Type: application/json" \
-d '{
    "collection_name": "test_vector123",
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
  "message": "Collection test_vector created successfully or exist already"
}


# 2. Delete Collection

curl -X DELETE "http://192.168.xxx.xxx:22000/vector/delete_collection" \
-H "Content-Type: application/json" \
-d '{
    "collection_name": "test_vector"
}' | jq .

# output

{
  "status": "success",
  "message": "Collection 'test_vector' deleted successfully"
}



# 3. Add Documents

curl -X POST "http://192.168.xxx.xxx:22000/vector/test_vector/add_documents" \
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
      },
      {
        "page_content": "The quick brown fox jumps over the lazy dog",
        "metadata": {
          "category": "Deep Learning",
          "source": "Research Paper",
          "created_at": "2024-01-16"
        }
      }
    ]
  }' | jq .

# Output

{
  "status": "success",
  "message": "Document added successfully",
  "results": [
    "29a2a9f4-ceef-4736-9b5c-1b2c60b46431",
    "88d353bf-0240-4557-945c-9d266a94cf60"
  ]
}



# 4. Search Documents (Higher vector score indicates greater similarity)

# hybrid_threshold: Retrieve data greater than the hybrid_threshold, limited by the limit. A higher hybrid_threshold makes it easier to retrieve similar data.


#vector:

curl -X POST "http://192.168.xxx.xxx:22000/vector/test_vector123/search" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Ruby is a good development language",
    "search_type": "vector",
    "limit": 100,
    "hybrid_threshold": 0.1,
    "vector_weight": 0.5,
    "fulltext_weight": 0.5
  }' | jq .



#Output

{
  "status": "success",
  "collection": "test_vector",
  "search_type": "vector",
  "result": [
    {
      "content": "Machine learning is one of the core technologies of artificial intelligence",
      "metadata": {
        "source": "Technical Documentation",
        "category": "AI",
        "created_at": "2024-01-15",
        "score": 0.3262292438354425
      },
      "score": 0.3262292438354425,
      "search_type": "vector",
      "hybrid_score": 0.0
    },
    {
      "content": "Deep learning has made breakthrough progress in the field of image recognition",
      "metadata": {
        "source": "Research Paper",
        "category": "Deep Learning",
        "created_at": "2024-01-16",
        "score": 0.23786205270373262
      },
      "score": 0.23786205270373262,
      "search_type": "vector",
      "hybrid_score": 0.0
    }
  ]
}



#fulltext:

curl -X POST "http://192.168.xxx.xxx:22000/vector/test_vector/search" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "fox jumps",
    "search_type": "fulltext",
    "limit": 5,
    "hybrid_threshold": 0.01,
    "vector_weight": 0.5,
    "fulltext_weight": 0.5
  }' | jq .


# output:

{
  "status": "success",
  "collection": "test_vector",
  "search_type": "fulltext",
  "result": [
    {
      "content": "The quick brown fox jumps over the lazy dog",
      "metadata": {
        "source": "Research Paper",
        "category": "Deep Learning",
        "created_at": "2024-01-16",
        "score": 0.09910321980714798
      },
      "score": 0.09910321980714798,
      "search_type": "fulltext",
      "hybrid_score": 0.0
    }
  ]
}


# hybrid:

curl -X POST "http://192.168.xxx.xxx:22000/vector/test_vector/search" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "java",
    "search_type": "hybrid",
    "limit": 5,
    "hybrid_threshold": 0.1,
    "vector_weight": 0.5,
    "fulltext_weight": 0.5
  }' | jq .

#Output

{
  "status": "success",
  "collection": "test_vector",
  "search_type": "hybrid",
  "result": [
    {
      "content": "Machine learning is one of the core technologies of artificial intelligence",
      "metadata": {
        "source": "Technical Documentation",
        "category": "AI",
        "created_at": "2024-01-15",
        "score": 0.21522790420471205
      },
      "score": 0.21522790420471205,
      "search_type": "vector",
      "hybrid_score": 0.15065953294329842
    },
    {
      "content": "Deep learning has made breakthrough progress in the field of image recognition",
      "metadata": {
        "source": "Research Paper",
        "category": "Deep Learning",
        "created_at": "2024-01-16",
        "score": 0.17985878230825192
      },
      "score": 0.17985878230825192,
      "search_type": "vector",
      "hybrid_score": 0.12590114761577634
    }
  ]
}





# 5. Delete Documents and Memories by ID

# Prepare test data


curl -X POST "http://192.168.xxx.xxx:22000/vector/test_vector/add_documents" \
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

{
  "status": "success",
  "message": "Document added successfully",
  "results": [
    "fa268a37-1b1e-4296-bd8f-3aeacb11c0bd",
    "b19a2053-e00a-4d52-8077-b9b20c7dc161"
  ]
}



curl -X DELETE "http://192.168.xxx.xxx:22000/vector/test_vector/delete_by_ids" \
  -H "Content-Type: application/json" \
  -d '{
    "documents": [
      "921a1523-3272-4d52-a49d-7c628b509f9d",
      "b5d29803-729a-4efb-8699-5907ec7a02ea",
      "de6f1a69-7b1b-4d0e-9d20-40dfb7242887"
    ]
  }' | jq .


# output

{
  "status": "success",
  "message": "Documents deleted successfully",
  "collection": "test_vector"
}

# 6. Delete All Documents and Memories in the Collection

curl -X DELETE "http://192.168.xxx.xxx:22000/vector/test_vector/delete_all" \
  -H "Content-Type: application/json" \
  -d '{}' | jq .


# 7. Delete Documents by meta field

# Prepare test data


curl -X POST "http://192.168.xxx.xxx:22000/vector/test_vector123/add_documents" \
  -H "Content-Type: application/json" \
  -d '{
    "documents": [
      {
        "page_content": "Ruby is a good development language",
        "metadata": {
          "category": "code",
          "source": "TechnicalDocumentation",
          "created_at": "2024-01-15"
        }
      },
      {
        "page_content": "Rust is a high-performance development language",
        "metadata": {
          "category": "code",
          "source": "ResearchPaper",
          "created_at": "2024-01-16"
        }
      }
    ]
  }' | jq .


# output

{
  "status": "success",
  "message": "Document added successfully",
  "results": [
    "fa268a37-1b1e-4296-bd8f-3aeacb11c0bd",
    "b19a2053-e00a-4d52-8077-b9b20c7dc161"
  ]
}



curl -X DELETE "http://192.168.xxx.xxx:22000/vector/test_vector123/delete_by_metadata_field" \
  -H "Content-Type: application/json" \
  -d '{
    "key": "source",
    "value": "ResearchPaper"
  }' | jq .


# output

{
  "status": "success",
  "message": "Documents deleted successfully",
  "collection": "test_vector123"
}

