# DAC API Server

[![Go Version](https://img.shields.io/badge/Go-1.25-blue.svg)](https://golang.org/)

> RESTful API server for managing AI agents on Kubernetes, including agent lifecycle, data descriptors, and chat APIs.

## 📖 Overview

DAC (Data Agent Container) API Server is a RESTful API service built with the CloudWeGo Hertz framework. It serves as the control plane for managing AI agents in Kubernetes environments and provides:

- **Agent Lifecycle Management**: Full CRUD operations for AI agent containers
- **Data Source Orchestration**: Manage and configure data descriptors for agent training
- **OpenAI-Compatible Chat API**: Stream-enabled conversational interface following OpenAI standards
- **User Authentication**: JWT-based secure authentication and authorization
- **Kubernetes Native**: Direct integration with Kubernetes custom resources (CRDs)

## ✨ Key Features

### 🤖 AI Agent Management
- Create, update, and delete agent containers with custom configurations
- Define agent skills, capabilities, and model specifications
- Automatic data source binding and synchronization
- Real-time agent status monitoring

### 📊 Data Descriptor Management
- Configure multiple data source types (SQL, documents, APIs)
- Define data extraction, processing, and cleaning rules
- Track data source synchronization status
- Classify and tag data for intelligent retrieval

### 💬 Chat Capabilities
- OpenAI-compatible `/v1/chat/completions` endpoint
- Server-Sent Events (SSE) streaming for real-time responses
- Integration with routing agent for intelligent query handling
- Session management and conversation history

### 🔐 Security & Authentication
- JWT-based authentication with token refresh
- User registration and login
- Protected API endpoints with middleware
- Role-based access control ready

### 🎛️ Operations
- Health check endpoints (readiness and liveness probes)
- Structured JSON logging with slog
- Graceful shutdown support
- Swagger API documentation
- Kubernetes deployment ready

## 🚀 Quick Start

### Prerequisites

- Go 1.25 or higher
- MySQL 8.0+
- Kubernetes cluster (for CRD management)
- kubectl configured with cluster access

### Installation

#### 1. Clone the Repository

```bash
git clone https://github.com/lvyanru/dac-apiserver.git
cd dac-apiserver
```

#### 2. Install Dependencies

```bash
make deps
```

#### 3. Configure the Service

Edit the configuration file:

```bash
cp configs/config.yaml configs/config-local.yaml
# Edit configs/config-local.yaml with your settings
```

Key configuration sections:
- **Database**: MySQL connection settings
- **JWT**: Secret key for token generation
- **Routing Agent**: URL and timeout for agent communication
- **Server**: Host, port, and timeout settings

#### 4. Run Database Migrations

```bash
# Ensure MySQL is running and accessible
mysql -u root -p < deploy/schema.sql
```

#### 5. Start the API Server

```bash
# Using make
make run

# Or build and run binary
make build
./bin/dac-apiserver -c configs/config-local.yaml
```

The server will start on `http://localhost:8080` (default).

### Using the CLI Tool

#### Install dactl

```bash
make build-cli
make install-cli
```

#### Login

```bash
dactl login http://localhost:8080 -u admin
```

#### List Resources

```bash
# List in default namespace
dactl list

# List across all namespaces
dactl list -A

```

#### Interactive Chat

```bash
dactl chat
```

## 📚 API Documentation

Once the server is running, access the Swagger documentation at:

```
http://localhost:8080/swagger/index.html
```

## 🛠️ Development

### Project Structure

```
dac-apiserver/
├── cmd/
│   ├── server/          # API server entry point
│   └── dactl/           # CLI tool entry point
├── internal/
│   ├── cli/             # CLI commands and UI
│   ├── config/          # Configuration loader
│   ├── domain/          # Domain entities and business logic
│   ├── ent/             # Database ORM (Ent framework)
│   ├── handler/         # HTTP handlers
│   ├── infrastructure/  # External service integrations
│   ├── middleware/      # HTTP middlewares
│   ├── router/          # Route definitions
│   └── usecase/         # Business use cases
├── pkg/
│   ├── database/        # Database client
│   ├── k8s/             # Kubernetes client
│   └── logger/          # Logging utilities
├── configs/             # Configuration files
├── deploy/              # Kubernetes manifests
├── docs/                # Swagger documentation
└── test/                # Integration tests
```

### Running Tests

```bash
# Run unit tests
make test

# Run integration tests (requires MySQL and routing agent)
make test-integration

# Generate coverage report
make coverage
```

### Code Quality

```bash
# Format code
make fmt

# Run linter
make lint

# Run go vet
make vet
```

## 🐳 Docker Deployment

### Build Docker Image

```bash
make docker-build
```

### Run with Docker

```bash
make docker-run
```

### Push to Registry

```bash
export DOCKER_REGISTRY=your-registry.com
export DOCKER_NAMESPACE=your-namespace
make docker-push
```

## ☸️ Kubernetes Deployment

### Prerequisites

Ensure your cluster has the required CRDs installed:
- `agentcontainers.daocloud.io`
- `datadescriptors.daocloud.io`

### Deploy

```bash
# Apply RBAC and deployment
make k8s-deploy

# Check status
make k8s-status

# View logs
make k8s-logs
```

### Undeploy

```bash
make k8s-delete
```

## 🔧 Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `CONFIG_FILE` | Path to config file | `configs/config.yaml` |
| `SERVER_PORT` | HTTP server port | `8080` |
| `LOG_LEVEL` | Logging level | `debug` |
| `DB_HOST` | MySQL host | `127.0.0.1` |
| `DB_PORT` | MySQL port | `3306` |

### Configuration File

See `configs/config.yaml` for a complete configuration example.

```yaml
server:
  host: ""
  port: 8080
  mode: "debug"
  read_timeout: 10s
  write_timeout: 10s

database:
  driver: "mysql"
  host: "127.0.0.1"
  port: 3306
  user: "dac_user"
  password: "dac_pass"
  database: "dac_db"

jwt:
  secret: "your-secret-key"

routing_agent:
  base_url: "http://routing-agent:30100"
  timeout: 30s
```
