import json
import time
import logging
import os
from typing import Dict, Any, Optional

import requests

logger = logging.getLogger("semantic_grouper_client")

DEFAULT_POLL_INTERVAL = 5       # seconds between status polls
DEFAULT_OVERALL_TIMEOUT = 720   # max seconds to wait for a task to complete


class SemanticGrouperClient:
    """
    HTTP client for the semantic-grouper service.

    Submits grouping requests and polls until completion.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: int = 60,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        overall_timeout: float = DEFAULT_OVERALL_TIMEOUT,
    ):
        """
        Args:
            base_url: semantic-grouper service URL
            timeout: HTTP request timeout per call (seconds)
            poll_interval: seconds between task_status polls
            overall_timeout: max total wait time (seconds)
        """
        self.base_url = (
            base_url
            or os.getenv(
                "SEMANTIC_GROUPER_URL",
                "http://semantic-grouper.dac.svc.cluster.local:8000",
            )
        ).rstrip("/")
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.overall_timeout = overall_timeout

    def _post(self, endpoint: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        response = requests.post(
            url,
            json=payload,
            timeout=self.timeout,
            headers={"Content-Type": "application/json"},
        )
        response.raise_for_status()
        return response.json()

    def _get(self, endpoint: str) -> Dict[str, Any]:
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        response = requests.get(url, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def group(self, operation: str, descriptor: Dict[str, str]) -> Dict[str, Any]:
        """
        Submit a semantic grouping request and wait for the result.

        Args:
            operation: "AddOrUpdate" or "Delete"
            descriptor: {"namespace": "...", "name": "..."}

        Returns:
            The task result dict from the semantic-grouper service.

        Raises:
            ValueError: on task failure or timeout
            requests.RequestException: on HTTP errors
        """
        dd_namespace = descriptor.get("namespace", "")
        dd_name = descriptor.get("name", "")

        # 1. Submit task
        logger.info(
            "Submitting semantic group task: operation=%s, dd=%s/%s",
            operation, dd_namespace, dd_name,
        )
        submit_response = self._post(
            "/api/v1/group",
            {"operation": operation, "descriptor": descriptor},
        )
        task_id = submit_response.get("task_id")
        if not task_id:
            raise ValueError(f"semantic-grouper returned no task_id: {submit_response}")

        logger.info("Semantic group task submitted: task_id=%s", task_id)

        # 2. Poll until done
        deadline = time.monotonic() + self.overall_timeout
        while True:
            status_response = self._get(f"/api/v1/task_status/{task_id}")
            status = status_response.get("status", "UNKNOWN")

            if status == "SUCCESS":
                result = status_response.get("result")
                logger.info(
                    "Semantic group task completed: task_id=%s, result=%s",
                    task_id, result,
                )
                return result

            if status == "FAILURE":
                error_info = status_response.get("result", {})
                error_msg = (
                    error_info.get("error", str(error_info))
                    if isinstance(error_info, dict)
                    else str(error_info)
                )
                logger.error(
                    "Semantic group task failed: task_id=%s, error=%s",
                    task_id, error_msg,
                )
                raise ValueError(
                    f"semantic-grouper task failed: {error_msg}"
                )

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                logger.error(
                    "Semantic group task timed out: task_id=%s, status=%s",
                    task_id, status,
                )
                raise ValueError(
                    f"semantic-grouper task timed out after {self.overall_timeout}s, "
                    f"task_id={task_id}, last status={status}"
                )

            logger.info(
                "Waiting for semantic group task: task_id=%s, status=%s, remaining=%.0fs",
                task_id, status, remaining,
            )
            time.sleep(min(self.poll_interval, remaining))

    def health_check(self) -> bool:
        """Check if the semantic-grouper service is reachable."""
        try:
            resp = self._get("/")
            return resp.get("status") == "running"
        except Exception:
            return False
