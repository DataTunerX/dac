# SkillAgent

## 运行时环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `ENABLE_LOCAL_SKILLS` | `true` | 关闭后 `SkillRunner` 不会初始化，所有请求返回“SkillRunner unavailable”。 |
| `LOCAL_SKILLS_DIR` | `/app/skills/` | 启动时扫描此目录加载 `*.zip` skill 包。为空则不加载任何 skill。 |
| `LOCAL_SKILL_MAX_STEPS` | `20` | 单次 `plan_and_run` 的 ReAct 步数上限。 |
| `LOCAL_SKILL_CMD_TIMEOUT_SEC` | `30` | `plan_cmd` 单次子进程超时（秒）。 |
| `LOCAL_SKILL_MAX_CONCURRENCY` | `8` | 同一进程内 `plan_cmd` 的并发上限，`0` 表示不限制。 |
| `ENABLE_THINKING_PARAM` | `true` | 为兼容 Qwen 思考模式参数，置 `false` 时向 LLM 传 `enable_thinking=False`。 |
| `Agent_Host` / `Agent_Port` / `Agent_Name` / `Agent_Description` | — | 覆盖 agent_card 的对外信息，用于注册到 Redis 时的地址/名称/描述。 |
| `REGISTER_AGENT` | `true` | 置 `false` / `0` / `no` 时不向 Redis 注册心跳。 |
| `LANGFUSE_SECRET_KEY` / `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_BASE_URL` / `LANGFUSE_AUTH_CHECK` | — | 可选：启用 LangFuse 追踪。 |
| `SKILLS` | — | 启动时从 **skill-hub** 拉取的 skill 名列表（与每个 zip 内 `SKILL.md` 的 `name` 一致）。未设置或为空则**不下载**。支持 JSON 数组（`'["hashgen","weather"]'`）或逗号/分号/空白分隔。详见 `agent/skill_download.py`。 |
| `SKILL_HUB_URL` | `http://skill-hub.dac.svc.cluster.local:8000` | skill-hub 服务根地址（不要带路径）。 |
| `SKILLS_DOWNLOAD_DIR` | `/app/skills/` | 下载的 `{name}.zip` 写入目录；应与 `LOCAL_SKILLS_DIR` 一致，便于随后 `preload_skill_runner()` 扫描加载。 |
| `SKILL_DOWNLOAD_TIMEOUT` | `30` | 单次 HTTP 下载超时（秒，浮点）。 |
| `SKILL_DOWNLOAD_OVERWRITE` | `false` | `true`/`1`/`yes` 时若本地已有同名 zip 会重新下载；否则跳过已有文件。 |
| `SKILL_DOWNLOAD_CONCURRENCY` | `8` | 并行下载线程数上限（`>= 1`）。每个线程使用独立 `httpx.Client`。 |

启动时若配置了 `SKILLS`，会先调用 `download_skills()` 从 hub 拉 zip，再构建 `SkillAgentExecutor`（见 `agent/server.py`）。随后 `SkillAgentExecutor.preload_skill_runner()` 会打印完整 skill 清单，在第一次请求到来前就能在 Pod 日志里看到当前加载了哪些 skill。进程退出时通过 `atexit` 调用 `shutdown_skill_runner()`，自动清理 `SkillLoader` 解压出的临时目录。

## 本地开发

```bash
uv run agent \
  --host 0.0.0.0 \
  --port 10100 \
  --provider openai_compatible \
  --api-key $DASHSCOPE_API_KEY \
  --base-url https://dashscope.aliyuncs.com/compatible-mode/v1 \
  --model deepseek-v3.2
```

把要执行的 skill 包（`*.zip`）放到 `LOCAL_SKILLS_DIR` 对应目录（开发环境通常临时指定为项目内某个目录）：

```bash
export LOCAL_SKILLS_DIR=$PWD/skills
export ENABLE_LOCAL_SKILLS=true
uv run agent --port 10100 --api-key $DASHSCOPE_API_KEY --model deepseek-v3.2
```

## Docker 运行

```bash
docker run --rm \
  -e "Agent_Host=192.168.3.7" \
  -e "Agent_Port=20100" \
  -e "Agent_Name=SkillAgent" \
  -e "LOCAL_SKILL_MAX_STEPS=20" \
  -e "LOCAL_SKILL_CMD_TIMEOUT_SEC=30" \
  -e "LOCAL_SKILL_MAX_CONCURRENCY=8" \
  -e "LANGFUSE_SECRET_KEY=sk-lf-xxx" \
  -e "LANGFUSE_PUBLIC_KEY=pk-lf-xxx" \
  -e "LANGFUSE_BASE_URL=http://192.168.3.7:3000" \
  -e "REGISTER_AGENT=false" \
  -e 'SKILLS=["hashgen","weather"]' \
  -e "SKILL_HUB_URL=http://192.168.3.7:8000" \
  -p 20100:10100 \
  registry.cn-shanghai.aliyuncs.com/jamesxiong/skill-agent:v0.10.0-amd64 \
  --redis-host 192.168.3.7 --redis-port 6389 --redis-db 2 --password 123 \
  --provider openai_compatible --api-key sk-xxx \
  --base-url https://dashscope.aliyuncs.com/compatible-mode/v1 \
  --model deepseek-v3.2
```
