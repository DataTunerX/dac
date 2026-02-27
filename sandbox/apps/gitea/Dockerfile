# syntax=docker/dockerfile:1.7

FROM m.daocloud.io/docker.io/gitea/gitea:1.21.11

USER root

# Seed dependencies (git + curl + wget + ca-certs)
RUN apk add --no-cache git curl wget ca-certificates

# Bake source code into the image at build time.
# Default: COPY the build context into /seed/src.
# Optional: if ZEYSI_REPO_URL is provided, it will override /seed/src by cloning.
ARG ZEYSI_REPO_URL=""
ARG ZEYSI_REPO_REF="main"

RUN mkdir -p /seed/src

# NOTE: build this image with your local repo path as the build context, e.g.:
#   docker build -t <REGISTRY>/dac/sandbox-gitea:seed \
#     -f <PATH_TO_DAC_REPO>/sandbox/apps/gitea/Dockerfile \
#     <PATH_TO_LOCAL_REPO>
COPY . /seed/src

RUN if [ -n "${ZEYSI_REPO_URL}" ]; then \
      echo "[build] overriding /seed/src by cloning ${ZEYSI_REPO_URL} (${ZEYSI_REPO_REF})"; \
      rm -rf /seed/src && mkdir -p /seed/src; \
      git clone --depth 1 --branch "${ZEYSI_REPO_REF}" "${ZEYSI_REPO_URL}" /seed/src; \
    fi

RUN cat > /usr/local/bin/dac-gitea-entrypoint <<'EOF' && \
chmod +x /usr/local/bin/dac-gitea-entrypoint && \
chown git:git /usr/local/bin/dac-gitea-entrypoint
#!/bin/sh
set -eu

# The upstream gitea image uses s6, which writes a lock file under the current
# working directory (e.g. .s6-svscan/lock). Ensure we start from a writable dir.
cd /tmp

GITEA_URL="${GITEA_URL:-http://127.0.0.1:3000}"
GITEA_ADMIN_USER="${GITEA_ADMIN_USER:-giteaadmin}"
GITEA_ADMIN_PASSWORD="${GITEA_ADMIN_PASSWORD:-giteaadminpass}"
GITEA_ADMIN_EMAIL="${GITEA_ADMIN_EMAIL:-admin@example.com}"
GITEA_REPO_NAME="${GITEA_REPO_NAME:-zeysi-apiserver}"
SEED_SRC="${GITEA_SEED_SRC:-/seed/src}"

APP_INI="/data/gitea/conf/app.ini"
mkdir -p /data/gitea/conf /data/gitea || true

# Bootstrap minimal config if not present. This avoids relying on s6-based entrypoints
# that may require root privileges in some Kubernetes clusters.
if [ ! -f "${APP_INI}" ]; then
  cat >"${APP_INI}" <<CFG
APP_NAME = DAC Sandbox Gitea
RUN_MODE = prod

[server]
DOMAIN = ${GITEA__server__DOMAIN:-dac-sandbox-host}
ROOT_URL = ${GITEA__server__ROOT_URL:-http://dac-sandbox-host:3000/}
HTTP_PORT = ${GITEA__server__HTTP_PORT:-3000}
PROTOCOL = http

[database]
DB_TYPE = sqlite3
PATH = /data/gitea/gitea.db

[service]
DISABLE_REGISTRATION = ${GITEA__service__DISABLE_REGISTRATION:-true}

[security]
INSTALL_LOCK = ${GITEA__security__INSTALL_LOCK:-true}
CFG
fi

# Start gitea web (no s6).
gitea web --config "${APP_INI}" --work-path /data/gitea &

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
if git -C "${SEED_SRC}" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  rm -rf /tmp/seed.git
  git clone --mirror "${SEED_SRC}" /tmp/seed.git
  cd /tmp/seed.git
  git push --mirror -f "http://${AUTH}@127.0.0.1:3000/${GITEA_ADMIN_USER}/${GITEA_REPO_NAME}.git"
  echo "[gitea-seed] seeded (mirror): ${GITEA_ADMIN_USER}/${GITEA_REPO_NAME}"
elif [ -d "${SEED_SRC}" ] && [ "$(ls -A "${SEED_SRC}" 2>/dev/null | wc -l | tr -d ' ')" != "0" ]; then
  echo "[gitea-seed] ${SEED_SRC} is not a git repo; seeding a snapshot commit..."
  rm -rf /tmp/seed.work
  mkdir -p /tmp/seed.work
  cp -R "${SEED_SRC}/." /tmp/seed.work/
  cd /tmp/seed.work
  git init -q
  git config user.name "dac-sandbox"
  git config user.email "dac-sandbox@example.com"
  git add -A
  git commit -qm "seed snapshot"
  git branch -M main
  git remote add origin "http://${AUTH}@127.0.0.1:3000/${GITEA_ADMIN_USER}/${GITEA_REPO_NAME}.git"
  git push -u -f origin main
  echo "[gitea-seed] seeded (snapshot): ${GITEA_ADMIN_USER}/${GITEA_REPO_NAME}"
else
  echo "[gitea-seed] no files found at ${SEED_SRC}; skip seeding"
fi

wait
EOF

USER git

ENTRYPOINT ["/usr/local/bin/dac-gitea-entrypoint"]

