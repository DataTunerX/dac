# skill-hub

`skill-hub` 是一个轻量的 HTTP 服务，用来把 skill zip 包索引起来，供 `skill-agent`（通过 `agent/skill_download.py`）按需拉取。镜像内已内置 `skills/` 目录下的全部 `*.zip`（见 Dockerfile 中的 `COPY skills /app/skills`），部署时无需 PVC。

## 接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/skills` | 返回当前已索引的全部 skill（name / description / 最新 version / 全部可用版本） |
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

覆盖目录后如需刷新索引，可调用 `POST /skills/reload`。
