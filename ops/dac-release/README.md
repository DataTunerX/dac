# DAC Build and Test-Cluster Release Plan

This directory defines the build-machine workflow for producing DAC AMD64
container images and deploying them to `test-cluster`.

The entry point is [`dac-release.sh`](./dac-release.sh). It deliberately keeps
build selection, image production, and cluster rollout in one auditable command
while still allowing each stage to run independently.

The provisioned host inventory, paths, installed versions, and validation record
are in [`BUILD_HOST.md`](./BUILD_HOST.md).

## Goals

- Select source by remote branch, tag, exact commit, or the latest commit on a
  branch.
- Resolve every source selection to an immutable full Git SHA before building.
- Build only affected images by default, including changed vendored SDK wheels
  inside component build contexts.
- Support an explicit `--full` rebuild and an optional `--no-cache` build.
- Push only `linux/amd64` images to the internal registry.
- Preserve the existing test-cluster passwords, API keys, storage settings,
  and other Helm values.
- Roll static DAC services and operator-managed `DataAgentContainer` workloads
  through their normal ownership paths.
- Record enough source, image, and Helm state to explain and roll back a
  release.

## Verified Environment

The defaults reflect the environment verified on 2026-10-01:

| Setting | Value |
|---|---|
| Registry | `10.124.48.120/dac` |
| Registry transport | HTTPS with a self-signed certificate |
| Kubernetes context | `test-cluster` |
| Kubernetes API | `https://10.124.48.127:6443` |
| Kubernetes architecture | `linux/amd64` |
| Helm release | `dac` |
| Helm namespace | `dac` |
| Chart | `installer/dac` |
| Build host | `dev@10.124.48.168` |
| Build storage | `/data/dac-build` on a dedicated 196 GiB ext4 filesystem |

The registry currently does not require credentials. Both the Docker daemon and
the BuildKit builder must allow the self-signed registry.

## Build Host

Recommended host for parallel or frequent full builds:

- Ubuntu 22.04 or 24.04 on native AMD64
- 16 CPU cores
- 32 GiB RAM minimum; 64 GiB preferred
- 300-500 GiB SSD for source, image layers, logs, and BuildKit cache
- Network access to the registry, cluster API, GitHub, and all package/image
  repositories referenced by DAC Dockerfiles

The current host has 16 AMD64 vCPUs, 16 GiB RAM, 4 GiB swap, and 196 GiB of
dedicated build storage. It is validated for the script's sequential image build
flow. Avoid running independent builds concurrently on this host.

Required commands:

- Bash 3 or later
- Docker Engine and Docker Buildx
- Git
- `kubectl`
- Helm
- `jq`, `curl`, `flock`, and standard GNU utilities

Use a dedicated `dacbuild` account. Its kubeconfig should have only the access
needed to read and update the DAC Helm release, its ConfigMaps and workloads,
and `DataAgentContainer` resources.

## Registry and Builder Bootstrap

Merge the following into `/etc/docker/daemon.json` and restart Docker:

```json
{
  "insecure-registries": ["10.124.48.120"]
}
```

Create `/etc/buildkit/buildkitd.toml`:

```toml
[registry."10.124.48.120"]
  http = false
  insecure = true
```

Create the persistent builder:

```bash
docker buildx create \
  --name dac-amd64-builder \
  --driver docker-container \
  --driver-opt network=host \
  --buildkitd-config /etc/buildkit/buildkitd.toml \
  --use

docker buildx inspect dac-amd64-builder --bootstrap
```

Copy `config.env.example` to `/etc/dac-release/config.env` and adjust it for the
host. That is the default config path; set `DAC_RELEASE_CONFIG` only when using
a different location.

The provisioned host already has this configuration, Docker's data root at
`/data/dac-build/docker`, and a persistent builder named
`dac-amd64-builder`.

## Source Selection

Exactly one primary source is selected:

```bash
# Latest remote commit on a branch
./ops/dac-release/dac-release.sh plan --branch install --latest

# A commit that must belong to a branch
./ops/dac-release/dac-release.sh plan \
  --branch install --commit 81a01da69d15

# A Git tag
./ops/dac-release/dac-release.sh plan --tag demo-ready-2026-09-11

# An exact commit
./ops/dac-release/dac-release.sh plan --commit 81a01da69d15
```

`--branch NAME` without `--commit` also means the latest fetched remote commit.
The generated image tag is derived from the source label and resolved SHA, for
example `install-81a01da69d15-amd64`. The script never uses `latest` as an image
tag.

## Commands

Inspect the operation without building or changing the cluster:

```bash
./ops/dac-release/dac-release.sh plan \
  --branch install --latest --cluster test-cluster
```

Build affected images only:

```bash
./ops/dac-release/dac-release.sh build \
  --branch install --latest
```

Build and deploy affected components:

```bash
./ops/dac-release/dac-release.sh all \
  --branch install --latest --cluster test-cluster
```

Force the complete image matrix:

```bash
./ops/dac-release/dac-release.sh all \
  --branch install --latest --cluster test-cluster --full
```

Force a clean complete build:

```bash
./ops/dac-release/dac-release.sh build \
  --branch install --latest --full --no-cache
```

Force selected images:

```bash
./ops/dac-release/dac-release.sh all \
  --branch install --latest \
  --images skill-agent,routing-agent
```

Deploy images already built by an earlier invocation:

```bash
./ops/dac-release/dac-release.sh deploy \
  --branch install --commit 81a01da69d15
```

Status, Helm history, and rollback:

```bash
./ops/dac-release/dac-release.sh status
./ops/dac-release/dac-release.sh history
./ops/dac-release/dac-release.sh rollback --helm-revision 3
```

Deploying requires an interactive confirmation. Automation must pass `--yes`.
Use `--dry-run` to render and validate the Helm release without applying it.

## Incremental Selection

After each successful deployment, the script stores the resolved Git revision
in ConfigMap `dac-release-state` in the Helm namespace. The next plan compares
that deployed revision with the requested target revision.

Direct component changes rebuild that component. Important fan-outs include:

- `model_sdk/**` and `skill_sdk/**`: no runtime image until a new wheel is
  published and vendored into component contexts
- component-local `sdks/*.whl`: the owning component image
- `data-sinkers/**`: job, status, and observer images
- `installer/dac/**`: chart deployment, with no automatic image rebuild
- `my-values.yaml`: reported but never applied; live Helm values remain authoritative
- documentation and test-only changes: no image rebuild
- unknown runtime paths: full rebuild as a fail-safe

The repository currently vendors SDK wheel files separately into each consuming
component. Changing top-level SDK source without refreshing those copies cannot
change any consumer image. The planner reports that condition and waits for the
vendored wheel changes; it does not spend time rebuilding images that would
still contain the old wheel.

Use `--baseline SHA` to override the cluster-recorded comparison revision. If
no baseline exists, the first automatic plan builds the full image matrix.

## Image Matrix

The complete build contains:

- `agent-registry`
- `chart-agent`
- `code-agent`
- `dac-apiserver`
- `dac-data-services`
- `data-services`
- `data-sinkers-job`
- `data-sinkers-status`
- `data-sinkers-observer`
- `doc-agent`
- `execution-engine`
- `expert-agent`
- `frontend`
- `orchestrator-agent`
- `routing-agent`
- `semantic-grouper`
- `skill-agent`
- `skill-hub`
- `tdb-gateway`

Each build uses its component directory as the Docker context and its AMD64
Dockerfile where one exists. Images are pushed directly to the registry with
OCI source, version, revision, and creation labels plus BuildKit provenance and
SBOM metadata.

## Deployment Behavior

The deployment stage:

1. Acquires a host-level release lock.
2. Confirms every planned image exists and includes `linux/amd64`.
3. Saves the current Helm values and rendered manifest under the private release
   state directory.
4. Generates image-only Helm overrides in memory.
5. Runs `helm lint` and `helm template`.
6. Runs `helm upgrade --rollback-on-failure --wait` while reusing the installed
   release's values.
7. Waits for affected static Deployments.
8. When a dynamic agent image changes, waits for existing operator-managed
   `DataAgentContainer` Deployments to reference the new tag, then waits for
   their rollouts.
9. Records the successful Git revision, image tag, image set, and Helm revision.

Changing `executionEngine.agentImages.skillAgent.tag` updates
`dac-configuration`. The execution-engine controller watches that ConfigMap and
requeues all existing `DataAgentContainer` resources. One `skill-agent` image
build can therefore roll many agent Deployments without rebuilding them.

CRDs are not upgraded automatically by Helm. If the selected revision changes
files under `installer/dac/crds`, deployment stops unless `--apply-crds` is
explicitly supplied.

## Safety Rules

- Never build from a mutable or dirty source checkout. Builds use a detached,
  temporary Git worktree at the resolved SHA.
- Never reuse a Git-derived image tag for a different SHA.
- Never deploy until all planned images pass registry and architecture checks.
- Never write Helm values snapshots into the source checkout; they may contain
  secrets.
- Never modify passwords, API keys, NFS settings, or LLM ConfigMaps as part of
  an image-only release.
- Never run two releases concurrently from the same build host.
- A failed Helm rollout must fail the command and rely on Helm atomic rollback.
- After a manual Helm rollback, the release-state ConfigMap is removed so the
  next automatic plan safely performs a full rebuild unless a baseline is
  provided.

## Acceptance Tests

Before using the machine for routine deployment, verify:

1. Branch-latest, tag, exact-commit, and branch-plus-commit selection.
2. Documentation-only changes produce an empty image plan.
3. A `skill-agent` source change builds one image and rolls all skill-agent
   consumers.
4. A component's vendored SDK wheel change rebuilds that component.
5. `--full` selects the complete image matrix.
6. `--no-cache` reaches BuildKit correctly.
7. A failed image build prevents Helm from running.
8. A missing or non-AMD64 image prevents deployment.
9. A failed rollout leaves the previous Helm revision active.
10. Re-running an already deployed SHA performs no work unless forced.
