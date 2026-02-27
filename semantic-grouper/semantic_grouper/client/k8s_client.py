"""
Lightweight Kubernetes client for patching DataDescriptor annotations.

Used by the Celery worker to notify execution-engine that a semantic group's
agent_card has been updated, triggering an immediate DD reconcile so the
blue-green DAC replacement logic can run without waiting for a periodic poll.
"""

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
