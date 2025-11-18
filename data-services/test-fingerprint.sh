```bash
#!/bin/bash

# 1. Create Fingerprint

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

# output
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

# 2. Batch Create Fingerprints

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

# output

{
  "status": "success",
  "data": {
    "count": 2
  },
  "message": "Successfully created 2 fingerprint records in batch",
  "count": null
}

# 3. Get by FID

curl -X GET "http://192.168.xxx.xxx:22000/fingerprints/86353825-902f-4403-b721-989e76859342" | jq .

# output
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

# 4. Get by Fingerprint ID

curl -X GET "http://192.168.xxx.xxx:22000/fingerprints/fingerprint_id/fp_001" | jq .

# output
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

# 5. Search by DD Info

curl -X POST "http://192.168.xxx.xxx:22000/fingerprints/search/by-dd" \
-H "Content-Type: application/json" \
-d '{
    "dd_namespace": "test_namespace",
    "dd_name": "test_name"
}' | jq .

# output
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

# 6. Update Fingerprint

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

# output
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

# 7. Delete Fingerprint

curl -X DELETE "http://192.168.xxx.xxx:22000/fingerprints/86353825-902f-4403-b721-989e76859342" | jq .

# output
{
  "status": "success",
  "data": null,
  "message": "Fingerprint record deleted successfully",
  "count": null
}

# 8. Delete by DD Info

curl -X DELETE "http://192.168.xxx.xxx:22000/fingerprints/dd_info/namespace2/name2" | jq .

# output
{
  "status": "success",
  "data": null,
  "message": "Fingerprint records with DD namespace 'namespace2', DD name 'name2' deleted successfully",
  "count": null
}

# 9. Check Existence by FID

curl -X GET "http://192.168.xxx.xxx:22000/fingerprints/90daba0c-73aa-44cd-b563-603d206b112c/exists" | jq .

# output
{
  "status": "success",
  "data": {
    "exists": true
  },
  "message": null,
  "count": null
}

# 10. Check Existence by DD Info

curl -X GET "http://192.168.xxx.xxx:22000/fingerprints/dd_info/namespace3/name3/exists" | jq .

# output
{
  "status": "success",
  "data": {
    "exists": true
  },
  "message": null,
  "count": null
}

# 11. Get Fingerprint Count

curl -X GET "http://192.168.xxx.xxx:22000/fingerprints/status/count" | jq .

# output
{
  "status": "success",
  "data": {
    "total_count": 1
  },
  "message": null,
  "count": null
}
```