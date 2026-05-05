# DAC sandbox — 一键构建/推送/部署
#
# 典型用法:
#   make mirror-public   # (首次/私有 registry 必跑) 同步 mysql/postgres/nginx/alpine/mc/minio/gitlab-ce 公共镜像
#   make vendor          # 下载 Sakila/Pagila/Chinook/MovieLens 到 seed/
#   make build           # 本地 build 五个 sandbox-* 镜像
#                        # (gitlab-seed 镜像构建期会自动 git clone gitee.com/jamesxiong888/test-code.git)
#   make push            # push sandbox-* 镜像到 $(REGISTRY)
#   make apply           # 部署到当前 kubectl 上下文
#   make all             # vendor + build + push
#   make verify          # 部署后做端口和数据自检

REGISTRY ?= release.daocloud.io/dac
TAG      ?= v0.10.0
PLATFORM ?= linux/amd64
BUILD    := docker build --platform $(PLATFORM)

MYSQL_IMAGE        := $(REGISTRY)/sandbox-mysql:$(TAG)
POSTGRES_IMAGE     := $(REGISTRY)/sandbox-postgres:$(TAG)
MINIO_SEED_IMAGE   := $(REGISTRY)/sandbox-minio-seed:$(TAG)
FILESERVER_IMAGE   := $(REGISTRY)/sandbox-fileserver:$(TAG)
GITLAB_SEED_IMAGE  := $(REGISTRY)/sandbox-gitlab-seed:$(TAG)

NAMESPACE := dac-sandbox

# gitlab-seed 镜像内置的示例代码仓库（构建期 git clone 进镜像）
GITLAB_SEED_REPO_URL ?= https://gitee.com/jamesxiong888/test-code.git
GITLAB_SEED_REPO_REF ?= master

.PHONY: help vendor mirror-public \
        build build-mysql build-postgres build-minio-seed build-fileserver build-gitlab-seed \
        push push-mysql push-postgres push-minio-seed push-fileserver push-gitlab-seed \
        apply delete restart logs verify clean all

help:
	@awk 'BEGIN{FS=":.*##"; printf "\nUsage:\n  make \033[36m<target>\033[0m\n\nTargets:\n"} /^[a-zA-Z0-9_-]+:.*?##/{printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# ------------- Vendor (开源数据集) -------------
vendor: ## 下载 Sakila / Pagila / Chinook / MovieLens 1M 到 seed/
	@bash scripts/download-vendor.sh

# ------------- Mirror Public Images -------------
# 把 sandbox 用到的所有外部公共镜像（base + runtime）从 docker.io 同步到 $(REGISTRY)
# 只在私有 registry 不是 docker hub 透明代理时需要跑一次。已存在则覆盖。
PUBLIC_IMAGES := \
  library/mysql:8.0 \
  library/postgres:16 \
  library/nginx:1.27-alpine \
  library/alpine:3.20 \
  minio/mc:latest \
  minio/minio:latest \
  gitlab/gitlab-ce:17.5.0-ce.0

mirror-public: ## 拉公共镜像 → retag → push 到 $(REGISTRY) （私有 registry 首次必跑）
	@set -e; \
	for src in $(PUBLIC_IMAGES); do \
	  short=$$(basename "$$src"); \
	  dst="$(REGISTRY)/$$short"; \
	  echo "\033[36m[mirror]\033[0m docker.io/$$src  ->  $$dst"; \
	  docker pull --platform $(PLATFORM) "docker.io/$$src"; \
	  docker tag  "docker.io/$$src" "$$dst"; \
	  docker push "$$dst"; \
	done
	@echo "\n\033[32m[mirror] DONE — $(words $(PUBLIC_IMAGES)) images synced to $(REGISTRY)\033[0m"

# ------------- Build -------------
build: build-mysql build-postgres build-minio-seed build-fileserver build-gitlab-seed ## build 全部 5 个镜像

build-mysql:        ## build MySQL 镜像
	$(BUILD) -t $(MYSQL_IMAGE)      -f images/mysql/Dockerfile      .
build-postgres:     ## build PostgreSQL 镜像
	$(BUILD) -t $(POSTGRES_IMAGE)   -f images/postgres/Dockerfile   .
build-minio-seed:   ## build MinIO seed Job 镜像
	$(BUILD) -t $(MINIO_SEED_IMAGE) -f images/minio-seed/Dockerfile .
build-fileserver:   ## build FileServer (nginx) 镜像
	$(BUILD) -t $(FILESERVER_IMAGE) -f images/fileserver/Dockerfile .
build-gitlab-seed:  ## build GitLab seed Job 镜像（构建期会克隆 $(GITLAB_SEED_REPO_URL)）
	$(BUILD) \
	  --build-arg SEED_REPO_URL=$(GITLAB_SEED_REPO_URL) \
	  --build-arg SEED_REPO_REF=$(GITLAB_SEED_REPO_REF) \
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
apply: ## kubectl apply 整个 sandbox
	kubectl apply -f k8s/00-namespace.yaml
	kubectl apply -f k8s/01-statefulset.yaml
	kubectl apply -f k8s/02-services.yaml
	kubectl apply -f k8s/03-seed-job.yaml
	kubectl apply -f k8s/04-gitlab-seed-job.yaml
	@echo
	@echo "等 Pod ready (GitLab 首次 reconfigure 约 3-5 分钟):  kubectl -n $(NAMESPACE) get pods -w"

delete: ## 拆掉 sandbox
	-kubectl delete -f k8s/04-gitlab-seed-job.yaml
	-kubectl delete -f k8s/03-seed-job.yaml
	-kubectl delete -f k8s/02-services.yaml
	-kubectl delete -f k8s/01-statefulset.yaml
	-kubectl delete -f k8s/00-namespace.yaml

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

clean: ## 清掉本地 vendor 缓存和派生文件
	rm -rf scripts/.vendor-cache \
	       seed/datasets/ml-1m \
	       seed/mysql/99-sakila.sql seed/postgres/98-pagila.sql seed/postgres/99-chinook.sql
