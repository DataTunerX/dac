# NVIDIA Environment Setup (x86_64)

This document summarizes key information for three technologies on x86_64 Linux: NVIDIA NeMo (Framework), NVIDIA NIM (Inference Microservices), and NeMo Agent Toolkit. Each section lists a brief overview, the latest version, official documentation, and environment highlights. For detailed installation and usage, follow the official docs.

## NVIDIA NeMo (Framework)

- Overview: A scalable generative AI framework for LLMs, multimodal, ASR, and TTS, built for researchers and developers.
- Latest stable: 2.3.3 (Sep 2025).
- Docs: NeMo Framework User Guide (Overview) – see official documentation for installation and usage.
  - Overview: [NeMo Framework Overview](https://docs.nvidia.com/nemo-framework/user-guide/latest/overview.html)
  - Releases: [GitHub Releases](https://github.com/NVIDIA-NeMo/NeMo/releases)
- Quick install (reference): pip install "nemo_toolkit[all]" or use NGC PyTorch containers per the User Guide.
- Environment (x86_64): Linux x86_64, Python 3.10 recommended, NVIDIA GPU with recent drivers, CUDA 12.x toolchain via NGC containers or compatible local stack (follow NeMo docs for exact matrix).

Step-by-step usage:

1. Create Python env and install NeMo

```bash
python -m venv .venv && source .venv/bin/activate
pip install "nemo_toolkit[all]"
```

1. Verify installation

```bash
python -c "import nemo; print('NeMo version:', nemo.__version__)"
```

1. Follow the official quickstart to run a minimal example

- [Quickstart with NeMo 2.0 API](https://docs.nvidia.com/nemo-framework/user-guide/latest/nemo-2.0/index.html)
- [Quickstart with NeMo-Run](https://docs.nvidia.com/nemo-framework/user-guide/latest/nemo-2.0/quickstart.html)

## NVIDIA NIM (Inference Microservices)

- Overview: Prebuilt, optimized inference microservices (containers) that expose standard APIs to deploy foundation and custom models across cloud, data center, workstations, and edge. Provided via NVIDIA (not the Nim programming language; not a standalone open-source repo as a single project).
- Latest (example): NIM for LLMs 1.14.0 (see Release Notes for exact per-microservice versions).
- Docs and product pages:
  - Developer page: [NVIDIA NIM for Developers](https://developer.nvidia.com/nim)
  - Product page: [NIM Microservices](https://www.nvidia.com/en-us/ai-data-science/products/nim-microservices/)
  - Release Notes (LLMs): [NIM for LLMs Release Notes](https://docs.nvidia.com/nim/large-language-models/latest/release-notes.html)
- Quick start (reference): Use NVIDIA-hosted endpoints or self-host by pulling the appropriate NIM container (see Developer page and Release Notes for commands and requirements).
- Environment (x86_64): Linux x86_64, NVIDIA GPUs with compatible drivers, container runtime (Docker/Containerd/Kubernetes). Follow the Release Notes for GPU/driver/CUDA compatibility and resource guidance.

Step-by-step usage:

1. Prepare credentials and login to NVIDIA Container Registry (NGC)

```bash
export NGC_API_KEY=<YOUR_NGC_API_KEY>
echo $NGC_API_KEY | docker login nvcr.io -u '$oauthtoken' --password-stdin
```

1. Choose a NIM image (see docs for available models/tags)

- [NIM for Developers](https://developer.nvidia.com/nim)
- [NIM for LLMs Release Notes](https://docs.nvidia.com/nim/large-language-models/latest/release-notes.html)

1. Run the NIM container

```bash
docker run --gpus all \
  -e NGC_API_KEY=$NGC_API_KEY \
  -p 8000:8000 \
  nvcr.io/nim/<publisher>/<model>:<tag>
```

1. Health check

```bash
curl -s http://localhost:8000/v1/health/ready
```

1. Send an example inference request (endpoint and payload vary by NIM)

```bash
curl -X POST \
  -H 'accept: application/json' \
  -H 'Content-Type: application/json' \
  'http://localhost:8000/v1/infer' \
  -d '{"inputs":["hello world"]}'
```

## NeMo Agent Toolkit

- Overview: An open-source toolkit to build, connect, evaluate, and optimize AI agents and agentic workflows; integrates with NIM microservices and supports MCP tooling.
- Latest stable: 1.2 (2025).
- Docs and source:
  - Release Notes: [NeMo Agent Toolkit 1.2 Release Notes](https://docs.nvidia.com/nemo/agent-toolkit/1.2/release-notes.html)
  - GitHub: [NVIDIA/NeMo-Agent-Toolkit](https://github.com/NVIDIA/NeMo-Agent-Toolkit)
- Quick install (reference): pip install nvidia-nat (see Release Notes for details and examples).
- Environment (x86_64): Linux x86_64, Python 3.10+, optional NVIDIA GPU for accelerated components; see docs for integrations with NIM and observability.

Step-by-step usage:

1. Create Python env and install the toolkit

```bash
python -m venv .venv && source .venv/bin/activate
pip install nvidia-nat
```

1. (Optional) Provide API key for NVIDIA-hosted endpoints when examples need it

```bash
export NVIDIA_API_KEY=<YOUR_API_KEY>
```

1. Run a simple workflow (use a config from docs/examples)

```bash
# CLI name may appear as `aiq` in some docs; follow the release notes for the version you install
aiq run --config_file=examples/simple/configs/config.yml --input "Hello"
```

1. Serve a workflow API locally

```bash
aiq serve --config_file=examples/simple/configs/config.yml
# Then query your local endpoint per the docs
```

References:

- [NeMo Agent Toolkit 1.2 Release Notes](https://docs.nvidia.com/nemo/agent-toolkit/1.2/release-notes.html)
- [NVIDIA/NeMo-Agent-Toolkit](https://github.com/NVIDIA/NeMo-Agent-Toolkit)
