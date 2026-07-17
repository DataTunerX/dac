#!/usr/bin/env bash
# 下载 Online Boutique (Google microservices-demo) K8s manifest 到 k8s/apps/
# 会去掉 LoadBalancer、改 namespace 为 dac-sandbox，并去掉 loadgenerator。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/k8s/apps/online-boutique.yaml"
SRC="$ROOT/scripts/.vendor-cache/online-boutique-kubernetes-manifests.yaml"

mkdir -p "$(dirname "$OUT")" "$ROOT/scripts/.vendor-cache"

log() { printf '\033[36m[vendor-apps] %s\033[0m\n' "$*"; }

if [[ -s "$SRC" ]]; then
  log "skip (cached): online-boutique-kubernetes-manifests.yaml"
else
  log "fetch: Google microservices-demo kubernetes-manifests.yaml"
  curl -fsSL --retry 3 --retry-delay 2 \
    -o "$SRC.tmp" \
    "https://raw.githubusercontent.com/GoogleCloudPlatform/microservices-demo/main/release/kubernetes-manifests.yaml"
  mv "$SRC.tmp" "$SRC"
fi

REGISTRY="${REGISTRY:-release.daocloud.io/dac}"
BOUTIQUE_TAG="${BOUTIQUE_TAG:-v0.10.5}"
export REGISTRY BOUTIQUE_TAG

python3 - <<'PY' "$SRC" "$OUT"
import os, re, sys
src, out = sys.argv[1], sys.argv[2]
registry = os.environ["REGISTRY"]
boutique_tag = os.environ["BOUTIQUE_TAG"]
text = open(src, encoding="utf-8").read()

def rewrite_image(img: str) -> str:
    img = img.strip()
    m = re.match(
        r"us-central1-docker\.pkg\.dev/google-samples/microservices-demo/([^:]+):(.+)",
        img,
    )
    if m:
        svc, _tag = m.group(1), m.group(2)
        return f"{registry}/boutique-{svc}:{boutique_tag}"
    if img in ("redis:alpine", "docker.io/library/redis:alpine"):
        return f"{registry}/redis:alpine"
    return img

chunks = re.split(r"\n---\n", text)
kept = []
for chunk in chunks:
    if not chunk.strip() or chunk.strip().startswith("#"):
        continue
    if "name: loadgenerator" in chunk:
        continue
    if "name: frontend-external" in chunk:
        continue
    if chunk.lstrip().startswith("kind: Namespace"):
        continue
    if "metadata:" in chunk and "namespace:" not in chunk:
        chunk = re.sub(
            r"(?m)^(metadata:\s*)$",
            r"\1\n  namespace: dac-sandbox",
            chunk,
            count=1,
        )
    chunk = re.sub(
        r"(?m)^(\s*image:\s*)(.+)$",
        lambda m: m.group(1) + rewrite_image(m.group(2)),
        chunk,
    )
    kept.append(chunk.strip())

body = "\n---\n".join(kept)
header = f"""# Online Boutique — vendor 生成，镜像已改写为私有 registry
# 上游: https://github.com/GoogleCloudPlatform/microservices-demo
# 重新生成: REGISTRY={registry} make vendor-apps
"""
open(out, "w", encoding="utf-8").write(header + body + "\n")
print(f"wrote: {out} (registry={registry})")
PY

log "DONE"
