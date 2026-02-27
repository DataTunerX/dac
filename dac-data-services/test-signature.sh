```bash
#!/bin/bash

# 1. Create Signature

curl -X POST "http://192.168.3.238:22000/signatures" \
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
    "dd_namespace": "test_namespace",
    "dd_name": "test_name"
}' | jq .

# output
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
    "dd_namespace": "test_namespace",
    "dd_name": "test_name"
  },
  "message": "signature create success",
  "count": null
}

# 2. Batch Create Signatures

curl -X POST "http://192.168.3.238:22000/signatures/batch" \
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
  "message": "batch create 2 signatures success",
  "count": null
}

# 3. Get by sig_id

curl -X GET "http://192.168.3.238:22000/signatures/e16f4c96-1d21-439f-b5bf-6491a53f2a1a" | jq .

# output
{
  "status": "success",
  "data": {
    "sig_id": "e16f4c96-1d21-439f-b5bf-6491a53f2a1a",
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
    "dd_namespace": "test_namespace",
    "dd_name": "test_name"
  },
  "message": null,
  "count": null
}

# 4. Get by Fingerprint

curl -X GET "http://192.168.3.238:22000/signatures/fingerprint/fp_001" | jq .

# output
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
    "dd_namespace": "test_namespace",
    "dd_name": "test_name"
  },
  "message": null,
  "count": null
}

# 5. Search by DD Info

curl -X POST "http://192.168.3.238:22000/signatures/search/by-dd" \
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
      "dd_namespace": "test_namespace",
      "dd_name": "test_name"
    }
  ],
  "count": 1
}

# 6. Update Signature

curl -X PUT "http://192.168.3.238:22000/signatures/e16f4c96-1d21-439f-b5bf-6491a53f2a1a" \
-H "Content-Type: application/json" \
-d '{
    "fingerprint": "fp_001_updated",
    "metadata_content": {
        "summary": "Updated signature summary"
    },
    "dd_namespace": "updated_namespace",
    "dd_name": "updated_name"
}' | jq .

# output
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
    "dd_namespace": "updated_namespace",
    "dd_name": "updated_name"
  },
  "message": "signature updated success",
  "count": null
}

# 7. Delete Signature

curl -X DELETE "http://192.168.3.238:22000/signatures/e16f4c96-1d21-439f-b5bf-6491a53f2a1a" | jq .

# output
{
  "status": "success",
  "data": null,
  "message": "signature deleted success",
  "count": null
}

# 8. Delete by DD Info

curl -X DELETE "http://192.168.3.238:22000/signatures/dd_info/test_namespace/test_name" | jq .

# output
{
  "status": "success",
  "data": null,
  "message": "the signature of DD namespace 'namespace2', DD name 'name2' is deleted success",
  "count": null
}

# 9. Check Existence by sig_id

curl -X GET "http://192.168.3.238:22000/signatures/3c3d9af4-5b0f-4105-9252-3d509eaa4655/exists" | jq .

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

curl -X GET "http://192.168.3.238:22000/signatures/dd_info/test_namespace/test_name/exists" | jq .

# output
{
  "status": "success",
  "data": {
    "exists": true
  },
  "message": null,
  "count": null
}

# 11. Get Signature Count

curl -X GET "http://192.168.3.238:22000/signatures/status/count" | jq .

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
