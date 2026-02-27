
# a2s server

test：

uv run orchestrator-agent --host 192.168.xxx.xxx --port 20001 --agent-card /Users/james/daocloud/code/raytest/dac/OrchestratorAgent/agent_card/orchestrator_agent.json --provider openai_compatible --api-key sk-xxx --base-url https://dashscope.aliyuncs.com/compatible-mode/v1 --model qwen2.5-72b-instruct



DataSourceType=SemanticDomain:

docker run --rm -e "Agent_Host=192.168.3.238" -e "Agent_Port=20004" -e "AgentRegistry=http://192.168.3.238:20001" -e "DataServicesURL=http://192.168.3.238:22000" -e "Data_Descriptor=bank" -e "DescriptorTypes=bank:structured-mysql" -e "DD_NAMESPACE=dac" -e "Enable_History=disable" -e "Agent_Name=FinancialDataAnalysisAgent" -e "Agent_Description=I am a professional financial data analysis intelligent agent that can query databases for required data to answer user-related questions." -e "LANGFUSE_SECRET_KEY=sk-lf-006f7d92-b2c6-4022-9142-5630355c9633" -e "LANGFUSE_PUBLIC_KEY=pk-lf-a19667ad-64d2-4133-939c-38e2c21144ba" -e "LANGFUSE_BASE_URL=http://192.168.3.238:3000" -e "DataSourceType=SemanticDomain" -p 20004:10100 registry.cn-shanghai.aliyuncs.com/jamesxiong/orchestrator-agent:v0.6.0-amd64 --redis-host 192.168.3.238 --redis-port 6389 --redis-db 0 --password 123 --provider openai_compatible --api-key sk-xxx --base-url https://dashscope.aliyuncs.com/compatible-mode/v1 --model deepseek-v3.2 --debug 1 --max-loops 3




DataSourceType=SemanticGroup

docker run --rm -e "Agent_Host=192.168.3.238" -e "Agent_Port=20004" -e "AgentRegistry=http://192.168.3.238:20001" -e "DataServicesURL=http://192.168.3.238:22000" -e "Enable_History=enable" -e "Agent_Name=FinancialDataAnalysisAgent" -e "Agent_Description=I am a professional financial data analysis intelligent agent that can query databases for required data to answer user-related questions." -e "LANGFUSE_SECRET_KEY=sk-lf-006f7d92-b2c6-4022-9142-5630355c9633" -e "LANGFUSE_PUBLIC_KEY=pk-lf-a19667ad-64d2-4133-939c-38e2c21144ba" -e "LANGFUSE_BASE_URL=http://192.168.3.238:3000" -e "DataSourceType=SemanticGroup" -e "SemanticGroupID=ce6a9111-f7da-4020-882c-d43686d52278" -p 20004:10100 registry.cn-shanghai.aliyuncs.com/jamesxiong/orchestrator-agent:v0.6.0-amd64 --redis-host 192.168.3.238 --redis-port 6389 --redis-db 2 --password 123 --provider openai_compatible --api-key sk-xxx --base-url https://dashscope.aliyuncs.com/compatible-mode/v1 --model deepseek-v3.2 --debug 1 --max-loops 3