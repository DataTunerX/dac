# DAC sandbox — 一键构建/推送/部署
#
# 典型用法（离线演示）:
#   make offline-prep      # 有网构建机：vendor SQL + mirror 全部外部镜像 + build/push
#   make apply-all         # 离线集群：仅拉私有 registry，不再访问外网
#   make mirror-images     # 仅同步外部镜像到 $(REGISTRY)
#   make vendor            # 仅下载 SQL/datasets 到 seed/（build 时打入 mysql/postgres 镜像）
#   make build           # 本地 build 五个 sandbox-* 镜像
#                        # (gitlab-seed 构建期 clone test-code + saleor)
#   make push            # push sandbox-* 镜像到 $(REGISTRY)
#   make apply           # 部署到当前 kubectl 上下文
#   make apply-apps      # 叠加 Odoo / Saleor / Online Boutique
#   make apply-all       # 核心 + 企业应用栈
#   make all             # vendor + build + push
#   make verify          # 部署后做端口和数据自检

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

# gitlab-seed 镜像内置的示例代码仓库（构建期 git clone 进镜像）
GITLAB_TEST_CODE_REPO_URL ?= https://gitee.com/jamesxiong888/test-code.git
GITLAB_TEST_CODE_REPO_REF ?= master
GITLAB_SALEOR_REPO_URL ?= https://github.com/saleor/saleor.git
GITLAB_SALEOR_REPO_REF ?= main

.PHONY: help vendor vendor-apps mirror-images mirror-public offline-prep \
        build build-mysql build-postgres build-minio-seed build-fileserver build-gitlab-seed \
        push push-mysql push-postgres push-minio-seed push-fileserver push-gitlab-seed \
        apply apply-apps apply-all delete delete-apps delete-all restart logs verify clean all

help:
	@awk 'BEGIN{FS=":.*##"; printf "\nUsage:\n  make \033[36m<target>\033[0m\n\nTargets:\n"} /^[a-zA-Z0-9_-]+:.*?##/{printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# ------------- Vendor (开源数据集) -------------
vendor: ## 下载 Sakila/Pagila/Chinook/MovieLens + 企业样本库到 seed/
	@bash scripts/download-vendor.sh

vendor-apps: ## 下载 Online Boutique manifest 并改写镜像为 $(REGISTRY)/boutique-*
	REGISTRY=$(REGISTRY) BOUTIQUE_TAG=v0.10.5 bash scripts/vendor-apps.sh

# ------------- Mirror External Images (离线必备) -------------
mirror-images: ## pull/tag/push 全部外部镜像（Docker Hub + GHCR Saleor + Boutique）到 $(REGISTRY)
	REGISTRY=$(REGISTRY) PLATFORM=$(PLATFORM) BOUTIQUE_TAG=v0.10.5 SALEOR_TAG=3.23 bash scripts/mirror-images.sh

mirror-public: mirror-images ## 兼容旧目标名，等同 mirror-images

offline-prep: ## 有网机一站式：vendor SQL + mirror 镜像 + build/push（离线集群只 make apply-all）
	REGISTRY=$(REGISTRY) TAG=$(TAG) PLATFORM=$(PLATFORM) bash scripts/offline-prep.sh

# ------------- Build -------------
build: build-mysql build-postgres build-minio-seed build-fileserver build-gitlab-seed ## build 全部 5 个镜像

build-mysql: vendor       ## build MySQL 镜像
	$(BUILD) -t $(MYSQL_IMAGE)      -f images/mysql/Dockerfile      .
build-postgres: vendor    ## build PostgreSQL 镜像
	$(BUILD) -t $(POSTGRES_IMAGE)   -f images/postgres/Dockerfile   .
build-minio-seed:   ## build MinIO seed Job 镜像
	$(BUILD) -t $(MINIO_SEED_IMAGE) -f images/minio-seed/Dockerfile .
build-fileserver:   ## build FileServer (nginx) 镜像
	$(BUILD) -t $(FILESERVER_IMAGE) -f images/fileserver/Dockerfile .
build-gitlab-seed:  ## build GitLab seed Job 镜像（test-code + saleor）
	$(BUILD) \
	  --build-arg TEST_CODE_REPO_URL=$(GITLAB_TEST_CODE_REPO_URL) \
	  --build-arg TEST_CODE_REPO_REF=$(GITLAB_TEST_CODE_REPO_REF) \
	  --build-arg SALEOR_REPO_URL=$(GITLAB_SALEOR_REPO_URL) \
	  --build-arg SALEOR_REPO_REF=$(GITLAB_SALEOR_REPO_REF) \
	  -t $(GITLAB_SEED_IMAGE) -f images/gitlab-seed/Dockerfile .

# ------------- Push -------------
push: push-mysql push-postgres push-minio-seed push-fileserver push-gitlab-seed ## push 5 个镜像到 registry

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

all: vendor build push ## 一把梭：下载数据 + build + push

# ------------- K8s -------------
apply: ## kubectl apply 核心 sandbox（MySQL/Postgres/MinIO/FileServer/GitLab）
	kubectl apply -f k8s/00-namespace.yaml
	kubectl apply -f k8s/01-statefulset.yaml
	kubectl apply -f k8s/02-services.yaml
	kubectl apply -f k8s/03-seed-job.yaml
	kubectl apply -f k8s/04-gitlab-seed-job.yaml
	@echo
	@echo "等 Pod ready (GitLab 首次 reconfigure 约 3-5 分钟):  kubectl -n $(NAMESPACE) get pods -w"

apply-apps: ## 部署企业应用栈（需先 offline-prep；manifest 已在 k8s/apps/）
	kubectl apply -f k8s/05-odoo.yaml
	kubectl apply -f k8s/06-saleor.yaml
	kubectl apply -f k8s/apps/online-boutique.yaml
	@echo
	@echo "企业应用栈已提交。Odoo 初始化 Job 约 5-10 分钟，Saleor populatedb 依赖 API ready。"

apply-all: apply apply-apps ## 核心 sandbox + 企业应用栈一把梭

delete: ## 拆掉核心 sandbox
	-kubectl delete -f k8s/04-gitlab-seed-job.yaml
	-kubectl delete -f k8s/03-seed-job.yaml
	-kubectl delete -f k8s/02-services.yaml
	-kubectl delete -f k8s/01-statefulset.yaml
	-kubectl delete -f k8s/00-namespace.yaml

delete-apps: ## 拆掉企业应用栈（Odoo / Saleor / Online Boutique）
	-kubectl delete -f k8s/apps/online-boutique.yaml
	-kubectl delete -f k8s/06-saleor.yaml
	-kubectl delete -f k8s/05-odoo.yaml

delete-all: delete-apps delete ## 拆掉全部（应用栈 + 核心 sandbox）

restart: ## 重启 Pod (快速重置数据)
	kubectl -n $(NAMESPACE) rollout restart statefulset/dac-sandbox

logs: ## 查 Pod 日志 (容器=mysql/postgres/minio/fileserver/gitlab)
	kubectl -n $(NAMESPACE) logs -f dac-sandbox-0 -c mysql --tail=50

# ------------- Verify -------------
verify: ## 部署后自检：端口可达 + 关键 db/bucket/repo 存在
	@echo "== Pods =="
	@kubectl -n $(NAMESPACE) get pods
	@echo
	@echo "== Services =="
	@kubectl -n $(NAMESPACE) get svc
	@echo
	@echo "== Pod IP =="
	@kubectl -n $(NAMESPACE) get pod dac-sandbox-0 -o jsonpath='{.status.podIP}{"\n"}'
	@echo
	@echo "== MySQL databases =="
	@kubectl -n $(NAMESPACE) exec dac-sandbox-0 -c mysql -- \
	  mysql -uroot -pdacpass -e "SHOW DATABASES;" 2>/dev/null | grep -vE '^(Database|mysql|information_schema|performance_schema|sys)$$' || true
	@echo
	@echo "== MySQL enterprise DBs (northwind/classicmodels/chinook/employees/world) =="
	@kubectl -n $(NAMESPACE) exec dac-sandbox-0 -c mysql -- \
	  mysql -uroot -pdacpass -N -e "SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME IN ('northwind','classicmodels','chinook','employees','world');" 2>/dev/null || true
	@echo
	@echo "== Postgres databases =="
	@kubectl -n $(NAMESPACE) exec dac-sandbox-0 -c postgres -- \
	  psql -U postgres -tAc "SELECT datname FROM pg_database WHERE datistemplate=false;" 2>/dev/null || true
	@echo
	@echo "== MinIO buckets =="
	@kubectl -n $(NAMESPACE) exec dac-sandbox-0 -c minio -- \
	  mc --json --insecure alias set localck http://127.0.0.1:9000 dac dacpassword >/dev/null 2>&1 || true
	@kubectl -n $(NAMESPACE) exec dac-sandbox-0 -c minio -- \
	  mc ls localck 2>/dev/null || true
	@echo
	@echo "== FileServer index =="
	@kubectl -n $(NAMESPACE) exec dac-sandbox-0 -c fileserver -- \
	  wget -qO- http://127.0.0.1:8000/ 2>/dev/null | grep -oE 'href="[^"]+"' | head -10 || true
	@echo
	@echo "== GitLab projects (root/) =="
	@kubectl -n $(NAMESPACE) exec dac-sandbox-0 -c gitlab -- \
	  curl -fsS -H "PRIVATE-TOKEN: $$GITLAB_ROOT_TOKEN" http://127.0.0.1:8929/api/v4/users/root/projects 2>/dev/null \
	  | (command -v jq >/dev/null && jq -r '.[] | "  - " + .path_with_namespace' || cat) \
	  || echo "(skipped — set GITLAB_ROOT_TOKEN to inspect via API; or browse http://<pod-ip>:8929/root)"
	@echo
	@echo "== Enterprise apps (make apply-apps) =="
	@kubectl -n $(NAMESPACE) get deploy,job 2>/dev/null \
	  | grep -E 'NAME|^(deployment|job)\.(apps/)?(odoo|saleor|frontend|currencyservice|checkoutservice)' || echo "(not deployed — run: make apply-apps)"
	@echo
	@echo "== Odoo ready =="
	@kubectl -n $(NAMESPACE) get deploy odoo -o jsonpath='{.status.readyReplicas}{" / "}{.spec.replicas}{"\n"}' 2>/dev/null || echo "n/a"
	@echo "== Saleor API ready =="
	@kubectl -n $(NAMESPACE) get deploy saleor-api -o jsonpath='{.status.readyReplicas}{" / "}{.spec.replicas}{"\n"}' 2>/dev/null || echo "n/a"
	@echo "== Saleor Dashboard ready =="
	@kubectl -n $(NAMESPACE) get deploy saleor-dashboard -o jsonpath='{.status.readyReplicas}{" / "}{.spec.replicas}{"\n"}' 2>/dev/null || echo "n/a"
	@echo "== Online Boutique frontend ready =="
	@kubectl -n $(NAMESPACE) get deploy frontend -o jsonpath='{.status.readyReplicas}{" / "}{.spec.replicas}{"\n"}' 2>/dev/null || echo "n/a"

scan-targets: ## 输出 DAC 资产探测参数（企业应用栈：一次扫描、多 Pod IP）
	@echo "== DAC 资产探测（复制到前端 /infra → 新建扫描）=="
	@echo
	@echo "目标（多 Pod IP，逗号分隔，一次扫描即可）:"
	@kubectl -n $(NAMESPACE) get pods --field-selector=status.phase=Running \
	  -o jsonpath='{range .items[*]}{.status.podIP}{","}{end}' 2>/dev/null | sed 's/,$$//' || echo "(no running pods — run: make apply-all)"
	@echo
	@echo
	@echo "推荐端口:"
	@echo "3306,5432,8069,8000,80,8929,9000,9001"
	@echo
	@echo "== Running Pods（扫描后应对上的指纹）=="
	@kubectl -n $(NAMESPACE) get pods --field-selector=status.phase=Running \
	  -o custom-columns='POD:.metadata.name,IP:.status.podIP' 2>/dev/null || true
	@echo
	@echo "  dac-sandbox-0     → 3306 mysql, 5432 postgres, 8000 fileserver, 8929 gitlab, 9000 minio"
	@echo "  odoo-*            → 8069 odoo（含餐厅 POS）"
	@echo "  odoo-db-*         → 5432 postgres (odoo_demo)"
	@echo "  saleor-api-*      → 8000 http/graphql"
	@echo "  saleor-dashboard-*→ 80 http"
	@echo "  saleor-db-*       → 5432 postgres (saleor)"
	@echo "  frontend-*        → 80 http (Online Boutique)"

clean: ## 清掉本地 vendor 缓存和派生文件
	rm -rf scripts/.vendor-cache \
	       seed/datasets/ml-1m \
	       seed/mysql/50-northwind.sql seed/mysql/51-classicmodels.sql \
	       seed/mysql/52-chinook.sql seed/mysql/53-employees.sh \
	       seed/mysql/53-employees-schema.sql seed/mysql/54-world.sql \
	       seed/mysql/employees-dumps/*.dump \
	       seed/mysql/99-sakila.sql seed/postgres/50-northwind.sql \
	       seed/postgres/98-pagila.sql seed/postgres/99-chinook.sql \
	       scripts/.vendor-cache/online-boutique-kubernetes-manifests.yaml
