#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

VERSION="0.1.0"
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
DEFAULT_REPO_ROOT=$(cd "$SCRIPT_DIR/../.." && pwd)

CONFIG_FILE=${DAC_RELEASE_CONFIG:-/etc/dac-release/config.env}
if [[ -f "$CONFIG_FILE" ]]; then
  # This is an administrator-owned shell environment file, not user input.
  # shellcheck disable=SC1090
  source "$CONFIG_FILE"
fi

REPO_ROOT=${DAC_REPO_ROOT:-$DEFAULT_REPO_ROOT}
REGISTRY=${DAC_REGISTRY:-10.124.48.120/dac}
KUBE_CONTEXT=${DAC_KUBE_CONTEXT:-test-cluster}
NAMESPACE=${DAC_NAMESPACE:-dac}
HELM_RELEASE=${DAC_HELM_RELEASE:-dac}
BUILDER=${DAC_BUILDER:-dac-amd64-builder}
STATE_DIR=${DAC_STATE_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/dac-release}
LOCK_FILE=${DAC_LOCK_FILE:-$STATE_DIR/dac-release.lock}
HELM_TIMEOUT=${DAC_HELM_TIMEOUT:-20m}
RELEASE_STATE_CONFIGMAP=${DAC_RELEASE_STATE_CONFIGMAP:-dac-release-state}

ACTION=""
SOURCE_BRANCH=""
SOURCE_TAG=""
SOURCE_COMMIT=""
SOURCE_LATEST=false
BASELINE_OVERRIDE=""
FULL_BUILD=false
NO_CACHE=false
EXPLICIT_IMAGES=""
DRY_RUN=false
ASSUME_YES=false
APPLY_CRDS=false
HELM_REVISION=""

TARGET_SHA=""
TARGET_SHORT_SHA=""
SOURCE_LABEL=""
IMAGE_TAG=""
BASELINE_SHA=""
CHART_CHANGED=false
CRD_CHANGED=false
WORKTREE=""
RELEASE_DIR=""

declare -a BUILD_IMAGES=()
declare -a CHANGED_PATHS=()
declare -a PLAN_NOTES=()

usage() {
  cat <<'EOF'
Usage:
  dac-release.sh plan|build|deploy|all [source options] [release options]
  dac-release.sh status|history
  dac-release.sh rollback --helm-revision REVISION [--yes]

Source options (select one primary source):
  --branch NAME             Use a remote branch.
  --tag NAME                Use a Git tag.
  --commit SHA              Use an exact commit. With --branch, verify ancestry.
  --latest                  Explicitly select the latest fetched branch commit.
  --baseline SHA            Override the deployed revision used for change detection.

Build options:
  --full                    Build the complete DAC image matrix.
  --force-build-all         Alias for --full.
  --images A,B,C            Build/deploy only the named images.
  --no-cache                Disable BuildKit layer reuse.

Deployment options:
  --cluster CONTEXT         Kubernetes context (default: test-cluster).
  --namespace NAMESPACE     Helm namespace (default: dac).
  --release NAME            Helm release name (default: dac).
  --registry PREFIX         Image prefix (default: 10.124.48.120/dac).
  --apply-crds              Permit explicit CRD application before Helm upgrade.
  --dry-run                 Render and validate, but do not change the cluster.
  --yes                     Skip interactive deployment confirmation.
  --helm-revision NUMBER    Helm revision used by rollback.

Examples:
  dac-release.sh plan --branch install --latest
  dac-release.sh all --branch install --latest --cluster test-cluster
  dac-release.sh all --tag demo-ready-2026-09-11 --full
  dac-release.sh build --commit 81a01da69d15 --images skill-agent,routing-agent
  dac-release.sh rollback --helm-revision 3
EOF
}

log() {
  printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"
}

warn() {
  printf '[%s] WARNING: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >&2
}

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "required command not found: $1"
}

cleanup() {
  if [[ -n "$WORKTREE" && -d "$WORKTREE" ]]; then
    git -C "$REPO_ROOT" worktree remove --force "$WORKTREE" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

all_image_names() {
  cat <<'EOF'
agent-registry
chart-agent
code-agent
dac-apiserver
dac-data-services
data-services
data-sinkers-job
data-sinkers-status
data-sinkers-observer
doc-agent
execution-engine
expert-agent
frontend
orchestrator-agent
routing-agent
semantic-grouper
skill-agent
skill-hub
tdb-gateway
EOF
}

image_spec() {
  case "$1" in
    agent-registry)       printf 'agent-registry\tDockerfile-amd64\n' ;;
    chart-agent)          printf 'chart-agent\tDockerfile-amd64\n' ;;
    code-agent)           printf 'code-agent\tDockerfile-amd64\n' ;;
    dac-apiserver)        printf 'dac-apiserver\tDockerfile-amd64\n' ;;
    dac-data-services)    printf 'dac-data-services\tDockerfile-amd64\n' ;;
    data-services)        printf 'data-services\tDockerfile-amd64\n' ;;
    data-sinkers-job)     printf 'data-sinkers\tDockerfile-job-amd64\n' ;;
    data-sinkers-status)  printf 'data-sinkers\tDockerfile-status-amd64\n' ;;
    data-sinkers-observer) printf 'data-sinkers\tDockerfile-observer-amd64\n' ;;
    doc-agent)            printf 'doc-agent\tDockerfile-amd64\n' ;;
    execution-engine)     printf 'execution-engine\tDockerfile\n' ;;
    expert-agent)         printf 'expert-agent\tDockerfile-amd64\n' ;;
    frontend)             printf 'frontend\tDockerfile-amd64\n' ;;
    orchestrator-agent)   printf 'orchestrator-agent\tDockerfile-amd64\n' ;;
    routing-agent)        printf 'routing-agent\tDockerfile-amd64\n' ;;
    semantic-grouper)     printf 'semantic-grouper\tDockerfile-amd64\n' ;;
    skill-agent)          printf 'skill-agent\tDockerfile-amd64\n' ;;
    skill-hub)            printf 'skill-hub\tDockerfile-amd64\n' ;;
    tdb-gateway)          printf 'tdb\tdocker/Dockerfile.gateway\n' ;;
    *) return 1 ;;
  esac
}

helm_keys_for_image() {
  case "$1" in
    agent-registry)
      printf '%s\n' orchestratorRegistry.image.tag bizOrchestratorRegistry.image.tag
      ;;
    chart-agent) printf '%s\n' bizChartAgent.image.tag ;;
    code-agent) printf '%s\n' executionEngine.agentImages.codeAgent.tag ;;
    dac-apiserver) printf '%s\n' apiserver.image.tag ;;
    dac-data-services) printf '%s\n' executionEngine.agentImages.dacDataServices.tag ;;
    data-services) printf '%s\n' dataServices.image.tag ;;
    data-sinkers-job) printf '%s\n' executionEngine.agentImages.dataSinkerJob.tag ;;
    data-sinkers-status) printf '%s\n' executionEngine.agentImages.dataSinkerStatus.tag ;;
    data-sinkers-observer) printf '%s\n' executionEngine.agentImages.dataSinkersObserver.tag ;;
    doc-agent) printf '%s\n' executionEngine.agentImages.docAgent.tag ;;
    execution-engine) printf '%s\n' executionEngine.image.tag ;;
    expert-agent) printf '%s\n' executionEngine.agentImages.expertAgent.tag ;;
    frontend) printf '%s\n' frontend.image.tag ;;
    orchestrator-agent) printf '%s\n' executionEngine.agentImages.orchestratorAgent.tag ;;
    routing-agent) printf '%s\n' bizRoutingAgent.image.tag ;;
    semantic-grouper) printf '%s\n' semanticGrouper.image.tag ;;
    skill-agent)
      printf '%s\n' bizSkillAgent.image.tag executionEngine.agentImages.skillAgent.tag
      ;;
    skill-hub) printf '%s\n' skillHub.image.tag ;;
    tdb-gateway) printf '%s\n' tdb.image.tag ;;
    *) return 1 ;;
  esac
}

static_deployments_for_image() {
  case "$1" in
    agent-registry) printf '%s\n' orchestrator-registry biz-orchestrator-registry ;;
    chart-agent) printf '%s\n' biz-chart-agent ;;
    dac-apiserver) printf '%s\n' dac-apiserver ;;
    data-services) printf '%s\n' data-services ;;
    execution-engine) printf '%s\n' execution-engine ;;
    frontend) printf '%s\n' frontend ;;
    routing-agent) printf '%s\n' biz-routing-agent ;;
    semantic-grouper) printf '%s\n' semantic-grouper-api semantic-grouper-worker ;;
    skill-agent) printf '%s\n' biz-skill-agent ;;
    skill-hub) printf '%s\n' skill-hub ;;
    tdb-gateway) printf '%s\n' tdb ;;
    *) return 0 ;;
  esac
}

is_dynamic_agent_image() {
  case "$1" in
    code-agent|dac-data-services|data-sinkers-job|data-sinkers-status|data-sinkers-observer|doc-agent|expert-agent|orchestrator-agent|skill-agent)
      return 0
      ;;
    *) return 1 ;;
  esac
}

valid_image_name() {
  image_spec "$1" >/dev/null 2>&1
}

add_image() {
  local candidate=$1 existing
  valid_image_name "$candidate" || die "unknown image name: $candidate"
  for existing in "${BUILD_IMAGES[@]:-}"; do
    [[ -n "$existing" ]] || continue
    [[ "$existing" == "$candidate" ]] && return 0
  done
  BUILD_IMAGES+=("$candidate")
}

add_note() {
  local candidate=$1 existing
  for existing in "${PLAN_NOTES[@]:-}"; do
    [[ "$existing" == "$candidate" ]] && return 0
  done
  PLAN_NOTES+=("$candidate")
}

add_all_images() {
  local image
  while IFS= read -r image; do
    [[ -n "$image" ]] && add_image "$image"
  done < <(all_image_names)
}

parse_args() {
  [[ $# -gt 0 ]] || { usage; exit 2; }
  ACTION=$1
  shift
  case "$ACTION" in
    plan|build|deploy|all|status|history|rollback) ;;
    -h|--help) usage; exit 0 ;;
    --version) printf '%s\n' "$VERSION"; exit 0 ;;
    *) die "unknown action: $ACTION" ;;
  esac

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --branch) SOURCE_BRANCH=${2:?missing branch}; shift 2 ;;
      --tag) SOURCE_TAG=${2:?missing tag}; shift 2 ;;
      --commit) SOURCE_COMMIT=${2:?missing commit}; shift 2 ;;
      --latest) SOURCE_LATEST=true; shift ;;
      --baseline) BASELINE_OVERRIDE=${2:?missing baseline}; shift 2 ;;
      --full|--force-build-all) FULL_BUILD=true; shift ;;
      --no-cache) NO_CACHE=true; shift ;;
      --images) EXPLICIT_IMAGES=${2:?missing image list}; shift 2 ;;
      --cluster) KUBE_CONTEXT=${2:?missing context}; shift 2 ;;
      --namespace) NAMESPACE=${2:?missing namespace}; shift 2 ;;
      --release) HELM_RELEASE=${2:?missing release}; shift 2 ;;
      --registry) REGISTRY=${2:?missing registry}; shift 2 ;;
      --apply-crds) APPLY_CRDS=true; shift ;;
      --dry-run) DRY_RUN=true; shift ;;
      --yes) ASSUME_YES=true; shift ;;
      --helm-revision) HELM_REVISION=${2:?missing Helm revision}; shift 2 ;;
      -h|--help) usage; exit 0 ;;
      *) die "unknown option: $1" ;;
    esac
  done
}

validate_source_args() {
  local primary=0
  [[ -n "$SOURCE_BRANCH" ]] && primary=$((primary + 1))
  [[ -n "$SOURCE_TAG" ]] && primary=$((primary + 1))
  if [[ -n "$SOURCE_COMMIT" && -z "$SOURCE_BRANCH" ]]; then
    primary=$((primary + 1))
  fi
  [[ $primary -eq 1 ]] || die "select exactly one of --branch, --tag, or --commit"
  [[ -z "$SOURCE_TAG" || -z "$SOURCE_COMMIT" ]] || die "--tag and --commit cannot be combined"
  if [[ "$SOURCE_LATEST" == true && -z "$SOURCE_BRANCH" ]]; then
    die "--latest is valid only with --branch"
  fi
  if [[ "$FULL_BUILD" == true && -n "$EXPLICIT_IMAGES" ]]; then
    die "--full and --images are mutually exclusive"
  fi
}

resolve_source() {
  require_command git
  git -C "$REPO_ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1 \
    || die "not a Git checkout: $REPO_ROOT"

  log "fetching source refs from origin"
  git -C "$REPO_ROOT" fetch --prune --tags origin

  if [[ -n "$SOURCE_BRANCH" ]]; then
    git -C "$REPO_ROOT" show-ref --verify --quiet "refs/remotes/origin/$SOURCE_BRANCH" \
      || die "remote branch not found: origin/$SOURCE_BRANCH"
    local branch_head
    branch_head=$(git -C "$REPO_ROOT" rev-parse "refs/remotes/origin/$SOURCE_BRANCH^{commit}")
    if [[ -n "$SOURCE_COMMIT" ]]; then
      TARGET_SHA=$(git -C "$REPO_ROOT" rev-parse "$SOURCE_COMMIT^{commit}" 2>/dev/null) \
        || die "commit not found: $SOURCE_COMMIT"
      git -C "$REPO_ROOT" merge-base --is-ancestor "$TARGET_SHA" "$branch_head" \
        || die "commit $TARGET_SHA does not belong to origin/$SOURCE_BRANCH"
    else
      TARGET_SHA=$branch_head
    fi
    SOURCE_LABEL=$SOURCE_BRANCH
  elif [[ -n "$SOURCE_TAG" ]]; then
    git -C "$REPO_ROOT" show-ref --verify --quiet "refs/tags/$SOURCE_TAG" \
      || die "tag not found: $SOURCE_TAG"
    TARGET_SHA=$(git -C "$REPO_ROOT" rev-parse "refs/tags/$SOURCE_TAG^{commit}")
    SOURCE_LABEL=$SOURCE_TAG
  else
    TARGET_SHA=$(git -C "$REPO_ROOT" rev-parse "$SOURCE_COMMIT^{commit}" 2>/dev/null) \
      || die "commit not found: $SOURCE_COMMIT"
    SOURCE_LABEL=commit
  fi

  TARGET_SHORT_SHA=$(git -C "$REPO_ROOT" rev-parse --short=12 "$TARGET_SHA")
  SOURCE_LABEL=$(printf '%s' "$SOURCE_LABEL" \
    | tr '[:upper:]' '[:lower:]' \
    | sed -E 's/[^a-z0-9_.-]+/-/g; s/^-+//; s/-+$//' \
    | cut -c1-96)
  [[ -n "$SOURCE_LABEL" ]] || SOURCE_LABEL=source
  IMAGE_TAG="${SOURCE_LABEL}-${TARGET_SHORT_SHA}-amd64"
}

cluster_available() {
  command -v kubectl >/dev/null 2>&1 \
    && kubectl --context "$KUBE_CONTEXT" get namespace "$NAMESPACE" >/dev/null 2>&1
}

resolve_baseline() {
  if [[ -n "$BASELINE_OVERRIDE" ]]; then
    BASELINE_SHA=$(git -C "$REPO_ROOT" rev-parse "$BASELINE_OVERRIDE^{commit}" 2>/dev/null) \
      || die "baseline commit not found: $BASELINE_OVERRIDE"
    return
  fi

  if cluster_available; then
    BASELINE_SHA=$(kubectl --context "$KUBE_CONTEXT" -n "$NAMESPACE" \
      get configmap "$RELEASE_STATE_CONFIGMAP" \
      -o jsonpath='{.data.revision}' 2>/dev/null || true)
  fi

  if [[ -n "$BASELINE_SHA" ]]; then
    if ! BASELINE_SHA=$(git -C "$REPO_ROOT" rev-parse "$BASELINE_SHA^{commit}" 2>/dev/null); then
      warn "cluster baseline is not present locally; using a full build"
      BASELINE_SHA=""
    fi
  fi
}

path_is_non_runtime() {
  case "$1" in
    .github/*|.claude/*|.codex_skill_import/*|docs/*|test-results/*|README.md|*/README.md|*/tests/*|*/test/*|*/test_*.py|*/__pycache__/*|*.pyc|*.pyo|.gitignore|.DS_Store|.mcp.json|LICENSE|ops/dac-release/*|frontend/tsconfig.tsbuildinfo|*DESIGN.md)
      return 0
      ;;
    *) return 1 ;;
  esac
}

map_changed_path() {
  local path=$1
  path_is_non_runtime "$path" && return 0

  case "$path" in
    installer/dac/crds/*)
      CHART_CHANGED=true
      CRD_CHANGED=true
      ;;
    installer/dac/*)
      CHART_CHANGED=true
      ;;
    my-values.yaml)
      add_note "my-values.yaml changed; it is intentionally not applied because deployment preserves live cluster values"
      ;;
    model_sdk/*)
      add_note "model_sdk source changed; publish and vendor a new wheel in consumer contexts before building runtime images"
      ;;
    skill_sdk/*)
      add_note "skill_sdk source changed; publish and vendor a new wheel in consumer contexts before building runtime images"
      ;;
    agent-registry/*) add_image agent-registry ;;
    chart-agent/*) add_image chart-agent ;;
    code-agent/*) add_image code-agent ;;
    dac-apiserver/*) add_image dac-apiserver ;;
    dac-data-services/*) add_image dac-data-services ;;
    data-services/*) add_image data-services ;;
    data-sinkers/*)
      add_image data-sinkers-job
      add_image data-sinkers-status
      add_image data-sinkers-observer
      ;;
    doc-agent/*) add_image doc-agent ;;
    execution-engine/*) add_image execution-engine ;;
    expert-agent/*) add_image expert-agent ;;
    frontend/*) add_image frontend ;;
    orchestrator-agent/*) add_image orchestrator-agent ;;
    routing-agent/*) add_image routing-agent ;;
    semantic-grouper/*) add_image semantic-grouper ;;
    skill-agent/*) add_image skill-agent ;;
    skill-hub/*) add_image skill-hub ;;
    tdb/*) add_image tdb-gateway ;;
    base-images/*)
      add_note "base image source changed; current component Dockerfiles do not consume these local images"
      ;;
    middleware/*)
      add_note "middleware compose files changed; they are outside the DAC Helm image matrix"
      ;;
    sandbox/*)
      add_note "sandbox path changed; sandbox images are outside the DAC Helm release matrix"
      ;;
    rollback/*)
      add_note "rollback snapshot changed; no runtime image selected"
      ;;
    *)
      add_note "unmapped runtime path '$path' triggered a fail-safe full build"
      FULL_BUILD=true
      ;;
  esac
}

parse_explicit_images() {
  local image
  local -a requested=()
  IFS=',' read -r -a requested <<<"$EXPLICIT_IMAGES"
  for image in "${requested[@]}"; do
    image=$(printf '%s' "$image" | tr -d '[:space:]')
    [[ -n "$image" ]] && add_image "$image"
  done
}

plan_release() {
  BUILD_IMAGES=()
  CHANGED_PATHS=()
  PLAN_NOTES=()
  CHART_CHANGED=false
  CRD_CHANGED=false

  if [[ -n "$EXPLICIT_IMAGES" ]]; then
    parse_explicit_images
    add_note "explicit image selection overrides automatic image detection"
  elif [[ "$FULL_BUILD" == true ]]; then
    add_all_images
  elif [[ -z "$BASELINE_SHA" ]]; then
    FULL_BUILD=true
    add_all_images
    add_note "no deployed baseline was found; selected a fail-safe full build"
  elif [[ "$BASELINE_SHA" == "$TARGET_SHA" ]]; then
    add_note "target revision is already recorded as deployed"
  else
    local path
    while IFS= read -r path; do
      [[ -n "$path" ]] && CHANGED_PATHS+=("$path")
    done < <(git -C "$REPO_ROOT" diff --name-only "$BASELINE_SHA" "$TARGET_SHA")
    for path in "${CHANGED_PATHS[@]:-}"; do
      [[ -n "$path" ]] && map_changed_path "$path"
    done
    if [[ "$FULL_BUILD" == true ]]; then
      BUILD_IMAGES=()
      add_all_images
    fi
  fi

  if [[ ${#BUILD_IMAGES[@]} -gt 0 ]]; then
    local -a sorted_images=()
    while IFS= read -r image; do
      [[ -n "$image" ]] && sorted_images+=("$image")
    done < <(printf '%s\n' "${BUILD_IMAGES[@]}" | LC_ALL=C sort -u)
    BUILD_IMAGES=("${sorted_images[@]}")
  fi
}

print_plan() {
  printf '\nDAC release plan\n'
  printf '  action:          %s\n' "$ACTION"
  printf '  source label:    %s\n' "$SOURCE_LABEL"
  printf '  target revision: %s\n' "$TARGET_SHA"
  printf '  baseline:        %s\n' "${BASELINE_SHA:-<none>}"
  printf '  image tag:       %s\n' "$IMAGE_TAG"
  printf '  registry:        %s\n' "$REGISTRY"
  printf '  cluster:         %s\n' "$KUBE_CONTEXT"
  printf '  Helm release:    %s/%s\n' "$NAMESPACE" "$HELM_RELEASE"
  printf '  full build:      %s\n' "$FULL_BUILD"
  printf '  chart changed:   %s\n' "$CHART_CHANGED"
  printf '  CRD changed:     %s\n' "$CRD_CHANGED"

  printf '\nChanged paths (%d):\n' "${#CHANGED_PATHS[@]}"
  if [[ ${#CHANGED_PATHS[@]} -eq 0 ]]; then
    printf '  <none or unavailable>\n'
  else
    printf '  %s\n' "${CHANGED_PATHS[@]}"
  fi

  printf '\nImages (%d):\n' "${#BUILD_IMAGES[@]}"
  if [[ ${#BUILD_IMAGES[@]} -eq 0 ]]; then
    printf '  <none>\n'
  else
    printf '  %s\n' "${BUILD_IMAGES[@]}"
  fi

  if [[ ${#PLAN_NOTES[@]} -gt 0 ]]; then
    printf '\nNotes:\n'
    printf '  - %s\n' "${PLAN_NOTES[@]}"
  fi
  printf '\n'
}

acquire_lock() {
  require_command flock
  mkdir -p "$(dirname "$LOCK_FILE")"
  exec 9>"$LOCK_FILE"
  flock -n 9 || die "another DAC release process holds $LOCK_FILE"
}

prepare_worktree() {
  [[ -n "$WORKTREE" ]] && return 0
  mkdir -p "$STATE_DIR/worktrees"
  WORKTREE="$STATE_DIR/worktrees/${TARGET_SHORT_SHA}-$$"
  git -C "$REPO_ROOT" worktree add --detach "$WORKTREE" "$TARGET_SHA" >/dev/null
  [[ -z "$(git -C "$WORKTREE" status --porcelain)" ]] \
    || die "temporary worktree is not clean: $WORKTREE"
}

prepare_release_dir() {
  RELEASE_DIR="$STATE_DIR/releases/$IMAGE_TAG"
  mkdir -p "$RELEASE_DIR/logs" "$RELEASE_DIR/metadata" "$RELEASE_DIR/deployment"
  chmod 700 "$STATE_DIR" "$STATE_DIR/releases" "$RELEASE_DIR" \
    "$RELEASE_DIR/logs" "$RELEASE_DIR/metadata" "$RELEASE_DIR/deployment" 2>/dev/null || true
}

verify_builder() {
  require_command docker
  docker info >/dev/null 2>&1 \
    || die "cannot access the Docker daemon; reconnect after joining the docker group and verify with 'docker info'"
  docker buildx inspect "$BUILDER" --bootstrap >/dev/null \
    || die "Buildx builder is unavailable: $BUILDER"
  local registry_host=${REGISTRY%%/*}
  curl -ksSf "https://$registry_host/v2/" >/dev/null \
    || die "registry is unreachable: https://$registry_host/v2/"
}

inspect_image() {
  local image=$1 output_file=$2
  docker manifest inspect --insecure --verbose "$image" >"$output_file"
  jq -e '
    [if type == "array" then .[] else . end
      | .Descriptor.platform?
      | select(.architecture == "amd64" and .os == "linux")]
    | length > 0
  ' "$output_file" >/dev/null \
    || die "image does not expose a linux/amd64 manifest: $image"
}

write_build_manifest() {
  local records=$RELEASE_DIR/image-records.tsv images_json
  images_json=$(jq -Rn '
    [inputs | split("\t") | {
      name: .[0], reference: .[1], digest: (.[2] // "")
    }]
  ' <"$records")

  jq -n \
    --arg schemaVersion "1" \
    --arg sourceLabel "$SOURCE_LABEL" \
    --arg revision "$TARGET_SHA" \
    --arg baseline "$BASELINE_SHA" \
    --arg imageTag "$IMAGE_TAG" \
    --arg registry "$REGISTRY" \
    --arg createdAt "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --argjson full "$FULL_BUILD" \
    --argjson noCache "$NO_CACHE" \
    --argjson images "$images_json" \
    '{
      schemaVersion: ($schemaVersion | tonumber),
      source: {label: $sourceLabel, revision: $revision, baseline: $baseline},
      imageTag: $imageTag,
      registry: $registry,
      build: {createdAt: $createdAt, full: $full, noCache: $noCache},
      images: $images
    }' >"$RELEASE_DIR/release.json"
}

build_images() {
  [[ ${#BUILD_IMAGES[@]} -gt 0 ]] || { log "no images need to be built"; return 0; }
  require_command jq
  require_command curl
  verify_builder
  prepare_worktree
  prepare_release_dir

  local created records image spec context dockerfile image_ref digest
  local -a cache_args=()
  created=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  records=$RELEASE_DIR/image-records.tsv
  : >"$records"
  [[ "$NO_CACHE" == true ]] && cache_args+=(--no-cache)

  for image in "${BUILD_IMAGES[@]:-}"; do
    [[ -n "$image" ]] || continue
    spec=$(image_spec "$image") || die "missing image spec: $image"
    IFS=$'\t' read -r context dockerfile <<<"$spec"
    [[ -f "$WORKTREE/$context/$dockerfile" ]] \
      || die "Dockerfile not found: $context/$dockerfile"
    image_ref="$REGISTRY/$image:$IMAGE_TAG"
    log "building $image_ref from $context/$dockerfile"

    docker buildx build \
      --builder "$BUILDER" \
      --platform linux/amd64 \
      --label org.opencontainers.image.source=https://github.com/DataTunerX/dac \
      --label "org.opencontainers.image.version=$SOURCE_LABEL" \
      --label "org.opencontainers.image.revision=$TARGET_SHA" \
      --label "org.opencontainers.image.created=$created" \
      --provenance=true \
      --sbom=true \
      --metadata-file "$RELEASE_DIR/metadata/$image.json" \
      --tag "$image_ref" \
      --file "$WORKTREE/$context/$dockerfile" \
      --push \
      "${cache_args[@]}" \
      "$WORKTREE/$context" \
      2>&1 | tee "$RELEASE_DIR/logs/$image.log"

    inspect_image "$image_ref" "$RELEASE_DIR/metadata/$image.inspect.txt"
    digest=$(jq -r '
      [if type == "array" then .[] else . end
        | select(.Descriptor.platform?.architecture == "amd64"
          and .Descriptor.platform?.os == "linux")
        | .Descriptor.digest][0] // ""
    ' "$RELEASE_DIR/metadata/$image.inspect.txt")
    printf '%s\t%s\t%s\n' "$image" "$image_ref" "${digest:-}" >>"$records"
  done

  write_build_manifest
  log "build completed; manifest: $RELEASE_DIR/release.json"
}

verify_deploy_images() {
  [[ ${#BUILD_IMAGES[@]} -gt 0 ]] || return 0
  require_command docker
  prepare_release_dir
  local image image_ref
  for image in "${BUILD_IMAGES[@]:-}"; do
    [[ -n "$image" ]] || continue
    image_ref="$REGISTRY/$image:$IMAGE_TAG"
    log "verifying $image_ref"
    inspect_image "$image_ref" "$RELEASE_DIR/metadata/$image.predeploy.inspect.txt"
  done
}

confirm_deploy() {
  [[ "$DRY_RUN" == true || "$ASSUME_YES" == true ]] && return 0
  [[ -t 0 ]] || die "deployment requires an interactive terminal or --yes"
  printf 'Deploy %s at %s to %s/%s? Type deploy to continue: ' \
    "$SOURCE_LABEL" "$TARGET_SHORT_SHA" "$KUBE_CONTEXT" "$NAMESPACE"
  local answer
  read -r answer
  [[ "$answer" == deploy ]] || die "deployment cancelled"
}

helm_reuse_flag() {
  if helm upgrade --help 2>/dev/null | grep -q -- '--reset-then-reuse-values'; then
    printf '%s\n' --reset-then-reuse-values
  else
    printf '%s\n' --reuse-values
  fi
}

rollout_if_present() {
  local namespace=$1 deployment=$2
  if kubectl --context "$KUBE_CONTEXT" -n "$namespace" get deployment "$deployment" >/dev/null 2>&1; then
    kubectl --context "$KUBE_CONTEXT" -n "$namespace" rollout status \
      "deployment/$deployment" --timeout="$HELM_TIMEOUT"
  fi
}

timeout_seconds() {
  case "$1" in
    *s) printf '%s\n' "${1%s}" ;;
    *m) printf '%s\n' "$(( ${1%m} * 60 ))" ;;
    *h) printf '%s\n' "$(( ${1%h} * 3600 ))" ;;
    *) die "unsupported timeout format '$1'; use an integer followed by s, m, or h" ;;
  esac
}

dynamic_agent_deployments() {
  local image=$1 expected
  expected=${REGISTRY}/${image}:${IMAGE_TAG}
  kubectl --context "$KUBE_CONTEXT" get deployments -A -o json \
    | jq -r --arg imageName "$image" --arg expected "$expected" '
      def image_name:
        split("@")[0] | split("/")[-1] | split(":")[0];
      .items[]
      | select(any(.metadata.ownerReferences[]?; .kind == "DataAgentContainer"))
      | select(any(.spec.template.spec.containers[]?; (.image | image_name) == $imageName))
      | [.metadata.namespace, .metadata.name,
          (any(.spec.template.spec.containers[]?; .image == $expected) | tostring)]
      | @tsv'
}

wait_for_dynamic_image() {
  local image=$1 entries namespace name updated
  local deadline=$(( $(date +%s) + $(timeout_seconds "$HELM_TIMEOUT") ))

  while true; do
    entries=$(dynamic_agent_deployments "$image")
    if [[ -z "$entries" ]] || ! grep -q $'\tfalse$' <<<"$entries"; then
      break
    fi
    (( $(date +%s) < deadline )) \
      || die "timed out waiting for operator-managed $image Deployments to reference $IMAGE_TAG"
    sleep 5
  done

  while IFS=$'\t' read -r namespace name updated; do
    [[ -n "$namespace" && -n "$name" ]] || continue
    rollout_if_present "$namespace" "$name"
  done <<<"$entries"
}

record_successful_deployment() {
  local helm_revision images_csv deployed_at manifest_file tmp
  helm_revision=$(helm --kube-context "$KUBE_CONTEXT" history "$HELM_RELEASE" \
    -n "$NAMESPACE" -o json | jq -r '.[-1].revision')
  images_csv=$(IFS=,; printf '%s' "${BUILD_IMAGES[*]:-}")
  deployed_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)

  kubectl --context "$KUBE_CONTEXT" -n "$NAMESPACE" create configmap \
    "$RELEASE_STATE_CONFIGMAP" \
    --from-literal="revision=$TARGET_SHA" \
    --from-literal="source-label=$SOURCE_LABEL" \
    --from-literal="image-tag=$IMAGE_TAG" \
    --from-literal="images=$images_csv" \
    --from-literal="helm-revision=$helm_revision" \
    --from-literal="deployed-at=$deployed_at" \
    --dry-run=client -o yaml \
    | kubectl --context "$KUBE_CONTEXT" apply -f - >/dev/null

  manifest_file=$RELEASE_DIR/release.json
  if [[ ! -f "$manifest_file" ]]; then
    jq -n \
      --arg revision "$TARGET_SHA" \
      --arg sourceLabel "$SOURCE_LABEL" \
      --arg imageTag "$IMAGE_TAG" \
      --arg registry "$REGISTRY" \
      '{source:{revision:$revision,label:$sourceLabel},imageTag:$imageTag,registry:$registry,images:[]}' \
      >"$manifest_file"
  fi
  tmp=$(mktemp)
  jq \
    --arg cluster "$KUBE_CONTEXT" \
    --arg namespace "$NAMESPACE" \
    --arg release "$HELM_RELEASE" \
    --arg revision "$helm_revision" \
    --arg deployedAt "$deployed_at" \
    '.deployment = {
      cluster:$cluster, namespace:$namespace, release:$release,
      helmRevision:$revision, deployedAt:$deployedAt
    }' "$manifest_file" >"$tmp"
  mv "$tmp" "$manifest_file"
  log "deployment recorded at Helm revision $helm_revision"
}

deploy_release() {
  require_command kubectl
  require_command helm
  require_command jq
  cluster_available || die "cluster context is unavailable: $KUBE_CONTEXT"
  prepare_worktree
  prepare_release_dir
  verify_deploy_images

  if [[ "$CRD_CHANGED" == true && "$APPLY_CRDS" != true ]]; then
    die "CRDs changed; rerun with --apply-crds after reviewing installer/dac/crds"
  fi

  local chart=$WORKTREE/installer/dac
  local current_values=$RELEASE_DIR/deployment/values-before.yaml
  local manifest_before=$RELEASE_DIR/deployment/manifest-before.yaml
  local rendered=$RELEASE_DIR/deployment/rendered.yaml
  local reuse_flag
  local image deployment key
  local -a set_args=(--set-string "global.imageRegistry=$REGISTRY")

  helm --kube-context "$KUBE_CONTEXT" get values "$HELM_RELEASE" \
    -n "$NAMESPACE" -a -o yaml >"$current_values"
  helm --kube-context "$KUBE_CONTEXT" get manifest "$HELM_RELEASE" \
    -n "$NAMESPACE" >"$manifest_before"
  chmod 600 "$current_values" "$manifest_before"

  for image in "${BUILD_IMAGES[@]:-}"; do
    [[ -n "$image" ]] || continue
    while IFS= read -r key; do
      [[ -n "$key" ]] && set_args+=(--set-string "$key=$IMAGE_TAG")
    done < <(helm_keys_for_image "$image")
  done

  helm lint "$chart" -f "$current_values" "${set_args[@]}"
  helm template "$HELM_RELEASE" "$chart" \
    --namespace "$NAMESPACE" \
    -f "$current_values" \
    "${set_args[@]}" >"$rendered"
  log "rendered manifest: $rendered"

  if [[ "$DRY_RUN" == true ]]; then
    log "dry run complete; no cluster changes were made"
    return 0
  fi

  confirm_deploy

  if [[ "$CRD_CHANGED" == true ]]; then
    log "applying reviewed CRD changes"
    kubectl --context "$KUBE_CONTEXT" apply --server-side -f "$chart/crds"
  fi

  reuse_flag=$(helm_reuse_flag)
  log "upgrading Helm release $NAMESPACE/$HELM_RELEASE"
  helm --kube-context "$KUBE_CONTEXT" upgrade "$HELM_RELEASE" "$chart" \
    -n "$NAMESPACE" \
    "$reuse_flag" \
    "${set_args[@]}" \
    --rollback-on-failure \
    --wait \
    --timeout "$HELM_TIMEOUT"

  for image in "${BUILD_IMAGES[@]:-}"; do
    [[ -n "$image" ]] || continue
    while IFS= read -r deployment; do
      [[ -n "$deployment" ]] && rollout_if_present "$NAMESPACE" "$deployment"
    done < <(static_deployments_for_image "$image")
  done
  for image in "${BUILD_IMAGES[@]:-}"; do
    [[ -n "$image" ]] || continue
    is_dynamic_agent_image "$image" && wait_for_dynamic_image "$image"
  done

  record_successful_deployment
}

show_status() {
  require_command kubectl
  require_command helm
  require_command jq
  printf 'Release state:\n'
  kubectl --context "$KUBE_CONTEXT" -n "$NAMESPACE" get configmap \
    "$RELEASE_STATE_CONFIGMAP" -o json 2>/dev/null \
    | jq -r '.data // {status:"not recorded"}' || printf 'not recorded\n'
  printf '\nHelm status:\n'
  helm --kube-context "$KUBE_CONTEXT" status "$HELM_RELEASE" -n "$NAMESPACE"
  printf '\nNon-running DAC/default pods:\n'
  kubectl --context "$KUBE_CONTEXT" get pods -A -o json \
    | jq -r '.items[]
      | select((.metadata.namespace == "dac" or .metadata.namespace == "default")
        and .status.phase != "Running" and .status.phase != "Succeeded")
      | [.metadata.namespace,.metadata.name,.status.phase] | @tsv'
}

show_history() {
  require_command helm
  helm --kube-context "$KUBE_CONTEXT" history "$HELM_RELEASE" -n "$NAMESPACE"
}

rollback_release() {
  [[ "$HELM_REVISION" =~ ^[0-9]+$ ]] || die "rollback requires --helm-revision NUMBER"
  require_command kubectl
  require_command helm
  acquire_lock
  if [[ "$ASSUME_YES" != true ]]; then
    [[ -t 0 ]] || die "rollback requires an interactive terminal or --yes"
    printf 'Rollback %s/%s on %s to revision %s? Type rollback to continue: ' \
      "$NAMESPACE" "$HELM_RELEASE" "$KUBE_CONTEXT" "$HELM_REVISION"
    local answer
    read -r answer
    [[ "$answer" == rollback ]] || die "rollback cancelled"
  fi
  helm --kube-context "$KUBE_CONTEXT" rollback "$HELM_RELEASE" "$HELM_REVISION" \
    -n "$NAMESPACE" --wait --cleanup-on-fail --timeout "$HELM_TIMEOUT"
  kubectl --context "$KUBE_CONTEXT" -n "$NAMESPACE" delete configmap \
    "$RELEASE_STATE_CONFIGMAP" --ignore-not-found
  warn "release state was cleared; the next automatic plan will use a full build unless --baseline is supplied"
}

main() {
  parse_args "$@"

  if [[ ${BASH_VERSINFO[0]} -lt 3 ]]; then
    die "Bash 3 or later is required"
  fi

  mkdir -p "$STATE_DIR"
  chmod 700 "$STATE_DIR" 2>/dev/null || true

  case "$ACTION" in
    status) show_status; return ;;
    history) show_history; return ;;
    rollback) rollback_release; return ;;
  esac

  validate_source_args
  resolve_source
  resolve_baseline
  plan_release
  print_plan

  case "$ACTION" in
    plan) return ;;
    build)
      acquire_lock
      build_images
      ;;
    deploy)
      acquire_lock
      if [[ ${#BUILD_IMAGES[@]} -eq 0 && "$CHART_CHANGED" != true ]]; then
        log "target revision requires no deployment"
        return
      fi
      deploy_release
      ;;
    all)
      acquire_lock
      if [[ ${#BUILD_IMAGES[@]} -eq 0 && "$CHART_CHANGED" != true ]]; then
        log "target revision requires no build or deployment"
        return
      fi
      build_images
      deploy_release
      ;;
  esac
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
