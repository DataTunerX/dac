# Component Description


## api-server
A service that receives API requests.

## execution-engine
A Kubernetes controller.

## celery-httpserver
Asynchronous HTTP-based Celery web service.

## data-sinkers
Processes data from DD.

## data-services
Provides APIs for operating vector data.

## agent-registry
An intelligent agent registration center that registers A2A agent cards through MCP resources.

## routing-agent
Receives user requests and analyzes which orchestrator agent to call.

## orchestrator-agent
Receives user requests and analyzes which ExpertAgents to call.

## expert-agent
The core of DAC, based on the A2A server.

## model_sdk
Encapsulates the model invocation SDK, including large language models, vector models, and rerank models.

## vector_sdk
Encapsulates the vector data processing SDK.