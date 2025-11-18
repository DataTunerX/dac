
1. agents

curl "http://192.168.xxx.xxx:20000/agents" \
-H "Content-Type: application/json" | jq .

# output

{
  "agent_cards": [
    {
      "additionalInterfaces": null,
      "capabilities": {
        "extensions": null,
        "pushNotifications": true,
        "stateTransitionHistory": false,
        "streaming": true
      },
      "defaultInputModes": [
        "text",
        "text/plain"
      ],
      "defaultOutputModes": [
        "text",
        "text/plain"
      ],
      "description": "我是一个金融数据分析的专业智能体，可以去数据库查询需要的数据来回答用户提出来的相关的问题。",
      "documentationUrl": null,
      "iconUrl": null,
      "name": "FinancialDataAnalysisAgent",
      "preferredTransport": "JSONRPC",
      "protocolVersion": "0.3.0",
      "provider": null,
      "security": null,
      "securitySchemes": null,
      "signatures": null,
      "skills": [],
      "supportsAuthenticatedExtendedCard": null,
      "url": "http://192.168.xxx.xxx:20003",
      "version": "1.0.0"
    },
    {
      "additionalInterfaces": null,
      "capabilities": {
        "extensions": null,
        "pushNotifications": true,
        "stateTransitionHistory": false,
        "streaming": true
      },
      "defaultInputModes": [
        "text",
        "text/plain"
      ],
      "defaultOutputModes": [
        "text",
        "text/plain"
      ],
      "description": "我是一个卫星智能体，可以回答一些和卫星相关的问题。",
      "documentationUrl": null,
      "iconUrl": null,
      "name": "SatelliteAgent",
      "preferredTransport": "JSONRPC",
      "protocolVersion": "0.3.0",
      "provider": null,
      "security": null,
      "securitySchemes": null,
      "signatures": null,
      "skills": [],
      "supportsAuthenticatedExtendedCard": null,
      "url": "http://192.168.xxx.xxx:20004",
      "version": "1.0.0"
    }
  ]
}




2. search agents

curl -X POST "http://192.168.xxx.xxx:20000/search" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "卫星Iridium NEXT系统是什么",
    "collection": "orchestrator_agent_cards",
    "limit": 100
  }' | jq .


# output

{
  "status": "success",
  "collection": "orchestrator_agent_cards",
  "search_type": "vector",
  "result": [
    {
      "content": "\n        Agent Name: SatelliteAgent\n        Description: 我是一个卫星智能体，可以回答一些和卫星相关的问题。\n        URL: http://192.168.xxx.xxx:20004\n        ",
      "metadata": {
        "type": "agent_card",
        "skills": [],
        "agent_url": "http://192.168.xxx.xxx:20004",
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



