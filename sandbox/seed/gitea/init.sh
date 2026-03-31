#!/bin/sh
set -eu

echo "[gitea-init] waiting for gitea..."
for i in $(seq 1 240); do
  if wget -qO- http://gitea:3000/api/v1/version >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

echo "[gitea-init] ensure admin user exists (idempotent)..."
if ! gitea admin user create \
  --username "${GITEA_ADMIN_USER}" \
  --password "${GITEA_ADMIN_PASSWORD}" \
  --email "${GITEA_ADMIN_EMAIL}" \
  --admin \
  --must-change-password=false \
  --config /data/gitea/conf/app.ini \
  --work-path /data/gitea \
  --custom-path /data/gitea \
  >/dev/null 2>&1; then
  # If creation failed, allow "already exists", but fail fast otherwise.
  if ! gitea admin user list \
    --config /data/gitea/conf/app.ini \
    --work-path /data/gitea \
    --custom-path /data/gitea \
    2>/dev/null | grep -qE "[[:space:]]${GITEA_ADMIN_USER}[[:space:]]"; then
    echo "[gitea-init] failed to create admin user ${GITEA_ADMIN_USER}"
    exit 1
  fi
fi

AUTH="${GITEA_ADMIN_USER}:${GITEA_ADMIN_PASSWORD}"

REPO_NAME="${GITEA_REPO_NAME:-sample-project}"

echo "[gitea-init] ensure repo ${REPO_NAME} exists..."
if ! curl -fsS "http://gitea:3000/api/v1/repos/${GITEA_ADMIN_USER}/${REPO_NAME}" >/dev/null 2>&1; then
  echo "[gitea-init] creating repo ${REPO_NAME}..."
  code="$(
    curl -sS -o /tmp/create_repo.json -w '%{http_code}' \
      -H "Content-Type: application/json" \
      -u "${AUTH}" \
      -d "{\"name\":\"${REPO_NAME}\",\"private\":false,\"auto_init\":false,\"description\":\"DAC sandbox seeded repo\"}" \
      http://gitea:3000/api/v1/user/repos
  )"
  if [ "${code}" != "201" ] && [ "${code}" != "409" ]; then
    echo "[gitea-init] repo create failed (http ${code}):"
    cat /tmp/create_repo.json || true
    exit 1
  fi
  if ! curl -fsS "http://gitea:3000/api/v1/repos/${GITEA_ADMIN_USER}/${REPO_NAME}" >/dev/null 2>&1; then
    echo "[gitea-init] repo still not visible after create"
    exit 1
  fi
fi

echo "[gitea-init] mirror push from /src (.git required) ..."
if [ ! -d "/src/.git" ]; then
  echo "[gitea-init] /src is not a git repo. Set SOURCE_REPO_PATH in .env to a local git repo."
  exit 1
fi

rm -rf /tmp/seed.git
git clone --mirror /src /tmp/seed.git
cd /tmp/seed.git
git remote set-url origin "http://${GITEA_ADMIN_USER}:${GITEA_ADMIN_PASSWORD}@gitea:3000/${GITEA_ADMIN_USER}/${REPO_NAME}.git"
git push --mirror -f origin

echo "[gitea-init] done"

