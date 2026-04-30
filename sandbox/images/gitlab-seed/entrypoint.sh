#!/bin/bash
# 等 GitLab HTTP 起来 → ROPC 拿 root token → 创建 project → push 代码
# 通过环境变量配置:
#   GITLAB_URL           (默认 http://localhost:8929)
#   GITLAB_ROOT_PASSWORD (默认 dacpassword；GitLab CE 强制要求 root 密码 >= 8 字符)
#   GITLAB_PROJECT       (默认 test-code，挂在 root 命名空间下)
#   SRC_DIR              (默认 /seed/code/test-code，由 Dockerfile 构建期克隆得到)

set -euo pipefail

URL="${GITLAB_URL:-http://localhost:8929}"
ROOT_PASS="${GITLAB_ROOT_PASSWORD:-dacpassword}"
PROJECT="${GITLAB_PROJECT:-test-code}"
SRC_DIR="${SRC_DIR:-/seed/code/test-code}"

log() { printf '\033[36m[gitlab-seed] %s\033[0m\n' "$*"; }

log "target: $URL  project: root/$PROJECT"

# 1) 等 GitLab HTTP ready (最多 600s — GitLab 首次 reconfigure 需要 3-5 分钟)
READY=0
for i in $(seq 1 120); do
  if curl -fsS -o /dev/null "$URL/-/health"; then
    log "gitlab HTTP ready"
    READY=1
    break
  fi
  log "waiting for gitlab HTTP... ($i/120)"
  sleep 5
done
[ "$READY" = "1" ] || { echo "FATAL: gitlab not ready after 600s"; exit 1; }

# 等到 OAuth /api 接口可用 (HTTP ready 不代表 rails 已经 boot 完)
API_READY=0
for i in $(seq 1 60); do
  HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$URL/api/v4/version")
  # 401 = 接口活了但需要鉴权；500/502 = 还在起
  if [ "$HTTP_CODE" = "401" ] || [ "$HTTP_CODE" = "200" ]; then
    log "gitlab API ready (http=$HTTP_CODE)"
    API_READY=1
    break
  fi
  log "waiting for gitlab API... ($i/60, http=$HTTP_CODE)"
  sleep 5
done
[ "$API_READY" = "1" ] || { echo "FATAL: gitlab API not ready"; exit 1; }

# 2) ROPC 拿 root access token
log "requesting OAuth token for root..."
TOKEN_RESP=""
for i in $(seq 1 30); do
  TOKEN_RESP=$(curl -sS -X POST "$URL/oauth/token" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    --data-urlencode "grant_type=password" \
    --data-urlencode "username=root" \
    --data-urlencode "password=$ROOT_PASS" \
    --data-urlencode "scope=api write_repository")
  TOKEN=$(echo "$TOKEN_RESP" | jq -r '.access_token // empty')
  if [ -n "$TOKEN" ]; then
    log "got OAuth token (${TOKEN:0:8}…)"
    break
  fi
  log "OAuth token not ready yet ($i/30): $TOKEN_RESP"
  sleep 5
done
[ -n "${TOKEN:-}" ] || { echo "FATAL: failed to obtain OAuth token: $TOKEN_RESP"; exit 1; }

AUTH=( -H "Authorization: Bearer $TOKEN" )

# 3) 创建 project (幂等)
PROJ_HTTP=$(curl -s -o /tmp/proj.json -w "%{http_code}" "${AUTH[@]}" \
            "$URL/api/v4/projects/root%2F$PROJECT")
if [ "$PROJ_HTTP" = "404" ]; then
  log "creating project root/$PROJECT"
  curl -fsS -X POST "${AUTH[@]}" -H "Content-Type: application/json" \
       -d "{\"name\":\"$PROJECT\",\"path\":\"$PROJECT\",\"visibility\":\"public\",\"default_branch\":\"main\",\"initialize_with_readme\":false}" \
       "$URL/api/v4/projects" >/dev/null
elif [ "$PROJ_HTTP" = "200" ]; then
  log "project root/$PROJECT already exists"
else
  echo "FATAL: unexpected project lookup status: $PROJ_HTTP"
  cat /tmp/proj.json || true
  exit 1
fi

# 4) push 源码 (force 同步当前 seed 内容)
WORK=/tmp/work
rm -rf "$WORK"
cp -a "$SRC_DIR" "$WORK"
cd "$WORK"

# 剔除不该进 demo repo 的大目录 / 构建产物
log "pruning vendor / build artifacts before push"
rm -rf .git vendor node_modules dist build out target \
       .idea .vscode coverage .next .nuxt \
       __pycache__ .pytest_cache .mypy_cache .ruff_cache 2>/dev/null || true
find . -type d -name '__pycache__' -prune -exec rm -rf {} + 2>/dev/null || true
find . -type f \( -name '*.pyc' -o -name '*.pyo' -o -name '*.log' \) -delete 2>/dev/null || true

git config --global user.email "seed@dac.local"
git config --global user.name  "DAC Seeder"
git config --global init.defaultBranch main
git config --global --add safe.directory "$WORK"
git config --global http.postBuffer 524288000

git init -q
git add -A
git commit -q -m "Initial import (DAC sandbox seed)" || log "(nothing to commit)"

SIZE=$(du -sh .git 2>/dev/null | awk '{print $1}')
log "git repo size: ${SIZE:-unknown}"

REMOTE_HOST=$(echo "$URL" | sed -E 's#^https?://##')
REMOTE="http://oauth2:$TOKEN@$REMOTE_HOST/root/$PROJECT.git"
git remote add origin "$REMOTE"
log "pushing to gitlab (force)..."
git push --force --progress origin main

log "DONE → $URL/root/$PROJECT"
