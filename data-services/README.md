# Server

## Local Testing:

# Initialize memory database, vector database, knowledge pyramid knowledge base

## PostgreSQL:

Create three databases: agent_memory, knowledge_vector, knowledge_graph

```bash
psql -U postgres -h localhost -p 5432

CREATE DATABASE agent_memory;

CREATE DATABASE knowledge_vector;

CREATE DATABASE knowledge_graph;

```

# Initialize fingerprint database

## MySQL:

```sql
CREATE DATABASE fingerprint CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

# Initialize history conversation database

## MySQL:

```sql
CREATE DATABASE history CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

## Database Operations

### View all databases

```bash
\l
```

### Switch to other database

```bash
\c <database>
```

# Disable telemetry

```bash
export EC_TELEMETRY="False"
export MEM0_TELEMETRY="False"
```

# Set embedding required variables

## Aliyun:
```bash
export EMBEDDING_PROVIDER="dashscope"
export EMBEDDING_API_KEY="sk-xxx"
export EMBEDDING_MODEL="text-embedding-v4"
```

# Set LLM required variables

```bash
export LLM_API_KEY="sk-xxx"
export LLM_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"
export LLM_MODEL="qwen3-32b"
export LLM_TEMPERATURE="0.01"
```

# MEMORY database configuration, for agent memory capability

```bash
export MEMORY_PGVECTOR_HOST="192.168.3.7"
export MEMORY_PGVECTOR_PORT="5433"
export MEMORY_PGVECTOR_USER="postgres"
export MEMORY_PGVECTOR_PASSWORD="postgres"
export MEMORY_PGVECTOR_MIN_CONNECTION="1"
export MEMORY_PGVECTOR_MAX_CONNECTION="50"
export MEMORY_DBNAME="agent_memory"
export MEMORY_COLLECTION="memories"
export MEMORY_EMBEDDING_DIMS="1024"
```

# Set knowledge pyramid configuration

## Pyramid vector pgvector settings
```bash
export PGVECTOR_HOST="192.168.3.7"
export PGVECTOR_PORT="5433"
export PGVECTOR_USER="postgres"
export PGVECTOR_PASSWORD="postgres"
export PGVECTOR_DATABASE="knowledge_vector"
export PGVECTOR_MIN_CONNECTION="1"
export PGVECTOR_MAX_CONNECTION="50"
```

## DD fingerprint database

```bash
export MYSQL_HOST="192.168.3.7"
export MYSQL_PORT="3307"
export MYSQL_USER="root"
export MYSQL_PASSWORD="123"
export MYSQL_DATABASE="fingerprint"
export MYSQL_MAX_CONNECTION="50"
```

## Memory graph database

```bash
export MEMORY_GRAPH_ENABLE="enable"
export MEMORY_GRAPH_DB_PROVIDER="neo4j"
export MEMORY_GRAPH_DB_URL="neo4j://192.168.3.7:7687"
export MEMORY_GRAPH_DB_USERNAME="neo4j"
export MEMORY_GRAPH_DB_PASSWORD="test123456"
export MEMORY_GRAPH_LLM_MODEL="deepseek-v3.1"
export MEMORY_GRAPH_LLM_APIKEY="sk-xxx"
export MEMORY_GRAPH_LLM_BASEURL="https://dashscope.aliyuncs.com/compatible-mode/v1"
```

# Complete local startup configuration

```bash
export EC_TELEMETRY="False"
export MEM0_TELEMETRY="False"
export EMBEDDING_PROVIDER="dashscope"
export EMBEDDING_API_KEY="sk-xxx"
export EMBEDDING_MODEL="text-embedding-v4"
export LLM_API_KEY="sk-xxx"
export LLM_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"
export LLM_MODEL="qwen3-32b"
export LLM_TEMPERATURE="0.01"

export MEMORY_PGVECTOR_HOST="192.168.3.7"
export MEMORY_PGVECTOR_PORT="5433"
export MEMORY_PGVECTOR_USER="postgres"
export MEMORY_PGVECTOR_PASSWORD="postgres"
export MEMORY_PGVECTOR_MIN_CONNECTION="1"
export MEMORY_PGVECTOR_MAX_CONNECTION="50"
export MEMORY_DBNAME="agent_memory"
export MEMORY_COLLECTION="memories"
export MEMORY_EMBEDDING_DIMS="1024"
export MEMORY_GRAPH_ENABLE="enable"
export MEMORY_GRAPH_DB_PROVIDER="neo4j"
export MEMORY_GRAPH_DB_URL="neo4j://192.168.3.7:7687"
export MEMORY_GRAPH_DB_USERNAME="neo4j"
export MEMORY_GRAPH_DB_PASSWORD="test123456"
export MEMORY_GRAPH_LLM_MODEL="deepseek-v3.1"
export MEMORY_GRAPH_LLM_APIKEY="sk-xxx"
export MEMORY_GRAPH_LLM_BASEURL="https://dashscope.aliyuncs.com/compatible-mode/v1"

export PGVECTOR_HOST="192.168.3.7"
export PGVECTOR_PORT="5433"
export PGVECTOR_USER="postgres"
export PGVECTOR_PASSWORD="postgres"
export PGVECTOR_DATABASE="knowledge_vector"
export PGVECTOR_MIN_CONNECTION="1"
export PGVECTOR_MAX_CONNECTION="50"

export MYSQL_HOST="192.168.3.7"
export MYSQL_PORT="3307"
export MYSQL_USER="root"
export MYSQL_PASSWORD="123"
export MYSQL_FINGERPRINT_DATABASE="fingerprint"
export MYSQL_MAX_CONNECTION="50"

export MYSQL_HISTORY_DATABASE="history"

uv run data-services --host 192.168.3.7 --port 22000
```

## Local Docker Testing:

docker run --rm \
  --name data-services \
  -p 22000:8000 \
  -e MEM0_TELEMETRY="False" \
  -e EC_TELEMETRY="False" \
  -e EMBEDDING_PROVIDER="dashscope" \
  -e EMBEDDING_API_KEY="sk-xxx" \
  -e EMBEDDING_MODEL="text-embedding-v4" \
  -e LLM_API_KEY="sk-xxx" \
  -e LLM_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1" \
  -e LLM_MODEL="deepseek-v3.2" \
  -e LLM_TEMPERATURE="0.01" \
  -e MEMORY_PGVECTOR_HOST="192.168.3.7" \
  -e MEMORY_PGVECTOR_PORT="5433" \
  -e MEMORY_PGVECTOR_USER="postgres" \
  -e MEMORY_PGVECTOR_PASSWORD="postgres" \
  -e MEMORY_DBNAME="agent_memory" \
  -e MEMORY_PGVECTOR_MIN_CONNECTION="1" \
  -e MEMORY_PGVECTOR_MAX_CONNECTION="50" \
  -e MEMORY_COLLECTION="memories" \
  -e MEMORY_EMBEDDING_DIMS="1024" \
  -e MEMORY_GRAPH_ENABLE="disable" \
  -e MEMORY_GRAPH_DB_PROVIDER="neo4j" \
  -e MEMORY_GRAPH_DB_URL="neo4j://192.168.3.7:7687" \
  -e MEMORY_GRAPH_DB_USERNAME="neo4j" \
  -e MEMORY_GRAPH_DB_PASSWORD="test123456" \
  -e MEMORY_GRAPH_LLM_MODEL="deepseek-v3.2" \
  -e MEMORY_GRAPH_LLM_APIKEY="sk-xxx" \
  -e MEMORY_GRAPH_LLM_BASEURL="https://dashscope.aliyuncs.com/compatible-mode/v1" \
  -e KNOWLEDGE_GRAPH_DB_URL="neo4j://192.168.3.7:7687" \
  -e KNOWLEDGE_GRAPH_DB_USERNAME="neo4j" \
  -e KNOWLEDGE_GRAPH_DB_PASSWORD="test123456" \
  -e KNOWLEDGE_GRAPH_EMBEDDING_DIMS="1024" \
  -e PGVECTOR_HOST="192.168.3.7" \
  -e PGVECTOR_PORT="5433" \
  -e PGVECTOR_USER="postgres" \
  -e PGVECTOR_PASSWORD="postgres" \
  -e PGVECTOR_DATABASE="knowledge_vector" \
  -e PGVECTOR_MIN_CONNECTION="1" \
  -e PGVECTOR_MAX_CONNECTION="50" \
  -e MYSQL_HOST="192.168.3.7" \
  -e MYSQL_PORT="3307" \
  -e MYSQL_USER="root" \
  -e MYSQL_PASSWORD="123" \
  -e MYSQL_FINGERPRINT_DATABASE="fingerprint" \
  -e MYSQL_MAX_CONNECTION="50" \
  -e MYSQL_HISTORY_DATABASE="history" \
  -e NEO4J_URI="bolt://192.168.3.7:7687" \
  -e NEO4J_USER="neo4j" \
  -e NEO4J_PASSWORD="test123456" \
  registry.cn-shanghai.aliyuncs.com/jamesxiong/data-services:v0.6.0-amd64
