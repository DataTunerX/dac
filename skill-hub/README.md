# skill-hub

`skill-hub` 是一个轻量的版本化 skill 仓库。外部发布者可以 push zip，agent 可以按名称/版本 pull；Helm 默认使用 PVC 保存发布内容，并用镜像内置的 skill 初始化空仓库。

## 接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/skills` | 返回当前已索引的全部 skill（name / description / 最新 version / 全部可用版本） |
| POST | `/skills[?overwrite=true]` | 把原始 zip 字节 push 到仓库；name/version 从包内元数据读取 |
| PUT | `/skills/{name}.zip[?overwrite=true]` | 命名 push；包内 name 必须与 URL 一致 |
| DELETE | `/skills/{name}.zip[?version=X]` | 删除指定版本；不带 version 时删除全部版本 |
| POST | `/skills/reload` | 重新扫描 `SKILLS_DIR` 并刷新索引（运行时往目录里加了新 zip 时用） |
| GET | `/{name}.zip[?version=X]` | 下载 skill 的 zip；`version` 可选，省略即最新版本（与 `skill_download.py` 的 URL 约定一致） |
| GET | `/skills/{name}.zip[?version=X]` | 同上的别名 |
| GET | `/healthz` | 健康检查 |

下载响应会附带 `X-Skill-Version` 响应头，指明本次实际返回的版本号。版本比较使用 PEP 440（`packaging.version.Version`），无法解析的版本号会按字典序排序并排在可解析版本之后。

服务在启动时（以及 `POST /skills/reload` 时）会用 `skill_sdk.skill.loader.SkillLoader`
扫描 `SKILLS_DIR`（默认 `/app/skills/`）下的所有 `*.zip`，解析 `_meta.json` 与
`SKILL.md` frontmatter，得到规范化的 skill 名称。下载接口会根据 skill 名称
自动映射到磁盘上真实的 zip 文件（例如 `/hashgen.zip` → `hashgen-1.0.0.zip`）。

## 环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `SKILLS_DIR` | `/app/skills/` | 存放 skill `*.zip` 的目录；一般无需改，除非用卷挂载覆盖 |
| `SKILL_HUB_SEED_DIR` | 空 | 仓库为空时复制此目录中的内置 zip（Helm 自动配置） |
| `SKILL_HUB_PUSH_TOKEN` | 空 | 设置后，push/delete/reload 必须携带 Bearer token；生产环境应设置 |
| `SKILL_HUB_MAX_UPLOAD_BYTES` | `52428800` | 单个 push 的最大字节数 |
| `SKILL_HUB_MAX_EXTRACTED_BYTES` | `262144000` | zip 解压后所有文件的最大总字节数 |
| `SKILL_HUB_MAX_ARCHIVE_ENTRIES` | `2048` | zip 内最多文件/目录条目数 |

## Push / pull

一个合法包必须包含带 `name`、`description` frontmatter 的 `SKILL.md`，以及带 `version` 的 `_meta.json`。同名同版本默认返回 `409`，显式 `overwrite=true` 才替换。

```bash
# publish
curl --fail-with-body \
  -H "Authorization: Bearer $SKILL_HUB_PUSH_TOKEN" \
  -H "Content-Type: application/zip" \
  --data-binary @my-skill-1.2.0.zip \
  https://skills.example.com/skills

# inspect and pull latest (or add ?version=1.2.0)
curl -sS https://skills.example.com/skills | jq .
curl -fLO https://skills.example.com/my-skill.zip
```

对集群外开放时，把 `skillHub.service.type` 配成 `NodePort`/`LoadBalancer` 或通过 Ingress 暴露，并配置 `skillHub.auth.existingSecret`。持久化参数位于 `skillHub.persistence`；如果使用多个 hub 副本，存储必须支持 `ReadWriteMany`。

## 本地运行（源码）

```bash
cd dac/skill-hub
uv sync
uv run skill-hub --host 0.0.0.0 --port 8000 --skills-dir ./skills
```

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

覆盖目录后如需刷新索引，可调用带写入 token 的 `POST /skills/reload`。
