# Sandbox 环境

用于 DAC 数据发现 / 扫描 / PII 检测的模拟目标环境。所有数据均为虚构样本，**请勿用于生产**。

sandbox 包含两类数据：

1. **预置模拟数据** — Postgres ERP 表、MinIO 文件、Trino 外表等，供发现/扫描/PII 检测使用
2. **组件自身数据** — Nextcloud / Odoo / ERPNext / Gitea 运行时自动产生的内部数据

## 包含的服务

| 服务 | 说明 | 镜像 |
|------|------|------|
| **Postgres** | ERP 样本库（`erp` / `appcfg` schema） | `postgres:16` |
| **MinIO** | S3 兼容对象存储（`objects` / `lake` bucket） | `minio/minio` |
| **Trino** | SQL 查询引擎（Hive + Postgres connector） | `trinodb/trino` |
| **Nextcloud** | 替代 O365 的文件/协作平台 | `nextcloud:29-apache` |
| **Odoo** | ERP 系统（客户/订单/库存等） | `odoo:17` |
| **ERPNext** | 全功能 ERP（仅 K8s 模式） | `erpnext:v15.95.0` |
| **Gitea** | Git 代码仓库 | `gitea/gitea:1.21.11` |

## 凭据

### 数据库

| 服务 | Host | Port | 用户 | 密码 | 数据库 |
|------|------|------|------|------|--------|
| Postgres（主） | localhost | 5432 | `dac` | `dacpass` | `dac_sandbox` |
| Postgres（Hive Metastore） | localhost | 5433 | `hive` | `hivepass` | `metastore` |
| Postgres（Odoo） | localhost | 5434 | `odoo` | `odoopass` | `postgres` |
| MariaDB（Nextcloud） | localhost | 3306 | `nextcloud` | `nextcloudpass` | `nextcloud`（root: `nextcloudroot`） |
| MariaDB（ERPNext，仅 K8s） | localhost | 3306 | `root` | `admin` | — |

### 应用

| 服务 | 用户 | 密码 |
|------|------|------|
| MinIO Console | `minioadmin` | `minioadmin` |
| Nextcloud | `admin` | `adminpass` |
| Odoo | — | —（首次访问时设置） |
| Gitea | `giteaadmin` | `giteaadminpass` |
| ERPNext（仅 K8s） | `Administrator` | `admin` |

## Docker Compose 模式

```bash
cd sandbox
cp env.example .env
# 编辑 .env，设置 SOURCE_REPO_PATH（Gitea 初始化用的本地 Git 仓库路径）
# 可选修改 SOURCE_REPO_NAME（仓库在 Gitea 中的名称，默认 sample-project）
docker compose up -d
docker compose ps
```

访问地址：

| 服务 | URL |
|------|-----|
| MinIO Console | http://localhost:9001 |
| MinIO S3 API | http://localhost:9000 |
| Trino | http://localhost:8080 |
| Nextcloud | http://localhost:8011 |
| Odoo | http://localhost:8012 |
| Gitea | http://localhost:8013 |

停止：

```bash
docker compose down
```

## Kubernetes 模式

所有 sandbox 服务运行在**单个 Pod（多容器）**中，共享网络命名空间，适合模拟单主机多端口扫描。

```bash
kubectl apply -f sandbox/k8s/00-namespace.yaml
kubectl apply -f sandbox/k8s/01-configmaps.yaml
kubectl apply -f sandbox/k8s/03-services.yaml
kubectl apply -f sandbox/k8s/02-statefulset.yaml
kubectl apply -f sandbox/k8s/04-jobs.yaml

# ERPNext（可选，资源消耗较大）
kubectl apply -f sandbox/k8s/05-erp.yaml
```

验证：

```bash
kubectl -n dac-sandbox get pods -w
kubectl -n dac-sandbox get svc
```

> K8s 模式使用 emptyDir，Pod 重建后数据重置。

### Gitea 镜像构建

K8s 模式使用预置源码的 Gitea 镜像。如需重新构建并推送：

```bash
docker login release.daocloud.io
REGISTRY_NS=release.daocloud.io/dac LOCAL_REPO_PATH=/path/to/your-local-repo sh sandbox/bin/publish-images.sh
```

## 样本数据

| 类型 | 内容 |
|------|------|
| **Postgres** | `erp.customers`、`erp.orders`、`erp.employees`（含 PII 字段：national_id、ssn、payment_card_last4） |
| **MinIO `objects`** | `o365/drive/readme.txt`、`erp/exports/customers.csv` |
| **MinIO `lake`** | `warehouse/demo.db/orders/orders.csv`（Trino 外表） |
| **Trino** | `hive.demo.orders`（S3 CSV）、`postgresql.dac_sandbox.erp.*`（关联查询） |
