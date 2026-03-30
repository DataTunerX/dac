"""
DD Sync Observer - runs as sidecar in ds DAC Pod.

Loops: sleep -> lightweight source change detection -> if changed, patch DD with
dac.dac.io/sync-requested-at to trigger execution-engine re-sync.

Env:
  DD_NAMESPACE, DD_NAME: DataDescriptor CR to observe (namespace must match where the DD lives;
    execution-engine sets DD_NAMESPACE to the DataAgentContainer namespace — DD and DAC must be co-located).
  DATA_SERVICES_URL: dac-data-services HTTP base in-pod (e.g. http://localhost:8000) for signatures and DD CR access
  DATA_DESCRIPTOR: must match dac-data-services DATA_DESCRIPTOR (namespace_name with '-' -> '_')
  SYNC_SCHEDULE: interval like "6h", "1h" or seconds (default "6h")
"""
import hashlib
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

import requests

from .client.signature_client import SignatureClient
from .fingerprint.fingerprint import FingerprintBuilder, get_remote_commit_sha


def _configure_observer_logging() -> None:
    """
    Attach a handler directly to this module's logger. Relying only on basicConfig()
    fails when another import already configured the root logger (basicConfig becomes a no-op),
    which can result in zero log lines in cluster.
    """
    pkg_log = logging.getLogger("dd_sync_observer")
    if pkg_log.handlers:
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(logging.INFO)
    handler.setFormatter(
        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )
    pkg_log.addHandler(handler)
    pkg_log.setLevel(logging.INFO)
    pkg_log.propagate = False


_configure_observer_logging()
logger = logging.getLogger("dd_sync_observer")

# 统一前缀，便于在日志平台按 feature= 检索（grep: dd-sync-observer）
_LOG = "[dd-sync-observer]"

# Annotation key for triggering re-sync
SYNC_REQUESTED_AT_ANNOTATION = "dac.dac.io/sync-requested-at"

# Log grep anchor: DD-OBSERVER-CYCLE-BOUNDARY


def _log_dd_check_cycle_boundary(
    phase: str,
    dd_namespace: str,
    dd_name: str,
    *,
    outcome: Optional[str] = None,
) -> None:
    """
    One highly visible line per cycle edge. Search logs for: DD-OBSERVER-CYCLE-BOUNDARY
    """
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    line = (
        f"{_LOG} ◆◇◆ DD-OBSERVER-CYCLE-BOUNDARY phase={phase} "
        f"dd={dd_namespace}/{dd_name} utc={ts}"
    )
    if outcome is not None:
        line += f" outcome={outcome}"
    line += " ◇◆◇ ━━━━━━━━━━ grep:DD-OBSERVER-CYCLE-BOUNDARY ━━━━━━━━━━ ◇◆◇"
    logger.info(line)


def _dd_snapshot_for_log(dd: Dict[str, Any]) -> Dict[str, Any]:
    """Subset of DataDescriptor safe for logs (no connection secrets)."""
    md = dd.get("metadata") or {}
    spec = dd.get("spec") or {}
    sources = spec.get("sources") or []
    src_out: List[Dict[str, Any]] = []
    for s in sources:
        if not isinstance(s, dict):
            continue
        src_out.append(
            {
                "name": s.get("name"),
                "type": s.get("type"),
                "extract": s.get("extract"),
            }
        )
    sync_policy = spec.get("syncPolicy")
    if isinstance(sync_policy, dict):
        sync_policy = {
            "enabled": sync_policy.get("enabled"),
            "schedule": sync_policy.get("schedule"),
        }
    return {
        "apiVersion": dd.get("apiVersion"),
        "kind": dd.get("kind"),
        "metadata": {
            "name": md.get("name"),
            "namespace": md.get("namespace"),
            "uid": md.get("uid"),
            "resourceVersion": md.get("resourceVersion"),
        },
        "spec": {
            "descriptorType": spec.get("descriptorType"),
            "syncPolicy": sync_policy,
            "sources": src_out,
        },
    }


def _parse_schedule(schedule_str: str) -> int:
    """Parse SYNC_SCHEDULE into seconds. E.g. '6h' -> 21600, '1h' -> 3600."""
    if not schedule_str:
        return 6 * 3600  # default 6h
    s = schedule_str.strip().lower()
    m = re.match(r"^(\d+)(h|m|s)?$", s)
    if not m:
        try:
            return int(s)
        except ValueError:
            return 6 * 3600
    val = int(m.group(1))
    unit = m.group(2) or "s"
    if unit == "h":
        return val * 3600
    if unit == "m":
        return val * 60
    return val


def _get_dd_via_http(
    base_url: str,
    namespace: str,
    name: str,
    data_descriptor: str,
) -> Optional[Dict[str, Any]]:
    """Load DataDescriptor JSON via local dac-data-services -> data-services -> Kubernetes."""
    url = f"{base_url.rstrip('/')}/datadescriptors/{namespace}/{name}"
    try:
        r = requests.get(
            url,
            headers={"Data-Descriptor": data_descriptor},
            timeout=30,
        )
        if r.status_code == 404:
            logger.warning(
                "%s feature=http_get_dd DataDescriptor not found %s/%s",
                _LOG,
                namespace,
                name,
            )
            return None
        r.raise_for_status()
        obj = r.json()
        if isinstance(obj, dict):
            snap = _dd_snapshot_for_log(obj)
            logger.info(
                "%s feature=http_get_dd Loaded DataDescriptor %s/%s from API snapshot=%s",
                _LOG,
                namespace,
                name,
                json.dumps(snap, ensure_ascii=False, sort_keys=False),
            )
        else:
            logger.info(
                "%s feature=http_get_dd Loaded DataDescriptor %s/%s (unexpected non-object body)",
                _LOG,
                namespace,
                name,
            )
        return obj
    except Exception as e:
        logger.warning("%s feature=http_get_dd Failed to get DD: %s", _LOG, e)
        return None


def _patch_dd_annotation_via_http(
    base_url: str,
    namespace: str,
    name: str,
    data_descriptor: str,
    annotation_key: str,
    value: str,
) -> bool:
    """PATCH sync-requested-at through dac-data-services (annotation_key should be SYNC_REQUESTED_AT_ANNOTATION)."""
    if annotation_key != SYNC_REQUESTED_AT_ANNOTATION:
        logger.error(
            "%s feature=http_patch_dd Only sync-requested-at endpoint is supported, got %s",
            _LOG,
            annotation_key,
        )
        return False
    url = f"{base_url.rstrip('/')}/datadescriptors/{namespace}/{name}/sync-requested-at"
    payload = {"value": value}
    logger.info(
        "%s feature=http_patch_dd Requesting PATCH url=%s DataDescriptor=%s/%s "
        "annotation_key=%r request_body=%s",
        _LOG,
        url,
        namespace,
        name,
        annotation_key,
        json.dumps(payload, ensure_ascii=False),
    )
    try:
        r = requests.patch(
            url,
            headers={
                "Data-Descriptor": data_descriptor,
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=30,
        )
        r.raise_for_status()
        logger.info(
            "%s feature=patch_sync_requested_at Applied PATCH ok http_status=%s "
            "DataDescriptor=%s/%s set metadata.annotations[%r]=%r "
            "(re-sync trigger for execution-engine)",
            _LOG,
            r.status_code,
            namespace,
            name,
            annotation_key,
            value,
        )
        return True
    except requests.HTTPError as e:
        resp = e.response
        detail = ""
        if resp is not None:
            try:
                detail = resp.text[:500]
            except Exception:
                detail = str(resp.status_code)
        logger.error(
            "%s feature=patch_sync_requested_at PATCH failed DataDescriptor=%s/%s "
            "url=%s http_error=%s body_prefix=%r",
            _LOG,
            namespace,
            name,
            url,
            e,
            detail,
        )
        return False
    except Exception as e:
        logger.error(
            "%s feature=patch_sync_requested_at PATCH failed DataDescriptor=%s/%s url=%s error=%s",
            _LOG,
            namespace,
            name,
            url,
            e,
        )
        return False


def _get_connection_config(source_type: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
    """Build connection config from DD source metadata (same as job.py)."""
    type_lower = source_type.lower()
    if type_lower == "mysql":
        return {
            "host": metadata.get("host", "localhost"),
            "port": int(metadata.get("port", 3306)),
            "user": metadata.get("user", "root"),
            "password": metadata.get("password", ""),
            "database": metadata.get("database", ""),
        }
    if type_lower == "postgres":
        return {
            "host": metadata.get("host", "localhost"),
            "port": int(metadata.get("port", 5432)),
            "user": metadata.get("user", "postgres"),
            "password": metadata.get("password", ""),
            "database": metadata.get("database", "postgres"),
        }
    if type_lower in ("github", "gitee", "gitlab"):
        return {
            "codeRepoPath": metadata.get("codeRepoPath", ""),
            "codeRepoBranch": metadata.get("codeRepoBranch", "main"),
            "token": metadata.get("codeRepoToken", ""),
        }
    if type_lower == "minio":
        return {
            "host": metadata.get("host", "localhost:9000"),
            "access_key": metadata.get("access_key", ""),
            "secret_key": metadata.get("secret_key", ""),
            "bucket": metadata.get("bucket", ""),
            "secure": metadata.get("secure", False),
        }
    return metadata


def _detect_mysql_change(
    connection_config: Dict[str, Any],
    extract_tables: List[str],
    stored_fingerprint: Optional[str],
) -> bool:
    """
    Lightweight MySQL change detection: fetch schema, build fingerprint, compare (structure only).
    """
    try:
        from .readers.mysql.mysql_reader import MySQLReader
        from .prompts.mysql import format_schema_to_markdown_with_all_tables
    except ImportError as e:
        logger.warning("%s feature=detect_mysql Import unavailable: %s", _LOG, e)
        return False

    try:
        reader = MySQLReader(connection_config)
        try:
            schema_results = reader.schema(extract_tables) if extract_tables else reader.schema([])
            tables_schema_md_list = format_schema_to_markdown_with_all_tables(schema_results)
            builder = FingerprintBuilder()
            current_summary = builder.generate_db_fingerprint_summary(
                "mysql", tables_schema_md_list
            )
            current_hash = builder.generate_fingerprint_id(current_summary)
            if not stored_fingerprint:
                return False
            if current_hash != stored_fingerprint:
                logger.info(
                    "%s feature=detect_mysql Fingerprint changed old=%s new=%s",
                    _LOG,
                    str(stored_fingerprint)[:8],
                    current_hash[:8],
                )
                return True
            return False
        finally:
            reader.close()
    except Exception as e:
        logger.warning("%s feature=detect_mysql Detection failed (non-fatal): %s", _LOG, e)
        return False


def _detect_postgres_change(
    connection_config: Dict[str, Any],
    extract_tables: List[str],
    stored_fingerprint: Optional[str],
) -> bool:
    """Postgres change detection (schema structure only)."""
    try:
        from .readers.postgres.postgres_reader import PostgresReader
        from .prompts.postgres import format_schema_to_markdown_with_all_tables
    except ImportError as e:
        logger.warning("%s feature=detect_postgres Import unavailable: %s", _LOG, e)
        return False

    try:
        reader = PostgresReader(connection_config)
        try:
            schema_results = reader.schema(extract_tables) if extract_tables else reader.schema([])
            tables_schema_md_list = format_schema_to_markdown_with_all_tables(schema_results)
            builder = FingerprintBuilder()
            current_summary = builder.generate_db_fingerprint_summary(
                "postgres", tables_schema_md_list
            )
            current_hash = builder.generate_fingerprint_id(current_summary)
            if not stored_fingerprint:
                return False
            if current_hash != stored_fingerprint:
                logger.info(
                    "%s feature=detect_postgres Fingerprint changed old=%s new=%s",
                    _LOG,
                    str(stored_fingerprint)[:8],
                    current_hash[:8],
                )
                return True
            return False
        finally:
            reader.close()
    except Exception as e:
        logger.warning("%s feature=detect_postgres Detection failed (non-fatal): %s", _LOG, e)
        return False


def _detect_minio_change(
    connection_config: Dict[str, Any],
    extract_files: List[str],
    stored_fingerprint: Optional[str],
) -> bool:
    """MinIO change detection: list objects, hash (path, etag, size), compare."""
    try:
        from .readers.minio.minio_conn import GeneralMinio
    except ImportError as e:
        logger.warning("%s feature=detect_minio Import unavailable: %s", _LOG, e)
        return False

    try:
        client = GeneralMinio(
            host=connection_config.get("host", "localhost:9000"),
            access_key=connection_config.get("access_key", ""),
            secret_key=connection_config.get("secret_key", ""),
        )
        bucket = connection_config.get("bucket", "")
        items = []
        for obj_name in extract_files or []:
            try:
                stat = client.conn.stat_object(bucket, obj_name)
                items.append((obj_name, stat.etag or "", stat.size))
            except Exception:
                items.append((obj_name, "", 0))
        items.sort(key=lambda x: x[0])
        obj_hash = hashlib.md5(json.dumps(items).encode()).hexdigest()
        builder = FingerprintBuilder()
        summary = builder.generate_object_list_fingerprint_summary(
            "minio", connection_config, obj_hash
        )
        current_hash = builder.generate_fingerprint_id(summary)
        if not stored_fingerprint:
            return False
        if current_hash != stored_fingerprint:
            logger.info(
                "%s feature=detect_minio Fingerprint changed old=%s new=%s",
                _LOG,
                str(stored_fingerprint)[:8],
                current_hash[:8],
            )
            return True
        return False
    except Exception as e:
        logger.warning("%s feature=detect_minio Detection failed (non-fatal): %s", _LOG, e)
        return False


def _detect_fileserver_change(
    connection_config: Dict[str, Any],
    extract_files: List[str],
    stored_fingerprint: Optional[str],
) -> bool:
    """Fileserver change detection: hash (host, port, files list)."""
    payload = {
        "host": connection_config.get("host"),
        "port": connection_config.get("port"),
        "files": sorted(extract_files) if isinstance(extract_files, list) else [],
    }
    obj_hash = hashlib.md5(json.dumps(payload).encode()).hexdigest()
    builder = FingerprintBuilder()
    summary = builder.generate_object_list_fingerprint_summary(
        "fileserver", connection_config, obj_hash
    )
    current_hash = builder.generate_fingerprint_id(summary)
    if not stored_fingerprint:
        return False
    if current_hash != stored_fingerprint:
        logger.info(
            "%s feature=detect_fileserver Fingerprint changed old=%s new=%s",
            _LOG,
            str(stored_fingerprint)[:8],
            current_hash[:8],
        )
        return True
    return False


def _detect_code_change(
    source_type: str,
    connection_config: Dict[str, Any],
    stored_fingerprint: Optional[str],
) -> bool:
    """
    Code repo change: fingerprint includes connection_information + commit_sha (git ls-remote).
    """
    repo_url = connection_config.get("codeRepoPath") or ""
    branch = connection_config.get("codeRepoBranch") or "main"
    token = connection_config.get("token") or connection_config.get("codeRepoToken") or ""
    commit_sha = get_remote_commit_sha(repo_url, branch, token or None)
    builder = FingerprintBuilder()
    summary = builder.generate_code_fingerprint_summary(source_type, connection_config, commit_sha)
    current_hash = builder.generate_fingerprint_id(summary)
    if not stored_fingerprint:
        return False
    if current_hash != stored_fingerprint:
        logger.info(
            "%s feature=detect_code Fingerprint changed type=%s commit_sha=%s old_hash=%s new_hash=%s",
            _LOG,
            source_type,
            commit_sha[:8] if commit_sha else "?",
            str(stored_fingerprint)[:8],
            current_hash[:8],
        )
        return True
    return False


def detect_source_change(
    dd_namespace: str,
    dd_name: str,
    source: Dict[str, Any],
    signature_client: SignatureClient,
) -> bool:
    """
    Detect if the given source has changed. Returns True if re-sync is needed.
    """
    source_type = source.get("type", "").lower()
    metadata = dict(source.get("metadata") or {})
    # Merge codeRepo into metadata for code sources (DD has CodeRepo as separate field)
    code_repo = source.get("codeRepo") or {}
    if isinstance(code_repo, dict):
        metadata.update({
            "codeRepoPath": code_repo.get("codeRepoPath") or metadata.get("codeRepoPath"),
            "codeRepoBranch": code_repo.get("codeRepoBranch") or metadata.get("codeRepoBranch", "main"),
            "codeRepoToken": code_repo.get("codeRepoToken") or metadata.get("codeRepoToken", ""),
        })
    extract = source.get("extract") or {}
    tables = extract.get("tables") or extract.get("querys")
    if isinstance(tables, str):
        tables = [tables] if tables else []
    elif not isinstance(tables, list):
        tables = []
    files = extract.get("files")
    if isinstance(files, str):
        files = [files] if files else []
    elif not isinstance(files, list):
        files = []

    # Get stored fingerprint from data-services
    try:
        resp = signature_client.search_signatures_by_dd(dd_namespace, dd_name)
    except Exception as e:
        logger.warning(
            "%s feature=signature_by_dd POST /signatures/search/by-dd failed for %s/%s: %s",
            _LOG,
            dd_namespace,
            dd_name,
            e,
        )
        return False

    data = resp.get("data") or resp.get("records") or []
    if isinstance(data, dict):
        data = data.get("items", data.get("records", []))
    stored_fingerprint = None
    if data:
        first = data[0] if isinstance(data, list) else data
        if isinstance(first, dict):
            stored_fingerprint = first.get("fingerprint")
            if not stored_fingerprint and first.get("metadata_content"):
                stored_fingerprint = json.dumps(first.get("metadata_content", {}), sort_keys=True)

    src_name = source.get("name") or ""
    has_baseline = bool(stored_fingerprint)
    logger.debug(
        "%s feature=detect_source Prepared check dd=%s/%s source_type=%s source_name=%s has_signature_baseline=%s",
        _LOG,
        dd_namespace,
        dd_name,
        source_type or "(empty)",
        src_name,
        has_baseline,
    )
    if not has_baseline:
        logger.debug(
            "%s feature=detect_source No stored fingerprint baseline; skipping diff until first data-sinker sync",
            _LOG,
        )

    conn_config = _get_connection_config(source_type, metadata)

    if source_type == "mysql":
        if tables:
            logger.info(
                "%s feature=detect_source mysql scope=dd_extract_tables only count=%d tables=%s "
                "(new DB tables must appear in DataDescriptor spec.sources[].extract.tables to be detected)",
                _LOG,
                len(tables),
                tables,
            )
        else:
            logger.info(
                "%s feature=detect_source mysql scope=full_database_schema extract.tables empty; "
                "fingerprint uses all tables in the configured database",
                _LOG,
            )
        return _detect_mysql_change(conn_config, tables, stored_fingerprint)
    if source_type == "postgres":
        if tables:
            logger.info(
                "%s feature=detect_source postgres scope=dd_extract_tables only count=%d tables=%s",
                _LOG,
                len(tables),
                tables,
            )
        else:
            logger.info(
                "%s feature=detect_source postgres scope=full_database_schema extract.tables empty",
                _LOG,
            )
        return _detect_postgres_change(conn_config, tables, stored_fingerprint)
    if source_type in ("github", "gitee", "gitlab"):
        return _detect_code_change(source_type, conn_config, stored_fingerprint)
    if source_type == "minio":
        return _detect_minio_change(conn_config, files, stored_fingerprint)
    if source_type == "fileserver":
        return _detect_fileserver_change(conn_config, files, stored_fingerprint)
    logger.info(
        "%s feature=detect_source Unsupported source_type=%s; skipping change detection",
        _LOG,
        source_type,
    )
    return False


def run_cycle(
    dd_namespace: str,
    dd_name: str,
    data_services_url: str,
    data_descriptor: str,
) -> bool:
    """
    Run one detection cycle. Returns True if DD was patched.
    """
    cycle_outcome: str = "exception"
    _log_dd_check_cycle_boundary("BEGIN", dd_namespace, dd_name)
    try:
        logger.info(
            "%s feature=run_cycle Starting cycle dd=%s/%s data_services_url=%s",
            _LOG,
            dd_namespace,
            dd_name,
            data_services_url,
        )
        dd = _get_dd_via_http(data_services_url, dd_namespace, dd_name, data_descriptor)
        if not dd:
            cycle_outcome = "no_dd_in_api"
            logger.info("%s feature=run_cycle Aborted: DataDescriptor not found in API", _LOG)
            return False
        spec = dd.get("spec") or {}
        sources = spec.get("sources") or []
        if not sources:
            cycle_outcome = "no_sources_in_spec"
            logger.info("%s feature=run_cycle No sources in DD spec; nothing to observe", _LOG)
            return False

        logger.info("%s feature=run_cycle Observing %d source(s)", _LOG, len(sources))
        signature_client = SignatureClient(base_url=data_services_url, timeout=30)
        changed = False
        for src in sources:
            if detect_source_change(dd_namespace, dd_name, src, signature_client):
                changed = True
                break

        if changed:
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            ok = _patch_dd_annotation_via_http(
                data_services_url,
                dd_namespace,
                dd_name,
                data_descriptor,
                SYNC_REQUESTED_AT_ANNOTATION,
                ts,
            )
            cycle_outcome = "patched_ok" if ok else "patch_failed"
            logger.info(
                "%s feature=run_cycle Source change detected; patch sync-requested-at success=%s ts=%s",
                _LOG,
                ok,
                ts,
            )
            return ok
        cycle_outcome = "no_source_change"
        logger.info("%s feature=run_cycle No source change; DD not patched", _LOG)
        return False
    finally:
        _log_dd_check_cycle_boundary(
            "END",
            dd_namespace,
            dd_name,
            outcome=cycle_outcome,
        )


def main() -> None:
    dd_namespace = os.getenv("DD_NAMESPACE", "")
    dd_name = os.getenv("DD_NAME", "")
    data_services_url = os.getenv("DATA_SERVICES_URL", os.getenv("DATA_SERVICES", "http://localhost:8000"))
    data_descriptor = os.getenv("DATA_DESCRIPTOR", "").strip()
    schedule_str = os.getenv("SYNC_SCHEDULE", "6h")
    interval = _parse_schedule(schedule_str)

    if not dd_namespace or not dd_name:
        logger.error("%s feature=main_loop Missing required env: DD_NAMESPACE and DD_NAME must be set", _LOG)
        raise SystemExit(1)
    if not data_descriptor:
        logger.error("%s feature=main_loop Missing required env: DATA_DESCRIPTOR must be set", _LOG)
        raise SystemExit(1)

    logger.info(
        "%s feature=main_loop Starting observer DD=%s/%s data_services=%s SYNC_SCHEDULE=%s parsed_interval_sec=%d",
        _LOG,
        dd_namespace,
        dd_name,
        data_services_url,
        schedule_str,
        interval,
    )

    while True:
        try:
            run_cycle(dd_namespace, dd_name, data_services_url, data_descriptor)
        except Exception as e:
            logger.exception("%s feature=main_loop Cycle failed: %s", _LOG, e)
        logger.info("%s feature=main_loop Sleeping %d seconds until next cycle", _LOG, interval)
        time.sleep(interval)


if __name__ == "__main__":
    main()
