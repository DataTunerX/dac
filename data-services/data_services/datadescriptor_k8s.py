"""Kubernetes access for DataDescriptor CRs (dd-sync-observer path via HTTP)."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

from fastapi import HTTPException

logger = logging.getLogger(__name__)

DD_API_GROUP = "dac.dac.io"
DD_API_VERSION = "v1alpha1"
DD_PLURAL = "datadescriptors"

_MISSING_K8S_DETAIL = (
    "Kubernetes Python client is not installed in this data-services environment. "
    "Ensure dependency 'kubernetes' is in pyproject.toml, run 'uv lock', and rebuild the image."
)


def descriptor_header_value(namespace: str, name: str) -> str:
    """Match execution-engine DATA_DESCRIPTOR: ReplaceAll(ns+'_'+name, '-', '_')."""
    return f"{namespace}_{name}".replace("-", "_")


def validate_data_descriptor_header(namespace: str, name: str, header_val: Optional[str]) -> None:
    if not header_val or not str(header_val).strip():
        raise HTTPException(status_code=403, detail="Data-Descriptor header is required")
    expected = descriptor_header_value(namespace, name)
    if str(header_val).strip() != expected:
        raise HTTPException(
            status_code=403,
            detail="Data-Descriptor header does not match requested DataDescriptor",
        )


def _custom_objects_api_and_exception() -> Tuple[Any, Any]:
    try:
        from kubernetes import client, config
        from kubernetes.client import ApiException
    except ImportError as e:
        logger.error("kubernetes import failed: %s", e)
        raise HTTPException(status_code=503, detail=_MISSING_K8S_DETAIL) from e
    try:
        config.load_incluster_config()
    except Exception:
        config.load_kube_config()
    return client.CustomObjectsApi(), ApiException


def get_datadescriptor(namespace: str, name: str) -> Dict[str, Any]:
    api, ApiException = _custom_objects_api_and_exception()
    try:
        return api.get_namespaced_custom_object(
            group=DD_API_GROUP,
            version=DD_API_VERSION,
            namespace=namespace,
            plural=DD_PLURAL,
            name=name,
        )
    except ApiException as e:
        if e.status == 404:
            raise HTTPException(status_code=404, detail="DataDescriptor not found") from e
        if e.status == 403:
            logger.warning("K8s get DataDescriptor forbidden (check data-services RBAC): %s", e)
            raise HTTPException(
                status_code=403,
                detail=(
                    "Kubernetes forbidden: this data-services identity needs get on "
                    "datadescriptors.dac.dac.io in the target namespace. "
                    "Apply a ClusterRoleBinding (see data-services config rbac example)."
                ),
            ) from e
        logger.warning("K8s get DataDescriptor failed: %s", e)
        raise HTTPException(status_code=502, detail=f"Kubernetes API error: {e.reason}") from e


def patch_datadescriptor_annotation(
    namespace: str, name: str, annotation_key: str, value: str
) -> None:
    api, ApiException = _custom_objects_api_and_exception()
    body = {"metadata": {"annotations": {annotation_key: value}}}
    try:
        api.patch_namespaced_custom_object(
            group=DD_API_GROUP,
            version=DD_API_VERSION,
            namespace=namespace,
            plural=DD_PLURAL,
            name=name,
            body=body,
        )
    except ApiException as e:
        if e.status == 404:
            raise HTTPException(status_code=404, detail="DataDescriptor not found") from e
        if e.status == 403:
            logger.warning("K8s patch DataDescriptor forbidden (check data-services RBAC): %s", e)
            raise HTTPException(
                status_code=403,
                detail=(
                    "Kubernetes forbidden: this data-services identity needs patch on "
                    "datadescriptors.dac.dac.io in the target namespace."
                ),
            ) from e
        logger.warning("K8s patch DataDescriptor failed: %s", e)
        raise HTTPException(status_code=502, detail=f"Kubernetes API error: {e.reason}") from e
