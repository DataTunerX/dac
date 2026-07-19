# DAC sandbox — 镜像准备 + Helm 安装
#
#   make offline-prep   # 有网机：vendor + mirror + build/push
#   make apply          # 集群：helm install 全量
#   make scan-targets   # 前端 /infra 扫描用 IP/端口
#   make verify
#   make uninstall

REGISTRY ?= release.daocloud.io/dac
TAG      ?= v0.11.0
PLATFORM ?= linux/amd64
BUILD    := docker build --platform $(PLATFORM)

MYSQL_IMAGE        := $(REGISTRY)/sandbox-mysql:$(TAG)
POSTGRES_IMAGE     := $(REGISTRY)/sandbox-postgres:$(TAG)
MINIO_SEED_IMAGE   := $(REGISTRY)/sandbox-minio-seed:$(TAG)
FILESERVER_IMAGE   := $(REGISTRY)/sandbox-fileserver:$(TAG)
GITLAB_SEED_IMAGE  := $(REGISTRY)/sandbox-gitlab-seed:$(TAG)

NAMESPACE := dac-sandbox
CHART     := ./chart
RELEASE   := dac-sandbox

GITLAB_TEST_CODE_REPO_URL ?= https://gitee.com/jamesxiong888/test-code.git
GITLAB_TEST_CODE_REPO_REF ?= master
GITLAB_SALEOR_REPO_URL ?= https://github.com/saleor/saleor.git
GITLAB_SALEOR_REPO_REF ?= main

.PHONY: help vendor mirror-images offline-prep \
        build build-mysql build-postgres build-minio-seed build-fileserver build-gitlab-seed \
        push push-mysql push-postgres push-minio-seed push-fileserver push-gitlab-seed \
        apply install uninstall template lint restart logs verify scan-targets clean all

help:
	@awk 'BEGIN{FS=":.*##"; printf "\nUsage:\n  make \033[36m<target>\033[0m\n\nTargets:\n"} /^[a-zA-Z0-9_-]+:.*?##/{printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# ------------- Prepare images (online machine) -------------
vendor: ## 下载 Sakila/Pagila/Chinook/MovieLens 等 SQL/datasets 到 seed/
	@bash scripts/download-vendor.sh

mirror-images: ## 外部镜像 pull/tag/push 到 $(REGISTRY)
	REGISTRY=$(REGISTRY) PLATFORM=$(PLATFORM) BOUTIQUE_TAG=v0.10.5 SALEOR_TAG=3.23 bash scripts/mirror-images.sh

offline-prep: ## 有网机一站式：vendor + mirror + build/push
	REGISTRY=$(REGISTRY) TAG=$(TAG) PLATFORM=$(PLATFORM) bash scripts/offline-prep.sh

build: build-mysql build-postgres build-minio-seed build-fileserver build-gitlab-seed ## build 5 个 sandbox-* 镜像

build-mysql: vendor
	$(BUILD) -t $(MYSQL_IMAGE) -f images/mysql/Dockerfile .
build-postgres: vendor
	$(BUILD) -t $(POSTGRES_IMAGE) -f images/postgres/Dockerfile .
build-minio-seed:
	$(BUILD) -t $(MINIO_SEED_IMAGE) -f images/minio-seed/Dockerfile .
build-fileserver:
	$(BUILD) -t $(FILESERVER_IMAGE) -f images/fileserver/Dockerfile .
build-gitlab-seed:
	$(BUILD) \
	  --build-arg TEST_CODE_REPO_URL=$(GITLAB_TEST_CODE_REPO_URL) \
	  --build-arg TEST_CODE_REPO_REF=$(GITLAB_TEST_CODE_REPO_REF) \
	  --build-arg SALEOR_REPO_URL=$(GITLAB_SALEOR_REPO_URL) \
	  --build-arg SALEOR_REPO_REF=$(GITLAB_SALEOR_REPO_REF) \
	  -t $(GITLAB_SEED_IMAGE) -f images/gitlab-seed/Dockerfile .

push: push-mysql push-postgres push-minio-seed push-fileserver push-gitlab-seed ## push 5 个镜像

push-mysql:
	docker push $(MYSQL_IMAGE)
push-postgres:
	docker push $(POSTGRES_IMAGE)
push-minio-seed:
	docker push $(MINIO_SEED_IMAGE)
push-fileserver:
	docker push $(FILESERVER_IMAGE)
push-gitlab-seed:
	docker push $(GITLAB_SEED_IMAGE)

all: vendor build push ## vendor + build + push（不含 mirror）

# ------------- Helm install (cluster) -------------
apply install: ## helm upgrade --install 全量沙盒
	helm upgrade --install $(RELEASE) $(CHART) \
	  -n $(NAMESPACE) --create-namespace \
	  --set global.imageRegistry=$(REGISTRY) \
	  --set global.imageTag=$(TAG)
	@echo
	@echo "Installed. Wait for GitLab (~3-5m) and Odoo/Saleor init on STS."
	@echo "Next: make scan-targets"

uninstall: ## helm uninstall + 删除命名空间
	-helm uninstall $(RELEASE) -n $(NAMESPACE)
	-kubectl delete ns $(NAMESPACE) --wait=false

template: ## helm template
	helm template $(RELEASE) $(CHART) -n $(NAMESPACE) \
	  --set global.imageRegistry=$(REGISTRY) \
	  --set global.imageTag=$(TAG)

lint: ## helm lint
	helm lint $(CHART)

restart: ## 重启 STS（emptyDir 数据会丢）
	kubectl -n $(NAMESPACE) rollout restart statefulset/dac-sandbox

logs: ## STS mysql 日志
	kubectl -n $(NAMESPACE) logs -f dac-sandbox-0 -c mysql --tail=50

verify: ## 部署后自检
	@echo "== Pods =="
	@kubectl -n $(NAMESPACE) get pods
	@echo
	@echo "== Services =="
	@kubectl -n $(NAMESPACE) get svc
	@echo
	@echo "== STS Pod IP =="
	@kubectl -n $(NAMESPACE) get pod dac-sandbox-0 -o jsonpath='{.status.podIP}{"\n"}'
	@echo
	@echo "== STS containers =="
	@kubectl -n $(NAMESPACE) get pod dac-sandbox-0 -o jsonpath='{range .status.containerStatuses[*]}{.name}{": ready="}{.ready}{"\n"}{end}' 2>/dev/null || true
	@echo
	@echo "== MySQL DBs =="
	@kubectl -n $(NAMESPACE) exec dac-sandbox-0 -c mysql -- \
	  mysql -uroot -pdacpass -N -e "SHOW DATABASES;" 2>/dev/null \
	  | grep -vE '^(mysql|information_schema|performance_schema|sys)$$' || true
	@echo
	@echo "== Postgres DBs =="
	@kubectl -n $(NAMESPACE) exec dac-sandbox-0 -c postgres -- \
	  psql -U postgres -tAc "SELECT datname FROM pg_database WHERE datistemplate=false;" 2>/dev/null || true
	@echo
	@echo "== HTTP on STS (dashboard / boutique) =="
	@kubectl -n $(NAMESPACE) exec dac-sandbox-0 -c saleor-dashboard -- \
	  wget -qO- http://127.0.0.1:9002/dashboard/ >/dev/null 2>&1 && echo "saleor-dashboard:9002 ok" || echo "saleor-dashboard: not ready"
	@kubectl -n $(NAMESPACE) exec dac-sandbox-0 -c boutique-frontend -- \
	  wget -qO- http://127.0.0.1:8080/_healthz >/dev/null 2>&1 && echo "boutique:8080 ok" || echo "boutique: not ready"

scan-targets: ## 前端 /infra 扫描（单个 STS IP）
	@echo "== 目标（只需 dac-sandbox-0 这一个 IP）=="
	@kubectl -n $(NAMESPACE) get pod dac-sandbox-0 -o jsonpath='{.status.podIP}{"\n"}' 2>/dev/null \
	  || echo "(no pod — run: make apply)"
	@echo
	@echo "== 端口 =="
	@echo "3306,5432,6379,8000,8001,8069,8080,8929,9000,9001,9002"
	@echo
	@echo "  3306 mysql | 5432 postgres | 6379 redis"
	@echo "  8000 fileserver | 8001 saleor-api | 8069 odoo"
	@echo "  8080 boutique | 8929 gitlab | 9000/9001 minio | 9002 saleor-dashboard"

clean: ## 清本地 vendor 缓存
	rm -rf scripts/.vendor-cache \
	       seed/datasets/ml-1m \
	       seed/mysql/50-northwind.sql seed/mysql/51-classicmodels.sql \
	       seed/mysql/52-chinook.sql seed/mysql/53-employees.sh \
	       seed/mysql/53-employees-schema.sql seed/mysql/54-world.sql \
	       seed/mysql/employees-dumps/*.dump \
	       seed/mysql/99-sakila.sql seed/postgres/50-northwind.sql \
	       seed/postgres/98-pagila.sql seed/postgres/99-chinook.sql
