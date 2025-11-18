
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



agent 1 （dd-a04 Rural Commercial Bank Data）:

docker run --rm -e "Agent_Host=192.168.xxx.xxx" -e "Agent_Port=20005" -e "DataServicesURL=http://192.168.xxx.xxx:22000" -e "Data_Descriptor=dd-a04" -e "DescriptorTypes=dd-a04:structured-mysql:host:192.168.xxx.xxx:port:3307:user:root:password:123:database:dactest" -e "DD_NAMESPACE=dac" -e "SQL_PROCESS_MODE=dictionary" -e "Agent_Name=FinancialDataAnalysisAgent" -e "Agent_Description=I am a professional financial data analysis intelligent agent that can query databases for required data to answer user-related questions." -e "LANGFUSE_SECRET_KEY=sk-xxx" -e "LANGFUSE_PUBLIC_KEY=pk-xxx" -e "LANGFUSE_BASE_URL=http://192.168.xxx.xxx:3000" -p 20005:10100 registry.cn-shanghai.aliyuncs.com/jamesxiong/expert-agent:v0.2.0-amd64 --redis-host 192.168.xxx.xxx --redis-port 6389 --redis-db 1 --password 123 --provider openai_compatible --api-key sk-xxx --base-url https://dashscope.aliyuncs.com/compatible-mode/v1 --model deepseek-v3.1 --max-steps 5


agent 2（dd-a05 Product Order Data）:

docker run --rm -e "Agent_Host=192.168.xxx.xxx" -e "Agent_Port=20006" -e "DataServicesURL=http://192.168.xxx.xxx:22000" -e "Data_Descriptor=dd-a05" -e "DescriptorTypes=dd-a05:structured-mysql:host:192.168.xxx.xxx:port:3307:user:root:password:123:database:test1" -e "DD_NAMESPACE=dac" -e "SQL_PROCESS_MODE=dictionary" -e "Agent_Name=ProductOrderAgent" -e "Agent_Description=I am a professional product order management system intelligent agent that can query databases for required data to answer user-related questions." -e "LANGFUSE_SECRET_KEY=sk-xxx" -e "LANGFUSE_PUBLIC_KEY=pk-xxx" -e "LANGFUSE_BASE_URL=http://192.168.xxx.xxx:3000" -p 20006:10100 registry.cn-shanghai.aliyuncs.com/jamesxiong/expert-agent:v0.2.0-amd64 --redis-host 192.168.xxx.xxx --redis-port 6389 --redis-db 1 --password 123 --provider openai_compatible --api-key sk-xxx --base-url https://dashscope.aliyuncs.com/compatible-mode/v1 --model deepseek-v3.1 --max-steps 5



agent 3（dd-e01 Satellite）:

docker run --rm -e "Agent_Host=192.168.xxx.xxx" -e "Agent_Port=20006" -e "DataServicesURL=http://192.168.xxx.xxx:22000" -e "Data_Descriptor=dd-e01" -e "DescriptorTypes=dd-e01:unstructured" -e "DD_NAMESPACE=dac" -e "SQL_PROCESS_MODE=dictionary" -e "Agent_Name=SatelliteAgent" -e "Agent_Description=I am a satellite intelligent agent that can answer questions related to satellites." -e "LANGFUSE_SECRET_KEY=sk-xxx" -e "LANGFUSE_PUBLIC_KEY=pk-xxx" -e "LANGFUSE_BASE_URL=http://192.168.xxx.xxx:3000" -p 20006:10100 registry.cn-shanghai.aliyuncs.com/jamesxiong/expert-agent:v0.2.0-amd64 --redis-host 192.168.xxx.xxx --redis-port 6389 --redis-db 1 --password 123 --provider openai_compatible --api-key sk-xxx --base-url https://dashscope.aliyuncs.com/compatible-mode/v1 --model deepseek-v3 --max-steps 5






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


