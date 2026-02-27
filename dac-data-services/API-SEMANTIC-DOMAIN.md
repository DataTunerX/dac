# Semantic Domain Records API Documentation

## Overview

This document provides complete API interface specifications for the semantic domain records management system, including create, query, update, delete operations and more.

---

## 1. Create Semantic Domain Record

**Create Single Semantic Domain Record**

- **Endpoint**: `POST /semantic_domains`
- **Content-Type**: `application/json`

### Request Example
```bash
curl -X POST "http://192.168.xxx.xxx:22000/semantic_domains" \
-H "Content-Type: application/json" \
-d '{
    "semantic_domain": "This is a test semantic domain for application services",
    "agent_card": "{\"name\": \"test_agent\", \"description\": \"Test agent for semantic domain\"}",
    "dd_namespace": "test_namespace",
    "dd_name": "test_name"
}' | jq .
```

### Response Example
```json
{
  "status": "success",
  "data": {
    "semantic_domain_id": "86353825-902f-4403-b721-989e76859342",
    "semantic_domain": "This is a test semantic domain for application services",
    "agent_card": "{\"name\": \"test_agent\", \"description\": \"Test agent for semantic domain\"}",
    "dd_namespace": "test_namespace",
    "dd_name": "test_name",
    "created_at": "2024-01-01T00:00:00",
    "updated_at": "2024-01-01T00:00:00"
  },
  "message": "semantic domain create success",
  "count": null
}
```

### Request Fields

- `semantic_domain_id` (optional): Semantic domain ID (UUID string, auto-generated if not provided)
- `semantic_domain` (optional): Semantic domain from analysis (text)
- `agent_card` (optional): Agent card information for agent creation (text, typically JSON string)
- `dd_namespace` (optional): DD namespace (string)
- `dd_name` (optional): DD name (string)

---

## 2. Batch Create Semantic Domain Records

**Batch Create Multiple Semantic Domain Records**

- **Endpoint**: `POST /semantic_domains/batch`
- **Content-Type**: `application/json`

### Request Example
```bash
curl -X POST "http://192.168.xxx.xxx:22000/semantic_domains/batch" \
-H "Content-Type: application/json" \
-d '[
    {
        "semantic_domain": "Semantic domain for database services",
        "agent_card": "{\"name\": \"db_agent\", \"type\": \"database\"}",
        "dd_namespace": "namespace2",
        "dd_name": "name2"
    },
    {
        "semantic_domain": "Semantic domain for API services",
        "agent_card": "{\"name\": \"api_agent\", \"type\": \"api\"}",
        "dd_namespace": "namespace3",
        "dd_name": "name3"
    }
]' | jq .
```

### Response Example
```json
{
  "status": "success",
  "data": {
    "count": 2
  },
  "message": "batch create 2 semantic domains success",
  "count": null
}
```

---

## 3. Get Semantic Domain Record by Primary Key

**Get Single Semantic Domain Record by semantic_domain_id**

- **Endpoint**: `GET /semantic_domains/{semantic_domain_id}`

### Request Example
```bash
curl -X GET "http://192.168.xxx.xxx:22000/semantic_domains/86353825-902f-4403-b721-989e76859342" | jq .
```

### Response Example
```json
{
  "status": "success",
  "data": {
    "semantic_domain_id": "86353825-902f-4403-b721-989e76859342",
    "semantic_domain": "This is a test semantic domain for application services",
    "agent_card": "{\"name\": \"test_agent\", \"description\": \"Test agent for semantic domain\"}",
    "dd_namespace": "test_namespace",
    "dd_name": "test_name",
    "created_at": "2024-01-01T00:00:00",
    "updated_at": "2024-01-01T00:00:00"
  },
  "message": null,
  "count": null
}
```

---

## 4. Search Semantic Domain Records by DD Information

**Search Semantic Domain Records by DD Namespace and Name**

- **Endpoint**: `POST /semantic_domains/search/by-dd`
- **Content-Type**: `application/json`

### Request Example
```bash
curl -X POST "http://192.168.xxx.xxx:22000/semantic_domains/search/by-dd" \
-H "Content-Type: application/json" \
-d '{
    "dd_namespace": "test_namespace",
    "dd_name": "test_name"
}' | jq .
```

### Response Example
```json
{
  "status": "success",
  "data": [
    {
      "semantic_domain_id": "86353825-902f-4403-b721-989e76859342",
      "semantic_domain": "This is a test semantic domain for application services",
      "agent_card": "{\"name\": \"test_agent\", \"description\": \"Test agent for semantic domain\"}",
      "dd_namespace": "test_namespace",
      "dd_name": "test_name",
      "created_at": "2024-01-01T00:00:00",
      "updated_at": "2024-01-01T00:00:00"
    }
  ],
  "count": 1
}
```

### Request Fields

- `dd_namespace` (required): DD namespace (string)
- `dd_name` (required): DD name (string)

---

## 5. Update Semantic Domain Record

**Update Semantic Domain Record by semantic_domain_id**

- **Endpoint**: `PUT /semantic_domains/{semantic_domain_id}`
- **Content-Type**: `application/json`

### Request Example
```bash
curl -X PUT "http://192.168.xxx.xxx:22000/semantic_domains/86353825-902f-4403-b721-989e76859342" \
-H "Content-Type: application/json" \
-d '{
    "semantic_domain": "Updated semantic domain content",
    "agent_card": "{\"name\": \"updated_agent\", \"description\": \"Updated agent card\"}",
    "dd_namespace": "updated_namespace",
    "dd_name": "updated_name"
}' | jq .
```

**Note**: All fields in the update request are optional. Only provided fields will be updated.

### Response Example
```json
{
  "status": "success",
  "data": {
    "semantic_domain_id": "86353825-902f-4403-b721-989e76859342",
    "semantic_domain": "Updated semantic domain content",
    "agent_card": "{\"name\": \"updated_agent\", \"description\": \"Updated agent card\"}",
    "dd_namespace": "updated_namespace",
    "dd_name": "updated_name",
    "created_at": "2024-01-01T00:00:00",
    "updated_at": "2024-01-01T01:00:00"
  },
  "message": "semantic domain updated success",
  "count": null
}
```

---

## 6. Delete Semantic Domain Record

**Delete Semantic Domain Record by semantic_domain_id**

- **Endpoint**: `DELETE /semantic_domains/{semantic_domain_id}`

### Request Example
```bash
curl -X DELETE "http://192.168.xxx.xxx:22000/semantic_domains/86353825-902f-4403-b721-989e76859342" | jq .
```

### Response Example
```json
{
  "status": "success",
  "data": null,
  "message": "semantic domain deleted success",
  "count": null
}
```

---

## 7. Delete Semantic Domain Records by DD Information

**Delete Semantic Domain Records by DD Namespace and Name**

- **Endpoint**: `DELETE /semantic_domains/dd_info/{dd_namespace}/{dd_name}`

### Request Example
```bash
curl -X DELETE "http://192.168.xxx.xxx:22000/semantic_domains/dd_info/namespace2/name2" | jq .
```

### Response Example
```json
{
  "status": "success",
  "data": null,
  "message": "the semantic domain of DD namespace 'namespace2', DD name 'name2' is deleted success",
  "count": null
}
```

---

## 8. Check Semantic Domain Record Existence

**Check if Semantic Domain Record Exists by semantic_domain_id**

- **Endpoint**: `GET /semantic_domains/{semantic_domain_id}/exists`

### Request Example
```bash
curl -X GET "http://192.168.xxx.xxx:22000/semantic_domains/86353825-902f-4403-b721-989e76859342/exists" | jq .
```

### Response Example
```json
{
  "status": "success",
  "data": {
    "exists": true
  },
  "message": null,
  "count": null
}
```

---

## 9. Check Semantic Domain Record Existence by DD Information

**Check if Semantic Domain Record Exists by DD Information**

- **Endpoint**: `GET /semantic_domains/dd_info/{dd_namespace}/{dd_name}/exists`

### Request Example
```bash
curl -X GET "http://192.168.xxx.xxx:22000/semantic_domains/dd_info/namespace3/name3/exists" | jq .
```

### Response Example
```json
{
  "status": "success",
  "data": {
    "exists": true
  },
  "message": null,
  "count": null
}
```

---

## 10. Get Total Semantic Domain Record Count

**Get Total Number of Semantic Domain Records in the System**

- **Endpoint**: `GET /semantic_domains/status/count`

### Request Example
```bash
curl -X GET "http://192.168.xxx.xxx:22000/semantic_domains/status/count" | jq .
```

### Response Example
```json
{
  "status": "success",
  "data": {
    "total_count": 1
  },
  "message": null,
  "count": null
}
```

---

## General Response Format

All API responses follow this format:

```json
{
  "status": "success|error",
  "data": { ... },
  "message": "Operation result message",
  "count": "Number of data items (if applicable)"
}
```

---

## Field Reference

### Semantic Domain Fields

- `semantic_domain_id`: Primary key (UUID string, auto-generated if not provided)
- `semantic_domain`: Semantic domain from analysis (optional, text)
- `agent_card`: Agent card information for agent creation (optional, text, typically JSON string)
- `dd_namespace`: DD namespace (optional, string)
- `dd_name`: DD name (optional, string)
- `created_at`: Creation timestamp (auto-generated)
- `updated_at`: Last update timestamp (auto-updated)

---

## Error Responses

### Common Error Codes

- `400 Bad Request`: Invalid request parameters or missing required fields
- `404 Not Found`: Resource not found (e.g., semantic domain with given ID doesn't exist)
- `500 Internal Server Error`: Server-side error during processing

### Error Response Example
```json
{
  "status": "error",
  "data": null,
  "message": "semantic domain not found",
  "count": null
}
```

---

## Notes

1. **Auto-generated IDs**: If `semantic_domain_id` is not provided in the create request, the system will automatically generate a UUID.

2. **Timestamps**: `created_at` and `updated_at` are automatically managed by the system. `created_at` is set on record creation, and `updated_at` is automatically updated whenever the record is modified.

3. **Agent Card Format**: The `agent_card` field is typically stored as a JSON string. When creating or updating records, ensure the JSON is properly escaped or stringified.

4. **DD Information**: The combination of `dd_namespace` and `dd_name` can be used to group and search related semantic domain records.

5. **Batch Operations**: Batch create operations will succeed only if all records in the batch are successfully created. If any record fails, the entire batch operation will fail.
