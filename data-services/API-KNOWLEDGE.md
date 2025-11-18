# Vector Store API Documentation

## Overview
Vector Store API provides functionality for creating vector storage collections, document management, search, and deletion, supporting both vector similarity-based search and full-text search.

## Basic Information
- **Base URL**: `http://192.168.xxx.xxx:22000`
- **Content-Type**: `application/json`

## API List

### 1. Create Collection

**Endpoint**: `POST /create_collection`

**Functionality**: Create a new vector storage collection and add initial documents

**Request Body Parameters**:
- `collection_name` (string, required): Collection name
- `documents` (array, required): Documents array
  - `page_content` (string): Document content
  - `metadata` (object, optional): Metadata

**Example Request**:
```bash
curl -X POST "http://192.168.xxx.xxx:22000/knowledge_pyramid/create_collection" \
  -H "Content-Type: application/json" \
  -d '{
    "collection_name": "test_collection",
    "documents": [
      {
        "page_content": "Python is a popular programming language",
        "metadata": {"author": "Guido van Rossum", "year": 1991}
      }
    ]
  }'
```

**Response**:
```json
{
  "status": "success",
  "message": "Collection 'test_collection' created with 1 documents"
}
```

# Knowledge Pyramid API Documentation

## Overview
Knowledge Pyramid API provides knowledge pyramid functionality, storing documents simultaneously in vector database and memory system, achieving dual storage and retrieval capabilities.

## Basic Information
- **Base URL**: `http://192.168.xxx.xxx:22000`
- **Content-Type**: `application/json`

## API List

### 1. Add Documents to Knowledge Pyramid

**Endpoint**: `POST /knowledge_pyramid/{collection_name}/add_documents`

**Functionality**: Add documents simultaneously to vector database and memory system, building knowledge pyramid

**Path Parameters**:
- `collection_name` (string, required): Collection name

**Request Body Parameters**:
- `documents` (array, required): Documents array
  - `page_content` (string): Document content
  - `metadata` (object, optional): Metadata

**Example Request**:
```bash
curl -X POST "http://192.168.xxx.xxx:22000/knowledge_pyramid/test_knowledge/add_documents" \
  -H "Content-Type: application/json" \
  -d '{
    "documents": [
      {
        "page_content": "Machine learning is one of the core technologies of artificial intelligence",
        "metadata": {
          "category": "AI",
          "source": "Technical documentation",
          "created_at": "2024-01-15"
        }
      },
      {
        "page_content": "Deep learning has made breakthrough progress in the field of image recognition",
        "metadata": {
          "category": "Deep Learning",
          "source": "Research paper",
          "created_at": "2024-01-16"
        }
      }
    ]
  }'
```

**Response**:
```json
{
  "status": "success",
  "message": "Document added successfully",
  "document_ids": [
    "d1044954-c55b-4961-8ad3-074a437cc210",
    "0854b15c-3623-4c9c-a40d-fd3fa170f357"
  ],
  "memory": {
    "results": [
      {
        "id": "697dcc7e-6007-407b-977c-4828e0ec6821",
        "memory": "Machine learning is one of the core technologies of artificial intelligence",
        "event": "ADD"
      },
      {
        "id": "645e3cbc-3b9b-448c-a819-8de18468c0ce",
        "memory": "Deep learning has made breakthrough progress in the field of image recognition",
        "event": "ADD"
      }
    ]
  }
}
```

### 2. Search Documents from Knowledge Pyramid

**Endpoint**: `POST /knowledge_pyramid/{collection_name}/search`

**Functionality**: Search relevant documents simultaneously from vector database and memory system, returning dual search results

**Path Parameters**:
- `collection_name` (string, required): Collection name

**Query Parameters**:
- `query` (string, required): Search query term
- `search_type` (string, optional): Search type, optional values: `vector` (vector search), `fulltext` (full-text search), default: `vector`
- `limit` (number, optional): Number of results to return, default: 10

**Example Request**:
```bash
curl -X POST "http://192.168.xxx.xxx:22000/knowledge_pyramid/test_knowledge/search" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Artificial intelligence technology",
    "search_type": "vector",
    "limit": 5
  }'
```

**Response**:
```json
{
  "status": "success",
  "collection": "test_knowledge",
  "search_type": "vector",
  "vector_results": [
    {
      "content": "Machine learning is one of the core technologies of artificial intelligence",
      "metadata": {
        "category": "AI",
        "source": "Technical documentation",
        "created_at": "2024-01-15",
        "score": 0.892
      },
      "score": 0.892,
      "search_type": "vector"
    },
    {
      "content": "Deep learning has made breakthrough progress in the field of image recognition",
      "metadata": {
        "category": "Deep Learning",
        "source": "Research paper",
        "created_at": "2024-01-16",
        "score": 0.756
      },
      "score": 0.756,
      "search_type": "vector"
    }
  ],
  "memory_result": {
    "query": "Artificial intelligence technology",
    "results": [
      {
        "memory_id": "mem_1234567890",
        "user_id": "test_knowledge",
        "content": "Machine learning is one of the core technologies of artificial intelligence, deep learning has made breakthrough progress in the field of image recognition",
        "similarity": 0.875,
        "created_at": "2024-01-20T10:30:00Z",
        "metadata": {
          "collection": "test_knowledge",
          "document_count": 2
        }
      }
    ],
    "count": 1
  }
}
```

## Feature Highlights

### Dual Storage Mechanism
- **Vector Database Storage**: For efficient semantic similarity search
- **Memory System Storage**: For context understanding and conversation memory

### Search Advantages
1. **Semantic Search**: Find semantically related documents through vector search
2. **Context Understanding**: Understand document context relationships through memory system
3. **Comprehensive Scoring**: Combine confidence scores from both search results

### Applicable Scenarios
- **Knowledge Management Systems**: Require both semantic search and context understanding
- **Intelligent Q&A Systems**: Combine fact retrieval and conversation memory
- **Document Analysis**: Multi-dimensional document retrieval and analysis

## Parameter Description

### Search Type (search_type)
- `vector`: Semantic search based on embedding vectors, suitable for concept matching
- `fulltext`: Full-text search based on keywords, suitable for exact matching

### Metadata Fields
- Can contain any custom fields for document classification and filtering
- Recommended to include: category, source, created_at, author and other standard fields

## Notes

1. **Collection Consistency**: Ensure using the same collection name for add and search operations
2. **Memory Usage**: Knowledge pyramid consumes more storage space (dual storage)
3. **Search Performance**: Performing both searches simultaneously may slightly increase response time
4. **Data Synchronization**: Add operations ensure data consistency between vector database and memory database

## Error Handling

API returns standardized error response format:

```json
{
  "status": "error",
  "message": "Error description"
}
```

Common error scenarios:
- Collection does not exist
- Missing request parameters or format errors
- Memory service unavailable
- Internal server error

## Best Practices

1. **Batch Addition**: Recommend batch adding documents to improve performance
2. **Reasonable Metadata**: Use meaningful metadata for subsequent retrieval and filtering
3. **Search Optimization**: Choose appropriate search type based on requirements
4. **Usage Monitoring**: Monitor storage usage to avoid excessive storage

### 3. Delete Documents and Memories by ID

**Endpoint**: `DELETE /knowledge_pyramid/{collection_name}/delete_by_ids`

**Functionality**: Delete corresponding documents and memories based on specified document IDs and memory IDs

**Path Parameters**:
- `collection_name` (string, required): Collection name

**Request Body Parameters**:
- `documents` (array, required): Array of document IDs to delete
- `memorys` (array, required): Array of memory IDs to delete

**Example Request**:
```bash
curl -X DELETE "http://192.168.xxx.xxx:22000/knowledge_pyramid/test_knowledge/delete_by_ids" \
  -H "Content-Type: application/json" \
  -d '{
    "documents": [
      "d1044954-c55b-4961-8ad3-074a437cc210",
      "0854b15c-3623-4c9c-a40d-fd3fa170f357"
    ],
    "memorys": [
      "697dcc7e-6007-407b-977c-4828e0ec6821",
      "645e3cbc-3b9b-448c-a819-8de18468c0ce"
    ]
  }'
```

**Response**:
```json
{
  "status": "success",
  "message": "Documents and Memories deleted successfully",
  "vector_documents": [
    "d1044954-c55b-4961-8ad3-074a437cc210",
    "0854b15c-3623-4c9c-a40d-fd3fa170f357"
  ],
  "memory_memorys": [
    "697dcc7e-6007-407b-977c-4828e0ec6821",
    "645e3cbc-3b9b-448c-a819-8de18468c0ce"
  ]
}
```

### 4. Delete All Documents and Memories in Collection

**Endpoint**: `DELETE /knowledge_pyramid/{collection_name}/delete_all`

**Functionality**: Delete all documents and memories in the specified collection

**Path Parameters**:
- `collection_name` (string, required): Collection name

**Request Body Parameters**:
**None (empty object)**

**Example Request**:
```bash
curl -X DELETE "http://192.168.xxx.xxx:22000/knowledge_pyramid/test_knowledge/delete_all" \
  -H "Content-Type: application/json" \
  -d '{}'
```

**Response**:
```json
{
  "status": "success",
  "message": "Documents and Memories deleted successfully",
  "collection": "test_knowledge"
}
```