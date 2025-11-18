# Memory API Documentation

## Overview
Memory API provides functionality for storing, retrieving, updating, and managing memories, supporting memory management based on users, agents, or run sessions.

## Basic Information
- **Base URL**: `http://<host>:<port>`
- **Content-Type**: `application/json`

## API List

### 1. Add Memory

**Endpoint**: `POST /memories`

**Request Body Parameters**:
- `user_id` (string, optional): User identifier
- `agent_id` (string, optional): Agent identifier  
- `run_id` (string, optional): Run session identifier
- `messages` (array, required): Conversation messages array
  - `role` (string): Role (user/assistant)
  - `content` (string): Message content
- `metadata` (object, optional): Metadata

**Note**: Must provide at least one of `user_id`, `agent_id`, or `run_id`

**Example Request**:
```bash
curl -X POST "http://<host>:<port>/memories" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user1",
    "messages": [
      {
        "role": "user",
        "content": "I like pizza and pasta"
      },
      {
        "role": "assistant", 
        "content": "Okay, I've remembered your dietary preferences"
      }
    ],
    "metadata": {
      "conversation_id": "conv_456",
      "timestamp": "2023-10-01T10:00:00Z"
    }
  }'
```

**Response**:
```json
{
  "status": "success",
  "message": "Memory added successfully",
  "data": {
    "results": [
      {
        "id": "memory_id",
        "memory": "Extracted memory content",
        "event": "ADD"
      }
    ]
  }
}
```

### 2. Get Single Memory

**Endpoint**: `GET /memories/{memory_id}`

**Path Parameters**:
- `memory_id` (string, required): Memory unique identifier

**Example Request**:
```bash
curl -X GET "http://<host>:<port>/memories/memory_id"
```

**Response**:
```json
{
  "status": "success",
  "data": {
    "id": "memory_id",
    "memory": "Memory content",
    "hash": "Content hash value",
    "metadata": {},
    "score": null,
    "created_at": "Creation time",
    "updated_at": "Update time",
    "user_id": "user_id"
  }
}
```

### 3. Get All Memories

**Endpoint**: `POST /memories/get_all`

**Request Body Parameters**:
- `user_id` (string, optional): Filter by user ID
- `agent_id` (string, optional): Filter by agent ID
- `run_id` (string, optional): Filter by run ID
- `limit` (number, optional): Limit on number of results to return

**Note**: Must provide at least one of `user_id`, `agent_id`, or `run_id`

**Example Request**:
```bash
curl -X POST "http://<host>:<port>/memories/get_all" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user1"
  }'
```

**Response**:
```json
{
  "status": "success",
  "data": {
    "memories": [
      {
        "id": "c9dd1492-4832-4f2a-aef4-682ed09d0ee6",
        "memory": "Likes pizza and pasta",
        "hash": "1fa6211ecb07b77eede443e4b82829f0",
        "metadata": {
          "timestamp": "2023-10-01T10:00:00Z",
          "conversation_id": "conv_456"
        },
        "created_at": "2025-08-22T06:28:48.474410-07:00",
        "updated_at": null,
        "user_id": "user1"
      }
    ],
    "count": 1
  }
}
```

### 4. Search Memories

**Endpoint**: `POST /memories/search`

**Request Body Parameters**:
- `query` (string, required): Search query term
- `user_id` (string, optional): Filter by user ID
- `agent_id` (string, optional): Filter by agent ID
- `run_id` (string, optional): Filter by run ID
- `limit` (number, optional): Limit on number of results to return
- `filters` (object, optional): Additional filters

**Note**: Must provide at least one of `user_id`, `agent_id`, or `run_id`

**Example Request**:
```bash
curl -X POST "http://<host>:<port>/memories/search" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "pasta",
    "user_id": "user1",
    "limit": 5
  }'
```

**Response**:
```json
{
  "status": "success",
  "data": {
    "query": "pasta",
    "results": [
      {
        "id": "0e4d8f9f-45b3-4ec8-ae5c-68eb4b42e64c",
        "memory": "Likes pizza and pasta",
        "hash": "1fa6211ecb07b77eede443e4b82829f0",
        "metadata": {
          "timestamp": "2023-10-01T10:00:00Z",
          "conversation_id": "conv_456"
        },
        "score": 0.2985008181035018,
        "created_at": "2025-08-21T23:43:14.879778-07:00",
        "updated_at": null,
        "user_id": "user1"
      },
      {
        "id": "49c8a48c-b8de-4c9c-9909-a86f52bddec2",
        "memory": "Likes basketball and table tennis",
        "hash": "f90939bd2ef7a9d1981e95c5934313c3",
        "metadata": {
          "timestamp": "2023-10-01T10:00:00Z",
          "conversation_id": "conv_456"
        },
        "score": 0.723334049284521,
        "created_at": "2025-08-21T23:46:07.903908-07:00",
        "updated_at": null,
        "user_id": "user1"
      }
    ],
    "count": 2
  }
}
```

### 5. Get Memory History

**Endpoint**: `GET /memories/{memory_id}/history`

**Path Parameters**:
- `memory_id` (string, required): Memory unique identifier

**Example Request**:
```bash
curl -X GET "http://<host>:<port>/memories/memory_id/history"
```

**Response**:
```json
{
  "status": "success",
  "data": {
    "memory_id": "37a54411-c606-4487-bb25-23492bddd145",
    "history": [
      {
        "id": "cb9c8fc7-abb8-46fa-a846-002ed5df05a6",
        "memory_id": "37a54411-c606-4487-bb25-23492bddd145",
        "old_memory": null,
        "new_memory": "Likes pizza and pasta",
        "event": "ADD",
        "created_at": "2025-08-22T05:20:21.455492-07:00",
        "updated_at": null,
        "is_deleted": false,
        "actor_id": null,
        "role": null
      },
      {
        "id": "fa1a3205-231b-41b6-a7fd-91905057a487",
        "memory_id": "37a54411-c606-4487-bb25-23492bddd145",
        "old_memory": "Likes pizza and pasta",
        "new_memory": "I like pizza, pasta, and bread",
        "event": "UPDATE",
        "created_at": "2025-08-22T05:20:21.455492-07:00",
        "updated_at": "2025-08-22T05:39:49.904435-07:00",
        "is_deleted": false,
        "actor_id": null,
        "role": null
      }
    ]
  }
}
```

### 6. Update Single Memory

**Endpoint**: `PUT /memories/{memory_id}`

**Path Parameters**:
- `memory_id` (string, required): Memory unique identifier

**Request Body Parameters**:
- `data` (string, required): New memory content

**Example Request**:
```bash
curl -X PUT "http://<host>:<port>/memories/memory_id" \
  -H "Content-Type: application/json" \
  -d '{
    "data": "New memory content"
  }'
```

**Response**:
```json
{
  "status": "success",
  "message": "Memory updated successfully",
  "data": {
    "message": "Memory updated successfully!"
  }
}
```

### 7. Delete Single Memory

**Endpoint**: `DELETE /memories/{memory_id}`

**Path Parameters**:
- `memory_id` (string, required): Memory unique identifier

**Example Request**:
```bash
curl -X DELETE "http://<host>:<port>/memories/memory_id"
```

**Response**:
```json
{
  "status": "success",
  "message": "Memory deleted successfully",
  "data": {
    "message": "Memory deleted successfully!"
  }
}
```

### 8. Batch Delete Memories

**Endpoint**: `POST /memories/delete`

**Request Body Parameters**:
- `user_id` (string, optional): Delete by user ID
- `agent_id` (string, optional): Delete by agent ID
- `run_id` (string, optional): Delete by run ID

**Note**: Must provide at least one filter condition

**Example Request**:
```bash
curl -X POST "http://<host>:<port>/memories/delete" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user1"
  }'
```

**Response**:
```json
{
  "status": "success",
  "message": "Memories deleted successfully",
  "data": {
    "message": "Memories deleted successfully!"
  }
}
```

### 9. Reset All Memories

**Endpoint**: `POST /reset`

**Example Request**:
```bash
curl -X POST "http://<host>:<port>/reset"
```

**Response**:
```json
{
  "status": "success",
  "message": "All memories reset successfully",
  "data": null
}
```

## Error Responses

When requests lack necessary parameters, API returns error information:

```json
{
  "detail": "Error description"
}
```

Common errors:
- `"At least one of 'user_id', 'agent_id', or 'run_id' must be provided."`
- `"At least one filter is required to delete all memories."`