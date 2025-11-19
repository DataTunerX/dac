.PHONY: help build run clean test test-integration coverage lint fmt vet docker-build docker-push build-cli install-cli

# Default target
.DEFAULT_GOAL := help

# Application name and version
APP_NAME := dac-apiserver
CLI_NAME := dactl
VERSION := $(shell git describe --tags --always --dirty 2>/dev/null || echo "dev")
COMMIT := $(shell git rev-parse --short HEAD 2>/dev/null || echo "unknown")
BUILD_TIME := $(shell date -u '+%Y-%m-%d_%H:%M:%S')

# Directories
BIN_DIR := bin
CMD_DIR := cmd/server
CLI_CMD_DIR := cmd/dactl

# Docker configuration
DOCKER_REGISTRY ?= release.daocloud.io
DOCKER_NAMESPACE ?= dac
DOCKER_IMAGE := $(DOCKER_REGISTRY)/$(DOCKER_NAMESPACE)/apiserver
DOCKER_TAG ?= v0.1

# Go related variables
GOCMD := go
GOBUILD := $(GOCMD) build
GORUN := $(GOCMD) run
GOCLEAN := $(GOCMD) clean
GOTEST := $(GOCMD) test
GOGET := $(GOCMD) get
GOFMT := $(GOCMD) fmt
GOVET := $(GOCMD) vet

# Build parameters
LDFLAGS := -ldflags "-w -s \
	-X main.version=$(VERSION) \
	-X main.commit=$(COMMIT) \
	-X main.buildTime=$(BUILD_TIME)"

help: ## Show help information
	@echo "Available Make targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

deps: ## Download dependencies
	@echo "Downloading dependencies..."
	$(GOCMD) mod download
	$(GOCMD) mod tidy

build: ## Build application
	@echo "Building application..."
	@mkdir -p $(BIN_DIR)
	$(GOBUILD) $(LDFLAGS) -o $(BIN_DIR)/$(APP_NAME) ./$(CMD_DIR)
	@echo "Build complete: $(BIN_DIR)/$(APP_NAME)"

build-linux: ## Build Linux version
	@echo "Building Linux version..."
	@mkdir -p $(BIN_DIR)
	CGO_ENABLED=0 GOOS=linux GOARCH=amd64 $(GOBUILD) $(LDFLAGS) -o $(BIN_DIR)/$(APP_NAME)-linux-amd64 ./$(CMD_DIR)
	@echo "Build complete: $(BIN_DIR)/$(APP_NAME)-linux-amd64"

build-cli: ## Build CLI tool
	@echo "Building CLI tool..."
	@mkdir -p $(BIN_DIR)
	$(GOBUILD) $(LDFLAGS) -o $(BIN_DIR)/$(CLI_NAME) ./$(CLI_CMD_DIR)
	@echo "Build complete: $(BIN_DIR)/$(CLI_NAME)"

build-all: build build-cli ## Build API Server and CLI tool

run: ## Run application
	@echo "Running application..."
	$(GORUN) ./$(CMD_DIR)

run-prod: ## Run with production config
	@echo "Running with production config..."
	$(GORUN) ./$(CMD_DIR) -c configs/config-prod.yaml

clean: ## Clean build files
	@echo "Cleaning build files..."
	$(GOCLEAN)
	rm -rf $(BIN_DIR)
	rm -f coverage.txt coverage.html

test: ## Run all unit tests
	@echo "Running all unit tests..."
	$(GOTEST) -v -race -coverprofile=coverage.txt -covermode=atomic ./...

test-integration: ## Run integration tests (requires MySQL + Routing Agent)
	@echo "Running integration tests..."
	@echo "Ensure MySQL is running: docker-compose up -d"
	$(GOTEST) -tags=integration -v ./test/integration/...

coverage: test ## Generate test coverage report
	@echo "Generating coverage report..."
	$(GOCMD) tool cover -html=coverage.txt -o coverage.html
	@echo "Coverage report generated: coverage.html"

fmt: ## Format code
	@echo "Formatting code..."
	$(GOFMT) ./...

vet: ## Run go vet
	@echo "Running go vet..."
	$(GOVET) ./...

lint: fmt vet ## Run code checks

install: build ## Install API Server
	@echo "Installing API Server..."
	@mkdir -p $(HOME)/go/bin
	cp $(BIN_DIR)/$(APP_NAME) $(HOME)/go/bin/
	@echo "Installed to $(HOME)/go/bin/$(APP_NAME)"

install-cli: build-cli ## Install CLI tool
	@echo "Installing CLI tool..."
	@mkdir -p $(HOME)/go/bin
	cp $(BIN_DIR)/$(CLI_NAME) $(HOME)/go/bin/
	@echo "CLI tool installed to $(HOME)/go/bin/$(CLI_NAME)"
	@echo "Make sure $(HOME)/go/bin is in your PATH"

install-all: install install-cli ## Install API Server and CLI tool

docker-build: ## Build Docker image
	@echo "Building Docker image..."
	docker build -t $(DOCKER_IMAGE):$(DOCKER_TAG) .
	docker tag $(DOCKER_IMAGE):$(DOCKER_TAG) $(DOCKER_IMAGE):latest
	@echo "Docker image built: $(DOCKER_IMAGE):$(DOCKER_TAG)"

docker-push: ## Push Docker image
	@echo "Pushing Docker image..."
	docker push $(DOCKER_IMAGE):$(DOCKER_TAG)
	docker push $(DOCKER_IMAGE):latest
	@echo "Docker image pushed"

docker-run: ## Run Docker container
	@echo "Running Docker container..."
	docker run -d \
		--name $(APP_NAME) \
		-p 8080:8080 \
		-p 9090:9090 \
		$(DOCKER_IMAGE):$(DOCKER_TAG)

docker-stop: ## Stop Docker container
	@echo "Stopping Docker container..."
	docker stop $(APP_NAME) || true
	docker rm $(APP_NAME) || true

k8s-deploy: ## Deploy to Kubernetes
	@echo "Deploying to Kubernetes..."
	kubectl apply -f deploy/rbac.yaml
	kubectl apply -f deploy/deployment.yaml
	@echo "Deployment complete"

k8s-delete: ## Delete from Kubernetes
	@echo "Deleting from Kubernetes..."
	kubectl delete -f deploy/deployment.yaml
	kubectl delete -f deploy/rbac.yaml
	@echo "Deletion complete"

k8s-logs: ## View Kubernetes logs
	kubectl logs -f deployment/$(APP_NAME)

k8s-status: ## View Kubernetes status
	kubectl get all -l app=$(APP_NAME)
	kubectl get sa $(APP_NAME)
	kubectl describe clusterrole $(APP_NAME)-role

version: ## Show version information
	@echo "Version:    $(VERSION)"
	@echo "Commit:     $(COMMIT)"
	@echo "Build Time: $(BUILD_TIME)"
