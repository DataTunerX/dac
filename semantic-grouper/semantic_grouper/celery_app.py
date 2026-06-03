import os
import json
import logging
import time
from typing import Dict, Any, List, Optional
from urllib.parse import quote_plus

from celery import Celery

from semantic_grouper.distributed_lock import get_semantic_group_lock
from semantic_grouper.client.vector_client import VectorClient
from semantic_grouper.client.semantic_group_client import SemanticGroupClient
from semantic_grouper.client.semantic_domain_client import SemanticDomainClient
from semantic_grouper.client.k8s_client import (
    get_semantic_group_ids_from_dd,
    notify_dd_reconcile,
    patch_semantic_group_ids,
)
from semantic_grouper.semantic_group import SemanticGrouper

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("semantic_grouper")

# ---------------------------------------------------------------------------
# Redis / Celery configuration
# ---------------------------------------------------------------------------
redis_host = os.getenv("REDIS_HOST", "localhost")
redis_port = os.getenv("REDIS_PORT", "6379")
redis_db_broker = os.getenv("REDIS_DB_BROKER", "8")
redis_db_backend = os.getenv("REDIS_DB_BACKEND", "9")
redis_password = os.getenv("REDIS_PASSWORD")

password_part = f":{quote_plus(redis_password)}@" if redis_password else ""
redis_db_beat = os.getenv("REDIS_DB_BEAT", "10")

broker_url = f"redis://{password_part}{redis_host}:{redis_port}/{redis_db_broker}"
backend_url = f"redis://{password_part}{redis_host}:{redis_port}/{redis_db_backend}"
redbeat_url = f"redis://{password_part}{redis_host}:{redis_port}/{redis_db_beat}"

celery = Celery(
    "semantic_grouper",
    broker=broker_url,
    backend=backend_url,
)

REDBEAT_KEY_PREFIX = os.getenv("REDBEAT_KEY_PREFIX", "semantic_grouper:redbeat")
REDBEAT_LOCK_KEY = os.getenv("REDBEAT_LOCK_KEY", f"{REDBEAT_KEY_PREFIX}:lock")
REDBEAT_LOCK_TIMEOUT_SECONDS = int(os.getenv("REDBEAT_LOCK_TIMEOUT_SECONDS", "120"))

beat_schedule: Dict[str, Any] = {}

celery.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_default_queue="semantic_group",
    task_routes={
        "semantic_grouper.group": {"queue": "semantic_group"},
    },
    task_track_started=True,
    result_expires=3600,
    beat_schedule=beat_schedule,
    redbeat_redis_url=redbeat_url,
    redbeat_key_prefix=REDBEAT_KEY_PREFIX,
    redbeat_lock_key=REDBEAT_LOCK_KEY,
    redbeat_lock_timeout=REDBEAT_LOCK_TIMEOUT_SECONDS,
)

# ---------------------------------------------------------------------------
# Service clients (shared across tasks in this worker process)
# ---------------------------------------------------------------------------
data_services_url = os.getenv("DATA_SERVICES", "http://localhost:8000")

vector_client = VectorClient(base_url=data_services_url, timeout=600)
vector_client.initialize()

semantic_group_client = SemanticGroupClient(base_url=data_services_url, timeout=600)
semantic_domain_client = SemanticDomainClient(base_url=data_services_url, timeout=600)

semantic_grouper = SemanticGrouper(
    vector_client=vector_client,
    semantic_group_client=semantic_group_client,
    semantic_domain_client=semantic_domain_client,
)


# ---------------------------------------------------------------------------
# Helper functions (ported from data-sinkers job.py)
# ---------------------------------------------------------------------------
def _parse_domain_data_first(semantic_domain: dict, dd_namespace: str, dd_name: str) -> dict:
    """Parse semantic_domain API response and return the first domain_data dict."""
    if not isinstance(semantic_domain, dict):
        raise ValueError(f"semantic_domain must be dict, got {type(semantic_domain)}")

    if "data" in semantic_domain:
        data_list = semantic_domain.get("data", [])
        if isinstance(data_list, list):
            if len(data_list) == 0:
                raise ValueError(f"未找到对应的语义域数据: {dd_namespace}/{dd_name}")
            domain_data = data_list[0]
        else:
            domain_data = data_list
    else:
        domain_data = semantic_domain

    if not isinstance(domain_data, dict):
        raise ValueError(f"domain_data must be dict, got {type(domain_data)}")
    return domain_data


def _parse_domain_data_all(semantic_domain: dict, dd_namespace: str, dd_name: str) -> list:
    """Parse semantic_domain API response and return ALL domain_data dicts."""
    if not isinstance(semantic_domain, dict):
        raise ValueError(f"semantic_domain must be dict, got {type(semantic_domain)}")

    if "data" in semantic_domain:
        data_list = semantic_domain.get("data", [])
        if isinstance(data_list, list):
            if len(data_list) == 0:
                raise ValueError(f"未找到对应的语义域数据: {dd_namespace}/{dd_name}")
            return data_list
        else:
            return [data_list] if isinstance(data_list, dict) else []
    else:
        return [semantic_domain] if isinstance(semantic_domain, dict) else []


def incremental_semantic_group(descriptor: dict) -> Dict[str, Any]:
    """对语义域进行增量分组"""
    dd_namespace = descriptor.get("namespace")
    dd_name = descriptor.get("name")

    semantic_domain = semantic_domain_client.search_semantic_domains_by_dd(
        dd_namespace=dd_namespace, dd_name=dd_name
    )
    if semantic_domain is None:
        raise ValueError(f"未找到对应的语义域数据: {dd_namespace}/{dd_name}")

    domain_data = _parse_domain_data_first(semantic_domain, dd_namespace, dd_name)

    domain = {
        "semantic_domain_id": domain_data.get("semantic_domain_id", ""),
        "semantic_domain": domain_data.get("semantic_domain", ""),
        "agent_card": domain_data.get("agent_card", ""),
        "dd_name": domain_data.get("dd_name", dd_name or ""),
        "dd_namespace": domain_data.get("dd_namespace", dd_namespace or ""),
    }

    result = semantic_grouper.incremental_semantic_group_analyse(domain)
    logger.info("语义域分组完成: %s", result)
    return result


def _persist_group_membership_on_dd(
    dd_namespace: str, dd_name: str, result: Dict[str, Any]
) -> None:
    """Write semantic-group-ids on the DD when it joins or creates a group."""
    if not isinstance(result, dict) or result.get("status") != "success":
        return
    group_id = result.get("group_id")
    if not group_id:
        return
    try:
        patch_semantic_group_ids(dd_namespace, dd_name, [group_id])
    except Exception as e:
        logger.warning(
            "Failed to persist semantic-group-ids on DD %s/%s (non-fatal): %s",
            dd_namespace,
            dd_name,
            e,
        )


_NO_RELATION_MESSAGE = "语义域没有关联的语义组"


def _reconcile_groups_from_dd_annotation(
    dd_namespace: str,
    dd_name: str,
    sd_id: str,
    reconciled_group_ids: set,
) -> Dict[str, Any]:
    """
    When dd_group_relation is already gone, read group ids from the deleting DD's
    K8s annotation and reconcile group metadata via data-services.
    """
    logger.info(
        "annotation fallback: sd=%s dd=%s/%s has no live relation, reading semantic-group-ids",
        sd_id,
        dd_namespace,
        dd_name,
    )
    try:
        group_ids = get_semantic_group_ids_from_dd(dd_namespace, dd_name)
    except Exception as e:
        logger.warning(
            "annotation fallback: failed to read semantic-group-ids from DD %s/%s: %s",
            dd_namespace,
            dd_name,
            e,
        )
        return {
            "status": "success",
            "action": "REMOVED",
            "message": _NO_RELATION_MESSAGE,
            "remaining_member_count": 0,
            "semantic_domain_id": sd_id,
        }

    if not group_ids:
        logger.warning(
            "annotation fallback: DD %s/%s has no semantic-group-ids; "
            "group metadata will not be reconciled",
            dd_namespace,
            dd_name,
        )
        return {
            "status": "success",
            "action": "REMOVED",
            "message": _NO_RELATION_MESSAGE,
            "remaining_member_count": 0,
            "semantic_domain_id": sd_id,
        }

    last_result: Dict[str, Any] = {
        "status": "success",
        "action": "REMOVED",
        "message": _NO_RELATION_MESSAGE,
        "semantic_domain_id": sd_id,
    }
    for group_id in group_ids:
        if group_id in reconciled_group_ids:
            logger.info(
                "annotation fallback: group %s already reconciled for dd=%s/%s, skipping",
                group_id,
                dd_namespace,
                dd_name,
            )
            continue
        logger.info(
            "annotation fallback: reconciling group %s via data-services (sd=%s, dd=%s/%s)",
            group_id,
            sd_id,
            dd_namespace,
            dd_name,
        )
        recon = semantic_grouper.reconcile_group_metadata(group_id)
        reconciled_group_ids.add(group_id)
        last_result = recon
        if isinstance(recon, dict) and recon.get("status") == "error":
            raise ValueError(recon.get("message", f"annotation fallback reconcile 失败: {group_id}"))

    return last_result


def decremental_semantic_group(descriptor: dict) -> Dict[str, Any]:
    """
    删除 DD 对应的所有语义域与语义组的关联。
    一个 DD 可能有多条 semantic_domain 记录，必须对全部执行 decremental。
    """
    dd_namespace = descriptor.get("namespace")
    dd_name = descriptor.get("name")

    semantic_domain = semantic_domain_client.search_semantic_domains_by_dd(
        dd_namespace=dd_namespace, dd_name=dd_name
    )
    if semantic_domain is None:
        raise ValueError(f"未找到对应的语义域数据: {dd_namespace}/{dd_name}")

    domain_list = _parse_domain_data_all(semantic_domain, dd_namespace, dd_name)

    last_result = None
    reconciled_group_ids: set = set()
    for domain_data in domain_list:
        if not isinstance(domain_data, dict):
            logger.warning("跳过无效的 domain_data，类型: %s", type(domain_data))
            continue
        sd_id = domain_data.get("semantic_domain_id")
        if not sd_id:
            logger.warning("跳过缺少 semantic_domain_id 的 domain_data")
            continue
        logger.info("对语义域 %s 执行 decremental: %s/%s", sd_id, dd_namespace, dd_name)
        result = semantic_grouper.decremental_semantic_group_analyse(sd_id)
        if isinstance(result, dict) and result.get("message") == _NO_RELATION_MESSAGE:
            result = _reconcile_groups_from_dd_annotation(
                dd_namespace,
                dd_name,
                sd_id,
                reconciled_group_ids,
            )
        last_result = result
        if isinstance(result, dict) and result.get("status") == "error":
            raise ValueError(result.get("message", "删除语义域失败"))

    logger.info("语义域分组完成 (共处理 %d 条): %s", len(domain_list), last_result)
    return last_result or {"status": "success", "message": "无语义域需处理"}


# ---------------------------------------------------------------------------
# Celery task
# ---------------------------------------------------------------------------
@celery.task(name="semantic_grouper.group", bind=True, acks_late=True)
def semantic_group_task(self, data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Celery task for semantic group operations.

    Acquires a global Redis distributed lock before executing to ensure
    only one grouping operation runs at a time across all workers/replicas.
    """
    operation = data.get("operation")
    descriptor = data.get("descriptor", {})

    dd_namespace = descriptor.get("namespace")
    dd_name = descriptor.get("name")

    if not all([dd_namespace, dd_name]):
        raise ValueError("Missing necessary fields in descriptor: namespace, name")

    logger.info(
        "============= start semantic_group_task %s, operation=%s, dd=%s/%s ===================",
        self.request.id, operation, dd_namespace, dd_name,
    )

    lock = get_semantic_group_lock()
    logger.info("Attempting to acquire distributed lock for %s/%s ...", dd_namespace, dd_name)

    with lock:
        logger.info(
            "Distributed lock acquired, executing: %s for %s/%s",
            operation, dd_namespace, dd_name,
        )

        if operation == "AddOrUpdate":
            result = incremental_semantic_group(descriptor)

            if isinstance(result, dict) and result.get("status") == "error":
                error_msg = result.get("message", "添加/更新语义域失败")
                logger.error("Failed to add/update semantic domain: %s", error_msg)
                raise ValueError(f"添加/更新语义域失败: {error_msg}")

            logger.info(
                "Successfully incremental semantic domain for %s/%s, result: %s",
                dd_namespace, dd_name, result,
            )

            _persist_group_membership_on_dd(dd_namespace, dd_name, result)

            # Notify execution-engine to reconcile the DD so it can detect
            # agent_card changes and perform blue-green DAC replacement.
            try:
                notify_dd_reconcile(dd_namespace, dd_name)
                logger.info("Notified DD %s/%s to reconcile", dd_namespace, dd_name)
            except Exception as e:
                logger.warning("Failed to notify DD reconcile (non-fatal): %s", e)

            return result

        elif operation == "Delete":
            result = decremental_semantic_group(descriptor)

            if isinstance(result, dict) and result.get("status") == "error":
                error_msg = result.get("message", "删除语义域失败")
                logger.error("Failed to delete semantic domain: %s", error_msg)
                raise ValueError(f"删除语义域失败: {error_msg}")

            logger.info(
                "Successfully decremental semantic domain for %s/%s, result: %s",
                dd_namespace, dd_name, result,
            )

            # 语义分组结束之后，删除被删除的 dd 的语义域
            semantic_domain_client.delete_semantic_domains_by_dd_info(
                dd_namespace=dd_namespace, dd_name=dd_name
            )
            logger.info(
                "Successfully deleted semantic domain for %s/%s",
                dd_namespace, dd_name,
            )

            return result

        else:
            raise ValueError(f"Unsupported operation: {operation}")

