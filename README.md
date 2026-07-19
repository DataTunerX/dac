# Instructions

## Deployment

### Platform (DAC)

For platform deployment (apiserver, frontend, agents, middleware), see [`installer/README.md`](installer/README.md):

```bash
helm upgrade --install dac ./installer/dac -n dac --create-namespace -f my-values.yaml
```

### Sandbox (enterprise scan fixture)

For the **demo data plane** used to simulate enterprise IPs for asset discovery (MySQL/Postgres/Redis/MinIO/GitLab/Odoo/Saleor/Boutique), see [`sandbox/README.md`](sandbox/README.md). It is a **separate** Helm chart — not part of the platform chart:

```bash
cd sandbox
make offline-prep   # online build machine (once)
make apply          # helm install ./chart -n dac-sandbox
make scan-targets   # IPs/ports for frontend /infra scan
```

Typical flow: install **platform** → install **sandbox** → scan sandbox Pod IPs in the UI → create data sources → run agents.

## Usage

### Access Address

In Kubernetes, locate the `frontend` service under the `dac` namespace and find the corresponding NodePort.

### Login

Default account: admin/changeme

### Configure the Default Model

select 【Model Management】, and then click 【New Configuration】.

1. Name: `llm-default`

2. Model: Must be the correct model name that can be accessed normally on the corresponding model platform.

3. Other parameters can be provided as needed.
