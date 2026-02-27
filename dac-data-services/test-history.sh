## 1. Create history record API test command

```bash
curl -X POST "http://192.168.3.212:22000/history/create" \
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
        "content": "Okay, I have remembered your dietary preferences",
        "think": "this is knowledge"
      }
    ]
}' | jq .
```

**Expected response example:**

```json
{
  "status": "success",
  "hid": "86353825-902f-4403-b721-989e76859342",
  "message": "history add success"
}
```

## 2. Search history record API test command

```bash
curl -X POST "http://192.168.xxx.xxx:22000/history/search" \
-H "Content-Type: application/json" \
-d '{
    "user_id": "user_001",
    "agent_id": "agent_001",
    "run_id": "run_001",
    "limit": 3
}' | jq .
```

**Expected response example:**

```json
{
  "status": "success",
  "data": [
    {
      "hid": "380c29f4-b0a5-48c1-a1b8-b07521b76ba7",
      "user_id": "user_001",
      "agent_id": "agent_001",
      "run_id": "run_001",
      "messages": [
        {
          "role": "user",
          "content": "I like bananas",
          "think": null
        },
        {
          "role": "assistant",
          "content": "Okay, I've remembered your dietary preferences",
          "think": "this is knowledge"
        }
      ],
      "think": ["", "this is knowledge"],
      "created_at": "2025-10-04T16:46:15",
      "updated_at": "2025-10-04T16:46:15"
    },
    {
      "hid": "c902f6b9-4dfa-4a19-a220-9cb0022a4a35",
      "user_id": "user_001",
      "agent_id": "agent_001",
      "run_id": "run_001",
      "messages": [
        {
          "role": "user",
          "content": "I like playing basketball",
          "think": null
        },
        {
          "role": "assistant",
          "content": "Okay",
          "think": null
        }
      ],
      "think": ["", ""],
      "created_at": "2025-10-04T16:46:20",
      "updated_at": "2025-10-04T16:46:20"
    },
    {
      "hid": "f7af87d8-0c0b-4690-9a5c-fe1525ed7436",
      "user_id": "user_001",
      "agent_id": "agent_001",
      "run_id": "run_001",
      "messages": [
        {
          "role": "user",
          "content": "I like playing table tennis",
          "think": null
        },
        {
          "role": "assistant",
          "content": "Okay",
          "think": null
        }
      ],
      "think": ["", ""],
      "created_at": "2025-10-04T16:46:25",
      "updated_at": "2025-10-04T16:46:25"
    }
  ],
  "total": 3,
  "message": "found 3 items"
}
```



## 3. Search history record with user and run

```bash
curl -X POST "http://192.168.3.212:22000/history/search_user_run" \
-H "Content-Type: application/json" \
-d '{
    "user_id": "user1233",
    "run_id": "run1233",
    "limit": 3
}' | jq .
```

**Expected response example:**

```json
{
  "status": "success",
  "data": [
    {
      "hid": "380c29f4-b0a5-48c1-a1b8-b07521b76ba7",
      "user_id": "user_001",
      "agent_id": "agent_001",
      "run_id": "run_001",
      "messages": [
        {
          "role": "user",
          "content": "I like bananas",
          "think": null
        },
        {
          "role": "assistant",
          "content": "Okay, I've remembered your dietary preferences",
          "think": "this is knowledge"
        }
      ],
      "think": ["", "this is knowledge"],
      "created_at": "2025-10-04T16:46:15",
      "updated_at": "2025-10-04T16:46:15"
    },
    {
      "hid": "c902f6b9-4dfa-4a19-a220-9cb0022a4a35",
      "user_id": "user_001",
      "agent_id": "agent_001",
      "run_id": "run_001",
      "messages": [
        {
          "role": "user",
          "content": "I like playing basketball",
          "think": null
        },
        {
          "role": "assistant",
          "content": "Okay",
          "think": null
        }
      ],
      "think": ["", ""],
      "created_at": "2025-10-04T16:46:20",
      "updated_at": "2025-10-04T16:46:20"
    },
    {
      "hid": "f7af87d8-0c0b-4690-9a5c-fe1525ed7436",
      "user_id": "user_001",
      "agent_id": "agent_001",
      "run_id": "run_001",
      "messages": [
        {
          "role": "user",
          "content": "I like playing table tennis",
          "think": null
        },
        {
          "role": "assistant",
          "content": "Okay",
          "think": null
        }
      ],
      "think": ["", ""],
      "created_at": "2025-10-04T16:46:25",
      "updated_at": "2025-10-04T16:46:25"
    }
  ],
  "total": 3,
  "message": "found 3 items"
}
```