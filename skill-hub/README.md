# skill-hub

`skill-hub` 是一个轻量的 HTTP 服务，用来把 skill zip 包索引起来，供 `skill-agent`（通过 `agent/skill_download.py`）按需拉取。镜像内已内置官方 skill——它们被放入内置的 `default` 命名空间目录 `/app/skills/default/`（见 Dockerfile 中的 `COPY skills/default /app/skills/default`），部署时无需 PVC。

> 本文档是简介；完整的接口规范（字段、错误码、示例）见 **[API.md](API.md)**。

## 接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/skills` | 返回 `default` 命名空间下已索引的全部 skill（name / description / 最新 version / 全部可用版本） |
| POST | `/skills/reload` | 重新扫描 `SKILLS_DIR` 并刷新所有命名空间的索引（运行时往目录里加了新 zip 时用） |
| GET | `/skills/{name}.zip[?version=X]` | 从 `default` 命名空间下载 skill 的 zip；`version` 可选，省略即最新版本（各 agent 的 `skill_download.py` 统一使用的路径） |
| GET | `/{name}.zip[?version=X]` | 同上；旧根路径别名，保留给历史调用方 |
| GET | `/namespaces` | 列出所有命名空间（含 `default`）及其可见性 |
| GET | `/namespaces/{ns}/exists` | 查询某命名空间是否存在（返回 `{"exists": true|false}`） |
| POST | `/namespaces/{ns}` | 显式创建命名空间（已存在返回 409） |
| DELETE | `/namespaces/{ns}` | 删除**空**命名空间（非空返回 409，`default` 禁止删除） |
| GET | `/namespaces/{ns}/skills` | 列出某命名空间下的 skill |
| GET | `/namespaces/{ns}/skills/{name}.zip[?version=X]` | 从某命名空间下载 skill 的 zip |
| POST | `/namespaces/{ns}/skills` | 上传 skill zip（multipart）到某命名空间；同命名空间内 `name`+`version` 相同时直接覆盖；namespace 不存在时自动创建；上传后立即刷新索引 |
| DELETE | `/namespaces/{ns}/skills/{name}.zip[?version=X]` | 删除某命名空间下的 skill（省略 `version` 时删除最新版本），删除后立即刷新索引 |
| GET | `/healthz` | 健康检查 |

> **多命名空间模型**：每个 `SKILLS_DIR` 的子目录是一个命名空间（tenant），目录名即命名空间名。`default` 是内置命名空间，其物理目录为 `SKILLS_DIR/default/`（官方 skill 打包在此，上传到 `default` 的 zip 也写入此目录）；为兼容旧布局，`SKILLS_DIR` 根目录下直接放置的 `*.zip` 也归入 `default`。**所有不带 namespace 的默认 API（`GET /skills`、`GET /skills/{name}.zip`、`GET /{name}.zip`、`POST /skills/reload`）都走 `default` 命名空间**，严格向后兼容旧调用方；操作其他命名空间需显式走 `/namespaces/{ns}/...` 路径。一个 skill 由 `(namespace, name, version)` 唯一确定。当前所有命名空间均为 `public`，`private` 已预留设计但未实现。

下载响应会附带 `X-Skill-Version` 响应头，指明本次实际返回的版本号。版本比较使用 PEP 440（`packaging.version.Version`），无法解析的版本号会按字典序排序并排在可解析版本之后。

服务在启动时（以及 `POST /skills/reload` 时）会用 `skill_sdk.skill.loader.SkillLoader`
扫描 `SKILLS_DIR`（默认 `/app/skills/`）下的所有 `*.zip`，解析 `_meta.json` 与
`SKILL.md` frontmatter，得到规范化的 skill 名称。下载接口会根据 skill 名称
自动映射到磁盘上真实的 zip 文件（例如 `/hashgen.zip` → `hashgen-1.0.0.zip`）。

默认情况下，服务还会**自动监听 `SKILLS_DIR` 目录**：一旦其中的 `*.zip`
文件发生增删改（带 2 秒防抖，避免批量拷贝时反复全量扫描），会立即触发索引
重建，无需手动调用 `POST /skills/reload`。可通过环境变量 `SKILLS_AUTO_RELOAD`
关闭该行为。

## 环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `SKILLS_DIR` | `/app/skills/` | 存放 skill `*.zip` 的目录；每个子目录是一个命名空间，其中 `default` 子目录是内置命名空间（根目录下直接放置的 `*.zip` 也归入 `default`，兼容旧布局） |
| `SKILLS_AUTO_RELOAD` | `1` | 是否自动监听 `SKILLS_DIR` 并在其中 `*.zip` 增删改时自动重建索引；设为 `0`/`false` 可关闭（此时需手动调用 `POST /skills/reload`） |

## 本地运行（源码）

```bash
cd dac/skill-hub
uv sync
uv run skill-hub --host 0.0.0.0 --port 8000 --skills-dir ./skills
```

## 运行测试

```bash
uv sync           # 安装依赖（含 dev-dependencies 里的 pytest）
uv run pytest tests/ -v
```

测试覆盖：多命名空间的索引/下载/上传/删除、PEP 440 版本排序、命名空间隔离、上传覆盖与立即索引、删除后版本回退、auto-reload 的 diff 日志与文件监听行为。

## Docker 运行

拉取并以后台方式启动（端口映射到本机 `8000`，与 `SKILL_HUB_URL` 示例一致）：

```bash

docker pull registry.cn-shanghai.aliyuncs.com/jamesxiong/skill-hub:v0.10.0-amd64

docker run -d --name skill-hub -p 8000:8000 -e LANGFUSE_ENABLED=false registry.cn-shanghai.aliyuncs.com/jamesxiong/skill-hub:v0.10.0-amd64

```

快速自检：

```bash

健康检查：

curl -s http://192.168.3.7:8000/healthz


查看skill：

curl -s http://10.17.0.41:31899/skills | jq '.skills[].name'

curl -s http://10.17.0.41:31899/skills | jq '.skills[] | {name, description}'


下载skill：

curl -sS -OJ "http://192.168.3.7:8000/hashgen.zip"

```

查看/操作命名空间：

```bash
# 列命名空间
curl -s http://<host>:8000/namespaces

# 查询某命名空间是否存在
curl -sS "http://<host>:8000/namespaces/team-a/exists"

# 显式创建命名空间（已存在返回 409）
curl -sS -X POST "http://<host>:8000/namespaces/team-b"

# 删除空命名空间（非空返回 409，default 禁止删除）
curl -sS -X DELETE "http://<host>:8000/namespaces/empty-ns"

# 查看某命名空间下的 skill
curl -s http://<host>:8000/namespaces/team-a/skills

# 从某命名空间下载（真实路由为 /namespaces/{ns}/skills/{name}.zip）
curl -sS -OJ "http://<host>:8000/namespaces/team-a/skills/report.zip"

# 上传 skill 到某命名空间（multipart，name/version 从 zip 内解析）
curl -sS -X POST "http://<host>:8000/namespaces/team-a/skills" \
  -F "file=@report-1.1.0.zip"

# 删除某命名空间下的 skill（省略 version 删除最新版本）
curl -sS -X DELETE "http://<host>:8000/namespaces/team-a/skills/report.zip?version=1.0.0"

```

停止并删除容器：

```bash
docker rm -f skill-hub
```

开发时若要用本机目录覆盖镜像内自带的 skills（可选）：

```bash
docker run -d --name skill-hub \
  -p 8000:8000 \
  -v "$(pwd)/skills:/app/skills:ro" \
  -e SKILLS_DIR=/app/skills \
  registry.cn-shanghai.aliyuncs.com/jamesxiong/skill-hub:v0.10.0-amd64
```

覆盖目录后如需刷新索引，可调用 `POST /skills/reload`。
