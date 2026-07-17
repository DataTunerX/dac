# DAC Sandbox

DAC（Data Agent Container）平台的端到端演示沙盒。在单个 Kubernetes Pod 中运行 5 个数据服务，并预置覆盖全部 4 种 `descriptorType`（`structured-mysql` / `structured-postgres` / `unstructured` / `code`）的种子数据。

> [!WARNING]
> 沙盒中所有数据均为虚构样本或公开开源数据集，仅用于演示和开发，不得用于生产环境。

---

## 目录

- [概述](#概述)
- [功能特性](#功能特性)
- [架构](#架构)
- [前置条件](#前置条件)
- [快速开始](#快速开始)
- [安装](#安装)
- [配置](#配置)
- [使用](#使用)
- [数据源参考](#数据源参考)
- [种子数据](#种子数据)
- [能力覆盖矩阵](#能力覆盖矩阵)
- [故障排查](#故障排查)
- [运维操作](#运维操作)
- [项目结构](#项目结构)
- [设计说明](#设计说明)
- [第三方数据集与许可](#第三方数据集与许可)
- [兼容性](#兼容性)
- [许可证](#许可证)

---

## 概述

DAC Sandbox 在单个 Kubernetes Pod 中提供完整的 DAC 演示环境，包含：

- 5 个数据服务容器：MySQL、PostgreSQL、MinIO、FileServer、GitLab CE
- 10 个手工/开源示例数据库、21 份多格式文件、MovieLens 1M 数据集、2 个示例代码仓库（test-code + saleor）
- **可选企业应用栈**（`make apply-apps`）：Odoo 17 + demo data、Saleor 电商平台、Google Online Boutique 微服务演示
- 与 `examples/dac-cr/` 完全对齐的连接信息，可直接用于 dac-apiserver 的 `DataDescriptor` / `DataAgentContainer` 自定义资源

部署完成后可在 DAC 前端完成「资产探测 → 创建数据源 → 运行 Agent」的完整闭环。

## 功能特性

- 覆盖全部 `DataSourceType`：`mysql` / `postgres` / `minio` / `fileserver` / `coderepo`
- 覆盖全部 `descriptorType`：`structured-mysql` / `structured-postgres` / `unstructured` / `code`
- 支持单连接多库 fan-out：一个 `DataDescriptor` 可展开生成多个 `DataSource`，每个对应一个数据库
- 不依赖 PersistentVolume，使用 `emptyDir`，可在 kind / minikube / CI 等最小化集群部署
- 不依赖手工初始化，所有种子数据在镜像 build 阶段或 Job 中自动注入
- 凭据集中固定，与 `examples/dac-cr/` 对齐
- 通过别名 Service 暴露稳定的 Kubernetes DNS，使示例 YAML 无需修改即可运行

## 架构

### 拓扑

```
┌──────────────────────── dac-sandbox-0 (Pod) ─────────────────────────┐
│  mysql:3306    postgres:5432    minio:9000/9001    fileserver:8000   │
│                                 gitlab:8929                          │
└──────────────────────────────────────────────────────────────────────┘
        ▲                                                  ▲
        │                                                  │
   seed-job (导入 MinIO 数据)                  gitlab-seed-job (创建仓库)

┌──────────── 企业应用栈（独立 Deployment，make apply-apps）────────────┐
│  odoo:8069 + odoo-db:5432 (odoo_demo，含 ERP demo data)              │
│  saleor-api:8000 + saleor-dashboard:9000 + saleor-db + saleor-cache  │
│  online-boutique: frontend:80 + 10+ 微服务（gRPC/HTTP）               │
└──────────────────────────────────────────────────────────────────────┘
```

部署在命名空间 `dac-sandbox` 下，由一个 StatefulSet（`dac-sandbox-0`）和两个 seed Job 组成。

### 服务与端口

| 容器 | 端口 | 协议 | 用途 | 对应 descriptor / source 类型 |
|------|------|------|------|-------------------------------|
| `mysql` | 3306 | TCP | MySQL 8 服务端 | `structured-mysql` / `mysql` |
| `postgres` | 5432 | TCP | PostgreSQL 16 服务端 | `structured-postgres` / `postgres` |
| `minio` | 9000 | HTTP | MinIO S3 API | `unstructured` / `minio` |
| `minio` | 9001 | HTTP | MinIO Console（管理 UI） | 不作为业务端口 |
| `fileserver` | 8000 | HTTP | nginx autoindex 静态目录 | `unstructured` / `fileserver` |
| `gitlab` | 8929 | HTTP | GitLab CE 17.5 代码仓库 | `code` / `coderepo` |

### Kubernetes Service

| Service | 暴露端口 | 用途 |
|---------|----------|------|
| `dac-sandbox` | 全部 6 个端口 | 主 Service，单一 ClusterIP 暴露所有服务，资产探测时使用 |
| `mysql-server` | 3306 | 别名 Service，使示例 YAML 可写 `host: mysql-server` |
| `postgres-server` | 5432 | 别名 Service |
| `fileserver` | 8000 | 别名 Service |
| `gitlab` | 8929 | 别名 Service |

跨命名空间访问时使用 FQDN，例如 `mysql-server.dac-sandbox.svc.cluster.local`。

## 前置条件

| 依赖 | 最低版本 | 说明 |
|------|----------|------|
| Kubernetes | 1.24+ | kind / minikube / 自建集群均可，建议 ≥ 4 vCPU / 8 GiB（GitLab CE 占用 4 GiB+ 内存） |
| `kubectl` | 与集群匹配 | 已配置可访问的 context |
| Docker | 20.10+ | 仅在构建或推送镜像时需要 |
| 镜像仓库 | - | 可推送的 registry，默认 `release.daocloud.io/dac` |
| 外网访问 | - | 仅 `make vendor` 下载开源数据集时需要 |

## 快速开始

### 离线演示（推荐）

沙盒设计为**两阶段**：有网构建机准备一次，离线集群只拉私有 registry。

**阶段 A — 有网构建机（只需跑一次）**

```bash
cd sandbox
docker login release.daocloud.io
make offline-prep
```

`offline-prep` 会依次完成：

1. **`make vendor`** — 下载 Sakila/Pagila/Chinook/Northwind/Employees/MovieLens 等 **SQL/dump** 到 `seed/`（不提交 git，打入镜像）
2. **`make mirror-images`** — 把 Docker Hub、GHCR Saleor、Online Boutique 共 **23 个外部镜像** pull → tag → push 到 `$(REGISTRY)`
3. **`make build push`** — 构建 `sandbox-mysql` / `sandbox-postgres` 等 5 个镜像（**vendor SQL 已 COPY 进镜像**）并推送

**阶段 B — 离线集群**

```bash
cd sandbox
make apply-all && make verify
```

集群**不再需要**访问 docker.io / ghcr.io / google-samples / GitHub / MySQL 下载站。

**离线能力一览**（阶段 B 集群内全程无需外网）：

| 组件 | 运行时联网 | 说明 |
|------|------------|------|
| 核心 sandbox（MySQL/Postgres/MinIO/FileServer/GitLab） | 否 | SQL、文件、代码仓在 `make build` / seed Job 中已注入 |
| Odoo 17 demo | 否 | 含 `point_of_sale` + `pos_restaurant`（餐厅）；随 `odoo:17.0` 镜像内置，init 本地安装 |
| Saleor API + Dashboard | 否 | `saleor:3.23`、`saleor-dashboard:3.23` + `populatedb` Job |
| Online Boutique | 否 | 10 个微服务镜像已 mirror 到 `$(REGISTRY)/boutique-*` |

> **演示时注意**：Odoo 界面里从「应用商店」在线安装**额外**模块需要外网。Sandbox 已预装销售/库存/会计 + **餐厅（pos_restaurant）**，无需在线安装。若需第三方应用商店插件（如 `pos_offline_restaurant`），须在有网机下载 zip 并打入自定义镜像（见下方）。

**已有 Odoo 环境升级餐厅模块**（filestore 正常、仅缺餐厅时）：

```bash
kubectl apply -f k8s/05-odoo.yaml
kubectl -n dac-sandbox rollout restart deploy/odoo
kubectl -n dac-sandbox logs deploy/odoo -c init-demo -f
```

若仍报 `filestore` 错误，按下方「Odoo 重新初始化」清空重来。

企业应用首次启动耗时：Odoo `init-demo` 约 5–10 分钟（`kubectl -n dac-sandbox logs deploy/odoo -c init-demo -f`），Saleor `saleor-populatedb` 依赖 API ready。

> [!IMPORTANT]
> 若跳过 `offline-prep` 只跑 `make apply`，Pod 会因缺少私有 registry 中的基础镜像而 `ImagePullBackOff`。离线环境必须先完成阶段 A。

### 仅核心沙盒（不含 Odoo/Saleor/Boutique）

```bash
make apply && make verify
```

`make verify` 会输出 Pod IP、各服务的连通性检查结果，以及 seed 数据状态。

## 安装

完整流程：同步公共镜像 → 构建沙盒镜像 → 部署 → 自检。

### 1. 同步外部镜像到私有 registry

离线环境**必须**在有网机器执行（`make offline-prep` 已包含此步）。仅补镜像时可单独跑：

```bash
docker login release.daocloud.io
make mirror-images    # 等同旧名 make mirror-public
```

`scripts/mirror-images.sh` 同步清单：

| 来源 | 私有 registry 目标 | 用途 |
|------|-------------------|------|
| `docker.io/library/mysql:8.0` | `$(REGISTRY)/mysql:8.0` | MySQL 基础镜像 + sandbox-mysql 父镜像 |
| `docker.io/library/postgres:16` | `$(REGISTRY)/postgres:16` | Postgres 基础 + Odoo/Saleor DB |
| `docker.io/nginx:1.27-alpine` | `$(REGISTRY)/nginx:1.27-alpine` | FileServer |
| `docker.io/alpine:3.20` | `$(REGISTRY)/alpine:3.20` | seed Job |
| `docker.io/minio/mc:latest` | `$(REGISTRY)/mc:latest` | MinIO seed |
| `docker.io/minio/minio:latest` | `$(REGISTRY)/minio:latest` | 对象存储 |
| `docker.io/gitlab/gitlab-ce:17.5.0-ce.0` | `$(REGISTRY)/gitlab-ce:17.5.0-ce.0` | GitLab CE |
| `docker.io/odoo:17.0` | `$(REGISTRY)/odoo:17.0` | Odoo ERP |
| `docker.io/valkey/valkey:8.1-alpine` | `$(REGISTRY)/valkey:8.1-alpine` | Saleor 缓存 |
| `docker.io/library/redis:alpine` | `$(REGISTRY)/redis:alpine` | Boutique cart Redis |
| `ghcr.io/saleor/saleor:3.23` | `$(REGISTRY)/saleor:3.23` | Saleor API + populatedb |
| `ghcr.io/saleor/saleor-dashboard:3.23` | `$(REGISTRY)/saleor-dashboard:3.23` | Saleor 管理后台 SPA |
| `google-samples/.../currencyservice:v0.10.5` 等 10 个 | `$(REGISTRY)/boutique-<svc>:v0.10.5` | Online Boutique 微服务 |

### 2. 下载 SQL 并打入镜像

开源样本 **SQL 不单独挂载**，而是在 `make build` 时 COPY 进 `sandbox-mysql` / `sandbox-postgres` 镜像：

```bash
make vendor    # 下载到 seed/mysql/*.sql、seed/postgres/*.sql、employees-dumps/
make build     # vendor 为 build-mysql/build-postgres 的前置依赖
make push
```

离线集群拉 `sandbox-mysql:v0.11.0` 即已含 northwind/sakila/employees 等全部库，**无需再下载 SQL**。

### 3. 构建沙盒镜像

```bash
make all          # vendor + build + push（不含 mirror-images，离线前请用 offline-prep）
```

等价于 `make vendor && make build && make push`。`gitlab-seed` 构建期 git clone `test-code` + `saleor` 进镜像，离线无需再访问 Gitee/GitHub。

### 4. 部署到 Kubernetes

```bash
make apply          # 仅核心 sandbox
# 或
make apply-all      # 核心 + Odoo / Saleor / Online Boutique
kubectl -n dac-sandbox get pods -w
```

Pod 通常需要 3–5 分钟进入 `Running` 状态（5/5 容器就绪）—— 其中 GitLab CE 首次启动会执行 reconfigure + 数据库迁移，单容器就要 3 分钟左右。`gitlab-seed-job` 内置最长 600 秒等待 GitLab Ready 的逻辑。

企业应用栈额外耗时：Odoo `init-demo` initContainer 约 5–10 分钟灌入 demo data；`saleor-populatedb` 在 API ready 后灌演示商品。全部镜像应已在私有 registry（`make offline-prep`）。

### 5. 自检

```bash
make verify
```

输出包含：

- Pod 与 Service 列表
- Pod IP（在前端创建数据源时使用）
- MySQL 数据库列表（应有 6 个）
- PostgreSQL 数据库列表（应有 4 个）
- MinIO bucket 列表（应有 `dac-files`、`dac-datasets`）
- FileServer 目录索引（前 10 项）
- GitLab 项目列表（应有 `root/test-code` 和 `root/saleor`）
- 企业应用栈 Deployment/Job 状态（`make apply-apps` 后应有 odoo / saleor-api / saleor-dashboard / frontend 等）

## 企业应用栈

在**保留原有 sandbox** 的前提下，通过独立 Deployment 叠加三套可运行的企业业务应用（不塞进单 Pod StatefulSet，避免与 GitLab 争抢内存）。

| 应用 | 部署文件 | 入口 Service | 端口 | 业务数据 |
|------|----------|--------------|------|----------|
| **Odoo 17 + demo** | `k8s/05-odoo.yaml` | `odoo` | 8069 | PostgreSQL `odoo_demo`（`init-demo`：`-i base,sale,stock,account,point_of_sale,pos_restaurant`；含**餐厅 POS** demo，完全离线） |
| **Saleor API** | `k8s/06-saleor.yaml` | `saleor-api` | 8000 | PostgreSQL `saleor`（Job `saleor-populatedb` 灌演示商品） |
| **Saleor Dashboard** | `k8s/06-saleor.yaml` | `saleor-dashboard` | 9000（→ 容器 80，`/dashboard/`） | 管理后台 SPA；nginx 反代 `/graphql/` → API；登录 `admin@example.com` / `admin` |
| **Online Boutique** | `k8s/apps/online-boutique.yaml`（`make vendor-apps` 生成，镜像已改写为 `$(REGISTRY)/boutique-*`） | `frontend` | 80 | 11 个微服务 gRPC/HTTP 电商链路 |

```bash
make apply-apps     # kubectl apply（离线集群直接跑，无需外网）
make delete-apps    # 仅卸应用栈
make delete-all     # 应用栈 + 核心 sandbox
```

有网机更新 Boutique manifest 时：`REGISTRY=... make vendor-apps`

**DAC 资产探测**：企业应用栈**故意拆成多个 Pod**（模拟真实环境里不同主机上的服务），供一次扫描发现多种指纹。不必扫多次——**一次扫描填多个 Pod IP** 即可（见 `make scan-targets`）。

### 资产探测演示（推荐流程）

```bash
make apply-all && make verify          # 等 Odoo init / Saleor populatedb 完成
make scan-targets                      # 复制「目标」和「端口」到前端
```

| 字段 | 取值 |
|------|------|
| **目标** | `make scan-targets` 输出的逗号分隔 IP 列表 |
| **端口** | `3306,5432,8069,8000,80,8929,9000,9001` |
| **并发 / 超时** | 默认即可 |

扫描完成后，**发现的服务** 里应出现（分布在不同 IP 上）：

| Pod | 端口 | 指纹 / 类型 | 演示用途 |
|-----|------|-------------|----------|
| `dac-sandbox-0` | 3306 | MYSQL | 多库 fan-out（northwind、sakila…） |
| `dac-sandbox-0` | 5432 | POSTGRES | pagila、chinook… |
| `dac-sandbox-0` | 9000 | MinIO | 对象存储 |
| `dac-sandbox-0` | 8929 | GitLab | 代码仓 |
| `dac-sandbox-0` | 8000 | HTTP 通用 | FileServer（手动建数据源） |
| `odoo-*` | **8069** | **product `odoo`** | ERP + 餐厅 POS |
| `odoo-db-*` | 5432 | POSTGRES | `odoo_demo` 业务库 |
| `saleor-api-*` | 8000 | HTTP / GraphQL | 电商 API |
| `saleor-dashboard-*` | 80 | HTTP 通用 | 管理后台 |
| `saleor-db-*` | 5432 | POSTGRES | `saleor` 业务库 |
| `frontend-*` | 80 | HTTP 通用 | Online Boutique 店面 |

> 端口 **8000** 会出现在 `dac-sandbox-0`（FileServer）和 `saleor-api-*`（GraphQL）两个不同 IP 上，靠 **host 区分**，这是多主机扫描演示的正常结果。

**Saleor Dashboard 浏览器访问**（扫描与登录无关）：

```bash
# 方式 A：Pod IP（DAC 扫描后常用）
# http://<saleor-dashboard-pod-ip>:80/dashboard/

# 方式 B：port-forward
kubectl -n dac-sandbox port-forward svc/saleor-dashboard 9000:9000
# http://127.0.0.1:9000/dashboard/
```

登录前确认 `saleor-populatedb` Job 已成功（`kubectl -n dac-sandbox get job saleor-populatedb`）。

**Odoo 重新初始化**（若日志出现 `filestore/... FileNotFoundError` 或仪表盘 `JSONDecodeError`，说明 DB 与附件目录不一致，需清空重来）：

```bash
kubectl -n dac-sandbox delete job odoo-init-demo --ignore-not-found
kubectl -n dac-sandbox delete deploy odoo odoo-db
kubectl apply -f k8s/05-odoo.yaml
kubectl -n dac-sandbox logs deploy/odoo -c init-demo -f   # 等 init 完成（约 5–10 分钟）
```

**示例 CR**（需先 `make apply-apps`）：

| 文件 | 说明 |
|------|------|
| `dd-odoo-postgres.yaml` | 直连 `odoo-db`，库 `odoo_demo` |
| `dd-saleor-postgres.yaml` | 直连 `saleor-db`，库 `saleor` |
| `dd-saleor.yaml` | GitLab 内 `root/saleor` 代码仓（与运行时 API 互补） |
| `dd-online-boutique.yaml` | 上游 `microservices-demo` GitHub 代码仓 |

| 服务 | 用户名 | 密码 |
|------|--------|------|
| Odoo DB (`odoo-db`) | `odoo` | `odopass` |
| Saleor DB (`saleor-db`) | `saleor` | `saleor` |
| Saleor 管理后台 | `admin@example.com` | `admin` |

### 环境变量

`make` 命令支持以下变量覆盖默认值：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `REGISTRY` | `release.daocloud.io/dac` | 沙盒镜像目标 registry |
| `TAG` | `v0.11.0` | 沙盒镜像标签 |
| `PLATFORM` | `linux/amd64` | Docker buildx 目标平台 |
| `NAMESPACE` | `dac-sandbox` | 部署命名空间，修改时需同步调整 Kubernetes manifest |

示例：

```bash
make all REGISTRY=harbor.example.com/dac TAG=v0.10.1
```

### 凭据

沙盒所有服务统一使用 `dac` 作为用户名 / access key，方便记忆。
密码默认 `dacpass`；MinIO 与 GitLab 因服务端硬性要求 ≥ 8 字符，使用 `dacpassword`。

| 服务 | 用户名 | 密码 | 说明 |
|------|--------|------|------|
| MySQL | `root` | `dacpass` | 超级用户 |
| MySQL | `dac` | `dacpass` | 业务账号（推荐使用） |
| PostgreSQL | `postgres` | `dacpass` | 超级用户 |
| PostgreSQL | `dac` | `dacpass` | 业务账号（推荐使用） |
| MinIO | `dac` | `dacpassword` | root 账号；同时作为 access key / secret key（MinIO 强制 secret ≥ 8 字符） |
| GitLab | `root` | `dacpassword` | 管理员账号（GitLab CE 强制 root 密码 ≥ 8 字符） |

> [!WARNING]
> 仅用于演示，不得在生产或暴露公网的环境中复用。

## 使用

沙盒提供两种工作流：通过 DAC 前端逐步操作，或直接 `kubectl apply` 预置的 CR 样例。

### 工作流 A：通过 DAC 前端

前提：DAC 前端与 dac-apiserver 已部署，并能访问 `dac-sandbox` 命名空间。

#### 1. 发起资产探测

1. 进入 **资产探测**（路由 `/infra`），点击 **新建扫描**。
2. 在 sandbox 目录执行 `make scan-targets`，复制输出的 **目标** 与 **端口**。
3. **目标**：多个 Pod IP 逗号分隔（一次扫描覆盖核心沙盒 + Odoo + Saleor + Boutique）。也支持 CIDR（`10.244.1.0/24`）。
4. **端口范围**：`3306,5432,8069,8000,80,8929,9000,9001`（留空则扫全端口，较慢）。
5. **并发** / **超时**：默认 `256` / `30000ms`。
6. 点击 **开始扫描**，等待状态变为 **已完成**。

#### 2. 按端口创建数据源

进入扫描详情页，**发现的服务** 表格列出全部探测到的端口。前端按以下规则识别可一键创建的服务：

| 端口 | 探测识别 | 可一键创建 | 说明 |
|------|----------|------------|------|
| 3306 | MYSQL | 是 | 跳转到 `mysql` 类型表单 |
| 5432 | POSTGRES | 是 | 跳转到 `postgres` 类型表单 |
| 9000 | HTTP（MinIO product） | 是 | 通过 product banner 识别 |
| 8929 | HTTP（GitLab product） | 是 | 通过端口与 product 联合识别 |
| 8069 | HTTP（**odoo** product） | 是 | 企业应用 Pod，`make apply-apps` 后 |
| 8000 | HTTP（通用） | 部分 | FileServer / Saleor API；靠 **IP** 区分，Saleor 需手动或示例 CR |
| 80 | HTTP（通用） | 否 | Dashboard / Boutique 店面，演示发现即可 |
| 9001 | HTTP（MinIO Console） | 否 | 管理 UI，不作为业务端口 |

点击 **创建数据源** 时，前端按以下规则预填表单：

- `name`：`<type>-<host>-<port>`，可修改
- `namespace`：`default`，可修改
- `type` / `host` / `port`：根据扫描结果填入，**不可修改**
- 凭据、bucket、仓库地址：手动填写，参考[凭据](#凭据)表

如同一 `(type, host, port)` 已存在数据源，按钮显示为 **已关联**，点击跳转到该数据源详情页。

#### 3. 手动创建 FileServer 数据源

进入 **数据源**（路由 `/datasources`），点击 **新建数据源**，按 [unstructured（FileServer）](#unstructuredfileserver)节填写字段。

#### 4. 多数据库 fan-out

仅适用于 `mysql` 与 `postgres`。单个连接可挂载多个数据库：

1. 填写 `host` / `port` / `user` / `password`。
2. 点击 **测试连接 & 拉取库列表**：前端调用 `/datasources/probe`，返回该实例下所有可见数据库、版本号、连接耗时。
3. 在返回列表中勾选目标数据库，或在下方输入框手动添加。
4. 提交后，后端按所选数据库展开生成多个 `DataSource`，每个 `DataSource` 共享相同的 `host` / `port` / `user` / `password`，仅 `metadata.database` 不同。

例如选择 `dac_sandbox`、`dactest`、`sakila`，会生成：

```
mysql-pod-3306-dac-sandbox
mysql-pod-3306-dactest
mysql-pod-3306-sakila
```

### 工作流 B：通过 kubectl

```bash
kubectl apply -f examples/dac-cr/
```

将一次性创建：

- 7 个 `DataDescriptor`：`dd-00`、`dd-01`、`dd-02`、`dd-postgres`、`dd-minio`、`dd-fileserver`、`dd-gitlab`，以及追加的 `dd-northwind`、`dd-classicmodels`、`dd-saleor`、`dd-odoo-postgres`、`dd-saleor-postgres`、`dd-online-boutique`（后三者需 `make apply-apps`）
- 3 个 `DataAgentContainer`：`dac-00`、`dac-01`、`dac-02`（金融问答 Agent 示例）

随后在前端 **数据源** / **Agent** 页面可直接看到。

## 数据源参考

下表给出在前端创建数据源时各字段的取值。`host` 列同时给出 Kubernetes FQDN 和 Pod IP 两种写法，二者均可。

### structured-mysql

| 字段 | 取值 |
|------|------|
| descriptorType | `structured-mysql`（前端按 source type 自动推断） |
| source type | `mysql` |
| host | `mysql-server.dac-sandbox.svc.cluster.local` 或 Pod IP |
| port | `3306` |
| user / password | `dac` / `dacpass`（推荐）或 `root` / `dacpass` |
| 数据库（可多选） | 手工库：`dac_sandbox` / `dactest` / `test1` / `corporate_hr` / `online_edu_bi_test`；开源库：`sakila` / `northwind` / `classicmodels` / `chinook` / `employees` / `world` |
| extract.tables | 留空表示扫整库；或对每个库指定表名数组 |

参考样例：`examples/dac-cr/dd-00.yaml`、`dd-01.yaml`、`dd-02.yaml`（`dd-02.yaml` 演示多库写法）。

### structured-postgres

| 字段 | 取值 |
|------|------|
| descriptorType | `structured-postgres` |
| source type | `postgres` |
| host | `postgres-server.dac-sandbox.svc.cluster.local` 或 Pod IP |
| port | `5432` |
| user / password | `dac` / `dacpass`（推荐）或 `postgres` / `dacpass` |
| 数据库（可多选） | 手工库：`dac_sandbox` / `relationship`；开源库：`pagila` / `chinook` / `northwind` |
| extract.tables | 同上 |

参考样例：`examples/dac-cr/dd-postgres.yaml`。

### unstructured（MinIO）

| 字段 | 取值 |
|------|------|
| descriptorType | `unstructured` |
| source type | `minio` |
| host | `dac-sandbox.dac-sandbox.svc.cluster.local` 或 Pod IP |
| port | `9000` |
| access_key / secret_key | `dac` / `dacpassword` |
| bucket | `dac-files` 或 `dac-datasets` |
| secure | `false` |
| extract.files | 文件 key 数组（必填） |

参考样例：`examples/dac-cr/dd-minio.yaml`。

### unstructured（FileServer）

| 字段 | 取值 |
|------|------|
| descriptorType | `unstructured` |
| source type | `fileserver` |
| host | `fileserver.dac-sandbox.svc.cluster.local` 或 Pod IP |
| port | `8000` |
| path | 留空 |
| extract.files | 文件名数组（必填），如 `manual.pdf`、`summary.pdf`、`paper.pdf`、`table.xlsx` |

参考样例：`examples/dac-cr/dd-fileserver.yaml`。

### code（CodeRepo）

`code` 类型不使用 `host` / `port` 字段，所有连接信息封装在 `codeRepo.codeRepoPath` 中。

> [!NOTE]
> data-sinkers 中的 `GitLabReader` 支持自托管 GitLab 实例。沙盒内置的 GitLab CE 容器在构建期从 `https://gitee.com/jamesxiong888/test-code.git` 克隆代码，并由 seed Job 导入到 `root/test-code` 项目，可直接作为 `code` 类型 DDD 的真实数据源。
>
> 如不便部署 GitLab CE（需要 4 GiB+ 内存、3–5 分钟启动），也可改为 `codeRepoType=gitee` 直接指向上游 `https://gitee.com/jamesxiong888/test-code.git`。

| 字段 | 取值 |
|------|------|
| descriptorType | `code` |
| source type | `coderepo` |
| codeRepo.codeRepoType | `gitlab`（或 `github` / `gitee`） |
| codeRepo.codeRepoPath | `http://gitlab.dac-sandbox.svc.cluster.local:8929/root/test-code.git` |
| codeRepo.codeRepoBranch | `master` |
| codeRepo.codeRepoToken | 留空（沙盒中项目设为 public） |

参考样例：`examples/dac-cr/dd-gitlab.yaml`。

## 种子数据

### MySQL（端口 3306）

| 数据库 | 主题 | 数据规模 | 演示用途 |
|--------|------|----------|----------|
| `dac_sandbox` | 金融（资产负债 / 贷款 / 存款） | 4 张核心表 | NL2SQL 中文场景 |
| `dactest` | 金融（同上） | 同 `dac_sandbox` | 多库扫描、跨库同名表识别 |
| `test1` | 电商 | 用户表、订单表 | 简单业务问答 |
| `corporate_hr` | 企业 HR | 完整模型 | 跨表 join、聚合 |
| `online_edu_bi_test` | 在线教育 BI | 多事实 / 维度表 | 复杂 BI 查询 |
| `sakila` | DVD 租赁（开源） | 16 张表，约 47k 行 | 业界标准 demo schema |
| `northwind` | 贸易公司（开源） | 客户/订单/采购/库存/员工 | ERP 业务问答 |
| `classicmodels` | 制造企业（开源） | 客户/订单/产品/销售代表 | 销售与订单分析 |
| `chinook` | 音乐零售（开源） | 发票/客户/曲目 | 跨方言（PG 也有 chinook） |
| `employees` | 企业员工（开源） | 部门/薪资/任职历史 | HR 分析（补充 corporate_hr） |
| `world` | 国家与城市（开源） | 地理维度数据 | 区域统计（可选，需 `make vendor` 能下载） |

### PostgreSQL（端口 5432）

| 数据库 | 主题 | 演示用途 |
|--------|------|----------|
| `dac_sandbox` | 金融（与 MySQL 同名同结构） | 跨方言验证：同一问题在 MySQL 与 PostgreSQL 上均可回答 |
| `relationship` | 关系网络 | 含外键的 schema 解析 |
| `pagila` | DVD 租赁（PostgreSQL 版 Sakila） | 业界标准 demo schema |
| `chinook` | 音乐商店 | 跨表 join、销售统计 |
| `northwind` | 贸易公司 | 采购/库存/供应商分析 |

### MinIO（端口 9000）

| Bucket | 内容 | 演示用途 |
|--------|------|----------|
| `dac-files` | 21 份多格式文件（PDF / DOCX / XLSX / PPTX / MD / CSV / PNG ……） | unstructured S3 路径 |
| `dac-datasets` | MovieLens 1M（约 100 万条评分） | 大数据集抽取 |

### FileServer（端口 8000）

通过 `curl http://<pod-ip>:8000/` 查看目录索引。文件清单与 MinIO `dac-files` 相同（21 份），用于演示 unstructured 的 HTTP 路径。

### GitLab CE（端口 8929）

| 项目 | 内容 | 演示用途 |
|------|------|----------|
| `root/test-code` | `gitee.com/jamesxiong888/test-code.git` 的快照 | 原有 DAC 代码演示 |
| `root/saleor` | `github.com/saleor/saleor.git` 的快照 | 开源电商后端，企业业务代码分析 |

> [!NOTE]
> data-sinkers 中的 `GitLabReader` 支持自托管 GitLab 实例，因此该项目可直接被 `examples/dac-cr/dd-gitlab.yaml` 引用作为 `code` 类型 DDD 的真实数据源。

## 能力覆盖矩阵

| DAC 能力 | 来源 | 沙盒覆盖 |
|----------|------|----------|
| `descriptorType: structured-mysql` | dac-apiserver | 是（MySQL × 11 库） |
| `descriptorType: structured-postgres` | dac-apiserver | 是（PostgreSQL × 5 库） |
| `descriptorType: unstructured` | dac-apiserver | 是（MinIO + FileServer 双路径） |
| `descriptorType: code` | dac-apiserver | 是（GitLabReader 直连集群内 GitLab CE，或回退到外部 GitHub / Gitee） |
| `DataSourceType: mysql / postgres / minio / fileserver / coderepo` | execution-engine CRD | 是 |
| 探测指纹：mysql / postgres / minio / gitlab | apiserver/discovery/scanner | 是 |
| 探测指纹：通用 HTTP | 同上 | 是（FileServer / GitLab / MinIO Console 均会被识别） |
| 探测指纹：redis / nextcloud / trino | 同上 | 否（与 DAC 业务无关） |
| 探测指纹：odoo | 同上 | 是（`make apply-apps` 后 8069） |
| 企业应用：Odoo / Saleor / Online Boutique | 独立 Deployment | 是（`make apply-apps`） |

## 故障排查

| 现象 | 排查方法 |
|------|----------|
| Pod 停留在 `ImagePullBackOff` | `kubectl -n dac-sandbox describe pod dac-sandbox-0` 查看缺哪个镜像。最常见是 `gitlab-ce:17.5.0-ce.0` 缺失（`make build push` 不会同步公共基础镜像），按[安装 §1](#1-同步公共基础镜像) 执行 `make mirror-public` 或单独补 `gitlab-ce` |
| Pod 停留在 `Init` / `ContainerCreating` | `kubectl -n dac-sandbox describe pod dac-sandbox-0`，多为镜像拉取超时或 PVC 待绑定 |
| `seed-job` 失败 | `kubectl -n dac-sandbox logs job/dac-sandbox-seed`。MinIO Ready 后 1–2 秒内完成 |
| `gitlab-seed-job` 失败 | `kubectl -n dac-sandbox logs job/dac-sandbox-gitlab-seed`。常见原因为 GitLab 启动慢（可达 5 分钟），Job 已配置 `backoffLimit: 10` 自动重试 |
| GitLab 容器长时间处于 `Running 0/1` | 属于正常现象，首次启动需 reconfigure + 数据库迁移；通过 `kubectl -n dac-sandbox logs dac-sandbox-0 -c gitlab -f` 观察 |
| 前端探测无结果 | 通过 `make verify` 确认 Pod IP；从 dac-apiserver Pod 内执行 `curl <pod-ip>:<port>` 验证网络连通性 |
| Odoo / Saleor Job 失败 | 多为内存不足；确认 `make mirror-images` 已把 `saleor:3.23`、`saleor-dashboard:3.23`、`odoo:17.0` 推入私有 registry |
| Odoo `filestore` / `JSONDecodeError`（仪表盘） | 旧版 Job 初始化与 Odoo Pod 不共享附件目录；删除 `odoo`/`odoo-db` Deployment 后重新 `apply`（见下方） |
| Saleor Dashboard 登录后 API 报错 | 确认 `saleor-populatedb` Job 已完成；访问路径为 `/dashboard/`；Pod IP 用容器口 **80** |
| Online Boutique 镜像拉取失败 | 确认 `boutique-*:v0.10.5` 与 `redis:alpine` 已在 `$(REGISTRY)`；manifest 由 `make vendor-apps` 自动改写 |
| 离线集群 ImagePullBackOff | 在有网机重跑 `make offline-prep`，或单独 `make mirror-images` + `make push` |
| 查看容器日志 | `kubectl -n dac-sandbox logs dac-sandbox-0 -c <mysql\|postgres\|minio\|fileserver\|gitlab>` |

## 运维操作

### 重置数据

```bash
make restart
```

重启 Pod，`emptyDir` 卷清空，seed Job 自动重跑。

### 卸载

```bash
make delete       # 仅核心 sandbox
make delete-apps  # 仅企业应用栈
make delete-all   # 全部
make clean        # 清理本地 vendor 缓存与派生 SQL（仅本机）
```

## 项目结构

```
sandbox/
├── Makefile                          构建 / 推送 / 部署 / 验证目标
├── README.md                         本文档
├── images/
│   ├── mysql/Dockerfile              FROM mysql:8 + COPY seed/mysql/*.sql → initdb.d
│   ├── postgres/Dockerfile           FROM postgres:16 + COPY seed/postgres/*.sql → initdb.d
│   ├── minio-seed/                   seed Job 镜像：mc + COPY seed/files + seed/datasets
│   ├── fileserver/                   nginx + autoindex + COPY seed/files
│   └── gitlab-seed/                  seed Job 镜像：git clone test-code + saleor
├── seed/
│   ├── mysql/                        手工 SQL + vendor 企业样本库
│   ├── postgres/                     手工 SQL + vendor 企业样本库
│   ├── files/                        21 份多格式文件
│   └── datasets/                     vendor 数据：ml-1m/
├── scripts/
│   ├── download-vendor.sh            下载 SQL/datasets 到 seed/（build 时打入镜像）
│   ├── vendor-apps.sh                下载 Boutique manifest 并改写镜像为 $(REGISTRY)
│   ├── mirror-images.sh              外部镜像 pull/tag/push 到私有 registry
│   └── offline-prep.sh               有网机一站式离线准备
├── k8s/
│   ├── 00-namespace.yaml
│   ├── 01-statefulset.yaml           单 Pod 五容器
│   ├── 02-services.yaml              主 Service + 别名 Service
│   ├── 03-seed-job.yaml              MinIO 数据导入
│   ├── 04-gitlab-seed-job.yaml       GitLab 项目初始化
│   ├── 05-odoo.yaml                  Odoo 17 + demo（独立 Deployment）
│   ├── 06-saleor.yaml                Saleor API + Dashboard + populatedb
│   └── apps/
│       └── online-boutique.yaml      vendor 生成（make vendor-apps）
└── examples/
    └── dac-cr/                       DataDescriptor / DataAgentContainer 样例
        ├── dd-00.yaml ~ dd-02.yaml
        ├── dac-00.yaml ~ dac-02.yaml
        ├── dd-postgres.yaml
        ├── dd-minio.yaml
        ├── dd-fileserver.yaml
        ├── dd-gitlab.yaml
        ├── dd-northwind.yaml
        ├── dd-classicmodels.yaml
        ├── dd-saleor.yaml
        ├── dd-odoo-postgres.yaml
        ├── dd-saleor-postgres.yaml
        └── dd-online-boutique.yaml
```

## 设计说明

- **零手工初始化**：所有种子数据通过镜像 build 阶段写入 `/docker-entrypoint-initdb.d/` 或在 Job 中执行；GitLab CE 通过 `GITLAB_OMNIBUS_CONFIG` + `GITLAB_ROOT_PASSWORD` 实现首启自动 reconfigure，配合 `startupProbe` 等待 `/-/health` 就绪，跳过手工初始化。
- **不依赖 ConfigMap**：种子数据体积超过 ConfigMap 1 MiB 上限，且包含二进制文件，改为自定义镜像 + emptyDir 方案。
- **不依赖 PV**：使用 emptyDir 使沙盒可在最小化集群（kind / minikube / CI）部署。需持久化时将 `01-statefulset.yaml` 的 `volumes` 改为 `volumeClaimTemplates`。
- **单 Pod 多容器**：使探测器能通过单一 IP 发现全部服务，更贴近真实演示场景。
- **服务别名**：`examples/dac-cr/` 中 `host` 字段使用 `mysql-server` / `fileserver` / `gitlab` 等稳定别名，独立 Service 保证示例 YAML 无需修改即可运行。
- **seed Job 解耦**：MinIO / GitLab 数据由独立 Job 注入，主服务容器仅负责常驻进程，失败可单独重试。`gitlab-seed-job` 通过 OAuth ROPC 流程获取 root token，依次创建 `root/test-code` 与 `root/saleor` 并 `git push`。
- **凭据对齐**：超级用户密码统一为 `123`，与历史 `examples/dac-cr/dd-*.yaml` 保持一致，避免维护多套连接串。

## 第三方数据集与许可

| 数据集 | 用途 | 许可 | 上游 |
|--------|------|------|------|
| Sakila | MySQL `sakila` | New BSD-style | https://dev.mysql.com/doc/sakila/en/ |
| Pagila | PostgreSQL `pagila` | New BSD-style | https://github.com/devrimgunduz/pagila |
| Chinook | PostgreSQL `chinook` / MySQL `chinook` | MIT | https://github.com/lerocha/chinook-database |
| Northwind | MySQL `northwind` / PostgreSQL `northwind` | MIT | https://github.com/dalers/mywind / https://github.com/pthom/northwind_psql |
| ClassicModels | MySQL `classicmodels` | MIT | https://www.mysqltutorial.org/mysql-sample-database.aspx |
| Employees | MySQL `employees` | CC BY-SA 3.0 | https://github.com/datacharmer/test_db |
| World | MySQL `world` | GPL | https://dev.mysql.com/doc/index-other.html |
| Saleor | GitLab `root/saleor` + 运行时 `saleor-api` | BSD-3-Clause | https://github.com/saleor/saleor |
| Odoo | `odoo_demo` 库 + HTTP 8069 | LGPL-3 | https://www.odoo.com |
| Online Boutique | `frontend` 微服务栈 | Apache-2.0 | https://github.com/GoogleCloudPlatform/microservices-demo |
| MovieLens 1M | MinIO `dac-datasets/ml-1m/` | CC BY 4.0 | https://grouplens.org/datasets/movielens/1m/ |

`make vendor` 自动下载并加工至 `seed/`，加工产物已加入 `.gitignore`。

## 兼容性

| 项 | 兼容范围 |
|----|----------|
| Kubernetes API | 1.24+ |
| MySQL | 8.x（沙盒固定 8.0） |
| PostgreSQL | 14 / 15 / 16（沙盒固定 16） |
| MinIO | 2024 年及之后版本 |
| GitLab CE | 17.5.x（其他 17.x / 16.x Omnibus 镜像理论可用，需自行验证 `/-/health` 与 OAuth ROPC 流程） |
| dac-apiserver | 与 `examples/dac-cr/` 中字段一致的版本 |

## 许可证

沙盒源码遵循仓库根目录 [`LICENSE`](../LICENSE) 文件中声明的许可。第三方数据集的许可见 [第三方数据集与许可](#第三方数据集与许可)。
