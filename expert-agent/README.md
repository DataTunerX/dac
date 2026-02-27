
# a2s server

test：

export Agent_Host="192.168.xxx.xxx"
export Agent_Port="10101"
export Data_Descriptor="dd-301"
export DescriptorTypes="dd-101:structured-mysql"
export DD_NAMESPACE="dac"
export Direct_Return="disable"
export SQL_PROCESS_MODE="dictionary"


uv run agent --redis-host 192.168.xxx.xxx --redis-port 6389 --redis-db 1 --password 123 --provider openai_compatible --api-key sk-xxx --base-url https://dashscope.aliyuncs.com/compatible-mode/v1 --model qwen3-32b --agent-card /Users/james/daocloud/code/raytest/dac/expert-agent/agent_card/agent_card.json --max-steps 3



## DataSourceType=SemanticDomain:

docker run --rm -e "Agent_Host=192.168.3.238" -e "Agent_Port=20006" -e "DataServicesURL=http://192.168.3.238:22000" -e "Data_Descriptor=bank" -e "DescriptorTypes=bank:structured-mysql:host:192.168.3.238:port:3307:user:root:password:123:database:dactest" -e "DD_NAMESPACE=dac" -e "SQL_PROCESS_MODE=dictionary" -e "Agent_Name=FinancialDataAnalysisAgent" -e "Agent_Description=I am a professional financial data analysis intelligent agent that can query databases for required data to answer user-related questions." -e "LANGFUSE_SECRET_KEY=sk-lf-006f7d92-b2c6-4022-9142-5630355c9633" -e "LANGFUSE_PUBLIC_KEY=pk-lf-a19667ad-64d2-4133-939c-38e2c21144ba" -e "LANGFUSE_BASE_URL=http://192.168.3.238:3000" -e "DataSourceType=SemanticDomain" -p 20006:10100 registry.cn-shanghai.aliyuncs.com/jamesxiong/expert-agent:v0.6.0-amd64 --redis-host 192.168.3.238 --redis-port 6389 --redis-db 1 --password 123 --provider openai_compatible --api-key sk-xxx --base-url https://dashscope.aliyuncs.com/compatible-mode/v1 --model deepseek-v3.2 --max-steps 3




## DataSourceType=SemanticGroup:

docker run --rm -e "Agent_Host=192.168.3.238" -e "Agent_Port=20006" -e "DataServicesURL=http://192.168.3.238:22000" -e "Agent_Name=FinancialDataAnalysisAgent" -e "Agent_Description=I am a professional financial data analysis intelligent agent that can query databases for required data to answer user-related questions." -e "LANGFUSE_SECRET_KEY=sk-lf-006f7d92-b2c6-4022-9142-5630355c9633" -e "LANGFUSE_PUBLIC_KEY=pk-lf-a19667ad-64d2-4133-939c-38e2c21144ba" -e "LANGFUSE_BASE_URL=http://192.168.3.238:3000" -e "DataSourceType=SemanticGroup" -e "SemanticGroupID=ce6a9111-f7da-4020-882c-d43686d52278"  -p 20006:10100 registry.cn-shanghai.aliyuncs.com/jamesxiong/expert-agent:v0.6.0-amd64 --redis-host 192.168.3.238 --redis-port 6389 --redis-db 3 --password 123 --provider openai_compatible --api-key sk-xxx --base-url https://dashscope.aliyuncs.com/compatible-mode/v1 --model deepseek-v3.2 --max-steps 3




# models

qwen3-coder-480b-a35b-instruct

qwen3-coder-30b-a3b-instruct



# View Registered Agents

To prevent key eviction:

config set maxmemory-policy volatile-lru

Difference between volatile-lru and allkeys-lru:

volatile-lru: Only evicts keys with expiration time set

allkeys-lru: Evicts all keys (including permanent ones), this is the default


## Select database
select 1


## View all registered Agents
HGETALL expert_agents

## View details of a specific Agent (replace your URL)
HGET expert_agents "http://192.168.xxx.xxx:20004/"


# Check heartbeat time
## View heartbeat times of all Agents
ZRANGE agent_heartbeats 0 -1 WITHSCORES

127.0.0.1:6379> ZRANGE agent_heartbeats 0 -1 WITHSCORES
1) "http://192.168.xxx.xxx:20004/"
2) "1751261589.98008"


## View last heartbeat time of a specific Agent (returns Unix timestamp)
ZSCORE agent_heartbeats "http://192.168.xxx.xxx:20004/"

127.0.0.1:6379> ZSCORE agent_heartbeats "http://192.168.xxx.xxx:20004/"
"1751261609.985187"


## Convert timestamp to readable format (Linux/Mac)

code：
from datetime import datetime

timestamp = 1751261589.98008
print(datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S.%f'))

output：
2025-06-29 00:33:09.980080


# Check TTL

## Check remaining time of TTL key (unit: seconds)
TTL "expert_agents:http://192.168.xxx.xxx:20004/"

127.0.0.1:6379> TTL "expert_agents:http://192.168.xxx.xxx:20004/"
(integer) 54

Negative numbers indicate the key does not exist


## Check if the key exists
EXISTS "expert_agents:http://192.168.xxx.xxx:20004/"

0 means does not exist
1 means exists


# Basic testing

python3 test.py


