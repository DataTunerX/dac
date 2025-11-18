# redis

It must be set, otherwise pubsub events cannot be monitored.

config set notify-keyspace-events AKE

You can add this to the Redis startup configuration:

notify-keyspace-events AKE




test：

uv run agent-registry --run mcp-server --transport sse --redis-host 192.168.xxx.xxx --redis-port 6389 --redis-db 0 --password 123

# Run only MCP server (original method)
uv run agent-registry --run mcp-server --host 0.0.0.0 --port 10100 --transport sse --redis-host 192.168.xxx.xxx --redis-port 6389 --redis-db 0 --password 123

# Run only FastAPI server
uv run agent-registry --run api-server --api-host 0.0.0.0 --api-port 8000 --redis-host 192.168.xxx.xxx --redis-port 6389 --redis-db 0 --password 123

# Run both servers simultaneously
uv run agent-registry --run both --host 0.0.0.0 --port 10100 --api-host 0.0.0.0 --api-port 8000 --transport sse --redis-host 192.168.xxx.xxx --redis-port 6389 --redis-db 0 --password 123






# client test

ipconfig getifaddr en0 



## get Agent Card list

python3 test.py \
  --host 192.168.xxx.xxx \
  --port 20000 \
  --transport sse \
  --resource "resource://agent_cards/list"


结果：[06/26/25 14:33:00] INFO     Starting Client to connect to MCP                                                                                                                                                                                          test.py:86
                    INFO     SSE ClientSession initialized successfully.                                                                                                                                                                                test.py:50
                    INFO     Reading resource: resource://agent_cards/list                                                                                                                                                                              test.py:69
                    INFO     meta=None contents=[TextResourceContents(uri=AnyUrl('resource://agent_cards/list'), mimeType='application/json', text='{\n  "agent_cards": [\n    "resource://agent_cards/expert_agent",\n                                 test.py:90
                             "resource://agent_cards/coder_agent"\n  ]\n}')]                                                                                                                                                                                      
                    INFO     {                                                                                                                                                                                                                          test.py:92
                               "agent_cards": [                                                                                                                                                                                                                   
                                 "resource://agent_cards/expert_agent",                                                                                                                                                                                           
                                 "resource://agent_cards/coder_agent"                                                                                                                                                                                             
                               ]                                                                                                                                                                                                                                  
                             }                                     


## get one Agent Card

python3 test.py \
  --host 192.168.xxx.xxx \
  --port 20000 \
  --transport sse \
  --resource "resource://agent_cards/HRAgent"


result：

[06/26/25 14:34:01] INFO     Starting Client to connect to MCP                                                                                                                                                                                          test.py:86
                    INFO     SSE ClientSession initialized successfully.                                                                                                                                                                                test.py:50
                    INFO     Reading resource: resource://agent_cards/expert_agent                                                                                                                                                                      test.py:69
                    INFO     meta=None contents=[TextResourceContents(uri=AnyUrl('resource://agent_cards/expert_agent'), mimeType='application/json', text='{\n  "agent_card": [\n    {\n      "name": "Expert Agent",\n      "description": "answer    test.py:90
                             user question using self knowledge",\n      "url": "http://localhost:10101/",\n      "provider": null,\n      "version": "1.0.0",\n      "documentationUrl": null,\n      "capabilities": {\n        "streaming":                    
                             "True",\n        "pushNotifications": "True",\n        "stateTransitionHistory": "False"\n      },\n      "authentication": {\n        "credentials": null,\n        "schemes": [\n          "public"\n        ]\n                   
                             },\n      "defaultInputModes": [\n        "text",\n        "text/plain"\n      ],\n      "defaultOutputModes": [\n        "text",\n        "text/plain"\n      ],\n      "skills": [\n        {\n          "id":                     
                             "answer-question",\n          "name": "Answer Question",\n          "description": "answer user question using self knowledge",\n          "tags": [\n            "expert agent"\n          ],\n          "examples": [\n            
                             "1+1等于几"\n          ],\n          "inputModes": null,\n          "outputModes": null\n        }\n      ]\n    }\n  ]\n}')]                                                                                                        
                    INFO     {                                                                                                                                                                                                                          test.py:92
                               "agent_card": [                                                                                                                                                                                                                    
                                 {                                                                                                                                                                                                                                
                                   "name": "Expert Agent",                                                                                                                                                                                                        
                                   "description": "answer user question using self knowledge",                                                                                                                                                                    
                                   "url": "http://localhost:10101/",                                                                                                                                                                                              
                                   "provider": null,                                                                                                                                                                                                              
                                   "version": "1.0.0",                                                                                                                                                                                                            
                                   "documentationUrl": null,                                                                                                                                                                                                      
                                   "capabilities": {                                                                                                                                                                                                              
                                     "streaming": "True",                                                                                                                                                                                                         
                                     "pushNotifications": "True",                                                                                                                                                                                                 
                                     "stateTransitionHistory": "False"                                                                                                                                                                                            
                                   },                                                                                                                                                                                                                             
                                   "authentication": {                                                                                                                                                                                                            
                                     "credentials": null,                                                                                                                                                                                                         
                                     "schemes": [                                                                                                                                                                                                                 
                                       "public"                                                                                                                                                                                                                   
                                     ]                                                                                                                                                                                                                            
                                   },                                                                                                                                                                                                                             
                                   "defaultInputModes": [                                                                                                                                                                                                         
                                     "text",                                                                                                                                                                                                                      
                                     "text/plain"                                                                                                                                                                                                                 
                                   ],                                                                                                                                                                                                                             
                                   "defaultOutputModes": [                                                                                                                                                                                                        
                                     "text",                                                                                                                                                                                                                      
                                     "text/plain"                                                                                                                                                                                                                 
                                   ],                                                                                                                                                                                                                             
                                   "skills": [                                                                                                                                                                                                                    
                                     {                                                                                                                                                                                                                            
                                       "id": "answer-question",                                                                                                                                                                                                   
                                       "name": "Answer Question",                                                                                                                                                                                                 
                                       "description": "answer user question using self knowledge",                                                                                                                                                                
                                       "tags": [                                                                                                                                                                                                                  
                                         "expert agent"                                                                                                                                                                                                           
                                       ],                                                                                                                                                                                                                         
                                       "examples": [                                                                                                                                                                                                              
                                         "1+1\u7b49\u4e8e\u51e0"                                                                                                                                                                                                  
                                       ],                                                                                                                                                                                                                         
                                       "inputModes": null,                                                                                                                                                                                                        
                                       "outputModes": null                                                                                                                                                                                                        
                                     }                                                                                                                                                                                                                            
                                   ]                                                                                                                                                                                                                              
                                 }                                                                                                                                                                                                                                
                               ]                                                                                                                                                                                                                                  
                             }                               
