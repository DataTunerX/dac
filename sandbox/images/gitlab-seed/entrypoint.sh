#!/bin/bash
# 等 GitLab HTTP 起来 → ROPC 拿 root token → 遍历 /seed/code/* 创建 project 并 push
# 环境变量:
#   GITLAB_URL           (默认 http://localhost:8929)
#   GITLAB_ROOT_PASSWORD (默认 dacpassword)
#   GITLAB_PROJECT       (可选，仅 push 单个项目；默认 push /seed/code 下全部目录)

set -euo pipefail

URL="${GITLAB_URL:-http://localhost:8929}"
ROOT_PASS="${GITLAB_ROOT_PASSWORD:-dacpassword}"

log() { printf '\033[36m[gitlab-seed] %s\033[0m\n' "$*"; }

push_project() {
  local project="$1"
  local src_dir="$2"

  log "project: root/$project"

  PROJ_HTTP=$(curl -s -o /tmp/proj.json -w "%{http_code}" "${AUTH[@]}" \
              "$URL/api/v4/projects/root%2F$project")
  if [ "$PROJ_HTTP" = "404" ]; then
    log "creating project root/$project"
    curl -fsS -X POST "${AUTH[@]}" -H "Content-Type: application/json" \
         -d "{\"name\":\"$project\",\"path\":\"$project\",\"visibility\":\"public\",\"default_branch\":\"main\",\"initialize_with_readme\":false}" \
         "$URL/api/v4/projects" >/dev/null
  elif [ "$PROJ_HTTP" = "200" ]; then
    log "project root/$project already exists"
  else
    echo "FATAL: unexpected project lookup status: $PROJ_HTTP"
    cat /tmp/proj.json || true
    exit 1
  fi

  local work="/tmp/work-$project"
  rm -rf "$work"
  cp -a "$src_dir" "$work"
  cd "$work"

  log "pruning vendor / build artifacts before push ($project)"
  rm -rf .git vendor node_modules dist build out target \
         .idea .vscode coverage .next .nuxt \
         __pycache__ .pytest_cache .mypy_cache .ruff_cache 2>/dev/null || true
  find . -type d -name '__pycache__' -prune -exec rm -rf {} + 2>/dev/null || true
  find . -type f \( -name '*.pyc' -o -name '*.pyo' -o -name '*.log' \) -delete 2>/dev/null || true

  git config --global user.email "seed@dac.local"
  git config --global user.name  "DAC Seeder"
  git config --global init.defaultBranch main
  git config --global --add safe.directory "$work"
  git config --global http.postBuffer 524288000

  git init -q
  git add -A
  git commit -q -m "Initial import (DAC sandbox seed)" || log "(nothing to commit)"

  local remote_host
  remote_host=$(echo "$URL" | sed -E 's#^https?://##')
  local remote="http://oauth2:$TOKEN@$remote_host/root/$project.git"
  git remote add origin "$remote"
  log "pushing root/$project to gitlab (force)..."
  git push --force --progress origin main
  log "pushed → $URL/root/$project"
}

log "target: $URL"

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

API_READY=0
for i in $(seq 1 60); do
  HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$URL/api/v4/version")
  if [ "$HTTP_CODE" = "401" ] || [ "$HTTP_CODE" = "200" ]; then
    log "gitlab API ready (http=$HTTP_CODE)"
    API_READY=1
    break
  fi
  log "waiting for gitlab API... ($i/60, http=$HTTP_CODE)"
  sleep 5
done
[ "$API_READY" = "1" ] || { echo "FATAL: gitlab API not ready"; exit 1; }

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

if [ -n "${GITLAB_PROJECT:-}" ] && [ -n "${SRC_DIR:-}" ]; then
  push_project "$GITLAB_PROJECT" "$SRC_DIR"
else
  for src_dir in /seed/code/*/; do
    [ -d "$src_dir" ] || continue
    project=$(basename "$src_dir")
    push_project "$project" "$src_dir"
  done
fi

log "DONE"
