# Signature Records API Documentation

## Overview

This document provides complete API interface specifications for the signature records management system, including create, query, update, delete operations and more.

---

## 1. Create Signature Record

**Create Single Signature Record**

- **Endpoint**: `POST /signatures`
- **Content-Type**: `application/json`

### Request Example
```bash
curl -X POST "http://192.168.xxx.xxx:22000/signatures" \
-H "Content-Type: application/json" \
-d '{
    "sig_type": "application",
    "discovery_mode": "auto",
    "fingerprint": "fp_001",
    "location_info": {
        "ip": "192.168.1.100",
        "url": "https://example.com"
    },
    "metadata_content": {
        "summary": "Test signature summary",
        "type": "test"
    },
    "semantic_domain": "semantic_domain",
    "agent_card": "agent_card",
    "dd_namespace": "test_namespace",
    "dd_name": "test_name"
}' | jq .
```

### Response Example
```json
{
  "status": "success",
  "data": {
    "sig_id": "86353825-902f-4403-b721-989e76859342",
    "sig_type": "application",
    "discovery_mode": "auto",
    "fingerprint": "fp_001",
    "location_info": {
        "ip": "192.168.1.100",
        "url": "https://example.com"
    },
    "metadata_content": {
        "summary": "Test signature summary",
        "type": "test"
    },
    "semantic_domain": "semantic_domain",
    "agent_card": "agent_card",
    "dd_namespace": "test_namespace",
    "dd_name": "test_name"
  },
  "message": "signature create success",
  "count": null
}
```

### Request Fields

- `sig_type` (required): Signature type, one of: `application`, `database`, `api`, `file_system`
- `discovery_mode` (required): Discovery mode, one of: `auto`, `manual`
- `fingerprint` (required): Fingerprint hash for change detection
- `location_info` (optional): Location information as JSON object (e.g., IP, URL, DB_Instance)
- `metadata_content` (optional): Metadata content as JSON object (e.g., table structure, fields, types)
- `semantic_domain` (optional): Semantic domain from analysis
- `agent_card` (optional): Agent card information for agent creation
- `dd_namespace` (optional): DD namespace
- `dd_name` (optional): DD name

---

## 2. Batch Create Signature Records

**Batch Create Multiple Signature Records**

- **Endpoint**: `POST /signatures/batch`
- **Content-Type**: `application/json`

### Request Example
```bash
curl -X POST "http://192.168.xxx.xxx:22000/signatures/batch" \
-H "Content-Type: application/json" \
-d '[
    {
        "sig_type": "database",
        "discovery_mode": "manual",
        "fingerprint": "fp_002",
        "location_info": {
            "ip": "192.168.1.101"
        },
        "metadata_content": {
            "summary": "Signature summary 2"
        },
        "semantic_domain": "semantic_domain",
        "agent_card": "agent_card",
        "dd_namespace": "namespace2",
        "dd_name": "name2"
    },
    {
        "sig_type": "api",
        "discovery_mode": "auto",
        "fingerprint": "fp_003",
        "location_info": {
            "url": "https://api.example.com"
        },
        "metadata_content": {
            "summary": "Signature summary 3"
        },
        "semantic_domain": "semantic_domain",
        "agent_card": "agent_card",
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
  "message": "batch create 2 signatures success",
  "count": null
}
```

---

## 3. Get Signature Record by Primary Key

**Get Single Signature Record by sig_id**

- **Endpoint**: `GET /signatures/{sig_id}`

### Request Example
```bash
curl -X GET "http://192.168.xxx.xxx:22000/signatures/86353825-902f-4403-b721-989e76859342" | jq .
```

### Response Example
```json
{
  "status": "success",
  "data": {
    "sig_id": "86353825-902f-4403-b721-989e76859342",
    "sig_type": "application",
    "discovery_mode": "auto",
    "fingerprint": "fp_001",
    "location_info": {
        "ip": "192.168.1.100",
        "url": "https://example.com"
    },
    "metadata_content": {
        "summary": "Test signature summary",
        "type": "test"
    },
    "semantic_domain": "semantic_domain",
    "agent_card": "agent_card",
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

## 4. Get Signature Record by Fingerprint

**Get Signature Record by Fingerprint Value**

- **Endpoint**: `GET /signatures/fingerprint/{fingerprint}`

### Request Example
```bash
curl -X GET "http://192.168.xxx.xxx:22000/signatures/fingerprint/fp_001" | jq .
```

### Response Example
```json
{
  "status": "success",
  "data": {
    "sig_id": "86353825-902f-4403-b721-989e76859342",
    "sig_type": "application",
    "discovery_mode": "auto",
    "fingerprint": "fp_001",
    "location_info": {
        "ip": "192.168.1.100",
        "url": "https://example.com"
    },
    "metadata_content": {
        "summary": "Test signature summary",
        "type": "test"
    },
    "semantic_domain": "semantic_domain",
    "agent_card": "agent_card",
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

## 5. Search Signature Records by DD Information

**Search Signature Records by DD Namespace and Name**

- **Endpoint**: `POST /signatures/search/by-dd`
- **Content-Type**: `application/json`

### Request Example
```bash
curl -X POST "http://192.168.xxx.xxx:22000/signatures/search/by-dd" \
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
      "sig_id": "86353825-902f-4403-b721-989e76859342",
      "sig_type": "application",
      "discovery_mode": "auto",
      "fingerprint": "fp_001",
      "location_info": {
          "ip": "192.168.1.100",
          "url": "https://example.com"
      },
      "metadata_content": {
          "summary": "Test signature summary",
          "type": "test"
      },
      "semantic_domain": "semantic_domain",
      "agent_card": "agent_card",
      "dd_namespace": "test_namespace",
      "dd_name": "test_name",
      "created_at": "2024-01-01T00:00:00",
      "updated_at": "2024-01-01T00:00:00"
    }
  ],
  "count": 1
}
```

---

## 6. Update Signature Record

**Update Signature Record by sig_id**

- **Endpoint**: `PUT /signatures/{sig_id}`
- **Content-Type**: `application/json`

### Request Example
```bash
curl -X PUT "http://192.168.xxx.xxx:22000/signatures/86353825-902f-4403-b721-989e76859342" \
-H "Content-Type: application/json" \
-d '{
    "fingerprint": "fp_001_updated",
    "metadata_content": {
        "summary": "Updated signature summary"
    },
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
    "sig_id": "86353825-902f-4403-b721-989e76859342",
    "sig_type": "application",
    "discovery_mode": "auto",
    "fingerprint": "fp_001_updated",
    "location_info": {
        "ip": "192.168.1.100",
        "url": "https://example.com"
    },
    "metadata_content": {
        "summary": "Updated signature summary"
    },
    "semantic_domain": "semantic_domain",
    "agent_card": "agent_card",
    "dd_namespace": "updated_namespace",
    "dd_name": "updated_name",
    "created_at": "2024-01-01T00:00:00",
    "updated_at": "2024-01-01T01:00:00"
  },
  "message": "signature updated success",
  "count": null
}
```

---

## 7. Delete Signature Record

**Delete Signature Record by sig_id**

- **Endpoint**: `DELETE /signatures/{sig_id}`

### Request Example
```bash
curl -X DELETE "http://192.168.xxx.xxx:22000/signatures/86353825-902f-4403-b721-989e76859342" | jq .
```

### Response Example
```json
{
  "status": "success",
  "data": null,
  "message": "signature deleted success",
  "count": null
}
```

---

## 8. Delete Signature Records by DD Information

**Delete Signature Records by DD Namespace and Name**

- **Endpoint**: `DELETE /signatures/dd_info/{dd_namespace}/{dd_name}`

### Request Example
```bash
curl -X DELETE "http://192.168.xxx.xxx:22000/signatures/dd_info/namespace2/name2" | jq .
```

### Response Example
```json
{
  "status": "success",
  "data": null,
  "message": "the signature of DD namespace 'namespace2', DD name 'name2' is deleted success",
  "count": null
}
```

---

## 9. Check Signature Record Existence

**Check if Signature Record Exists by sig_id**

- **Endpoint**: `GET /signatures/{sig_id}/exists`

### Request Example
```bash
curl -X GET "http://192.168.xxx.xxx:22000/signatures/90daba0c-73aa-44cd-b563-603d206b112c/exists" | jq .
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

## 10. Check Signature Record Existence by DD Information

**Check if Signature Record Exists by DD Information**

- **Endpoint**: `GET /signatures/dd_info/{dd_namespace}/{dd_name}/exists`

### Request Example
```bash
curl -X GET "http://192.168.xxx.xxx:22000/signatures/dd_info/namespace3/name3/exists" | jq .
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

## 11. Get Total Signature Record Count

**Get Total Number of Signature Records in the System**

- **Endpoint**: `GET /signatures/status/count`

### Request Example
```bash
curl -X GET "http://192.168.xxx.xxx:22000/signatures/status/count" | jq .
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

### Signature Fields

- `sig_id`: Primary key (UUID string, auto-generated)
- `sig_type`: Signature type - `application`, `database`, `api`, or `file_system`
- `discovery_mode`: Discovery mode - `auto` or `manual`
- `fingerprint`: Fingerprint hash value for change detection (string)
- `location_info`: Location information as JSON object (optional)
- `metadata_content`: Metadata content as JSON object (optional)
- `semantic_domain`: Semantic domain from analysis (optional, text)
- `agent_card`: Agent card information for agent creation (optional, text)
- `dd_namespace`: DD namespace (optional, string)
- `dd_name`: DD name (optional, string)
- `created_at`: Creation timestamp (auto-generated)
- `updated_at`: Last update timestamp (auto-updated)
