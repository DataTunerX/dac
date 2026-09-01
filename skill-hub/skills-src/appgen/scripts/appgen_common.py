"""Shared helpers for AppGen: talk to skill-hub and the Kubernetes API.

Both endpoints are reached from inside the agent pod:
  * skill-hub over its in-cluster Service
  * the Kubernetes API with the pod's mounted ServiceAccount token
No credentials are baked into this skill.
"""
from __future__ import annotations

import json
import os
import re
import ssl
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

SKILL_HUB_URL = os.getenv("SKILL_HUB_URL", "http://skill-hub.dac.svc.cluster.local:8000").rstrip("/")
SKILL_NAMESPACE = os.getenv("APPGEN_SKILL_NAMESPACE", "default")
AGENT_NAMESPACE = os.getenv("APPGEN_AGENT_NAMESPACE", "default")

_SA_DIR = Path("/var/run/secrets/kubernetes.io/serviceaccount")
_NAME_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")


class AppGenError(RuntimeError):
    """Raised with a message meant to be shown to the user verbatim."""


def validate_name(name: str, what: str = "name") -> str:
    """Names become Kubernetes object names and skill-hub slugs, so both rule
    sets apply: lowercase alphanumeric and dashes, starting and ending
    alphanumeric."""
    value = (name or "").strip()
    if not value:
        raise AppGenError(f"{what} is required")
    if len(value) > 50:
        raise AppGenError(f"{what} must be 50 characters or fewer, got {len(value)}")
    if not _NAME_RE.match(value):
        raise AppGenError(
            f"{what} must be lowercase letters, digits and dashes, starting and "
            f"ending with a letter or digit; got {value!r}"
        )
    return value


def http_json(url: str, *, method: str = "GET", body: bytes | None = None,
              headers: dict[str, str] | None = None, timeout: int = 60) -> Any:
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    ctx = None
    if url.startswith("https://"):
        ca = _SA_DIR / "ca.crt"
        ctx = ssl.create_default_context(cafile=str(ca)) if ca.is_file() else ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500]
        raise AppGenError(f"{method} {url} failed: HTTP {exc.code} {detail}") from exc
    except urllib.error.URLError as exc:
        raise AppGenError(f"{method} {url} unreachable: {exc.reason}") from exc
    return json.loads(raw) if raw.strip() else {}


def k8s_request(path: str, *, method: str = "GET", payload: dict | None = None) -> Any:
    """Call the Kubernetes API with the pod's ServiceAccount credentials."""
    token_path = _SA_DIR / "token"
    if not token_path.is_file():
        raise AppGenError(
            "no Kubernetes ServiceAccount token in this pod, so the agent cannot "
            "be created from here. Publish the skill, then create the agent from "
            "the DAC UI or with kubectl."
        )
    token = token_path.read_text().strip()
    host = os.getenv("KUBERNETES_SERVICE_HOST", "kubernetes.default.svc")
    port = os.getenv("KUBERNETES_SERVICE_PORT", "443")
    url = f"https://{host}:{port}{path}"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    body = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    return http_json(url, method=method, body=body, headers=headers)


def skill_exists(name: str) -> bool:
    try:
        listing = http_json(f"{SKILL_HUB_URL}/namespaces/{SKILL_NAMESPACE}/skills")
    except AppGenError:
        return False
    items = listing if isinstance(listing, list) else listing.get("skills") or listing.get("items") or []
    return any((s or {}).get("name") == name for s in items)
