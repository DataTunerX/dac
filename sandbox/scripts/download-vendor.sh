#!/usr/bin/env bash
# 下载并加工外部开源演示数据，输出到 sandbox/seed/{mysql,postgres,datasets}/
#   - Sakila      → seed/mysql/99-sakila.sql        (DVD 出租店, 16 张表 + 外键 + 触发器)
#   - Pagila      → seed/postgres/98-pagila.sql     (Sakila 的 PostgreSQL 版本)
#   - Chinook     → seed/postgres/99-chinook.sql    (数字音乐商店, 11 张表)
#   - MovieLens 1M → seed/datasets/ml-1m/           (4 个 CSV/DAT, 进 MinIO 演示对象存储扫描)
#
# 企业开源样本（在原有手工库基础上追加，不替换）:
#   - Northwind (MySQL)     → seed/mysql/50-northwind.sql
#   - ClassicModels (MySQL) → seed/mysql/51-classicmodels.sql
#   - Chinook (MySQL)       → seed/mysql/52-chinook.sql
#   - Employees (MySQL)     → seed/mysql/53-employees.sh + employees-dumps/
#   - World (MySQL)         → seed/mysql/54-world.sql (可选，下载失败则跳过)
#   - Northwind (PostgreSQL)→ seed/postgres/50-northwind.sql
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
strip_create_database() {
  grep -vE '^(CREATE DATABASE|DROP DATABASE|\\c |USE `|USE )' "$1" \
    | sed -E 's/^CREATE SCHEMA IF NOT EXISTS `[^`]+`.*;//g' \
    | sed -E 's/^DROP SCHEMA IF EXISTS `[^`]+`.*;//g'
}
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

# ---------- Northwind (MySQL) ----------
NW_SCHEMA="$VENDOR/northwind-schema.sql"
NW_DATA="$VENDOR/northwind-data.sql"
fetch "https://raw.githubusercontent.com/dalers/mywind/master/northwind.sql" "$NW_SCHEMA"
fetch "https://raw.githubusercontent.com/dalers/mywind/master/northwind-data.sql" "$NW_DATA"
{
  echo "-- vendor: Northwind (https://github.com/dalers/mywind)"
  echo "USE northwind;"
  strip_create_database "$NW_SCHEMA"
  strip_create_database "$NW_DATA"
} > "$SEED_MYSQL/50-northwind.sql"
log "wrote: seed/mysql/50-northwind.sql ($(wc -c < "$SEED_MYSQL/50-northwind.sql") bytes)"

# ---------- ClassicModels (MySQL) ----------
CM_SQL="$VENDOR/classicmodels.sql"
fetch "https://raw.githubusercontent.com/Azure-Samples/mysql-database-samples/main/mysqltutorial.org/mysql-classicmodesl.sql" "$CM_SQL"
{
  echo "-- vendor: ClassicModels (https://www.mysqltutorial.org/mysql-sample-database.aspx)"
  echo "USE classicmodels;"
  strip_create_database "$CM_SQL"
} > "$SEED_MYSQL/51-classicmodels.sql"
log "wrote: seed/mysql/51-classicmodels.sql ($(wc -c < "$SEED_MYSQL/51-classicmodels.sql") bytes)"

# ---------- Chinook (MySQL) ----------
CHINOOK_MYSQL="$VENDOR/chinook_mysql.sql"
fetch "https://raw.githubusercontent.com/lerocha/chinook-database/master/ChinookDatabase/DataSources/Chinook_MySql.sql" "$CHINOOK_MYSQL"
{
  echo "-- vendor: Chinook (https://github.com/lerocha/chinook-database)"
  echo "USE chinook;"
  grep -vE '^(CREATE DATABASE|DROP DATABASE)' "$CHINOOK_MYSQL"
} > "$SEED_MYSQL/52-chinook.sql"
log "wrote: seed/mysql/52-chinook.sql ($(wc -c < "$SEED_MYSQL/52-chinook.sql") bytes)"

# ---------- Employees (MySQL, schema + dump files) ----------
EMP_SQL="$VENDOR/employees.sql"
EMP_DUMPS="$SEED_MYSQL/employees-dumps"
mkdir -p "$EMP_DUMPS"
fetch "https://raw.githubusercontent.com/datacharmer/test_db/master/employees.sql" "$EMP_SQL"
for dump in load_departments load_employees load_dept_emp load_dept_manager load_titles \
            load_salaries1 load_salaries2 load_salaries3; do
  fetch "https://raw.githubusercontent.com/datacharmer/test_db/master/${dump}.dump" \
        "$EMP_DUMPS/${dump}.dump"
done
{
  echo "-- vendor: Employees (https://github.com/datacharmer/test_db)"
  echo "USE employees;"
  grep -vE '^(DROP DATABASE|CREATE DATABASE|USE employees)' "$EMP_SQL" \
    | sed '/^source /,$d'
} > "$SEED_MYSQL/53-employees-schema.sql"
cat > "$SEED_MYSQL/53-employees.sh" <<'EOF'
#!/bin/bash
set -euo pipefail
mysql -uroot -p"${MYSQL_ROOT_PASSWORD}" < /docker-entrypoint-initdb.d/53-employees-schema.sql
for dump in load_departments load_employees load_dept_emp load_dept_manager load_titles \
            load_salaries1 load_salaries2 load_salaries3; do
  mysql -uroot -p"${MYSQL_ROOT_PASSWORD}" employees \
    < "/docker-entrypoint-initdb.d/employees-dumps/${dump}.dump"
done
EOF
chmod +x "$SEED_MYSQL/53-employees.sh"
log "wrote: seed/mysql/53-employees.sh + employees-dumps/ ($(ls "$EMP_DUMPS" | wc -l | tr -d ' ') dumps)"

# ---------- World (MySQL, optional) ----------
WORLD_ZIP="$VENDOR/world-db.zip"
if curl -fsSL --retry 2 -A "Mozilla/5.0" -o "$WORLD_ZIP.tmp" \
     "https://downloads.mysql.com/docs/world-db.zip"; then
  mv "$WORLD_ZIP.tmp" "$WORLD_ZIP"
  rm -rf "$VENDOR/world-db"
  unzip -q "$WORLD_ZIP" -d "$VENDOR"
  {
    echo "-- vendor: World (https://dev.mysql.com/doc/index-other.html)"
    echo "USE world;"
    grep -vE '^(CREATE DATABASE|DROP DATABASE)' "$VENDOR/world-db/world.sql"
  } > "$SEED_MYSQL/54-world.sql"
  log "wrote: seed/mysql/54-world.sql ($(wc -c < "$SEED_MYSQL/54-world.sql") bytes)"
else
  rm -f "$WORLD_ZIP.tmp"
  log "skip: world-db.zip (download blocked, optional)"
fi

# ---------- Northwind (PostgreSQL) ----------
NW_PG="$VENDOR/northwind_pg.sql"
fetch "https://raw.githubusercontent.com/pthom/northwind_psql/master/northwind.sql" "$NW_PG"
{
  echo "-- vendor: Northwind (https://github.com/pthom/northwind_psql)"
  echo "\\connect northwind"
  grep -vE '^(CREATE DATABASE|DROP DATABASE|\\c )' "$NW_PG"
} > "$SEED_PG/50-northwind.sql"
log "wrote: seed/postgres/50-northwind.sql ($(wc -c < "$SEED_PG/50-northwind.sql") bytes)"

log "DONE"
