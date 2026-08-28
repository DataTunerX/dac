# DAC Helm Chart

[DAC](https://github.com/James-Dao/dac) 本 Chart 用于在 Kubernetes 集群中一键部署全部平台组件。

> Chart 版本 `0.1.0` · App 版本 `0.11.0`

## 前置条件

- Kubernetes >= 1.24
- Helm >= 3.x
- 集群中存在可用的 `StorageClass`（默认使用 `nfs-csi`，按需修改）
- PV provisioner 支持（MySQL / Redis / PGVector 需要持久存储）
- 兼容 OpenAI Chat Completions API 的 LLM 服务（如阿里云 DashScope、DeepSeek、vLLM、Ollama 等）及对应 API Key

## 安装

### 1. 准备配置文件

安装前**必须**创建 `my-values.yaml` 配置 API Key 和密码。`my-values.yaml` 不需要复制整个 `values.yaml`，只写需要覆盖的参数，Helm 会自动与默认值合并。

> **LLM API 兼容性**：DAC 使用 OpenAI 兼容协议调用大模型，`baseUrl` 需指向兼容 OpenAI Chat Completions API 的端点。

示例 `my-values.yaml`：

```yaml
global:
  # LLM 配置全局生效，所有 Agent 和 llmConfigs 条目均继承
  llm:
    provider: "openai_compatible"
    apiKey: "sk-your-real-key"
    baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1"
    model: "deepseek-v3.2"
  embedding:
    provider: "dashscope"
    apiKey: "sk-your-real-key"
    model: "text-embedding-v4"
    dims: "1024"
  # embedding:
  #   provider: "openai_compatible"
  #   apiKey: "sk-your-real-key"
  #   baseUrl: "https://xxx/v1"
  #   model: "bge-m3"
  #   dims: "1024"

  # LLM 观测（Langfuse）：默认关闭，开启后（enabled: true），用于观测所有对话过程中llm的调用的观测数据。
  langfuse:
    enabled: false
    baseUrl: "http://your-langfuse-host:3000"
    secretKey: "sk-lf-your-langfuse-secret-key"
    publicKey: "pk-lf-your-langfuse-public-key"

# llmConfigs 条目留空的字段会自动继承 global.llm 对应值；如需为某个条目使用不同模型，可单独覆盖
executionEngine:
  llmConfigs:
    - name: "llm-default"
      provider: "openai_compatible"
      apiKey: "sk-your-real-key"
      baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1"
      model: "deepseek-v3.2"

# 配置k8s的存储，用于mysql, redis, pgvector, neo4j的数据持久化，根据环境真实storage class设置
storageClass: "nfs-csi"

mysql:
  rootPassword: "changeme"
redis:
  password: "changeme"
pgvector:
  password: "changeme"
neo4j:
  password: "changeme"
```

### 1.1 使用外部中间件（可选）

如果已有 MySQL / Redis / PGVector / Neo4j 实例，配置对应的 `external` 字段即可：连接会指向外部实例，且**不会**再渲染内置 StatefulSet / Service。

```yaml
mysql:
  external:
    host: "192.168.1.100"
    port: 3306
    password: "your-mysql-password"

redis:
  external:
    host: "redis-ha.example.com"
    port: 6379
    password: "your-redis-password"

pgvector:
  external:
    host: "pg.example.com"
    port: 5432
    password: "your-pg-password"

neo4j:
  external:
    host: "neo4j.example.com"
    boltPort: 7687
    password: "your-neo4j-password"
```

> **说明**：
> - 设置 `external.host` 后自动跳过对应中间件的内置部署（无需再设 `enabled: false`；`enabled` 在此时被忽略）。
> - 端口可省略：MySQL 默认 3306、Redis 6379、PGVector 5432、Neo4j Bolt 7687。
> - Neo4j 的 `bolt://` / `neo4j://` URL 会由 `external.host` + `boltPort` 自动生成，无需再改 `dataServices.config.neo4j.boltUrl` / `neo4jUrl`。
> - 请确保集群内 Pod 能访问这些外部地址，且目标库已提前创建（内置 initdb 脚本不会对外部实例执行）。

### 2. 安装

#### 2.1 预先pull 镜像

有的镜像比较大，如果想启动速度快，可以提前将所有的镜像pull到机器上。所有相关镜像列表在images.md 文件中。

#### 2.2 执行安装

```bash
# 从 Chart 目录安装
helm install dac ./installer/dac -n dac --create-namespace -f my-values.yaml

```

生产环境可叠加内置的 `values-prod.yaml`（更大副本数、资源配额与 Ingress）：

```bash
helm install dac ./installer/dac -n dac --create-namespace \
  -f ./installer/dac/values-prod.yaml \
  -f my-values.yaml
```

> **注意**：`executionEngine.llmConfigs` 是数组类型，使用 `--set 'executionEngine.llmConfigs[0].apiKey=xxx'` 会**替换整个数组元素**而非合并，导致 `name`、`baseUrl` 等字段丢失。**对数组参数请务必使用 `-f` 文件方式覆盖**，不要用 `--set`。

### 3. 查看所有可配置参数

```bash
helm show values ./installer/dac
```

<details>
<summary>点击展开完整默认值</summary>

```yaml
# =============================================================================
# DAC Helm Chart - Default Values
# All values are documented inline. Override via --set or -f values-prod.yaml
# =============================================================================

# -- Override the chart name used in resource names
nameOverride: ""
# -- Override the full release name (takes precedence over nameOverride)
fullnameOverride: ""

# ---------------------------------------------------------------------------
# Global settings shared across all components
# ---------------------------------------------------------------------------
global:
  # -- Target namespace (informational; actual namespace is set at install time)
  namespace: dac
  # -- Container image registry prefix for all DAC images
  imageRegistry: "registry.cn-shanghai.aliyuncs.com/jamesxiong"
  # -- Default image pull policy (IfNotPresent | Always | Never)
  imagePullPolicy: IfNotPresent
  # -- Image pull secrets for private registries
  imagePullSecrets: []
  #  - name: my-registry-secret
  # -- Default StorageClass for all middleware PVCs ("" = cluster default)
  storageClass: "nfs-csi"

  # -- LLM provider configuration (shared by all agents)
  llm:
    # -- LLM provider type
    provider: "openai_compatible"
    # -- LLM API key (replace placeholder before use, e.g. sk-xxx → your real key)
    apiKey: "sk-xxx"
    # -- LLM API base URL
    baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1"
    # -- Default LLM model for agents
    model: "qwen2.5-72b-instruct"
    # -- Default LLM temperature
    temperature: "0.01"

  # -- Langfuse LLM observability (biz-routing-agent, biz-chart-agent); set enabled: true and fill keys to turn on
  langfuse:
    enabled: false
    baseUrl: ""
    secretKey: ""
    publicKey: ""

  # -- Embedding model configuration (used by data-services)
  embedding:
    # -- Embedding provider name
    provider: "dashscope"
    # -- Embedding API key (replace placeholder before use)
    apiKey: "sk-xxx"
    # -- Embedding model name
    model: "text-embedding-v4"
    # -- Embedding vector dimensions
    dims: "1024"

# =============================================================================
# Middleware - Built-in single-node StatefulSet instances
# Set <svc>.external.host to use an external instance (skips built-in deploy).
# =============================================================================

# ---------------------------------------------------------------------------
# MySQL 8.0 (used by: apiserver DB, data-services fingerprint/history)
# ---------------------------------------------------------------------------
mysql:
  # -- Deploy built-in MySQL. Set false to use external MySQL.
  enabled: true
  image:
    repository: mysql
    tag: "8.0"
  # -- MySQL service port
  port: 3306
  # -- Root password (CHANGE THIS before production use)
  rootPassword: "dac123"
  # -- Databases to create on init
  databases:
    - dac_db
    - fingerprint
    - history
  persistence:
    # -- Enable persistent storage via volumeClaimTemplates
    enabled: true
    # -- Override global.storageClass for MySQL ("" = use global)
    storageClass: ""
    # -- PVC size
    size: 2Gi
  resources:
    requests:
      cpu: 200m
      memory: 512Mi
    limits:
      cpu: 1000m
      memory: 2Gi

# ---------------------------------------------------------------------------
# Redis 7 (used by: agents, data-sinkers-job, semantic-grouper, registries)
# ---------------------------------------------------------------------------
redis:
  # -- Deploy built-in Redis. Set false to use external Redis.
  enabled: true
  image:
    repository: redis
    tag: "7.0.4"
  # -- Redis service port
  port: 6379
  # -- Redis auth password (CHANGE THIS before production use)
  password: "123"
  persistence:
    # -- Enable persistent storage via volumeClaimTemplates
    enabled: true
    # -- Override global.storageClass for Redis ("" = use global)
    storageClass: ""
    # -- PVC size
    size: 2Gi
  resources:
    requests:
      cpu: 100m
      memory: 256Mi
    limits:
      cpu: 500m
      memory: 1Gi

# ---------------------------------------------------------------------------
# PostgreSQL 16 + pgvector (used by: data-services vectors and memory)
# ---------------------------------------------------------------------------
pgvector:
  # -- Deploy built-in pgvector. Set false to use external PostgreSQL.
  enabled: true
  image:
    repository: pgvector
    tag: "pg16-amd64"
  # -- PostgreSQL service port
  port: 5432
  # -- PostgreSQL superuser name
  user: "postgres"
  # -- PostgreSQL superuser password (CHANGE THIS before production use)
  password: "postgres"
  # -- Databases to create on init (vector extension enabled in each)
  databases:
    - knowledge_vector
    - agent_memory
  persistence:
    # -- Enable persistent storage via volumeClaimTemplates
    enabled: true
    # -- Override global.storageClass for PGVector ("" = use global)
    storageClass: ""
    # -- PVC size
    size: 2Gi
  resources:
    requests:
      cpu: 200m
      memory: 512Mi
    limits:
      cpu: 1000m
      memory: 2Gi

# =============================================================================
# Core Platform Services
# =============================================================================

# ---------------------------------------------------------------------------
# dac-apiserver - Go HTTP API server with JWT auth and Casbin RBAC
# ---------------------------------------------------------------------------
apiserver:
  # -- Enable apiserver deployment
  enabled: true
  image:
    repository: dac-apiserver
    tag: "12-amd64"
  # -- Number of replicas
  replicas: 1
  service:
    # -- Service type (ClusterIP | NodePort | LoadBalancer)
    type: ClusterIP
    # -- Service port exposed to other services
    port: 80
    # -- Container port the Go binary listens on
    targetPort: 8080
    # -- Prometheus metrics port
    metricsPort: 9090
  config:
    server:
      # -- Gin run mode (release | debug)
      mode: "release"
      readTimeout: "60s"
      writeTimeout: "60s"
      # -- Max request body size in bytes (10 MB)
      maxRequestBodySize: 10485760
    log:
      # -- Log level (debug | info | warn | error)
      level: "info"
      # -- Log format (json | text)
      format: "json"
    observability:
      enableMetrics: false
      enableTracing: false
    routingAgent:
      # -- Timeout for routing agent calls
      timeout: "300s"
      # -- Session timeout for chat sessions
      sessionTimeout: "30m"
    database:
      # -- MySQL user for apiserver database
      user: "root"
      # -- Database name
      database: "dac_db"
      maxOpenConns: 25
      maxIdleConns: 5
      connMaxLifetime: "5m"
    jwt:
      # -- JWT signing secret (CHANGE THIS before production use)
      secret: "dac-jwt-secret-change-me"
  resources:
    requests:
      cpu: 100m
      memory: 128Mi
    limits:
      cpu: 500m
      memory: 512Mi

# ---------------------------------------------------------------------------
# frontend - Next.js UI with nginx reverse proxy
# ---------------------------------------------------------------------------
frontend:
  # -- Enable frontend deployment
  enabled: true
  image:
    registry: ""
    repository: frontend
    tag: "12"
  # -- Number of replicas
  replicas: 1
  service:
    # -- Service type (NodePort for direct access, ClusterIP behind ingress)
    type: NodePort
    # -- Service port
    port: 3000
    # -- Container port
    targetPort: 3000
  # -- Ingress for external HTTPS access (disabled by default)
  ingress:
    enabled: false
    # -- Ingress class name (e.g. nginx, traefik)
    className: "nginx"
    # -- Additional ingress annotations
    annotations: {}
    hosts:
      - host: dac.example.com
        paths:
          - path: /
            pathType: Prefix
    # -- TLS configuration
    tls: []
    #  - secretName: dac-tls
    #    hosts:
    #      - dac.example.com
  resources:
    requests:
      cpu: 100m
      memory: 128Mi
    limits:
      cpu: 500m
      memory: 512Mi

# ---------------------------------------------------------------------------
# data-services - Core data/vector/memory/knowledge-graph API
# ---------------------------------------------------------------------------
dataServices:
  # -- Enable data-services deployment
  enabled: true
  image:
    repository: data-services
    tag: "12-amd64"
  # -- Number of replicas
  replicas: 1
  service:
    type: ClusterIP
    port: 8000
    targetPort: 8000
  config:
    mysql:
      user: "root"
      # -- MySQL database for fingerprint storage
      fingerprintDatabase: "fingerprint"
      # -- MySQL database for history storage
      historyDatabase: "history"
      maxConnection: "50"
    pgvector:
      # -- pgvector database for knowledge vectors
      knowledgeDatabase: "knowledge_vector"
      minConnection: "1"
      maxConnection: "50"
    memory:
      # -- pgvector database for agent memory (mem0)
      database: "agent_memory"
      # -- Default memory collection name
      collection: "memories"
      minConnection: "1"
      maxConnection: "50"
      # -- Graph memory (enable | disable). Requires Neo4j.
      graphEnable: "disable"
    # -- Neo4j connection (only needed if graphEnable=enable)
    neo4j:
      url: "bolt://neo4j-server:7687"
      username: "neo4j"
      password: "test123456"
  resources:
    requests:
      cpu: 200m
      memory: 1Gi
    limits:
      cpu: 1000m
      memory: 2Gi

# =============================================================================
# Execution Engine - CRD-based Operator (manages DataAgentContainer / DataDescriptor)
#
# The execution-engine operator watches DataAgentContainer (DAC) and
# DataDescriptor (DD) custom resources and DYNAMICALLY creates Deployments
# containing orchestrator-agent, expert-agent, code-agent, doc-agent,
# dac-data-services, data-sinkers-job, etc. Those components are NOT installed
# as static Deployments by Helm; they are created/destroyed by the operator
# at runtime in response to CR lifecycle events.
# =============================================================================
executionEngine:
  # -- Deploy the execution-engine operator
  enabled: true
  image:
    repository: execution-engine
    tag: "12-amd64"
  replicas: 1
  resources:
    requests:
      cpu: 100m
      memory: 128Mi
    limits:
      cpu: 500m
      memory: 256Mi

  # -- Images the operator injects into dynamically created Deployments.
  #    When a DataAgentContainer CR is created, the operator uses these images
  #    for the orchestrator-agent, expert-agent, code-agent, doc-agent,
  #    dac-data-services, data-sinkers-job and data-sinkers-status containers.
  agentImages:
    orchestratorAgent:
      tag: "12-amd64"
    expertAgent:
      tag: "12-amd64"
    codeAgent:
      tag: "12-amd64"
    docAgent:
      tag: "12-amd64"
    dacDataServices:
      tag: "12-amd64"
    dataSinkerJob:
      tag: "12-amd64"
    dataSinkerStatus:
      tag: "12-amd64"

  # -- dac-configuration ConfigMap values (read by DAC controller)
  dacConfig:
    # -- Default planner LLM ConfigMap name
    defaultPlannerLLM: "llm-default"
    # -- Default expert LLM ConfigMap name
    defaultExpertLLM: "llm-default"
    # -- Optional Langfuse override (only when global.langfuse.enabled; else ignored; coalesced with global.langfuse.* for observation-* ConfigMaps and LANGFUSE_* env)
    observationBaseUrl: ""
    observationSecretKey: ""
    observationPublicKey: ""

  # -- dd-configuration ConfigMap values (read by DD controller)
  ddConfig:
    # -- LLM ConfigMap name used by data-sinkers-job
    llmConfig: "llm-default"

  # -- LLM model ConfigMaps created in the release namespace.
  #    The operator and CR spec reference these by name.
  llmConfigs:
    - name: "llm-default"
      provider: "openai_compatible"
      apiKey: "sk-xxx"
      baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1"
      model: "qwen2.5-72b-instruct"

# ---------------------------------------------------------------------------
# semantic-grouper - Semantic grouping API + Celery worker
# ---------------------------------------------------------------------------
semanticGrouper:
  # -- Enable semantic-grouper deployment
  enabled: true
  image:
    repository: semantic-grouper
    tag: "12-amd64"
  api:
    replicas: 1
    resources:
      requests:
        cpu: 100m
        memory: 256Mi
      limits:
        cpu: 500m
        memory: 512Mi
  worker:
    replicas: 1
    # -- Number of Celery worker processes in each pod
    celeryWorkerAmount: "2"
    hierarchyMergeDebounceSeconds: "60"
    resources:
      requests:
        cpu: 200m
        memory: 512Mi
      limits:
        cpu: 1000m
        memory: 1Gi
  config:
    # -- Redis DB index for Celery broker
    redisBrokerDb: "8"
    # -- Redis DB index for Celery result backend
    redisBackendDb: "9"
    # -- Redis DB index for distributed locks
    redisLockDb: "6"
    llm:
      provider: "openai_compatible"
      model: "deepseek-v3.2"
      temperature: "0.01"
  service:
    type: ClusterIP
    port: 8000
    targetPort: 8000

# =============================================================================
# Agent Registry - A2A agent card discovery
# =============================================================================

# ---------------------------------------------------------------------------
# orchestrator-registry - Registry for orchestrator agent cards
# ---------------------------------------------------------------------------
orchestratorRegistry:
  enabled: true
  image:
    repository: agent-registry
    tag: "12-amd64"
  replicas: 1
  config:
    # -- Vector collection name for agent cards
    collectionName: "orchestrator_agent_cards"
    # -- Redis DB index
    redisDb: "0"
  service:
    type: ClusterIP
    port: 8000
    targetPort: 8000
  resources:
    requests:
      cpu: 50m
      memory: 256Mi
    limits:
      cpu: 100m
      memory: 1Gi

# ---------------------------------------------------------------------------
# biz-orchestrator-registry - Registry for business orchestrator agent cards
# ---------------------------------------------------------------------------
bizOrchestratorRegistry:
  enabled: true
  image:
    repository: agent-registry
    tag: "12-amd64"
  replicas: 1
  config:
    collectionName: "biz_orchestrator_agent_cards"
    redisDb: "2"
  service:
    type: ClusterIP
    port: 8000
    targetPort: 8000
  resources:
    requests:
      cpu: 50m
      memory: 256Mi
    limits:
      cpu: 100m
      memory: 1Gi

# =============================================================================
# Agents - A2A protocol agents
# =============================================================================

# ---------------------------------------------------------------------------
# biz-routing-agent - Entry point: routes user queries to biz orchestrator agents
# ---------------------------------------------------------------------------
bizRoutingAgent:
  enabled: true
  image:
    repository: routing-agent
    tag: "12-amd64"
  replicas: 1
  config:
    # -- Redis DB index for agent state
    redisDb: "2"
    # -- Agent card collection to search for orchestrators
    registryCollection: "biz_orchestrator_agent_cards"
    # -- Max retries for LLM routing calls
    maxRetries: "1"
  service:
    type: ClusterIP
    # -- A2A protocol port
    port: 10100
    targetPort: 10100
  resources:
    requests:
      cpu: 100m
      memory: 512Mi
    limits:
      cpu: 1000m
      memory: 2Gi

# ---------------------------------------------------------------------------
# biz-chart-agent - ECharts generation agent (agent mode, self-registers)
# ---------------------------------------------------------------------------
bizChartAgent:
  enabled: true
  image:
    repository: chart-agent
    tag: "12-amd64"
  replicas: 1
  config:
    redisDb: "2"
    agentName: "ChartAgent"
    agentDescription: "根据用户描述与数据判断是否可绘图并生成 ECharts 图表；数据不足时明确说明无法生成。"
    # -- Start mode (agent = self-register to biz registry)
    startMode: "agent"
    # -- Whether to self-register to agent registry
    registerAgent: "true"
  service:
    type: ClusterIP
    port: 10100
    targetPort: 10100
  resources:
    requests:
      cpu: 50m
      memory: 512Mi
    limits:
      cpu: 100m
      memory: 2Gi

# =============================================================================
# NOTE: orchestrator-agent, expert-agent, code-agent, doc-agent,
# dac-data-services and data-sinkers-job are NOT deployed statically by Helm.
# They are dynamically created by the execution-engine operator when
# DataAgentContainer / DataDescriptor CRs are applied.
# See executionEngine.agentImages above for image configuration.
# =============================================================================
```

</details>

安装完成后 Helm 会输出 NOTES，包含各服务端点和后续操作提示。随时可重新查看：

```bash
helm get notes dac -n dac
```

### CRD

本 Chart 在 `crds/` 目录下包含以下 Custom Resource Definition，Helm 会在首次安装时自动创建：

- `dataagentcontainers.dac.dac.io`（DataAgentContainer）
- `datadescriptors.dac.dac.io`（DataDescriptor）

> Helm 不会在 `helm upgrade` 时更新 CRD。如需升级 CRD，请手动执行：
>
> ```bash
> kubectl apply -f ./installer/dac/crds/
> ```

## 配套：Sandbox（企业扫描演示数据面）

平台 Chart **不包含**演示库 / Odoo / Saleor / Boutique。验证「资产探测 → 建数据源」时，另装独立沙盒 Chart：

```bash
cd sandbox
make offline-prep   # 有网机构建/推送镜像（一次）
make apply          # helm upgrade --install ./chart -n dac-sandbox
make scan-targets   # 复制 IP/端口到前端 /infra
```

详见 [`sandbox/README.md`](../sandbox/README.md) 与 [`sandbox/chart/SPEC.md`](../sandbox/chart/SPEC.md)。  
Sandbox 与本 Chart 命名空间分离（默认 `dac-sandbox` vs `dac`），互不共用 MySQL/Redis。

## 安装后验证

```bash
kubectl get pods -n dac
helm status dac -n dac
```

默认配置下预期有以下 Pod（均为 1 副本）：

| Pod | 说明 |
|-----|------|
| `dac-apiserver-*` | API 服务 |
| `frontend-*` | 前端 UI |
| `data-services-*` | 数据 / 向量 / 记忆服务 |
| `execution-engine-*` | CRD Operator |
| `semantic-grouper-api-*` | 语义分组 API |
| `semantic-grouper-worker-*` | 语义分组 Worker |
| `orchestrator-registry-*` | Agent 注册中心 |
| `biz-orchestrator-registry-*` | 业务 Agent 注册中心 |
| `biz-routing-agent-*` | 路由 Agent |
| `biz-chart-agent-*` | 图表 Agent |
| `biz-skill-agent-*` | 技能 Agent |
| `skill-hub-*` | 技能 zip 包索引 / 下载服务（biz-skill-agent 启动时从这里按 `SKILLS` 拉取 zip） |
| `mysql-0` | MySQL StatefulSet（配置了 `mysql.external.host` 时不部署） |
| `redis-0` | Redis StatefulSet（配置了 `redis.external.host` 时不部署） |
| `pgvector-0` | PGVector StatefulSet（配置了 `pgvector.external.host` 时不部署） |
| `neo4j-0` | Neo4j StatefulSet（配置了 `neo4j.external.host` 时不部署） |

所有 Pod 进入 `Running` / `Ready` 后，按 NOTES 中的说明访问前端（NodePort / Ingress / port-forward）。

### 将 Skill 本地附加到 DAC

创建 Data Descriptor 或 Semantic Group 智能体时，可在表单中启用“本地技能附件”，从 Skill Hub 选择 `namespace / name / version`。选择结果写入 DAC 的 `spec.skillPolicy`；execution-engine 会为该 DAC 的 `orchestrator` 容器挂载临时技能目录，并在启动时下载、加载这些 zip。Skill 内容更新不需要重建 DAC 镜像；修改绑定或版本会更新 Deployment 并触发 Pod 滚动。

`dacType=skill` 的独立 `skill-agent` 模式仍然保留，适合需要单独注册和复用的技能 Agent。本地附件仅在所属 DAC 内执行，不会注册成独立 Agent。未固定版本时，每次 Pod 启动拉取最新版本；已固定版本始终拉取指定版本。

## 配置

所有参数均在 [`values.yaml`](dac/values.yaml) 中以行内注释形式说明。下表列出安装前**必须检查**的关键项。

### 密钥 / 凭据

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `global.llm.apiKey` | LLM 服务 API Key | `sk-xxx`（占位符） |
| `global.embedding.apiKey` | Embedding 服务 API Key | `sk-xxx`（占位符） |
| `executionEngine.llmConfigs[].apiKey` | Operator 管理的 Agent LLM API Key | `sk-xxx`（占位符） |
| `apiserver.config.jwt.secret` | JWT 签名密钥 | `dac-jwt-secret-change-me` |
| `mysql.rootPassword` | MySQL root 密码（内置实例） | `dac123` |
| `redis.password` | Redis 密码（内置实例） | `123` |
| `pgvector.password` | PostgreSQL 密码（内置实例） | `postgres` |
| `neo4j.password` | Neo4j 密码（内置实例） | `test123456` |
| `*.external.password` | 外部中间件密码（设置 `external.host` 时使用） | `""` |

> **注意**：所有 `sk-xxx` 均为占位符，部署前必须替换为真实 API Key。数据库密码和 JWT Secret 同样不应使用默认值。

### 镜像

所有 DAC 组件的镜像地址由 `global.imageRegistry` 统一控制：

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `global.imageRegistry` | 镜像仓库前缀 | `registry.cn-shanghai.aliyuncs.com/jamesxiong` |
| `frontend.image.registry` | 前端仓库（空则用 global） | `""` → `global.imageRegistry` |
| `global.imagePullPolicy` | 拉取策略 | `IfNotPresent` |
| `global.imagePullSecrets` | 私有仓库认证 Secret | `[]` |
| `tdb.enabled` | 部署共享 TDB API 服务 | `true` |
| `tdb.image.repository` / `tdb.image.tag` | TDB 组合运行时镜像 | `tdb-gateway` / `12-amd64` |
| `tdb.database.name` | TDB 使用的 PostgreSQL 逻辑数据库 | `tdb` |
| `tdb.database.existingSecret` | 可选，提供 `DATABASE_URL` 的现有 Secret | `""` |

### 存储

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `global.storageClass` | 所有中间件 PVC 的 StorageClass | `nfs-csi` |
| `skillHub.persistence.enabled` | 持久化 skill zip（上传/创建），避免 Pod 重启丢失 | `true` |
| `skillHub.persistence.type` | `hostPath`（单节点）或 `pvc` | `hostPath` |
| `skillHub.persistence.hostPath.path` | 节点本地目录 | `/var/lib/dac/skill-hub/skills` |
| `skillHub.persistence.pvc.size` | type=pvc 时的声明大小 | `5Gi` |

各中间件可通过 `mysql.persistence.storageClass` / `redis.persistence.storageClass` / `pgvector.persistence.storageClass` 单独覆盖；留空则使用 `global.storageClass`。将 `global.storageClass` 设为 `""` 可使用集群默认 StorageClass。

`skillHub.persistence.type=hostPath` 时数据在**节点本地**，要求 `replicas: 1`；多节点生产环境建议改为 `type: pvc`。每次 Pod 启动时 initContainer 会把镜像内置的 `default/` skill **同步覆盖**到持久卷（同名 zip 随镜像升级刷新；用户在 `default/` 下额外上传的其它 zip、以及其它命名空间不会被删）。

### 前端访问

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `frontend.service.type` | Service 类型 | `NodePort` |
| `frontend.ingress.enabled` | 启用 Ingress | `false` |
| `frontend.ingress.hosts[].host` | Ingress 域名 | `dac.example.com` |

### 使用外部中间件

Chart 内置的 MySQL、Redis、PGVector、Neo4j 均为单节点实例，适合开发和测试。生产环境建议对接外部托管实例。

推荐方式：在 `my-values.yaml` 中配置 `external`（见 [1.1](#11-使用外部中间件可选)）。设置 `external.host` 后，Chart 会跳过内置部署，并将 apiserver / data-services / agents 等组件的连接信息解析到外部地址。

```yaml
mysql:
  external:
    host: "mysql.example.com"
    port: 3306
    password: "your-mysql-password"

redis:
  external:
    host: "redis.example.com"
    password: "your-redis-password"

pgvector:
  external:
    host: "pg.example.com"
    password: "your-pg-password"

neo4j:
  external:
    host: "neo4j.example.com"
    password: "your-neo4j-password"
```

如需同时改数据库用户名等，再覆盖 `apiserver.config.database.user`、`dataServices.config.mysql.user`、`dataServices.config.neo4j.username` 等字段即可。

## 升级

```bash
helm upgrade dac ./installer/dac -n dac -f my-values.yaml
```

> 如 CRD 有变更，需在升级前手动 apply（见上方 [CRD](#crd) 章节）。

## 卸载

```bash
helm uninstall dac -n dac
```

卸载后 PVC 和 CRD 不会自动删除。如需完全清理：

```bash
# 删除持久数据
kubectl delete pvc -l app.kubernetes.io/instance=dac -n dac

# 删除 CRD（将同时删除所有 DataAgentContainer 和 DataDescriptor 资源）
kubectl delete crd dataagentcontainers.dac.dac.io datadescriptors.dac.dac.io
```

## 常见问题

**Pod 处于 Pending 状态**

通常是 PVC 无法绑定。检查 `StorageClass` 是否存在以及 PV provisioner 是否正常：

```bash
kubectl describe pvc -n dac
kubectl get sc
```

**LLM 调用失败**

确认 `global.llm.apiKey` 已替换为真实密钥，且集群到 `global.llm.baseUrl` 的网络可达。

**前端无法访问 API**

前端通过集群内部 Service 名称 `dac-apiserver` 反向代理后端。如修改了 `fullnameOverride`，请确认前后端 Service 名称匹配。

## 架构概览

```
┌─────────────────────────────────────────────────────┐
│                    Helm 静态部署                      │
│                                                     │
│  ┌──────────┐  ┌──────────┐  ┌───────────────────┐  │
│  │ frontend │  │apiserver │  │  data-services    │  │
│  └────┬─────┘  └────┬─────┘  └────────┬──────────┘  │
│       │             │                 │              │
│  ┌────┴─────────────┴─────────────────┴──────────┐  │
│  │          MySQL / Redis / PGVector             │  │
│  └───────────────────────────────────────────────┘  │
│                                                     │
│  ┌──────────────────┐  ┌─────────────────────────┐  │
│  │ semantic-grouper │  │ orchestrator-registry   │  │
│  │  (API + Worker)  │  │ biz-orchestrator-reg.   │  │
│  └──────────────────┘  └─────────────────────────┘  │
│                                                     │
│  ┌──────────────────┐  ┌─────────────────────────┐  │
│  │ biz-routing-agent│  │ biz-chart-agent         │  │
│  └──────────────────┘  └─────────────────────────┘  │
│  ┌──────────────────┐                               │
│  │ biz-skill-agent  │                               │
│  └──────────────────┘                               │
│                                                     │
│  ┌──────────────────────────────────────────────┐   │
│  │         execution-engine (Operator)          │   │
│  └──────────────────┬───────────────────────────┘   │
└─────────────────────┼───────────────────────────────┘
                      │ watches CRD
                      ▼
        ┌─────────────────────────────┐
        │    Operator 动态创建          │
        │  orchestrator-agent         │
        │  expert-agent / code-agent  │
        │  doc-agent / data-sinkers-job
        │  data-sinkers-observer      |
        └─────────────────────────────┘
```

| 层级 | 组件 | 说明 |
|------|------|------|
| **中间件** | MySQL、Redis、PGVector、Neo4j | 内置单节点 StatefulSet；设 `*.external.host` 对接外部实例并跳过内置部署 |
| **共享数据服务** | TDB | 面向 DAC 和其他 Agent 的 HTTP API；默认复用 PGVector 实例中的独立 `tdb` 数据库 |
| **平台服务** | apiserver、frontend、data-services | API 网关 / 前端 UI / 数据与向量服务 |
| **Operator** | execution-engine | 监听 `DataAgentContainer` / `DataDescriptor` CRD，动态创建 Agent 工作负载 |
| **语义分组** | semantic-grouper（API + Worker） | Celery 异步语义分组 |
| **Agent 注册中心** | orchestrator-registry、biz-orchestrator-registry | A2A Agent Card 发现 |
| **Agent** | biz-routing-agent、biz-chart-agent、biz-skill-agent | 路由 / 图表生成 / 技能执行等业务 Agent |
| **Skill Hub** | skill-hub | 技能 zip 包索引 / 下载 HTTP 服务，供 biz-skill-agent 启动时按 `SKILLS` 拉取；上传/创建的 zip 默认落在节点 hostPath（`skillHub.persistence`），避免 Pod 重启丢失 |

TDB 启用后，chart 会把集群内地址写入 `dac-configuration` 的 `tdb-url`。execution-engine 会将它作为 `TDB_BASE_URL` 注入动态创建的 orchestrator、expert 和 skill agent；内置 `biz-skill-agent` 也会收到同一变量。

> `orchestrator-agent`、`expert-agent`、`code-agent`、`doc-agent`、`data-sinkers-job` 、`data-sinkers-observer` 等组件**不在 Helm 中静态部署**，由 execution-engine Operator 根据 CR 动态管理。
