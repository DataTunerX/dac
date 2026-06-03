"""
Lightweight Kubernetes client for patching DataDescriptor annotations.

Used by the Celery worker to notify execution-engine that a semantic group's
agent_card has been updated, triggering an immediate DD reconcile so the
blue-green DAC replacement logic can run without waiting for a periodic poll.
"""

import json
import logging
import os
from datetime import datetime, timezone

from kubernetes import client, config
from kubernetes.client.rest import ApiException

logger = logging.getLogger("semantic_grouper.client.k8s")

_k8s_initialised = False


def _ensure_k8s_config():
    """Load kubeconfig once (in-cluster first, fallback to local kubeconfig)."""
    global _k8s_initialised
    if _k8s_initialised:
        return
    try:
        config.load_incluster_config()
        logger.info("Loaded in-cluster Kubernetes config")
    except config.ConfigException:
        try:
            config.load_kube_config()
            logger.info("Loaded local kubeconfig")
        except config.ConfigException:
            logger.warning("No Kubernetes config available; DD notification will be skipped")
            raise
    _k8s_initialised = True


# CRD coordinates
_DD_GROUP = os.getenv("DD_CRD_GROUP", "dac.dac.io")
_DD_VERSION = os.getenv("DD_CRD_VERSION", "v1alpha1")
_DD_PLURAL = "datadescriptors"
_ANNOTATION_KEY = "dac.dac.io/group-updated-at"
_ANNOTATION_SEMANTIC_GROUP_IDS = "dac.dac.io/semantic-group-ids"


def notify_dd_reconcile(dd_namespace: str, dd_name: str) -> None:
    """
    Patch a DataDescriptor's annotation with the current UTC timestamp.

    This triggers the execution-engine DD controller's watch, which will
    reconcile the DD and run ensureAutoNormalDAC (blue-green check).

    The call is best-effort: callers should catch exceptions and log a
    warning rather than failing the main grouping task.
    """
    _ensure_k8s_config()

    api = client.CustomObjectsApi()
    body = {
        "metadata": {
            "annotations": {
                _ANNOTATION_KEY: datetime.now(timezone.utc).isoformat(),
            }
        }
    }

    api.patch_namespaced_custom_object(
        group=_DD_GROUP,
        version=_DD_VERSION,
        namespace=dd_namespace,
        plural=_DD_PLURAL,
        name=dd_name,
        body=body,
    )
    logger.info(
        "Patched DD %s/%s annotation '%s' to trigger reconcile",
        dd_namespace, dd_name, _ANNOTATION_KEY,
    )


def get_semantic_group_ids_from_dd(dd_namespace: str, dd_name: str) -> list[str]:
    """
    Read dac.dac.io/semantic-group-ids from a DataDescriptor CR.

    Used during DD delete when dd_group_relation rows are already gone but the
    annotation still records which groups the DD belonged to.
    """
    _ensure_k8s_config()
    api = client.CustomObjectsApi()
    try:
        obj = api.get_namespaced_custom_object(
            group=_DD_GROUP,
            version=_DD_VERSION,
            namespace=dd_namespace,
            plural=_DD_PLURAL,
            name=dd_name,
        )
    except ApiException as e:
        if e.status == 404:
            logger.info(
                "DD %s/%s not found while reading semantic-group-ids",
                dd_namespace,
                dd_name,
            )
            return []
        raise

    annotations = (obj.get("metadata") or {}).get("annotations") or {}
    raw = annotations.get(_ANNOTATION_SEMANTIC_GROUP_IDS, "")
    if not raw:
        return []

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning(
            "Invalid %s on DD %s/%s: %r",
            _ANNOTATION_SEMANTIC_GROUP_IDS,
            dd_namespace,
            dd_name,
            raw,
        )
        return []

    if not isinstance(parsed, list):
        logger.warning(
            "Expected JSON array for %s on DD %s/%s, got %s",
            _ANNOTATION_SEMANTIC_GROUP_IDS,
            dd_namespace,
            dd_name,
            type(parsed).__name__,
        )
        return []

    ids = sorted({str(g).strip() for g in parsed if g and str(g).strip()})
    logger.info(
        "Read %d semantic group id(s) from DD %s/%s annotation",
        len(ids),
        dd_namespace,
        dd_name,
    )
    return ids


def patch_semantic_group_ids(
    dd_namespace: str, dd_name: str, group_ids: list[str]
) -> None:
    """
    Record semantic group membership on a DD when it joins a group.

    The annotation is append-only and kept until the DD delete job completes,
    so normal DAC sync after delete does not depend on live dd_group_relation
    rows or on notifying other group members.
    """
    ids = sorted({gid.strip() for gid in group_ids if gid and gid.strip()})
    if not ids:
        return

    _ensure_k8s_config()
    api = client.CustomObjectsApi()

    merged: set[str] = set()
    try:
        existing = api.get_namespaced_custom_object(
            group=_DD_GROUP,
            version=_DD_VERSION,
            namespace=dd_namespace,
            plural=_DD_PLURAL,
            name=dd_name,
        )
        annotations = (existing.get("metadata") or {}).get("annotations") or {}
        raw = annotations.get(_ANNOTATION_SEMANTIC_GROUP_IDS, "")
        if raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    merged.update(str(g).strip() for g in parsed if g)
            except json.JSONDecodeError:
                logger.warning(
                    "Invalid %s on DD %s/%s, replacing",
                    _ANNOTATION_SEMANTIC_GROUP_IDS,
                    dd_namespace,
                    dd_name,
                )
    except ApiException as e:
        if e.status != 404:
            raise

    merged.update(ids)
    body = {
        "metadata": {
            "annotations": {
                _ANNOTATION_SEMANTIC_GROUP_IDS: json.dumps(sorted(merged)),
            }
        }
    }

    api.patch_namespaced_custom_object(
        group=_DD_GROUP,
        version=_DD_VERSION,
        namespace=dd_namespace,
        plural=_DD_PLURAL,
        name=dd_name,
        body=body,
    )
    logger.info(
        "Patched DD %s/%s annotation '%s' with %d group id(s)",
        dd_namespace,
        dd_name,
        _ANNOTATION_SEMANTIC_GROUP_IDS,
        len(merged),
    )
