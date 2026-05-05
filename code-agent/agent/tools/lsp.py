"""Language Server Protocol (LSP) client stack .

Provides a stdio JSON-RPC client, per-server lifecycle (start / initialize / shutdown),
optional multi-server routing by file extension, and text sync helpers (``didOpen`` /
``didChange`` / …). Configuration is supplied by the host (unlike TS, there is no built-in
plugin loader here); pass a dict into :func:`LSPServerManager.initialize`.

Dependencies: ``python-lsp-jsonrpc`` (LSP framing + JSON-RPC endpoint).
"""

from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
from collections.abc import Callable, Mapping
from concurrent.futures import Future, TimeoutError as FutureTimeoutError
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, TypeVar

from pylsp_jsonrpc.endpoint import Endpoint
from pylsp_jsonrpc.exceptions import JsonRpcException
from pylsp_jsonrpc.streams import JsonRpcStreamReader, JsonRpcStreamWriter

# Generic JSON-RPC errors use ``JsonRpcException.from_dict`` → base ``__init__``, which assumes
# ``CODE`` / ``MESSAGE`` exist (only defined on subclasses). Avoid reader-thread crashes on odd payloads.
if "CODE" not in JsonRpcException.__dict__:
    JsonRpcException.CODE = -32001
if "MESSAGE" not in JsonRpcException.__dict__:
    JsonRpcException.MESSAGE = "JSON-RPC Error"

logger = logging.getLogger(__name__)

T = TypeVar("T")

# LSP JSON-RPC error code: "content modified" (e.g. rust-analyzer indexing).
LSP_ERROR_CONTENT_MODIFIED = -32801
MAX_RETRIES_FOR_TRANSIENT_ERRORS = 3
RETRY_BASE_DELAY_MS = 500

LspServerState = Literal["stopped", "starting", "running", "stopping", "error"]


@dataclass
class ScopedLspServerConfig:
    """Single LSP server definition (aligned with Claude Code plugin LSP config)."""

    command: str
    extension_to_language: dict[str, str]
    args: list[str] = field(default_factory=list)
    env: dict[str, str] | None = None
    workspace_folder: str | None = None
    initialization_options: dict[str, Any] | None = None
    max_restarts: int | None = 3
    startup_timeout_ms: int | None = None
    # Declared in TS types but rejected at runtime there; we mirror the validation.
    restart_on_crash: bool | None = None
    shutdown_timeout: int | None = None


def _error_message(exc: BaseException) -> str:
    return str(exc) if str(exc) else type(exc).__name__


def _with_timeout_ms(future: Future[T], ms: int, message: str) -> T:
    try:
        return future.result(timeout=ms / 1000.0)
    except FutureTimeoutError as e:
        raise TimeoutError(message) from e


def _file_uri_to_path(uri: str) -> str:
    """Best-effort ``file://`` URI → local path (POSIX + common Windows URIs)."""
    from urllib.parse import unquote, urlparse

    parsed = urlparse(uri)
    if parsed.scheme != "file":
        return uri
    path = unquote(parsed.path or "")
    if parsed.netloc:
        return f"//{parsed.netloc}{path}"
    return path


def _client_capabilities() -> dict[str, Any]:
    """Same shape as ``LSPServerInstance`` in TS (minimal client feature set)."""
    return {
        "workspace": {
            "configuration": False,
            "workspaceFolders": False,
        },
        "textDocument": {
            "synchronization": {
                "dynamicRegistration": False,
                "willSave": False,
                "willSaveWaitUntil": False,
                "didSave": True,
            },
            "publishDiagnostics": {
                "relatedInformation": True,
                "tagSupport": {"valueSet": [1, 2]},
                "versionSupport": False,
                "codeDescriptionSupport": True,
                "dataSupport": False,
            },
            "hover": {
                "dynamicRegistration": False,
                "contentFormat": ["markdown", "plaintext"],
            },
            "definition": {"dynamicRegistration": False, "linkSupport": True},
            "references": {"dynamicRegistration": False},
            "documentSymbol": {
                "dynamicRegistration": False,
                "hierarchicalDocumentSymbolSupport": True,
            },
            "callHierarchy": {"dynamicRegistration": False},
        },
        "general": {"positionEncodings": ["utf-16"]},
    }


class LSPClient:
    """JSON-RPC over stdio to one language server process."""

    def __init__(self, server_name: str, on_crash: Callable[[Exception], None] | None = None):
        self._name = server_name
        self._on_crash = on_crash
        self._proc: subprocess.Popen[bytes] | None = None
        self._reader: JsonRpcStreamReader | None = None
        self._writer: JsonRpcStreamWriter | None = None
        self._endpoint: Endpoint | None = None
        self._read_thread: threading.Thread | None = None
        self._capabilities: dict[str, Any] | None = None
        self._initialized = False
        self._start_failed = False
        self._start_error: Exception | None = None
        self._is_stopping = False
        self._dispatcher: dict[str, Callable[..., Any]] = {}
        self._pending_notifications: list[tuple[str, Callable[[Any], None]]] = []
        self._pending_requests: list[
            tuple[str, Callable[[Any], Any | Future[Any]]]
        ] = []

        self._lock = threading.Lock()

    @property
    def capabilities(self) -> dict[str, Any] | None:
        return self._capabilities

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    def _check_start_failed(self) -> None:
        if self._start_failed:
            raise self._start_error or RuntimeError(
                f"LSP server {self._name} failed to start",
            )

    def _consume_outbound(self, message: dict[str, Any]) -> None:
        if self._writer:
            self._writer.write(message)

    def _merge_dispatcher(self, method: str, fn: Callable[..., Any]) -> None:
        self._dispatcher[method] = fn

    def start(
        self,
        command: str,
        args: list[str],
        *,
        env: Mapping[str, str] | None = None,
        cwd: str | None = None,
    ) -> None:
        """Spawn the server and start the JSON-RPC reader thread."""
        with self._lock:
            try:
                merged_env = os.environ.copy()
                if env:
                    merged_env.update(dict(env))

                self._proc = subprocess.Popen(
                    [command, *args],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=cwd,
                    env=merged_env,
                )

                if self._proc.stdin is None or self._proc.stdout is None:
                    raise RuntimeError("LSP server process stdio not available")

                # Executable-not-found etc.: child exits quickly; surface stderr.
                time.sleep(0.05)
                poll = self._proc.poll()
                if poll is not None and poll != 0:
                    err_bytes = b""
                    if self._proc.stderr:
                        err_bytes = self._proc.stderr.read() or b""
                    raise RuntimeError(
                        f"LSP server process exited immediately (code {poll}): "
                        f"{err_bytes.decode(errors='replace').strip()}",
                    )

                stderr_pipe = self._proc.stderr

                def _drain_stderr() -> None:
                    if stderr_pipe is None:
                        return
                    for line in iter(stderr_pipe.readline, b""):
                        if not line:
                            break
                        text = line.decode(errors="replace").rstrip()
                        if text:
                            logger.debug("[%s stderr] %s", self._name, text)

                threading.Thread(target=_drain_stderr, daemon=True).start()

                def _on_exit(code: int | None) -> None:
                    if self._is_stopping:
                        return
                    self._initialized = False
                    if code not in (0, None):
                        exc = RuntimeError(
                            f"LSP server {self._name} crashed with exit code {code}",
                        )
                        logger.error("%s", exc)
                        self._on_crash and self._on_crash(exc)

                def _watch_exit() -> None:
                    assert self._proc is not None
                    code = self._proc.wait()
                    _on_exit(code)

                threading.Thread(target=_watch_exit, daemon=True).start()

                self._writer = JsonRpcStreamWriter(self._proc.stdin)
                self._reader = JsonRpcStreamReader(self._proc.stdout)
                self._endpoint = Endpoint(self._dispatcher, self._consume_outbound)

                for method, handler in self._pending_notifications:
                    self._merge_dispatcher(
                        method,
                        lambda params, h=handler: h(params),
                    )
                self._pending_notifications.clear()

                for method, handler in self._pending_requests:
                    self._merge_dispatcher(
                        method,
                        lambda params, h=handler: h(params),
                    )
                self._pending_requests.clear()

                def _listen() -> None:
                    assert self._reader is not None and self._endpoint is not None
                    try:
                        self._reader.listen(self._endpoint.consume)
                    except Exception as e:
                        if not self._is_stopping:
                            self._start_failed = True
                            self._start_error = e
                            logger.exception("LSP reader failed for %s", self._name)

                self._read_thread = threading.Thread(target=_listen, daemon=True)
                self._read_thread.start()

                logger.debug("LSP client started for %s", self._name)
            except Exception as e:
                logger.exception("LSP server %s failed to start: %s", self._name, e)
                self._cleanup_process()
                raise

    def initialize(
        self,
        params: dict[str, Any],
        *,
        timeout_ms: int | None = None,
    ) -> dict[str, Any]:
        if self._endpoint is None:
            raise RuntimeError("LSP client not started")
        self._check_start_failed()
        try:
            fut: Future[Any] = self._endpoint.request("initialize", params)
            if timeout_ms is not None:
                result = _with_timeout_ms(
                    fut,
                    timeout_ms,
                    f"LSP server '{self._name}' timed out after {timeout_ms}ms during initialization",
                )
            else:
                result = fut.result(timeout=120.0)
            result_typed: dict[str, Any] = result  # type: ignore[assignment]
            self._capabilities = result_typed.get("capabilities")
            self._endpoint.notify("initialized", {})
            self._initialized = True
            logger.debug("LSP server %s initialized", self._name)
            return result_typed
        except Exception as e:
            logger.exception("LSP server %s initialize failed: %s", self._name, e)
            raise

    def send_request(self, method: str, params: Any) -> Any:
        if self._endpoint is None:
            raise RuntimeError("LSP client not started")
        self._check_start_failed()
        if not self._initialized:
            raise RuntimeError("LSP server not initialized")
        try:
            return self._endpoint.request(method, params).result(timeout=120.0)
        except Exception as e:
            logger.exception(
                "LSP server %s request %s failed: %s",
                self._name,
                method,
                e,
            )
            raise

    def send_notification(self, method: str, params: Any) -> None:
        if self._endpoint is None:
            raise RuntimeError("LSP client not started")
        self._check_start_failed()
        try:
            self._endpoint.notify(method, params)
        except Exception as e:
            logger.warning(
                "LSP server %s notification %s failed (continuing): %s",
                self._name,
                method,
                e,
            )

    def on_notification(self, method: str, handler: Callable[[Any], None]) -> None:
        wrapped = lambda params, h=handler: h(params)
        if self._endpoint is None:
            self._pending_notifications.append((method, handler))
            logger.debug(
                "Queued notification handler for %s.%s",
                self._name,
                method,
            )
            return
        self._merge_dispatcher(method, wrapped)

    def on_request(
        self,
        method: str,
        handler: Callable[[Any], Any | Future[Any]],
    ) -> None:
        if self._endpoint is None:
            self._pending_requests.append((method, handler))
            logger.debug("Queued request handler for %s.%s", self._name, method)
            return
        self._merge_dispatcher(method, handler)

    def stop(self) -> None:
        shutdown_error: Exception | None = None
        self._is_stopping = True
        try:
            if self._endpoint is not None:
                try:
                    self._endpoint.request("shutdown", {}).result(timeout=30.0)
                    self._endpoint.notify("exit", {})
                except Exception as e:
                    shutdown_error = e
                    logger.exception(
                        "LSP server %s stop shutdown sequence failed: %s",
                        self._name,
                        e,
                    )
        finally:
            if self._reader:
                try:
                    self._reader.close()
                except Exception:
                    pass
                self._reader = None

            if self._endpoint:
                try:
                    self._endpoint.shutdown()
                except Exception:
                    pass
                self._endpoint = None

            self._cleanup_process()

            self._initialized = False
            self._capabilities = None
            self._writer = None
            self._is_stopping = False
            if shutdown_error:
                self._start_failed = True
                self._start_error = shutdown_error

            logger.debug("LSP client stopped for %s", self._name)

        if shutdown_error:
            raise shutdown_error

    def _cleanup_process(self) -> None:
        proc = self._proc
        self._proc = None
        if proc is None:
            return
        try:
            proc.kill()
        except Exception:
            pass
        try:
            proc.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            pass
        except Exception:
            pass


def _validate_server_config(name: str, config: ScopedLspServerConfig) -> None:
    if config.restart_on_crash is not None:
        raise ValueError(
            f"LSP server '{name}': restart_on_crash is not yet implemented.",
        )
    if config.shutdown_timeout is not None:
        raise ValueError(
            f"LSP server '{name}': shutdown_timeout is not yet implemented.",
        )


class LSPServerInstance:
    """One named server: state machine, init params, retries on ContentModified."""

    def __init__(self, name: str, config: ScopedLspServerConfig):
        _validate_server_config(name, config)
        self.name = name
        self.config = config
        self._state: LspServerState = "stopped"
        self._start_time: float | None = None
        self._last_error: Exception | None = None
        self._restart_count = 0
        self._crash_recovery_count = 0

        def _on_crash(exc: Exception) -> None:
            self._state = "error"
            self._last_error = exc
            self._crash_recovery_count += 1

        self._client = LSPClient(name, on_crash=_on_crash)

    @property
    def state(self) -> LspServerState:
        return self._state

    @property
    def start_time(self) -> float | None:
        return self._start_time

    @property
    def last_error(self) -> Exception | None:
        return self._last_error

    @property
    def restart_count(self) -> int:
        return self._restart_count

    def start(self) -> None:
        if self._state in ("running", "starting"):
            return

        max_restarts = self.config.max_restarts if self.config.max_restarts is not None else 3
        if self._state == "error" and self._crash_recovery_count > max_restarts:
            err = RuntimeError(
                f"LSP server '{self.name}' exceeded max crash recovery attempts ({max_restarts})",
            )
            self._last_error = err
            logger.error("%s", err)
            raise err

        try:
            self._state = "starting"
            logger.debug("Starting LSP server instance: %s", self.name)

            self._client.start(
                self.config.command,
                list(self.config.args or []),
                env=self.config.env,
                cwd=self.config.workspace_folder or os.getcwd(),
            )

            workspace_folder = self.config.workspace_folder or os.getcwd()
            workspace_uri = Path(workspace_folder).resolve().as_uri()

            init_params: dict[str, Any] = {
                "processId": os.getpid(),
                "initializationOptions": self.config.initialization_options or {},
                "workspaceFolders": [
                    {
                        "uri": workspace_uri,
                        "name": Path(workspace_folder).name,
                    },
                ],
                "rootPath": workspace_folder,
                "rootUri": workspace_uri,
                "capabilities": _client_capabilities(),
            }

            self._client.initialize(
                init_params,
                timeout_ms=self.config.startup_timeout_ms,
            )

            self._state = "running"
            self._start_time = time.time()
            self._crash_recovery_count = 0
            logger.debug("LSP server instance started: %s", self.name)
        except Exception as e:
            try:
                self._client.stop()
            except Exception:
                pass
            self._state = "error"
            self._last_error = e
            logger.exception("LSP server %s failed to start", self.name)
            raise

    def stop(self) -> None:
        if self._state in ("stopped", "stopping"):
            return
        try:
            self._state = "stopping"
            self._client.stop()
            self._state = "stopped"
            logger.debug("LSP server instance stopped: %s", self.name)
        except Exception as e:
            self._state = "error"
            self._last_error = e
            logger.exception("LSP server %s failed to stop", self.name)
            raise

    def restart(self) -> None:
        try:
            self.stop()
        except Exception as e:
            wrapped = RuntimeError(
                f"Failed to stop LSP server '{self.name}' during restart: {_error_message(e)}",
            )
            logger.exception("%s", wrapped)
            raise wrapped from e

        self._restart_count += 1
        max_restarts = self.config.max_restarts if self.config.max_restarts is not None else 3
        if self._restart_count > max_restarts:
            err = RuntimeError(
                f"Max restart attempts ({max_restarts}) exceeded for server '{self.name}'",
            )
            logger.error("%s", err)
            raise err

        try:
            self.start()
        except Exception as e:
            wrapped = RuntimeError(
                f"Failed to start LSP server '{self.name}' during restart "
                f"(attempt {self._restart_count}/{max_restarts}): {_error_message(e)}",
            )
            logger.exception("%s", wrapped)
            raise wrapped from e

    def is_healthy(self) -> bool:
        return self._state == "running" and self._client.is_initialized

    def send_request(self, method: str, params: Any) -> Any:
        if not self.is_healthy():
            msg = (
                f"Cannot send request to LSP server '{self.name}': server is {self._state}"
                + (f", last error: {self._last_error}" if self._last_error else "")
            )
            err = RuntimeError(msg)
            logger.error("%s", err)
            raise err

        last_exc: Exception | None = None
        for attempt in range(MAX_RETRIES_FOR_TRANSIENT_ERRORS + 1):
            try:
                return self._client.send_request(method, params)
            except JsonRpcException as e:
                last_exc = e
                code = getattr(e, "code", None)
                is_content_modified = code == LSP_ERROR_CONTENT_MODIFIED
                if is_content_modified and attempt < MAX_RETRIES_FOR_TRANSIENT_ERRORS:
                    delay_ms = RETRY_BASE_DELAY_MS * (2**attempt)
                    logger.debug(
                        "LSP request '%s' to '%s' ContentModified; retry in %sms",
                        method,
                        self.name,
                        delay_ms,
                    )
                    time.sleep(delay_ms / 1000.0)
                    continue
                break
            except Exception as e:
                last_exc = e
                break

        req_err = RuntimeError(
            f"LSP request '{method}' failed for server '{self.name}': "
            f"{_error_message(last_exc) if last_exc else 'unknown error'}",
        )
        logger.error("%s", req_err)
        raise req_err from last_exc

    def send_notification(self, method: str, params: Any) -> None:
        if not self.is_healthy():
            err = RuntimeError(
                f"Cannot send notification to LSP server '{self.name}': "
                f"server is {self._state}",
            )
            logger.error("%s", err)
            raise err
        try:
            self._client.send_notification(method, params)
        except Exception as e:
            wrapped = RuntimeError(
                f"LSP notification '{method}' failed for server '{self.name}': "
                f"{_error_message(e)}",
            )
            logger.exception("%s", wrapped)
            raise wrapped from e

    def on_notification(self, method: str, handler: Callable[[Any], None]) -> None:
        self._client.on_notification(method, handler)

    def on_request(
        self,
        method: str,
        handler: Callable[[Any], Any | Future[Any]],
    ) -> None:
        self._client.on_request(method, handler)


class LSPServerManager:
    """Routes paths to servers by extension; lazy-starts servers."""

    def __init__(self) -> None:
        self._servers: dict[str, LSPServerInstance] = {}
        self._extension_map: dict[str, list[str]] = {}
        self._opened_files: dict[str, str] = {}

    def initialize(self, servers: Mapping[str, ScopedLspServerConfig]) -> None:
        """Register server configs (idempotent replace: clears previous registrations)."""
        self._servers.clear()
        self._extension_map.clear()
        self._opened_files.clear()

        for server_name, config in servers.items():
            try:
                if not config.command:
                    raise ValueError(f"Server {server_name} missing required 'command'")
                if not config.extension_to_language:
                    raise ValueError(
                        f"Server {server_name} missing required 'extension_to_language'",
                    )

                for ext in config.extension_to_language:
                    key = ext.lower()
                    self._extension_map.setdefault(key, []).append(server_name)

                instance = LSPServerInstance(server_name, config)
                instance.on_request(
                    "workspace/configuration",
                    lambda p: [None] * len((p or {}).get("items") or []),
                )
                self._servers[server_name] = instance
            except Exception as e:
                logger.exception("Failed to initialize LSP server %s: %s", server_name, e)

        logger.debug("LSP manager initialized with %s servers", len(self._servers))

    def shutdown(self) -> None:
        to_stop = [
            (n, s)
            for n, s in self._servers.items()
            if s.state in ("running", "error")
        ]
        errors: list[str] = []
        for name, server in to_stop:
            try:
                server.stop()
            except Exception as e:
                errors.append(f"{name}: {_error_message(e)}")

        self._servers.clear()
        self._extension_map.clear()
        self._opened_files.clear()

        if errors:
            err = RuntimeError(
                f"Failed to stop {len(errors)} LSP server(s): {'; '.join(errors)}",
            )
            logger.error("%s", err)
            raise err

    def get_server_for_file(self, file_path: str) -> LSPServerInstance | None:
        ext = Path(file_path).suffix.lower()
        names = self._extension_map.get(ext)
        if not names:
            return None
        first = names[0]
        return self._servers.get(first)

    def ensure_server_started(self, file_path: str) -> LSPServerInstance | None:
        server = self.get_server_for_file(file_path)
        if server is None:
            return None
        if server.state in ("stopped", "error"):
            server.start()
        return server

    def send_request(self, file_path: str, method: str, params: Any) -> Any | None:
        server = self.ensure_server_started(file_path)
        if server is None:
            return None
        try:
            return server.send_request(method, params)
        except Exception as e:
            logger.exception(
                "LSP request failed for file %s method %s: %s",
                file_path,
                method,
                e,
            )
            raise

    def get_all_servers(self) -> dict[str, LSPServerInstance]:
        return dict(self._servers)

    def open_file(self, file_path: str, content: str) -> None:
        server = self.ensure_server_started(file_path)
        if server is None:
            return

        uri = Path(file_path).resolve().as_uri()
        if self._opened_files.get(uri) == server.name:
            logger.debug("LSP: file already open, skip didOpen for %s", file_path)
            return

        ext = Path(file_path).suffix.lower()
        language_id = server.config.extension_to_language.get(ext, "plaintext")

        server.send_notification(
            "textDocument/didOpen",
            {
                "textDocument": {
                    "uri": uri,
                    "languageId": language_id,
                    "version": 1,
                    "text": content,
                },
            },
        )
        self._opened_files[uri] = server.name
        logger.debug("LSP: didOpen %s (%s)", file_path, language_id)

    def change_file(self, file_path: str, content: str) -> None:
        server = self.get_server_for_file(file_path)
        if server is None or server.state != "running":
            self.open_file(file_path, content)
            return

        uri = Path(file_path).resolve().as_uri()
        if self._opened_files.get(uri) != server.name:
            self.open_file(file_path, content)
            return

        server.send_notification(
            "textDocument/didChange",
            {
                "textDocument": {"uri": uri, "version": 1},
                "contentChanges": [{"text": content}],
            },
        )
        logger.debug("LSP: didChange %s", file_path)

    def save_file(self, file_path: str) -> None:
        server = self.get_server_for_file(file_path)
        if server is None or server.state != "running":
            return
        uri = Path(file_path).resolve().as_uri()
        server.send_notification(
            "textDocument/didSave",
            {"textDocument": {"uri": uri}},
        )
        logger.debug("LSP: didSave %s", file_path)

    def close_file(self, file_path: str) -> None:
        server = self.get_server_for_file(file_path)
        if server is None or server.state != "running":
            return
        uri = Path(file_path).resolve().as_uri()
        server.send_notification(
            "textDocument/didClose",
            {"textDocument": {"uri": uri}},
        )
        self._opened_files.pop(uri, None)
        logger.debug("LSP: didClose %s", file_path)

    def is_file_open(self, file_path: str) -> bool:
        uri = Path(file_path).resolve().as_uri()
        return uri in self._opened_files


def map_lsp_severity(
    lsp_severity: int | None,
) -> Literal["Error", "Warning", "Info", "Hint"]:
    """Map LSP DiagnosticSeverity (1–4) to string labels."""
    if lsp_severity == 2:
        return "Warning"
    if lsp_severity == 3:
        return "Info"
    if lsp_severity == 4:
        return "Hint"
    return "Error"


def format_diagnostics_for_attachment(
    params: dict[str, Any],
) -> list[dict[str, Any]]:
    """Convert ``textDocument/publishDiagnostics`` params to a compact file+diagnostics list."""
    raw_uri = params.get("uri", "")
    try:
        uri = (
            _file_uri_to_path(raw_uri)
            if isinstance(raw_uri, str) and raw_uri.startswith("file:")
            else str(raw_uri)
        )
    except Exception:
        uri = str(raw_uri)

    out_diags = []
    for d in params.get("diagnostics", []) or []:
        rng = d.get("range") or {}
        start = (rng.get("start") or {})
        end = (rng.get("end") or {})
        code = d.get("code")
        out_diags.append(
            {
                "message": d.get("message", ""),
                "severity": map_lsp_severity(d.get("severity")),
                "range": {
                    "start": {
                        "line": start.get("line", 0),
                        "character": start.get("character", 0),
                    },
                    "end": {
                        "line": end.get("line", 0),
                        "character": end.get("character", 0),
                    },
                },
                "source": d.get("source"),
                "code": None if code is None else str(code),
            },
        )

    return [{"uri": uri, "diagnostics": out_diags}]


def register_publish_diagnostics_handler(
    manager: LSPServerManager,
    on_diagnostics: Callable[[str, list[dict[str, Any]]], None],
) -> dict[str, Any]:
    """Register ``textDocument/publishDiagnostics`` on every known server instance.

    ``on_diagnostics`` receives ``(server_name, files)`` where ``files`` matches
    :func:`format_diagnostics_for_attachment` output shape.
    """
    registration_errors: list[dict[str, str]] = []
    success = 0
    servers_map = manager.get_all_servers()
    total_servers = len(servers_map)
    for server_name, inst in servers_map.items():
        try:

            def _handler(
                params: Any,
                *,
                sn: str = server_name,
            ) -> None:
                if not isinstance(params, dict) or "uri" not in params:
                    logger.warning("Invalid diagnostic params from %s", sn)
                    return
                files = format_diagnostics_for_attachment(params)
                if not files or not files[0].get("diagnostics"):
                    return
                on_diagnostics(sn, files)

            inst.on_notification("textDocument/publishDiagnostics", _handler)
            success += 1
        except Exception as e:
            registration_errors.append(
                {"serverName": server_name, "error": _error_message(e)},
            )
            logger.exception("Failed to register diagnostics handler for %s", server_name)

    return {
        "totalServers": total_servers,
        "successCount": success,
        "registrationErrors": registration_errors,
    }


def create_lsp_server_manager() -> LSPServerManager:
    """Return a new manager instance (parity with TS ``createLSPServerManager``)."""
    return LSPServerManager()
