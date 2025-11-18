# Fingerprint Records API Documentation

## Overview

This document provides complete API interface specifications for the fingerprint records management system, including create, query, update, delete operations and more.

---

## 1. Create Fingerprint Record

**Create Single Fingerprint Record**

- **Endpoint**: `POST /fingerprints`
- **Content-Type**: `application/json`

### Request Example
```bash
curl -X POST "http://192.168.xxx.xxx:22000/fingerprints" \
-H "Content-Type: application/json" \
-d '{
    "fingerprint_id": "fp_001",
    "fingerprint_summary": "Test fingerprint summary",
    "agent_info_name": "Test Agent",
    "agent_info_description": "Test Agent description",
    "dd_namespace": "test_namespace",
    "dd_name": "test_name"
}' | jq .
```

### Response Example
```json
{
  "status": "success",
  "data": {
    "fid": "86353825-902f-4403-b721-989e76859342",
    "fingerprint_id": "fp_001",
    "fingerprint_summary": "Test fingerprint summary",
    "agent_info_name": "Test Agent",
    "agent_info_description": "Test Agent description",
    "dd_namespace": "test_namespace",
    "dd_name": "test_name"
  },
  "message": "Fingerprint record created successfully",
  "count": null
}
```

---

## 2. Batch Create Fingerprint Records

**Batch Create Multiple Fingerprint Records**

- **Endpoint**: `POST /fingerprints/batch`
- **Content-Type**: `application/json`

### Request Example
```bash
curl -X POST "http://192.168.xxx.xxx:22000/fingerprints/batch" \
-H "Content-Type: application/json" \
-d '[
    {
        "fingerprint_id": "fp_002",
        "fingerprint_summary": "Fingerprint summary 2",
        "agent_info_name": "Agent2",
        "agent_info_description": "Agent2 description",
        "dd_namespace": "namespace2",
        "dd_name": "name2"
    },
    {
        "fingerprint_id": "fp_003",
        "fingerprint_summary": "Fingerprint summary 3",
        "agent_info_name": "Agent3",
        "agent_info_description": "Agent3 description",
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
  "message": "Successfully created 2 fingerprint records in batch",
  "count": null
}
```

---

## 3. Get Fingerprint Record by Primary Key

**Get Single Fingerprint Record by FID**

- **Endpoint**: `GET /fingerprints/{fid}`

### Request Example
```bash
curl -X GET "http://192.168.xxx.xxx:22000/fingerprints/86353825-902f-4403-b721-989e76859342" | jq .
```

### Response Example
```json
{
  "status": "success",
  "data": {
    "fid": "34ffba76-1feb-40a6-832b-fe81595d3680",
    "fingerprint_id": "fp_001",
    "fingerprint_summary": "Test fingerprint summary",
    "agent_info_name": "Test Agent",
    "agent_info_description": "Test Agent description",
    "dd_namespace": "test_namespace",
    "dd_name": "test_name"
  },
  "message": null,
  "count": null
}
```

---

## 4. Get Fingerprint Record by Fingerprint ID

**Get Fingerprint Record by Fingerprint ID**

- **Endpoint**: `GET /fingerprints/fingerprint_id/{fingerprint_id}`

### Request Example
```bash
curl -X GET "http://192.168.xxx.xxx:22000/fingerprints/fingerprint_id/fp_001" | jq .
```

### Response Example
```json
{
  "status": "success",
  "data": {
    "fid": "34ffba76-1feb-40a6-832b-fe81595d3680",
    "fingerprint_id": "fp_001",
    "fingerprint_summary": "Test fingerprint summary",
    "agent_info_name": "Test Agent",
    "agent_info_description": "Test Agent description",
    "dd_namespace": "test_namespace",
    "dd_name": "test_name"
  },
  "message": null,
  "count": null
}
```

---

## 5. Search Fingerprint Records by DD Information

**Search Fingerprint Records by DD Namespace and Name**

- **Endpoint**: `POST /fingerprints/search/by-dd`
- **Content-Type**: `application/json`

### Request Example
```bash
curl -X POST "http://192.168.xxx.xxx:22000/fingerprints/search/by-dd" \
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
      "fid": "34ffba76-1feb-40a6-832b-fe81595d3680",
      "fingerprint_id": "fp_001",
      "fingerprint_summary": "Test fingerprint summary",
      "agent_info_name": "Test Agent",
      "agent_info_description": "Test Agent description",
      "dd_namespace": "test_namespace",
      "dd_name": "test_name"
    }
  ],
  "count": 1
}
```

---

## 6. Update Fingerprint Record

**Update Fingerprint Record by FID**

- **Endpoint**: `PUT /fingerprints/{fid}`
- **Content-Type**: `application/json`

### Request Example
```bash
curl -X PUT "http://192.168.xxx.xxx:22000/fingerprints/86353825-902f-4403-b721-989e76859342" \
-H "Content-Type: application/json" \
-d '{
    "fingerprint_id": "fp_001_updated",
    "fingerprint_summary": "Updated fingerprint summary",
    "agent_info_name": "Updated Agent",
    "agent_info_description": "Updated Agent description",
    "dd_namespace": "updated_namespace",
    "dd_name": "updated_name"
}' | jq .
```

### Response Example
```json
{
  "status": "success",
  "data": {
    "fid": "34ffba76-1feb-40a6-832b-fe81595d3680",
    "fingerprint_id": "fp_001_updated",
    "fingerprint_summary": "Updated fingerprint summary",
    "agent_info_name": "Updated Agent",
    "agent_info_description": "Updated Agent description",
    "dd_namespace": "updated_namespace",
    "dd_name": "updated_name"
  },
  "message": "Fingerprint record updated successfully",
  "count": null
}
```

---

## 7. Delete Fingerprint Record

**Delete Fingerprint Record by FID**

- **Endpoint**: `DELETE /fingerprints/{fid}`

### Request Example
```bash
curl -X DELETE "http://192.168.xxx.xxx:22000/fingerprints/86353825-902f-4403-b721-989e76859342" | jq .
```

### Response Example
```json
{
  "status": "success",
  "data": null,
  "message": "Fingerprint record deleted successfully",
  "count": null
}
```

---

## 8. Delete Fingerprint Records by DD Information

**Delete Fingerprint Records by DD Namespace and Name**

- **Endpoint**: `DELETE /fingerprints/dd_info/{dd_namespace}/{dd_name}`

### Request Example
```bash
curl -X DELETE "http://192.168.xxx.xxx:22000/fingerprints/dd_info/namespace2/name2" | jq .
```

### Response Example
```json
{
  "status": "success",
  "data": null,
  "message": "Fingerprint records with DD namespace 'namespace2', DD name 'name2' deleted successfully",
  "count": null
}
```

---

## 9. Check Fingerprint Record Existence

**Check if Fingerprint Record Exists by FID**

- **Endpoint**: `GET /fingerprints/{fid}/exists`

### Request Example
```bash
curl -X GET "http://192.168.xxx.xxx:22000/fingerprints/90daba0c-73aa-44cd-b563-603d206b112c/exists" | jq .
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

## 10. Check Fingerprint Record Existence by DD Information

**Check if Fingerprint Record Exists by DD Information**

- **Endpoint**: `GET /fingerprints/dd_info/{dd_namespace}/{dd_name}/exists`

### Request Example
```bash
curl -X GET "http://192.168.xxx.xxx:22000/fingerprints/dd_info/namespace3/name3/exists" | jq .
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

## 11. Get Total Fingerprint Record Count

**Get Total Number of Fingerprint Records in the System**

- **Endpoint**: `GET /fingerprints/status/count`

### Request Example
```bash
curl -X GET "http://192.168.xxx.xxx:22000/fingerprints/status/count" | jq .
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