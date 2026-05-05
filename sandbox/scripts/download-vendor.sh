#!/usr/bin/env bash
# 下载并加工外部开源演示数据，输出到 sandbox/seed/{mysql,postgres,datasets}/
#   - Sakila      → seed/mysql/99-sakila.sql        (DVD 出租店, 16 张表 + 外键 + 触发器)
#   - Pagila      → seed/postgres/98-pagila.sql     (Sakila 的 PostgreSQL 版本)
#   - Chinook     → seed/postgres/99-chinook.sql    (数字音乐商店, 11 张表)
#   - MovieLens 1M → seed/datasets/ml-1m/           (4 个 CSV/DAT, 进 MinIO 演示对象存储扫描)
#
# 重复运行幂等。已下载会跳过。需要网络。

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENDOR="$ROOT/scripts/.vendor-cache"
SEED_MYSQL="$ROOT/seed/mysql"
SEED_PG="$ROOT/seed/postgres"
SEED_DS="$ROOT/seed/datasets"

mkdir -p "$VENDOR" "$SEED_MYSQL" "$SEED_PG" "$SEED_DS"

log()  { printf '\033[36m[vendor] %s\033[0m\n' "$*"; }
fetch() {
  local url="$1" out="$2"
  if [[ -s "$out" ]]; then
    log "skip (cached): $(basename "$out")"
    return
  fi
  log "fetch: $url"
  curl -fsSL --retry 3 --retry-delay 2 -o "$out.tmp" "$url"
  mv "$out.tmp" "$out"
}

# ---------- Sakila (MySQL) ----------
SAKILA_TAR="$VENDOR/sakila-db.tar.gz"
fetch "https://downloads.mysql.com/docs/sakila-db.tar.gz" "$SAKILA_TAR"
rm -rf "$VENDOR/sakila-db"
tar -xzf "$SAKILA_TAR" -C "$VENDOR"
{
  echo "-- vendor: Sakila (https://dev.mysql.com/doc/sakila/en/)"
  echo "USE sakila;"
  cat "$VENDOR/sakila-db/sakila-schema.sql"
  cat "$VENDOR/sakila-db/sakila-data.sql"
} > "$SEED_MYSQL/99-sakila.sql"
log "wrote: seed/mysql/99-sakila.sql ($(wc -c < "$SEED_MYSQL/99-sakila.sql") bytes)"

# ---------- Pagila (PostgreSQL) ----------
PAGILA_SCHEMA="$VENDOR/pagila-schema.sql"
PAGILA_DATA="$VENDOR/pagila-data.sql"
fetch "https://raw.githubusercontent.com/devrimgunduz/pagila/master/pagila-schema.sql" "$PAGILA_SCHEMA"
fetch "https://raw.githubusercontent.com/devrimgunduz/pagila/master/pagila-data.sql"   "$PAGILA_DATA"
{
  echo "-- vendor: Pagila (https://github.com/devrimgunduz/pagila)"
  echo "\\connect pagila"
  cat "$PAGILA_SCHEMA"
  cat "$PAGILA_DATA"
} > "$SEED_PG/98-pagila.sql"
log "wrote: seed/postgres/98-pagila.sql ($(wc -c < "$SEED_PG/98-pagila.sql") bytes)"

# ---------- Chinook (PostgreSQL) ----------
CHINOOK_SQL="$VENDOR/chinook_postgres.sql"
fetch "https://raw.githubusercontent.com/lerocha/chinook-database/master/ChinookDatabase/DataSources/Chinook_PostgreSql.sql" "$CHINOOK_SQL"
{
  echo "-- vendor: Chinook (https://github.com/lerocha/chinook-database)"
  echo "\\connect chinook"
  # Chinook 自带 'CREATE DATABASE chinook;' 和 '\\c chinook;'，去掉避免 init 失败
  grep -vE "^CREATE DATABASE chinook|^\\\\c chinook|^DROP DATABASE" "$CHINOOK_SQL"
} > "$SEED_PG/99-chinook.sql"
log "wrote: seed/postgres/99-chinook.sql ($(wc -c < "$SEED_PG/99-chinook.sql") bytes)"

# ---------- MovieLens 1M (CSV → MinIO) ----------
ML_ZIP="$VENDOR/ml-1m.zip"
fetch "https://files.grouplens.org/datasets/movielens/ml-1m.zip" "$ML_ZIP"
rm -rf "$SEED_DS/ml-1m"
unzip -q "$ML_ZIP" -d "$SEED_DS"
log "wrote: seed/datasets/ml-1m/ ($(du -sh "$SEED_DS/ml-1m" | cut -f1))"

log "DONE"
