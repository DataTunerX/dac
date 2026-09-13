#!/bin/sh
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
dist_dir=$(mktemp -d)
trap 'rm -rf "$dist_dir"' EXIT

uv build "$repo_root/agent-contracts" --wheel --out-dir "$dist_dir"
wheel="$dist_dir/agent_contracts-0.1.0-py3-none-any.whl"

for component in agent-registry skill-hub skill-agent routing-agent orchestrator-agent; do
    mkdir -p "$repo_root/$component/sdks"
    cp "$wheel" "$repo_root/$component/sdks/"
done

shasum -a 256 "$repo_root"/*/sdks/agent_contracts-0.1.0-py3-none-any.whl
