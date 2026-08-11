"""
HTTP client for data-services ``/unstructured-files`` APIs (MySQL table ``unstructured_files``).

Mirrors :mod:`semantic_group_client` patterns: sync ``UnstructuredFilesClient``,
async ``AsyncUnstructuredFilesClient``, optional ``Data-Descriptor`` header from env.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import aiohttp
import requests


@dataclass
class UnstructuredFileRecord:
    """Payload for upsert / batch (matches data-services ``UnstructuredFileUpsertRequest``)."""

    dd_namespace: str
    dd_name: str
    file_name: str
    bucket: str
    minio_path: str
    file_size: int
    file_summary: Optional[str] = None
    content_hash: Optional[str] = None
    id: Optional[int] = None

    def to_upsert_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "dd_namespace": self.dd_namespace,
            "dd_name": self.dd_name,
            "file_name": self.file_name,
            "bucket": self.bucket,
            "minio_path": self.minio_path,
            "file_size": int(self.file_size),
        }
        # Only include file_summary when we actually have one. Data-services treats
        # a missing key as "do not overwrite" on duplicate-key update, so incremental
        # runs that do not re-summarize a file will not blank out its stored summary.
        if self.file_summary is not None and str(self.file_summary).strip():
            d["file_summary"] = str(self.file_summary).strip()
        # content_hash (MinIO etag) drives per-file change detection in the job's
        # incremental diff. Only send it when we have a real value so a caller that
        # upserts without it does not clobber a previously-stored hash (data-services
        # keeps the old value when the incoming content_hash is NULL).
        if self.content_hash is not None and str(self.content_hash).strip():
            d["content_hash"] = str(self.content_hash).strip()
        return d


class UnstructuredFilesClient:
    """Synchronous client for unstructured-files APIs."""

    def __init__(
        self,
        base_url: str = "http://data-services.dac.svc.cluster.local:8000",
        timeout: int = 300,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _make_request(
        self,
        method: str,
        endpoint: str,
        payload: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        headers = {"Content-Type": "application/json"}
        data_descriptor = os.getenv("DATA_DESCRIPTOR")
        if data_descriptor:
            headers["Data-Descriptor"] = data_descriptor
        try:
            request_kwargs: Dict[str, Any] = {
                "method": method,
                "url": url,
                "timeout": self.timeout,
                "headers": headers,
            }
            if payload is not None:
                request_kwargs["json"] = payload
            if params is not None:
                request_kwargs["params"] = params
            with requests.Session() as session:
                response = session.request(**request_kwargs)
                response.raise_for_status()
                return response.json()
        except requests.RequestException as e:
            raise Exception(f"HTTP request failed: {e}") from e
        except json.JSONDecodeError as e:
            raise Exception(f"Response JSON parsing failed: {e}") from e

    def upsert_unstructured_file(self, record: UnstructuredFileRecord) -> Dict[str, Any]:
        """POST ``/unstructured-files`` (single upsert)."""
        return self._make_request("POST", "/unstructured-files", record.to_upsert_dict())

    def batch_upsert_unstructured_files(self, records: List[UnstructuredFileRecord]) -> Dict[str, Any]:
        """POST ``/unstructured-files/batch``."""
        payload = {"files": [r.to_upsert_dict() for r in records]}
        return self._make_request("POST", "/unstructured-files/batch", payload)

    def get_unstructured_file_by_id(self, row_id: int) -> Dict[str, Any]:
        """GET ``/unstructured-files/{row_id}``."""
        return self._make_request("GET", f"/unstructured-files/{row_id}")

    def list_unstructured_files(
        self,
        bucket: Optional[str] = None,
        dd_namespace: Optional[str] = None,
        dd_name: Optional[str] = None,
        limit: int = 500,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """
        GET ``/unstructured-files`` with query params (same rules as server:
        ``dd_namespace`` and ``dd_name`` must both be set if either is used).
        """
        if (dd_namespace is not None) ^ (dd_name is not None):
            raise ValueError("dd_namespace and dd_name must both be set or both omitted")
        params: Dict[str, Any] = {"limit": limit, "offset": offset}
        if bucket is not None:
            params["bucket"] = bucket
        if dd_namespace is not None:
            params["dd_namespace"] = dd_namespace
            params["dd_name"] = dd_name
        return self._make_request("GET", "/unstructured-files", params=params)

    def delete_unstructured_file_by_id(self, row_id: int) -> Dict[str, Any]:
        """DELETE ``/unstructured-files/{row_id}``."""
        return self._make_request("DELETE", f"/unstructured-files/{row_id}")

    def delete_unstructured_file_by_object(
        self,
        dd_namespace: str,
        dd_name: str,
        bucket: str,
        minio_path: str,
    ) -> Dict[str, Any]:
        """POST ``/unstructured-files/delete-by-object`` (one row)."""
        payload = {
            "dd_namespace": dd_namespace,
            "dd_name": dd_name,
            "bucket": bucket,
            "minio_path": minio_path,
        }
        return self._make_request("POST", "/unstructured-files/delete-by-object", payload)

    def delete_unstructured_files_by_dd(self, dd_namespace: str, dd_name: str) -> Dict[str, Any]:
        """POST ``/unstructured-files/delete-by-dd`` (all rows for that DataDescriptor)."""
        payload = {"dd_namespace": dd_namespace, "dd_name": dd_name}
        return self._make_request("POST", "/unstructured-files/delete-by-dd", payload)

    def delete_unstructured_files_by_bucket(self, bucket: str) -> Dict[str, Any]:
        """DELETE ``/unstructured-files/bucket/{bucket}`` (all rows in that MinIO bucket)."""
        return self._make_request("DELETE", f"/unstructured-files/bucket/{bucket}")

    def health_check(self) -> bool:
        """Light check via GET ``/info``."""
        try:
            self._make_request("GET", "/info")
            return True
        except Exception:
            return False


class AsyncUnstructuredFilesClient:
    """Async client for unstructured-files APIs."""

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        timeout: int = 300,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = aiohttp.ClientTimeout(total=timeout)

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        payload: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        headers = {"Content-Type": "application/json"}
        data_descriptor = os.getenv("DATA_DESCRIPTOR")
        if data_descriptor:
            headers["Data-Descriptor"] = data_descriptor
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            try:
                request_kwargs: Dict[str, Any] = {"method": method, "url": url, "headers": headers}
                if payload is not None:
                    request_kwargs["json"] = payload
                if params is not None:
                    request_kwargs["params"] = params
                async with session.request(**request_kwargs) as response:
                    response.raise_for_status()
                    return await response.json()
            except aiohttp.ClientError as e:
                raise Exception(f"HTTP request failed: {e}") from e
            except json.JSONDecodeError as e:
                raise Exception(f"Response JSON parsing failed: {e}") from e

    async def aupsert_unstructured_file(self, record: UnstructuredFileRecord) -> Dict[str, Any]:
        return await self._make_request("POST", "/unstructured-files", record.to_upsert_dict())

    async def abatch_upsert_unstructured_files(self, records: List[UnstructuredFileRecord]) -> Dict[str, Any]:
        payload = {"files": [r.to_upsert_dict() for r in records]}
        return await self._make_request("POST", "/unstructured-files/batch", payload)

    async def aget_unstructured_file_by_id(self, row_id: int) -> Dict[str, Any]:
        return await self._make_request("GET", f"/unstructured-files/{row_id}")

    async def alist_unstructured_files(
        self,
        bucket: Optional[str] = None,
        dd_namespace: Optional[str] = None,
        dd_name: Optional[str] = None,
        limit: int = 500,
        offset: int = 0,
    ) -> Dict[str, Any]:
        if (dd_namespace is not None) ^ (dd_name is not None):
            raise ValueError("dd_namespace and dd_name must both be set or both omitted")
        params: Dict[str, Any] = {"limit": limit, "offset": offset}
        if bucket is not None:
            params["bucket"] = bucket
        if dd_namespace is not None:
            params["dd_namespace"] = dd_namespace
            params["dd_name"] = dd_name
        return await self._make_request("GET", "/unstructured-files", params=params)

    async def adelete_unstructured_file_by_id(self, row_id: int) -> Dict[str, Any]:
        return await self._make_request("DELETE", f"/unstructured-files/{row_id}")

    async def adelete_unstructured_file_by_object(
        self,
        dd_namespace: str,
        dd_name: str,
        bucket: str,
        minio_path: str,
    ) -> Dict[str, Any]:
        payload = {
            "dd_namespace": dd_namespace,
            "dd_name": dd_name,
            "bucket": bucket,
            "minio_path": minio_path,
        }
        return await self._make_request("POST", "/unstructured-files/delete-by-object", payload)

    async def adelete_unstructured_files_by_dd(self, dd_namespace: str, dd_name: str) -> Dict[str, Any]:
        payload = {"dd_namespace": dd_namespace, "dd_name": dd_name}
        return await self._make_request("POST", "/unstructured-files/delete-by-dd", payload)

    async def adelete_unstructured_files_by_bucket(self, bucket: str) -> Dict[str, Any]:
        return await self._make_request("DELETE", f"/unstructured-files/bucket/{bucket}")

    async def ahealth_check(self) -> bool:
        try:
            await self._make_request("GET", "/info")
            return True
        except Exception:
            return False
