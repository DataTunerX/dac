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
- 10 个示例数据库、21 份多格式文件、MovieLens 1M 数据集、1 个示例代码仓库
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

> [!IMPORTANT]
> 首次部署需先将 `mysql` / `postgres` / `nginx` / `alpine` / `minio/mc` / `minio/minio` / `gitlab/gitlab-ce` 等公共基础镜像同步到目标 registry，否则 Pod 会停留在 `ImagePullBackOff`。详见[安装 §1](#1-同步公共基础镜像)。

镜像就绪后，部署只需两条命令：

```bash
cd sandbox
make apply && make verify
```

`make verify` 会输出 Pod IP、各服务的连通性检查结果，以及 seed 数据状态。

## 安装

完整流程：同步公共镜像 → 构建沙盒镜像 → 部署 → 自检。

### 1. 同步公共基础镜像

`make build push` 只构建并推送 5 个 sandbox 派生镜像，**不会**同步公共基础镜像。判断方法：在能拉取目标 registry 的机器上执行 `docker pull $(REGISTRY)/gitlab-ce:17.5.0-ce.0`，能拉到说明 registry 已经直通或透明代理 Docker Hub，可以跳过本步；提示 `repository not found / unauthorized` 就必须执行：

```bash
docker login release.daocloud.io
make mirror-public
```

`mirror-public` 会把以下公共镜像逐个 `pull → tag → push` 到 `$(REGISTRY)`，使集群离线也能拉取：

| 镜像 | 大小（约） | 用途 |
|------|-----------|------|
| `mysql:8.0`、`postgres:16` | 600 MB / 400 MB | 业务数据库基础镜像 |
| `nginx:1.25-alpine` | 50 MB | FileServer |
| `alpine:3.20`、`minio/mc:latest` | 10 MB / 50 MB | seed Job 工具链 |
| `minio/minio:latest` | 250 MB | 对象存储 |
| **`gitlab/gitlab-ce:17.5.0-ce.0`** | **3 GB** | 代码仓库基础镜像，最容易遗漏，缺失会导致 Pod 停留在 `ImagePullBackOff` |

只补 GitLab CE 这一个镜像（不重复同步其他已就绪的镜像）：

```bash
docker pull gitlab/gitlab-ce:17.5.0-ce.0
docker tag  gitlab/gitlab-ce:17.5.0-ce.0 release.daocloud.io/dac/gitlab-ce:17.5.0-ce.0
docker push release.daocloud.io/dac/gitlab-ce:17.5.0-ce.0
```

### 2. 构建沙盒镜像

```bash
make all
```

等价于：

```bash
make vendor   # 下载 Sakila / Pagila / Chinook / MovieLens 1M 到 seed/
# （无需 make prep；gitlab-seed 镜像构建期会自动 git clone 示例仓库）
make build    # 构建 5 个 sandbox-* 镜像
make push     # 推送到 $(REGISTRY)
```

### 3. 部署到 Kubernetes

```bash
make apply
kubectl -n dac-sandbox get pods -w
```

Pod 通常需要 3–5 分钟进入 `Running` 状态（5/5 容器就绪）—— 其中 GitLab CE 首次启动会执行 reconfigure + 数据库迁移，单容器就要 3 分钟左右。`gitlab-seed-job` 内置最长 600 秒等待 GitLab Ready 的逻辑。

### 4. 自检

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
- GitLab 项目列表（应有 `root/test-code`）

## 配置

### 环境变量

`make` 命令支持以下变量覆盖默认值：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `REGISTRY` | `release.daocloud.io/dac` | 沙盒镜像目标 registry |
| `TAG` | `v0.10.0` | 沙盒镜像标签 |
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
2. 填写扫描参数：
   - **目标**：`make verify` 输出的 Pod IP（例如 `10.244.1.23`）。也支持 CIDR（`10.244.1.0/24`）或区间（`10.244.1.10-20`），多目标以逗号或空格分隔。
   - **端口范围**（可选）：留空表示扫 `1-65535`。快速演示可填 `3306,5432,9000,9001,8000,8929`。
   - **并发** / **超时**：默认 `256` / `30000ms`，单 Pod 沙盒无需修改。
3. 点击 **开始扫描**，等待状态变为 **已完成**。

#### 2. 按端口创建数据源

进入扫描详情页，**发现的服务** 表格列出全部探测到的端口。前端按以下规则识别可一键创建的服务：

| 端口 | 探测识别 | 可一键创建 | 说明 |
|------|----------|------------|------|
| 3306 | MYSQL | 是 | 跳转到 `mysql` 类型表单 |
| 5432 | POSTGRES | 是 | 跳转到 `postgres` 类型表单 |
| 9000 | HTTP（MinIO product） | 是 | 通过 product banner 识别 |
| 8929 | HTTP（GitLab product） | 是 | 通过端口与 product 联合识别 |
| 8000 | HTTP（通用） | 否 | FileServer 无业务指纹，需手动创建（见步骤 3） |
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

- 7 个 `DataDescriptor`：`dd-00`、`dd-01`、`dd-02`、`dd-postgres`、`dd-minio`、`dd-fileserver`、`dd-gitlab`
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
| 数据库（可多选） | `dac_sandbox` / `dactest` / `test1` / `corporate_hr` / `online_edu_bi_test` / `sakila` 任选一个或多个 |
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
| 数据库（可多选） | `dac_sandbox` / `relationship` / `pagila` / `chinook` 任选一个或多个 |
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

### PostgreSQL（端口 5432）

| 数据库 | 主题 | 演示用途 |
|--------|------|----------|
| `dac_sandbox` | 金融（与 MySQL 同名同结构） | 跨方言验证：同一问题在 MySQL 与 PostgreSQL 上均可回答 |
| `relationship` | 关系网络 | 含外键的 schema 解析 |
| `pagila` | DVD 租赁（PostgreSQL 版 Sakila） | 业界标准 demo schema |
| `chinook` | 音乐商店 | 跨表 join、销售统计 |

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
| `root/test-code` | `gitee.com/jamesxiong888/test-code.git` 的快照（构建期 `git clone` + seed Job `git push`） | 资产探测 + 集群内 Git 服务可视化 + `code` 类型 DDD 抓取 |

> [!NOTE]
> data-sinkers 中的 `GitLabReader` 支持自托管 GitLab 实例，因此该项目可直接被 `examples/dac-cr/dd-gitlab.yaml` 引用作为 `code` 类型 DDD 的真实数据源。

## 能力覆盖矩阵

| DAC 能力 | 来源 | 沙盒覆盖 |
|----------|------|----------|
| `descriptorType: structured-mysql` | dac-apiserver | 是（MySQL × 6 库） |
| `descriptorType: structured-postgres` | dac-apiserver | 是（PostgreSQL × 4 库） |
| `descriptorType: unstructured` | dac-apiserver | 是（MinIO + FileServer 双路径） |
| `descriptorType: code` | dac-apiserver | 是（GitLabReader 直连集群内 GitLab CE，或回退到外部 GitHub / Gitee） |
| `DataSourceType: mysql / postgres / minio / fileserver / coderepo` | execution-engine CRD | 是 |
| 探测指纹：mysql / postgres / minio / gitlab | apiserver/discovery/scanner | 是 |
| 探测指纹：通用 HTTP | 同上 | 是（FileServer / GitLab / MinIO Console 均会被识别） |
| 探测指纹：redis / nextcloud / trino / odoo | 同上 | 否（与 DAC 业务无关） |

## 故障排查

| 现象 | 排查方法 |
|------|----------|
| Pod 停留在 `ImagePullBackOff` | `kubectl -n dac-sandbox describe pod dac-sandbox-0` 查看缺哪个镜像。最常见是 `gitlab-ce:17.5.0-ce.0` 缺失（`make build push` 不会同步公共基础镜像），按[安装 §1](#1-同步公共基础镜像) 执行 `make mirror-public` 或单独补 `gitlab-ce` |
| Pod 停留在 `Init` / `ContainerCreating` | `kubectl -n dac-sandbox describe pod dac-sandbox-0`，多为镜像拉取超时或 PVC 待绑定 |
| `seed-job` 失败 | `kubectl -n dac-sandbox logs job/dac-sandbox-seed`。MinIO Ready 后 1–2 秒内完成 |
| `gitlab-seed-job` 失败 | `kubectl -n dac-sandbox logs job/dac-sandbox-gitlab-seed`。常见原因为 GitLab 启动慢（可达 5 分钟），Job 已配置 `backoffLimit: 10` 自动重试 |
| GitLab 容器长时间处于 `Running 0/1` | 属于正常现象，首次启动需 reconfigure + 数据库迁移；通过 `kubectl -n dac-sandbox logs dac-sandbox-0 -c gitlab -f` 观察 |
| 前端探测无结果 | 通过 `make verify` 确认 Pod IP；从 dac-apiserver Pod 内执行 `curl <pod-ip>:<port>` 验证网络连通性 |
| 查看容器日志 | `kubectl -n dac-sandbox logs dac-sandbox-0 -c <mysql\|postgres\|minio\|fileserver\|gitlab>` |

## 运维操作

### 重置数据

```bash
make restart
```

重启 Pod，`emptyDir` 卷清空，seed Job 自动重跑。

### 卸载

```bash
make delete   # 删除 namespace 下全部资源
make clean    # 清理本地 vendor 缓存与派生 SQL（仅本机）
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
│   └── gitlab-seed/                  seed Job 镜像：git/curl/jq + 构建期 git clone test-code.git
├── seed/
│   ├── mysql/                        6 份 SQL 初始化脚本
│   ├── postgres/                     3 份 SQL + vendor 下载的 pagila / chinook
│   ├── files/                        21 份多格式文件
│   └── datasets/                     vendor 数据：ml-1m/
├── scripts/
│   └── download-vendor.sh            下载并加工 Sakila / Pagila / Chinook / MovieLens
├── k8s/
│   ├── 00-namespace.yaml
│   ├── 01-statefulset.yaml           单 Pod 五容器
│   ├── 02-services.yaml              主 Service + 别名 Service
│   ├── 03-seed-job.yaml              MinIO 数据导入
│   └── 04-gitlab-seed-job.yaml       GitLab 项目初始化
└── examples/
    └── dac-cr/                       DataDescriptor / DataAgentContainer 样例
        ├── dd-00.yaml ~ dd-02.yaml
        ├── dac-00.yaml ~ dac-02.yaml
        ├── dd-postgres.yaml
        ├── dd-minio.yaml
        ├── dd-fileserver.yaml
        └── dd-gitlab.yaml
```

## 设计说明

- **零手工初始化**：所有种子数据通过镜像 build 阶段写入 `/docker-entrypoint-initdb.d/` 或在 Job 中执行；GitLab CE 通过 `GITLAB_OMNIBUS_CONFIG` + `GITLAB_ROOT_PASSWORD` 实现首启自动 reconfigure，配合 `startupProbe` 等待 `/-/health` 就绪，跳过手工初始化。
- **不依赖 ConfigMap**：种子数据体积超过 ConfigMap 1 MiB 上限，且包含二进制文件，改为自定义镜像 + emptyDir 方案。
- **不依赖 PV**：使用 emptyDir 使沙盒可在最小化集群（kind / minikube / CI）部署。需持久化时将 `01-statefulset.yaml` 的 `volumes` 改为 `volumeClaimTemplates`。
- **单 Pod 多容器**：使探测器能通过单一 IP 发现全部服务，更贴近真实演示场景。
- **服务别名**：`examples/dac-cr/` 中 `host` 字段使用 `mysql-server` / `fileserver` / `gitlab` 等稳定别名，独立 Service 保证示例 YAML 无需修改即可运行。
- **seed Job 解耦**：MinIO / GitLab 数据由独立 Job 注入，主服务容器仅负责常驻进程，失败可单独重试。`gitlab-seed-job` 通过 OAuth ROPC 流程获取 root token，创建 `root/test-code` 项目并 `git push` 镜像内预克隆的代码。
- **凭据对齐**：超级用户密码统一为 `123`，与历史 `examples/dac-cr/dd-*.yaml` 保持一致，避免维护多套连接串。

## 第三方数据集与许可

| 数据集 | 用途 | 许可 | 上游 |
|--------|------|------|------|
| Sakila | MySQL `sakila` | New BSD-style | https://dev.mysql.com/doc/sakila/en/ |
| Pagila | PostgreSQL `pagila` | New BSD-style | https://github.com/devrimgunduz/pagila |
| Chinook | PostgreSQL `chinook` | MIT | https://github.com/lerocha/chinook-database |
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
