# DAC Build Host

This document records the build and deployment environment provisioned for DAC
on 2026-10-01.

## Host Inventory

| Setting | Value |
|---|---|
| Host | `10.124.48.168` |
| Login | `dev` |
| Operating system | Ubuntu 24.04.1 LTS |
| Architecture | `x86_64` / `linux/amd64` |
| CPU | 16 vCPUs, Intel Xeon Gold 6126 |
| Memory | 16 GiB RAM, 4 GiB swap |
| Build filesystem | `/dev/sdb1`, ext4, mounted at `/data` |
| Build capacity | 196 GiB total, 186 GiB available after provisioning |

The release script builds images sequentially. Do not run separate builds in
parallel on this host; 16 GiB is adequate for the sequential workflow but does
not leave enough margin for multiple concurrent component builds.

## Installed Toolchain

| Tool | Version |
|---|---|
| Docker Engine | `29.8.2` |
| Docker Buildx | `0.37.1` |
| BuildKit | `0.33.1` |
| kubectl | `1.32.13` |
| Helm | `4.3.0` |
| Git | `2.43.0` or the current Ubuntu security update |
| jq | `1.7.1` or the current Ubuntu security update |
| Bash | `5.2.21` |

`kubectl` is held on the Kubernetes 1.32 package line because `test-cluster`
runs Kubernetes 1.32.9. Upgrade it deliberately when the cluster minor version
changes.

## Filesystem Layout

| Path | Purpose |
|---|---|
| `/data/dac-build/docker` | Docker data root, BuildKit container and cache data |
| `/data/dac-build/source/dac` | DAC Git checkout |
| `/data/dac-build/state` | Private release logs, manifests, worktrees, and lock |
| `/etc/dac-release/config.env` | Release-script environment configuration |
| `/etc/docker/daemon.json` | Docker data root, registry, and log rotation |
| `/etc/buildkit/buildkitd.toml` | BuildKit registry transport configuration |
| `/home/dev/.kube/config` | Minimal flattened `test-cluster` kubeconfig, mode `0600` |

Docker is configured to use `10.124.48.120` as an insecure registry because its
HTTPS certificate is self-signed and not standards-compliant. BuildKit uses
HTTPS with certificate verification disabled for that registry.

## Buildx Builder

The persistent builder is named `dac-amd64-builder`. It uses the
`docker-container` driver, host networking, and the BuildKit configuration above.
Its advertised native platforms include `linux/amd64`.

Inspect it with:

```bash
docker buildx inspect dac-amd64-builder --bootstrap
```

## Source Checkout

The initial checkout tracks `origin/install`:

```text
/data/dac-build/source/dac
```

At provisioning time it resolved to commit
`81a01da69d15f04bd979a426748847d67a51b45e`. The release script always fetches
the requested remote branch or tag and resolves it to an immutable commit before
building, so this initial revision is not a permanent pin.

Until `ops/dac-release` is committed to the branch, that directory is synced
from the workstation and appears as an untracked path in the host checkout. The
build source itself remains a detached clean worktree at the requested Git SHA.

## Operator Commands

Connect and inspect status:

```bash
ssh dev@10.124.48.168
cd /data/dac-build/source/dac
./ops/dac-release/dac-release.sh status
```

Preview the next release:

```bash
./ops/dac-release/dac-release.sh plan --branch install --latest
```

Build and deploy affected images after reviewing the plan:

```bash
./ops/dac-release/dac-release.sh all \
  --branch install --latest \
  --cluster test-cluster \
  --yes
```

Force all DAC images to rebuild:

```bash
./ops/dac-release/dac-release.sh all \
  --branch install --latest \
  --cluster test-cluster \
  --full \
  --yes
```

## Provisioning Validation

The following checks passed on 2026-10-01 without changing the cluster:

- Docker service active and using `/data/dac-build/docker`.
- BuildKit scratch build for `linux/amd64`.
- Registry access to `10.124.48.120/dac` and inspection of an AMD64 manifest.
- `kubectl` access to `dce7`, `dce8`, and `dce9`; all report Ready and AMD64.
- Helm access to release `dac` in namespace `dac`, revision 3, status deployed.
- `helm lint` and `helm template` against `installer/dac`.
- Git fetch and release planning for `origin/install`.

No test deployment or registry push was performed during provisioning.

## Initial Release Dry Run

The first `install` branch release was checked on 2026-10-01 before starting a
real build:

- Target revision: `81a01da69d15f04bd979a426748847d67a51b45e`.
- Prospective image tag: `install-81a01da69d15-amd64`.
- No deployment baseline exists yet, so the fail-safe plan selects all 19 images.
- BuildKit check-only mode resolved every Dockerfile and base image.
- Seventeen Dockerfiles passed with no warnings.
- `dac-apiserver/Dockerfile-amd64` and `frontend/Dockerfile-amd64` report only
  `FromPlatformFlagConstDisallowed` because their AMD64-specific files also set
  `FROM --platform=linux/amd64`; this does not block their builds.
- Helm lint, local rendering, and a server-side upgrade dry run passed with 21
  image-tag overrides and secrets hidden.
- The live Helm release remained revision 3, all 12 DAC Deployments remained
  ready, and no live workload referenced the prospective image tag.

Private preflight logs and rendered artifacts are stored at:

```text
/data/dac-build/state/preflight/install-81a01da69d15-amd64
```

## Maintenance

Check disk and cache usage before a full rebuild:

```bash
df -h /data
docker system df
docker buildx du --builder dac-amd64-builder
```

Review package updates rather than applying an unattended toolchain upgrade.
In particular, keep `kubectl` within one minor version of the cluster and verify
Docker/BuildKit registry behavior after upgrades.

### Docker Socket Permission

Group membership is fixed when a login session starts. A shell opened before the
`dev` account joined the `docker` group may fail with:

```text
permission denied while trying to connect to the docker API at unix:///var/run/docker.sock
```

Exit that shell and reconnect over SSH, then verify access before rerunning:

```bash
id
docker info
```

The `id` output must include the `docker` group. A failed release process closes
its lock and removes its temporary worktree, so the same build command can be
rerun safely after reconnecting.
