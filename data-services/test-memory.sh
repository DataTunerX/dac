
# 1. Adding Memory

# 1.1 Only userid :user1

curl -X POST "http://192.168.xxx.xxx:22000/memories" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user1",
    "messages": [
      {
        "role": "user",
        "content": "I like to eat pizza and pasta"
      },
      {
        "role": "assistant",
        "content": "Okay, your dietary preferences have been remembered"
      }
    ],
    "metadata": {
      "conversation_id": "conv_456",
      "timestamp": "2023-10-01T10:00:00Z"
    }
  }' | jq .


# Output:

{
  "status": "success",
  "message": "Memory added successfully",
  "data": {
    "results": [
      {
        "id": "0e4d8f9f-45b3-4ec8-ae5c-68eb4b42e64c",
        "memory": "Likes to eat pizza and pasta",
        "event": "ADD"
      }
    ],
    "relations": {
      "deleted_entities": [
        []
      ],
      "added_entities": [
        [
          {
            "source": "user_id:_user1",
            "relationship": "likes",
            "target": "pizza"
          }
        ],
        [
          {
            "source": "user_id:_user1",
            "relationship": "likes",
            "target": "pasta"
          }
        ]
      ]
    }
  }
}


# Add two memories for the same user, convenient for testing, but the memory content is different.

curl -X POST "http://192.168.xxx.xxx:22000/memories" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user1",
    "messages": [
      {
        "role": "user",
        "content": "I like basketball and table tennis"
      },
      {
        "role": "assistant",
        "content": "Okay, your dietary preferences have been remembered"
      }
    ],
    "metadata": {
      "conversation_id": "conv_456",
      "timestamp": "2023-10-01T10:00:00Z"
    }
  }' | jq .



# 1.2 Only agentid: agent1:

curl -X POST "http://192.168.xxx.xxx:22000/memories" \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {
        "role": "user",
        "content": "I like to eat pizza and pasta"
      },
      {
        "role": "assistant",
        "content": "Okay, your dietary preferences have been remembered"
      }
    ],
    "agent_id": "agent1",
    "metadata": {
      "topic": "Artificial Intelligence",
      "category": "Technology",
      "importance": "high"
    }
  }' | jq .



# agent1 No facts: The messages contain no specific facts, resulting in no memory being created even if the request is sent.

curl -X POST "http://192.168.xxx.xxx:22000/memories" \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {
        "role": "user",
        "content": "Hello, I would like to learn about the history of artificial intelligence"
      },
      {
        "role": "assistant",
        "content": "The development of artificial intelligence has gone through multiple stages such as symbolism, connectionism, and behaviorism..."
      }
    ],
    "run_id": "run1",
    "metadata": {
      "topic": "Artificial Intelligence",
      "category": "Technology",
      "importance": "high"
    }
  }' | jq .



# 1.3 Only runid: run1

curl -X POST "http://192.168.xxx.xxx:22000/memories" \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {
        "role": "user",
        "content": "I like to eat pizza and pasta"
      },
      {
        "role": "assistant",
        "content": "Okay, your dietary preferences have been remembered"
      }
    ],
    "run_id": "run1",
    "metadata": {
      "topic": "Artificial Intelligence",
      "category": "Technology",
      "importance": "high"
    }
  }' | jq .


# 1.4 Contains userid, agentid, and runid simultaneously

curl -X POST "http://192.168.xxx.xxx:22000/memories" \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {
        "role": "user",
        "content": "I like to eat pizza and pasta"
      },
      {
        "role": "assistant",
        "content": "Okay, your dietary preferences have been remembered"
      }
    ],
    "user_id": "user1",
    "agent_id": "agent1",
    "run_id": "run1",
    "metadata": {
      "topic": "Artificial Intelligence",
      "category": "Technology",
      "importance": "high"
    }
  }' | jq .



# 1.5 Error will occur if none of userid, agentid, or runid are set

curl -X POST "http://192.168.xxx.xxx:22000/memories" \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {
        "role": "user",
        "content": "I like to eat pizza and pasta"
      },
      {
        "role": "assistant",
        "content": "Okay, your dietary preferences have been remembered"
      }
    ],
    "metadata": {
      "topic": "Artificial Intelligence",
      "category": "Technology",
      "importance": "high"
    }
  }' | jq .

#Output

# {
#   "detail": "At least one of 'user_id', 'agent_id', or 'run_id' must be provided."
# }


# 2. Get Single Memory

curl -s -X GET "http://192.168.xxx.xxx:22000/memories/c9dd1492-4832-4f2a-aef4-682ed09d0ee6" | jq .

# Output:

# {
#   "status": "success",
#   "data": {
#     "id": "0e4d8f9f-45b3-4ec8-ae5c-68eb4b42e64c",
#     "memory": "Likes to eat pizza and pasta",
#     "hash": "1fa6211ecb07b77eede443e4b82829f0",
#     "metadata": {
#       "timestamp": "2023-10-01T10:00:00Z",
#       "conversation_id": "conv_456"
#     },
#     "score": null,
#     "created_at": "2025-08-21T23:43:14.879778-07:00",
#     "updated_at": null,
#     "user_id": "user1"
#   }
# }


# 3. Get All Memories

# 3.1. Get all memories - will error if none of userid, agentid, or runid are set

curl -X POST "http://192.168.xxx.xxx:22000/memories/get_all" \
  -H "Content-Type: application/json" \
  -d '{}' | jq .

# {
#   "detail": "At least one of 'user_id', 'agent_id', or 'run_id' must be provided."
# }


# 3.2 Get memories by user ID

curl -X POST "http://192.168.xxx.xxx:22000/memories/get_all" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user1"
  }' | jq .

# Output

# {
#   "status": "success",
#   "data": {
#     "memories": [
#       {
#         "id": "c9dd1492-4832-4f2a-aef4-682ed09d0ee6",
#         "memory": "Likes to eat pizza and pasta",
#         "hash": "1fa6211ecb07b77eede443e4b82829f0",
#         "metadata": {
#           "timestamp": "2023-10-01T10:00:00Z",
#           "conversation_id": "conv_456"
#         },
#         "created_at": "2025-08-22T06:28:48.474410-07:00",
#         "updated_at": null,
#         "user_id": "user1"
#       }
#     ],
#     "count": 1
#   }
# }


# 3.3 Get memories by agent_id

curl -X POST "http://192.168.xxx.xxx:22000/memories/get_all" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "agent1"
  }' | jq .


# 3.4 Get memories by run_id

curl -X POST "http://192.168.xxx.xxx:22000/memories/get_all" \
  -H "Content-Type: application/json" \
  -d '{
    "run_id": "run1"
  }' | jq .


# 3.5 Query with combined conditions

curl -X POST "http://192.168.xxx.xxx:22000/memories/get_all" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user1",
    "agent_id": "agent1",
    "limit": 50
  }' | jq .


# 4. Search Memories

# 4.1 Basic keyword search - will error if none of userid, agentid, or runid are set

curl -X POST "http://192.168.xxx.xxx:22000/memories/search" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "pasta"
  }' | jq .

# {
#   "detail": "At least one of 'user_id', 'agent_id', or 'run_id' must be provided."
# }


# 4.2 Search by user ID

curl -X POST "http://192.168.xxx.xxx:22000/memories/search" \
     -H "Content-Type: application/json" \
     -d '{
       "query": "pasta",
       "user_id": "user1",
       "limit": 5
     }' | jq .

# Output:

{
  "status": "success",
  "data": {
    "query": "pasta",
    "results": [
      {
        "id": "0e4d8f9f-45b3-4ec8-ae5c-68eb4b42e64c",
        "memory": "Likes to eat pizza and pasta",
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


# 4.3 Search by agent_id

curl -X POST "http://192.168.xxx.xxx:22000/memories/search" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "pasta",
    "agent_id": "agent1"
  }' | jq .


# 4.4 Search by run_id

curl -X POST "http://192.168.xxx.xxx:22000/memories/search" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "pasta",
    "run_id": "run1"
  }' | jq .


# 4.5 Limit number of returned results

curl -X POST "http://192.168.xxx.xxx:22000/memories/search" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user1",
    "query": "pasta",
    "limit": 5
  }' | jq .


# 4.6 Search with combined conditions

curl -X POST "http://192.168.xxx.xxx:22000/memories/search" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "pasta",
    "user_id": "user1",
    "agent_id": "agent1",
    "limit": 10
  }' | jq .


curl -X POST "http://192.168.xxx.xxx:22000/memories/search" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "pasta",
    "user_id": "user1",
    "agent_id": "assistant_001",
    "run_id": "run_123456",
    "limit": 10
  }' | jq .



# output：

{
  "status": "success",
  "data": {
    "query": "pasta",
    "results": {
      "results": [
        {
          "id": "276c397f-90c5-4ca2-8d39-eba0462915b9",
          "memory": "Likes to eat pizza and pasta",
          "hash": "1fa6211ecb07b77eede443e4b82829f0",
          "metadata": {
            "conversation_id": "conv_456"
          },
          "score": 0.2985008181035018,
          "created_at": "2025-09-18T05:38:36.042830-07:00",
          "updated_at": null,
          "user_id": "user1",
          "agent_id": "assistant_001",
          "run_id": "run_123456"
        }
      ]
    },
    "count": 1
  }
}


# 4.7 Search using filters

curl -X POST "http://192.168.xxx.xxx:22000/memories/search" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "pasta",
    "user_id": "user1",
    "filters": {
      "status": "completed"
    }
  }' | jq .








# 5. 获取记忆历史
# 替换 {memory_id} 为实际的记忆 ID
curl -X GET "http://192.168.xxx.xxx:22000/memories/37a54411-c606-4487-bb25-23492bddd145/history" | jq .

# 输出：

# {
#   "status": "success",
#   "data": {
#     "memory_id": "37a54411-c606-4487-bb25-23492bddd145",
#     "history": [
#       {
#         "id": "cb9c8fc7-abb8-46fa-a846-002ed5df05a6",
#         "memory_id": "37a54411-c606-4487-bb25-23492bddd145",
#         "old_memory": null,
#         "new_memory": "喜欢吃披萨和意大利面",
#         "event": "ADD",
#         "created_at": "2025-08-22T05:20:21.455492-07:00",
#         "updated_at": null,
#         "is_deleted": false,
#         "actor_id": null,
#         "role": null
#       },
#       {
#         "id": "fa1a3205-231b-41b6-a7fd-91905057a487",
#         "memory_id": "37a54411-c606-4487-bb25-23492bddd145",
#         "old_memory": "喜欢吃披萨和意大利面",
#         "new_memory": "我喜欢吃披萨、意大利面和面包",
#         "event": "UPDATE",
#         "created_at": "2025-08-22T05:20:21.455492-07:00",
#         "updated_at": "2025-08-22T05:39:49.904435-07:00",
#         "is_deleted": false,
#         "actor_id": null,
#         "role": null
#       }
#     ]
#   }
# }


# 6. Update Single Memory
# Replace {memory_id} with the actual memory ID

curl -X PUT "http://192.168.xxx.xxx:22000/memories/37a54411-c606-4487-bb25-23492bddd145" \
     -H "Content-Type: application/json" \
     -d '{
       "data": "I like to eat pizza, pasta, and bread"
     }' | jq .

# Output:

# {
#   "status": "success",
#   "message": "Memory updated successfully",
#   "data": {
#     "message": "Memory updated successfully!"
#   }
# }


# 7. Delete Single Memory
# Replace {memory_id} with the actual memory ID

curl -X DELETE "http://192.168.xxx.xxx:22000/memories/37a54411-c606-4487-bb25-23492bddd145" | jq .

# Output:

# {
#   "status": "success",
#   "message": "Memory deleted successfully",
#   "data": {
#     "message": "Memory deleted successfully!"
#   }
# }


# 8. Delete All Memories for a User

# 8.1 Delete all memories for a specific user

curl -X POST "http://192.168.xxx.xxx:22000/memories/delete" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user1"
  }' | jq .

# Output

# {
#   "status": "success",
#   "message": "Memories deleted successfully",
#   "data": {
#     "message": "Memories deleted successfully!"
#   }
# }


# 8.2 Delete all memories for a specific agent

curl -X POST "http://192.168.xxx.xxx:22000/memories/delete" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "agent1"
  }' | jq .


# 8.3 Delete all memories for a specific run

curl -X POST "http://192.168.xxx.xxx:22000/memories/delete" \
  -H "Content-Type: application/json" \
  -d '{
    "run_id": "run1"
  }' | jq .


# 8.4 Delete with combined conditions (user + agent)

curl -X POST "http://192.168.xxx.xxx:22000/memories/delete" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user1",
    "agent_id": "agent1"
  }' | jq .


# 8.5 Delete with combined conditions (user + run)

curl -X POST "http://192.168.xxx.xxx:22000/memories/delete" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user1",
    "run_id": "run1"
  }' | jq .


# 8.6 Delete with combined conditions (agent + run)

curl -X POST "http://192.168.xxx.xxx:22000/memories/delete" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "agent1",
    "run_id": "run1"
  }' | jq .


# 8.7 Delete with three combined conditions

curl -X POST "http://192.168.xxx.xxx:22000/memories/delete" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user1",
    "agent_id": "agent1",
    "run_id": "run1"
  }' | jq .


# 8.8 Delete all memories (empty conditions)

curl -X POST "http://192.168.xxx.xxx:22000/memories/delete" \
  -H "Content-Type: application/json" \
  -d '{}' | jq .

# Output:
# {
#   "detail": "At least one filter is required to delete all memories. If you want to delete all memories, use the `reset()` method."
# }


# 9. Reset All Memories

curl -X POST "http://192.168.xxx.xxx:22000/memories/reset" | jq .

# Output:

# {
#   "status": "success",
#   "message": "All memories reset successfully",
#   "data": null
# }
