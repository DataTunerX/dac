# History Records Management API Documentation

## Overview
This document provides API interface specifications for history records management, including two main functionalities: creating history records and searching history records.

---

## 1. Create History Record

Create new conversation history records.

### Basic Information
- **Endpoint**: `POST /history/create`
- **Content-Type**: `application/json`

### Request Parameters

#### Request Body (CreateHistoryRequest)
- `user_id` (string, optional): User identifier
- `agent_id` (string, optional): Agent identifier  
- `run_id` (string, optional): Run session identifier
- `messages` (array, required): Conversation messages array
  - `role` (string): Role (user/assistant)
  - `content` (string): Message content

### Request Example
```bash
curl -X POST "http://192.168.xxx.xxx:22000/history/create" \
-H "Content-Type: application/json" \
-d '{
    "user_id": "user_001",
    "agent_id": "agent_001", 
    "run_id": "run_001",
    "messages": [
      {
        "role": "user",
        "content": "I like pizza and pasta"
      },
      {
        "role": "assistant", 
        "content": "Okay, I've remembered your dietary preferences"
      }
    ]
}' | jq .
```

### Response Parameters

#### Response Body (CreateHistoryResponse)
| Field Name | Type | Description |
|------------|------|-------------|
| `status` | string | Request status ("success" or "error") |
| `hid` | string | Created history record unique identifier |
| `message` | string | Operation result message |

### Response Example
```json
{
  "status": "success",
  "hid": "86353825-902f-4403-b721-989e76859342",
  "message": "history add success"
}
```

### Error Handling
- **500 Internal Server Error**: Internal server error
  ```json
  {
    "detail": "Failed to create history record: [error details]"
  }
  ```

---

## 2. Search History Records

Retrieve history records based on user ID, agent ID, and run ID.

### Basic Information
- **Endpoint**: `POST /history/search`
- **Content-Type**: `application/json`

### Request Parameters

#### Request Body (SearchHistoryRequest)
| Field Name | Type | Required | Description |
|------------|------|----------|-------------|
| `user_id` | string | Yes | User unique identifier |
| `agent_id` | string | Yes | Agent unique identifier |
| `run_id` | string | Yes | Run session unique identifier |
| `limit` | int | No | Limit on number of records to return (optional) |

### Request Example
```bash
curl -X POST "http://192.168.xxx.xxx:22000/history/search" \
-H "Content-Type: application/json" \
-d '{
    "user_id": "user_001",
    "agent_id": "agent_001",
    "run_id": "run_001",
    "limit": 10
}' | jq .
```

### Response Parameters

#### Response Body (SearchHistoryResponse)
| Field Name | Type | Description |
|------------|------|-------------|
| `status` | string | Request status ("success" or "error") |
| `data` | array | History records list |
| `total` | int | Total number of records returned |
| `message` | string | Operation result message |

#### HistoryRecordResponse Object
| Field Name | Type | Description |
|------------|------|-------------|
| `hid` | string | History record unique identifier |
| `user_id` | string | User unique identifier |
| `agent_id` | string | Agent unique identifier |
| `run_id` | string | Run session unique identifier |
| `messages` | array | Conversation content |
| `created_at` | datetime | Record creation time |
| `updated_at` | datetime | Record update time |

### Response Example
```json
{
  "status": "success",
  "data": [
    {
      "hid": "0fcf4c39-0389-44c7-8079-809c66bc0fcd",
      "user_id": "user_001",
      "agent_id": "agent_001",
      "run_id": "run_001",
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
      "created_at": "2025-10-03T22:58:27",
      "updated_at": "2025-10-03T22:58:27"
    }
  ],
  "total": 1,
  "message": "found 1 items"
}
```

### Error Handling
- **500 Internal Server Error**: Internal server error
  ```json
  {
    "detail": "search history error: [error details]"
  }
  ```