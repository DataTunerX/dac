
# a2s server

local test：

uv run routing-agent --host 192.168.xxx.xxx --port 19999 --agent-card /Users/james/daocloud/code/raytest/dac/RoutingAgent/agent_card/routing_agent.json --provider openai_compatible --api-key sk-xxx --base-url https://dashscope.aliyuncs.com/compatible-mode/v1 --model qwen2.5-72b-instruct


docker test：

docker run --rm -e "Agent_Host=192.168.xxx.xxx" -e "Agent_Port=20002" -e "AgentRegistry=http://192.168.xxx.xxx:20000" -e "LANGFUSE_SECRET_KEY=sk-xxx" -e "LANGFUSE_PUBLIC_KEY=pk-xxx" -e "LANGFUSE_BASE_URL=http://192.168.xxx.xxx:3000" -p 20002:10100 routing-agent:v0.2.0-amd64 --redis-host 192.168.xxx.xxx --redis-port 6389 --redis-db 0 --password 123 --provider openai_compatible --api-key sk-xxx --base-url https://dashscope.aliyuncs.com/compatible-mode/v1 --model qwen3-32b




