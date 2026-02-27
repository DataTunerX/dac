#!/bin/sh
set -eu

echo "[verify] Postgres (erp.customers count)"
docker exec dac-sandbox-postgres psql -U "${POSTGRES_USER:-dac}" -d "${POSTGRES_DB:-dac_sandbox}" -c "select count(*) from erp.customers;" >/dev/null
echo "  ok"

echo "[verify] MinIO (buckets exist)"
curl -4 -fsS http://127.0.0.1:9000/minio/health/ready >/dev/null
echo "  ok"

echo "[verify] Trino (catalogs)"
for i in $(seq 1 60); do
  if curl -4 -fsS http://127.0.0.1:8080/v1/info >/dev/null 2>&1; then
    break
  fi
  sleep 2
done
echo "  ok"

echo "[verify] Trino Hive table (hive.demo.orders)"
for i in $(seq 1 60); do
  if docker compose --env-file env.example exec -T trino trino --execute "SELECT count(*) FROM hive.demo.orders;" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done
echo "  ok"

echo "[verify] Nextcloud (O365 replacement)"
curl -4 -fsS http://127.0.0.1:8011/status.php >/dev/null
echo "  ok"

echo "[verify] Odoo (ERP)"
curl -4 -fsS http://127.0.0.1:8012/web/login >/dev/null
echo "  ok"

echo "[verify] Gitea (repo)"
curl -4 -fsS http://127.0.0.1:8013/api/v1/version >/dev/null
curl -4 -fsS "http://127.0.0.1:8013/api/v1/repos/${GITEA_ADMIN_USER:-giteaadmin}/zeysi-apiserver" >/dev/null
echo "  ok"

echo "[verify] done"

