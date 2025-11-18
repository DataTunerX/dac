
# a2s server

test：

uv run orchestrator-agent --host 192.168.xxx.xxx --port 20001 --agent-card /Users/james/daocloud/code/raytest/dac/OrchestratorAgent/agent_card/orchestrator_agent.json --provider openai_compatible --api-key sk-xxx --base-url https://dashscope.aliyuncs.com/compatible-mode/v1 --model qwen2.5-72b-instruct



agent 1 （dd-a04 Rural Commercial Bank Data）:

docker run --rm -e "Agent_Host=192.168.xxx.xxx" -e "Agent_Port=20003" -e "AgentRegistry=http://192.168.xxx.xxx:20001" -e "DataServicesURL=http://192.168.xxx.xxx:22000" -e "Data_Descriptor=dd-a04" -e "DescriptorTypes=dd-a04:structured-mysql" -e "DD_NAMESPACE=dac" -e "Enable_History=enable" -e "Agent_Name=FinancialDataAnalysisAgent" -e "Agent_Description=I am a professional financial data analysis intelligent agent that can query databases for required data to answer user-related questions." -e "LANGFUSE_SECRET_KEY=sk-xxx" -e "LANGFUSE_PUBLIC_KEY=pk-xxx" -e "LANGFUSE_BASE_URL=http://192.168.xxx.xxx:3000" -p 20003:10100 registry.cn-shanghai.aliyuncs.com/jamesxiong/orchestrator-agent:v0.1.1-amd64 --redis-host 192.168.xxx.xxx --redis-port 6389 --redis-db 0 --password 123 --provider openai_compatible --api-key sk-xxx --base-url https://dashscope.aliyuncs.com/compatible-mode/v1 --model qwen3-32b --debug 1 --max-loops 3



agent 2（dd-a05 Product Order Data）:

docker run --rm -e "Agent_Host=192.168.xxx.xxx" -e "Agent_Port=20004" -e "AgentRegistry=http://192.168.xxx.xxx:20001" -e "DataServicesURL=http://192.168.xxx.xxx:22000" -e "Data_Descriptor=dd-a05" -e "DescriptorTypes=dd-a05:structured-mysql" -e "DD_NAMESPACE=dac" -e "Enable_History=enable" -e "Agent_Name=ProductOrderAgent" -e "Agent_Description=I am a professional product order management system intelligent agent that can query databases for required data to answer user-related questions." -e "LANGFUSE_SECRET_KEY=sk-xxx" -e "LANGFUSE_PUBLIC_KEY=pk-xxx" -e "LANGFUSE_BASE_URL=http://192.168.xxx.xxx:3000" -p 20004:10100 registry.cn-shanghai.aliyuncs.com/jamesxiong/orchestrator-agent:v0.1.1-amd64 --redis-host 192.168.xxx.xxx --redis-port 6389 --redis-db 0 --password 123 --provider openai_compatible --api-key sk-xxx --base-url https://dashscope.aliyuncs.com/compatible-mode/v1 --model qwen3-32b --debug 1 --max-loops 3



agent 3（dd-e01 Satellite）:

docker run --rm -e "Agent_Host=192.168.xxx.xxx" -e "Agent_Port=20004" -e "AgentRegistry=http://192.168.xxx.xxx:20001" -e "DataServicesURL=http://192.168.xxx.xxx:22000" -e "Data_Descriptor=dd-e01" -e "DescriptorTypes=dd-e01:unstructured" -e "DD_NAMESPACE=dac" -e "Enable_History=enable" -e "Agent_Name=SatelliteAgent" -e "Agent_Description=I am a satellite intelligent agent that can answer questions related to satellites." -e "LANGFUSE_SECRET_KEY=sk-xxx" -e "LANGFUSE_PUBLIC_KEY=pk-xxx" -e "LANGFUSE_BASE_URL=http://192.168.xxx.xxx:3000" -p 20004:10100 registry.cn-shanghai.aliyuncs.com/jamesxiong/orchestrator-agent:v0.1.1-amd64 --redis-host 192.168.xxx.xxx --redis-port 6389 --redis-db 0 --password 123 --provider openai_compatible --api-key sk-xxx --base-url https://dashscope.aliyuncs.com/compatible-mode/v1 --model qwen3-32b --debug 1 --max-loops 3