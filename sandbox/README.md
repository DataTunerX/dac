# Sandbox Environment (Discovery / Scanning Playground)

This sandbox spins up a small-but-representative environment for building and testing:
- Infra discovery (hosts/ports/services) — optional
- Application discovery (APIs/config/runtime)
- Data source discovery (DB/filesystem/object store)
- Profiling & PII detection (sample schemas + sample files)
- (Simple) data lake querying (Trino over S3/MinIO)

## What you get

- **Database**: Postgres with sample `erp` schema + PII-like fields
- **Filesystem**: local directories under `sandbox/data/filesystem/` (mounted into mock apps)
- **Object store**: MinIO with buckets `objects` and `lake`
- **Data lake**: Trino querying:
  - Postgres tables (for relational discovery)
  - Hive connector over MinIO bucket `lake` (Parquet/CSV objects as lake files)
- **Applications (mock)**:
  - `o365-mock`: minimal Mail/Drive-like APIs
  - `erp-mock`: Customers/Orders APIs backed by Postgres
  - `vertical-mock`: a generic industry app exposing a couple domain endpoints
- **Source code repo (local folder)**: `sandbox/data/source-repos/sample-app/`

## Quick start

1) Start everything:

```bash
cd sandbox
docker compose up -d
```

2) Verify:

```bash
docker compose ps
```

Or run the helper scripts:

```bash
sh ./bin/up.sh
sh ./bin/verify.sh
```

## Kubernetes mode (single Pod = “one host IP” sandbox)

If you run DAC on a Linux server / Kubernetes, this mode gives you a more realistic discovery target:
all sandbox services run **in one Pod (multi-container)**, sharing a single network namespace/IP.
So you can scan **one IP** and discover many open ports/services, like scanning a single Linux host.

Apply:

```bash
kubectl apply -f sandbox/k8s/00-namespace.yaml
kubectl apply -f sandbox/k8s/01-configmaps.yaml
kubectl apply -f sandbox/k8s/03-services.yaml
kubectl apply -f sandbox/k8s/02-statefulset.yaml
kubectl apply -f sandbox/k8s/04-jobs.yaml
```

### Gitea repo seeding (bake source into the image)

The Kubernetes sandbox uses a custom Gitea image (`release.daocloud.io/dac/sandbox-gitea:seed`) so the repo can be present without mounting local paths.

If your code is only on your local machine, you can publish all required images (including the seeded Gitea image) into `release.daocloud.io/dac`:

```bash
docker login release.daocloud.io
REGISTRY_NS=release.daocloud.io/dac LOCAL_REPO_PATH=~/go/src/zeysi-apiserver sh sandbox/bin/publish-images.sh
```

After pushing, apply the Kubernetes manifests as usual.

If your cluster storage (PVC) is not available (e.g. NFS CSI issues), this sandbox uses **emptyDir (ephemeral)** storage by default.
Recreating the Pod will reset all data — which is fine for discovery demos.

Check:

```bash
kubectl -n dac-sandbox get pods -w
kubectl -n dac-sandbox get svc dac-sandbox-host
kubectl -n dac-sandbox get pod -l app=dac-sandbox-host -o wide
```

4) Useful URLs

- MinIO Console: `http://localhost:9001` (default: `minioadmin/minioadmin`)
- MinIO S3 API: `http://localhost:9000`
- Trino: `http://localhost:8080`
- Nextcloud (O365 replacement): `http://localhost:8011`
- Odoo (ERP): `http://localhost:8012`
- Gitea (Repo): `http://localhost:8013`

## Notes / assumptions

- This sandbox is intentionally **non-production** and uses simple default credentials.
- If your scanners require credentials, use the `.env` values and treat them as *sandbox-only*.
- Some images will be pulled from Docker Hub on first run.

## Seeded artifacts (for scanners)

- **Filesystem**:
  - `sandbox/data/filesystem/user-home/alice/` and `.../bob/` with a few files (including PII-like strings)
- **Object store**:
  - Bucket `objects`: mock documents under prefixes like `o365/drive/` and `erp/exports/`
  - Bucket `lake`: lake files under `warehouse/demo.db/...`
- **Source repos**:
  - `sandbox/data/source-repos/sample-app/` with a few fake services + CI/CD configs
