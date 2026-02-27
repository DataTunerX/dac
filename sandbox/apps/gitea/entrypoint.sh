#!/bin/sh
set -eu

# Start gitea (use the original entrypoint if present).
# gitea image provides /usr/bin/entrypoint (multi-arch). Fall back to gitea web.
if [ -x /usr/bin/entrypoint ]; then
  /usr/bin/entrypoint &
else
  /usr/local/bin/gitea web &
fi

GITEA_URL="${GITEA_URL:-http://127.0.0.1:3000}"
GITEA_ADMIN_USER="${GITEA_ADMIN_USER:-giteaadmin}"
GITEA_ADMIN_PASSWORD="${GITEA_ADMIN_PASSWORD:-giteaadminpass}"
GITEA_ADMIN_EMAIL="${GITEA_ADMIN_EMAIL:-admin@example.com}"
GITEA_REPO_NAME="${GITEA_REPO_NAME:-zeysi-apiserver}"
SEED_SRC="${GITEA_SEED_SRC:-/seed/src}"

echo "[gitea-seed] waiting for gitea..."
for i in $(seq 1 240); do
  if wget -qO- "${GITEA_URL}/api/v1/version" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

echo "[gitea-seed] ensure admin user exists (idempotent)..."
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
  if ! gitea admin user list \
    --config /data/gitea/conf/app.ini \
    --work-path /data/gitea \
    --custom-path /data/gitea \
    2>/dev/null | grep -qE "[[:space:]]${GITEA_ADMIN_USER}[[:space:]]"; then
    echo "[gitea-seed] failed to create admin user ${GITEA_ADMIN_USER}"
    exit 1
  fi
fi

AUTH="${GITEA_ADMIN_USER}:${GITEA_ADMIN_PASSWORD}"

echo "[gitea-seed] ensure repo ${GITEA_REPO_NAME} exists..."
if ! curl -fsS "${GITEA_URL}/api/v1/repos/${GITEA_ADMIN_USER}/${GITEA_REPO_NAME}" >/dev/null 2>&1; then
  code="$(
    curl -sS -o /tmp/create_repo.json -w '%{http_code}' \
      -H "Content-Type: application/json" \
      -u "${AUTH}" \
      -d "{\"name\":\"${GITEA_REPO_NAME}\",\"private\":false,\"auto_init\":false,\"description\":\"DAC sandbox seeded repo\"}" \
      "${GITEA_URL}/api/v1/user/repos"
  )"
  if [ "${code}" != "201" ] && [ "${code}" != "409" ]; then
    echo "[gitea-seed] repo create failed (http ${code}):"
    cat /tmp/create_repo.json || true
    exit 1
  fi
fi

echo "[gitea-seed] seed repo from ${SEED_SRC} (requires .git) ..."
if [ -d "${SEED_SRC}/.git" ]; then
  rm -rf /tmp/seed.git
  git clone --mirror "${SEED_SRC}" /tmp/seed.git
  cd /tmp/seed.git
  git remote set-url origin "${GITEA_URL}/${GITEA_ADMIN_USER}/${GITEA_REPO_NAME}.git"
  git push --mirror -f "http://${AUTH}@127.0.0.1:3000/${GITEA_ADMIN_USER}/${GITEA_REPO_NAME}.git"
  echo "[gitea-seed] seeded: ${GITEA_ADMIN_USER}/${GITEA_REPO_NAME}"
else
  echo "[gitea-seed] no git repo found at ${SEED_SRC}; skip seeding"
fi

wait

