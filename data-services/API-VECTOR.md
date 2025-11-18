# Vector Database API Documentation

## Overview
This API provides collection management and document operations for vector databases, supporting vector search, full-text search, and hybrid search.

## Basic Information
- **Base URL**: `http://192.168.xxx.xxx:22000`
- **Content-Type**: `application/json`

---

## 1. Create Collection

### Endpoint
```
POST /vector/create_collection
```

### Description
Create a new vector collection, with the option to add initial documents simultaneously.

### Request Body
```json
{
    "collection_name": "string",
    "documents": [
        {
            "page_content": "string",
            "metadata": {
                "author": "string",
                "year": "number",
                // Other custom metadata fields
            }
        }
    ]
}
```

### Parameter Description
- `collection_name`: Collection name (required)
- `documents`: Initial document list (optional)

### Response Example
```json
{
    "status": "success",
    "message": "Collection test_vector created successfully or exist already"
}
```

---

## 2. Delete Collection

### Endpoint
```
DELETE /vector/delete_collection
```

### Description
Delete the specified vector collection.

### Request Body
```json
{
    "collection_name": "string"
}
```

### Response Example
```json
{
    "status": "success",
    "message": "Collection 'test_vector' deleted successfully"
}
```

---

## 3. Add Documents

### Endpoint
```
POST /vector/{collection_name}/add_documents
```

### Description
Add one or more documents to the specified collection.

### Path Parameters
- `collection_name`: Target collection name

### Request Body
```json
{
    "documents": [
        {
            "page_content": "string",
            "metadata": {
                "category": "string",
                "source": "string",
                "created_at": "string",
                // Other custom metadata fields
            }
        }
    ]
}
```

### Response Example
```json
{
    "status": "success",
    "message": "Document added successfully",
    "results": [
        "29a2a9f4-ceef-4736-9b5c-1b2c60b46431",
        "88d353bf-0240-4557-945c-9d266a94cf60"
    ]
}
```

### Response Field Description
- `results`: List of added document IDs

---

## 4. Search Documents

### Endpoint
```
POST /vector/{collection_name}/search
```

### Description
Search for relevant documents in the specified collection, supporting three search modes.

### Path Parameters
- `collection_name`: Target collection name

### Request Body
```json
{
    "query": "string",
    "search_type": "vector|fulltext|hybrid",
    "limit": 100,
    "hybrid_threshold": 0.1,
    "vector_weight": 0.5,
    "fulltext_weight": 0.5
}
```

### Parameter Description
- `query`: Search query text (required)
- `search_type`: Search type (required)
  - `vector`: Vector similarity search
  - `fulltext`: Full-text search
  - `hybrid`: Hybrid search
- `limit`: Limit on number of results to return (default: 100)
- `hybrid_threshold`: Hybrid search threshold (default: 0.1)
- `vector_weight`: Vector search weight (used in hybrid search, default: 0.5)
- `fulltext_weight`: Full-text search weight (used in hybrid search, default: 0.5)

### Search Type Description

#### 4.1 Vector Search (vector)
Semantic similarity-based search, where larger score indicates higher similarity.

**Request Example**
```json
{
    "query": "What is Java",
    "search_type": "vector",
    "limit": 100,
    "hybrid_threshold": 0.1
}
```

**Response Example**
```json
{
    "status": "success",
    "collection": "test_vector",
    "search_type": "vector",
    "result": [
        {
            "content": "Machine learning is one of the core technologies of artificial intelligence",
            "metadata": {
                "source": "Technical documentation",
                "category": "AI",
                "created_at": "2024-01-15",
                "score": 0.3262292438354425
            },
            "score": 0.3262292438354425,
            "search_type": "vector",
            "hybrid_score": 0.0
        }
    ]
}
```

#### 4.2 Full-text Search (fulltext)
Text search based on keyword matching.

**Request Example**
```json
{
    "query": "fox jumps",
    "search_type": "fulltext",
    "limit": 5,
    "hybrid_threshold": 0.01
}
```

**Response Example**
```json
{
    "status": "success",
    "collection": "test_vector",
    "search_type": "fulltext",
    "result": [
        {
            "content": "The quick brown fox jumps over the lazy dog",
            "metadata": {
                "source": "Research paper",
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
```

#### 4.3 Hybrid Search (hybrid)
Hybrid mode combining vector search and full-text search.

**Request Example**
```json
{
    "query": "Java",
    "search_type": "hybrid",
    "limit": 5,
    "hybrid_threshold": 0.1,
    "vector_weight": 0.5,
    "fulltext_weight": 0.5
}
```

**Response Example**
```json
{
    "status": "success",
    "collection": "test_vector",
    "search_type": "hybrid",
    "result": [
        {
            "content": "Machine learning is one of the core technologies of artificial intelligence",
            "metadata": {
                "source": "Technical documentation",
                "category": "AI",
                "created_at": "2024-01-15",
                "score": 0.21522790420471205
            },
            "score": 0.21522790420471205,
            "search_type": "vector",
            "hybrid_score": 0.15065953294329842
        }
    ]
}
```

---

## 5. Delete Documents by ID

### Endpoint
```
DELETE /vector/{collection_name}/delete_by_ids
```

### Description
Delete documents in the specified collection based on document IDs.

### Path Parameters
- `collection_name`: Target collection name

### Request Body
```json
{
    "documents": [
        "uuid1",
        "uuid2",
        "uuid3"
    ]
}
```

### Response Example
```json
{
    "status": "success",
    "message": "Documents deleted successfully",
    "collection": "test_vector"
}
```

---

## 6. Delete All Documents in Collection

### Endpoint
```
DELETE /vector/{collection_name}/delete_all
```

### Description
Delete all documents in the specified collection.

### Path Parameters
- `collection_name`: Target collection name

### Request Body
```json
{}
```

### Response Example
```json
{
    "status": "success",
    "message": "All documents deleted successfully",
    "collection": "test_vector"
}
```

---

## Error Response

All API endpoints may return the following error format:

```json
{
    "status": "error",
    "message": "Error description",
    "error_code": "ERROR_TYPE"
}
```

## Notes

1. **Collection Name**: Collection names should be unique within the system
2. **Document ID**: UUID automatically generated when adding documents, used for subsequent deletion operations
3. **Search Score**: For vector search, larger score values indicate higher similarity
4. **Hybrid Search**: Larger `hybrid_threshold` values mean stricter filtering conditions and more similar results