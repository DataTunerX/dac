# agent registry for orchestrator agent discover

test：

## amd64:

docker run --rm -e DATA_SERVICES="http://192.168.3.238:22000" -e "COLLECTION_NAME=biz_orchestrator_agent_cards" -p 20000:8000 registry.cn-shanghai.aliyuncs.com/jamesxiong/agent-registry:v0.3.0-amd64 --redis-host 192.168.3.238 --redis-port 6389 --redis-db 2 --password 123



## arm64:

docker run --rm -e DATA_SERVICES="http://192.168.3.238:22000" -e "COLLECTION_NAME=biz_orchestrator_agent_cards" -p 20000:8000 registry.cn-shanghai.aliyuncs.com/jamesxiong/agent-registry:v0.2.0-arm64 --redis-host 192.168.3.238 --redis-port 6389 --redis-db 2 --password 123




curl -X POST "http://192.168.3.238:22000/vector/create_collection" \
-H "Content-Type: application/json" \
-d '{
    "collection_name": "biz_orchestrator_agent_cards",
    "documents": [
        {
            "page_content": "Python is a popular programming language",
            "metadata": {"author": "Guido van Rossum", "year": 1991}
        }
    ]
}' | jq .



# client test

1. get all agents

curl "http://10.17.0.41:30444/agents" | jq .


2. search agents

curl -X POST "http://192.168.3.238:20000/search" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "卫星Iridium NEXT系统是什么",
    "collection": "biz_orchestrator_agent_cards",
    "limit": 100
  }' | jq .


# output

{
  "status": "success",
  "collection": "biz_orchestrator_agent_cards",
  "search_type": "vector",
  "result": [
    {
      "content": "\n        Agent Name: SatelliteAgent\n        Description: 我是一个卫星智能体，可以回答一些和卫星相关的问题。\n        URL: http://192.168.3.238:20004\n        ",
      "metadata": {
        "type": "agent_card",
        "skills": [],
        "agent_url": "http://192.168.3.238:20004",
        "timestamp": "2025-11-11T12:59:39.786163",
        "agent_name": "SatelliteAgent",
        "description": "我是一个卫星智能体，可以回答一些和卫星相关的问题。",
        "score": 0.5066654674213568
      },
      "score": 0.5066654674213568,
      "search_type": "vector",
      "hybrid_score": 0.0
    }
  ]
}
