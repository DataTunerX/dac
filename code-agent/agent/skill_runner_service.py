"""Process-wide SkillRunner lifecycle for code-agent (skill-sdk route B).

Cluster defaults (no env required):
- ``LOCAL_SKILLS_DIR``: ``/app/skills/`` (same as skill-hub download target)
- skills loaded at startup: ``read-code`` (internal only)
- LSP binaries: pre-installed in Docker image; ``SKILL_SDK_LSP_SERVERS`` lists only
  servers whose languages appear in cloned repos (see ``lsp_repo_detect.py``).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time as _time
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

try:
    from skill_sdk.skill.runner import SkillRunner
except ImportError:  # pragma: no cover
    SkillRunner = None  # type: ignore[assignment,misc]

try:
    from skill_sdk.tool.code_execution import CodeExecution
except ImportError:  # pragma: no cover
    CodeExecution = None  # type: ignore[assignment,misc]

from model_sdk import ModelManager

from .lsp_repo_detect import (
    LspServerTemplate,
    select_lsp_servers_for_repos,
    select_lsp_servers_with_workspaces,
)

logger = logging.getLogger(__name__)

LOCAL_SKILLS_ENABLED = os.getenv("ENABLE_LOCAL_SKILLS", "true").strip().lower() in (
    "1", "true", "yes",
)
LOCAL_SKILLS_DIR = os.getenv("LOCAL_SKILLS_DIR", "/app/skills/").strip()
SKILL_FALLBACK_ON_EMPTY = os.getenv("SKILL_FALLBACK_ON_EMPTY", "true").strip().lower() in (
    "1", "true", "yes",
)

try:
    LOCAL_SKILL_MAX_STEPS = int(os.getenv("LOCAL_SKILL_MAX_STEPS", "50"))
except (TypeError, ValueError):
    LOCAL_SKILL_MAX_STEPS = 50
try:
    LOCAL_SKILL_CMD_TIMEOUT_SEC = int(os.getenv("LOCAL_SKILL_CMD_TIMEOUT_SEC", "30"))
except (TypeError, ValueError):
    LOCAL_SKILL_CMD_TIMEOUT_SEC = 30
try:
    LOCAL_SKILL_MAX_CONCURRENCY = int(os.getenv("LOCAL_SKILL_MAX_CONCURRENCY", "8"))
except (TypeError, ValueError):
    LOCAL_SKILL_MAX_CONCURRENCY = 8

ENABLE_CODE_EXEC = os.getenv("ENABLE_CODE_EXEC", "true").strip().lower() in ("1", "true", "yes")
try:
    CODE_EXEC_MAX_RETRIES = int(os.getenv("CODE_EXEC_MAX_RETRIES", "3"))
except (TypeError, ValueError):
    CODE_EXEC_MAX_RETRIES = 3


def build_lsp_server_configs(workspace_roots: Sequence[str]) -> dict[str, LspServerTemplate]:
    """Return LSP configs required by repo content and available on PATH."""
    return select_lsp_servers_for_repos(workspace_roots)


def build_skill_sdk_lsp_servers_json(
    workspace_roots: Sequence[str],
    *,
    repo_root: str,
) -> str:
    """Build ``SKILL_SDK_LSP_SERVERS`` for repo languages detected under ``workspace_roots``.

    ``workspaceFolder`` on every entry is set to ``repo_root`` (same as ``WORKSPACE_FOLDER``).
    skill_sdk applies ``WORKSPACE_FOLDER`` to all LSP servers at startup.
    """
    servers = select_lsp_servers_with_workspaces(workspace_roots)
    root = str(Path(repo_root).resolve())
    payload: Dict[str, Any] = {}
    for entry in servers:
        cfg = entry.template
        payload[entry.name] = {
            "command": cfg.command,
            "args": list(cfg.args or []),
            "extensionToLanguage": dict(cfg.extension_to_language or {}),
            "startupTimeoutMs": cfg.startup_timeout_ms or 120_000,
            "workspaceFolder": root,
        }
    return json.dumps(payload, ensure_ascii=False)


def configure_skill_runtime_env(code_paths: Dict[str, str]) -> None:
    """Set ``WORKSPACE_FOLDER`` / ``SKILL_SDK_LSP_SERVERS`` for read-code skill.

    skill_sdk applies ``WORKSPACE_FOLDER`` as the code repo root for **every** LSP server
    (see read-code SKILL.md). code-agent sets it to the cloned repository root and builds
    ``SKILL_SDK_LSP_SERVERS`` with the same ``workspaceFolder`` on each entry. Which LSP
    binaries to start is decided by scanning repo languages (``lsp_repo_detect``).
    """
    if not code_paths:
        return
    workspaces = [str(Path(p).resolve()) for p in code_paths.values() if p]
    if not workspaces:
        return
    repo_root = workspaces[0]
    # Always refresh so each clone / request uses the correct repo root for grep/glob.
    os.environ["WORKSPACE_FOLDER"] = repo_root
    if not os.environ.get("SKILL_SDK_LSP_SERVERS", "").strip():
        lsp_json = build_skill_sdk_lsp_servers_json(workspaces, repo_root=repo_root)
        if lsp_json and lsp_json != "{}":
            os.environ["SKILL_SDK_LSP_SERVERS"] = lsp_json
            try:
                parsed = json.loads(lsp_json)
                for name, cfg in parsed.items():
                    ws = cfg.get("workspaceFolder", "")
                    logger.info(
                        "[CodeAgent][Skill] LSP %s workspaceFolder=%s",
                        name,
                        ws,
                    )
            except json.JSONDecodeError:
                pass
            logger.info(
                "[CodeAgent][Skill] SKILL_SDK_LSP_SERVERS configured repo_root=%s scan_roots=%s",
                repo_root,
                workspaces,
            )
        else:
            logger.info(
                "[CodeAgent][Skill] No LSP servers matched repo languages or binaries missing; "
                "read-code lsp tool may be unavailable"
            )


class CodeAgentSkillRunnerService:
    """Lazy process-wide ``SkillRunner`` holder for ``CodeAgentExecutor``."""

    def __init__(
        self,
        *,
        provider: str,
        api_key: Optional[str],
        base_url: str,
        model: str,
        temperature: float,
    ):
        self.provider = provider
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.temperature = temperature
        self._runner: Optional["SkillRunner"] = None
        self._initialised = False
        self._lock = asyncio.Lock()

    @property
    def runner(self) -> Optional["SkillRunner"]:
        return self._runner

    def _build_llm(self) -> Any:
        mgr = ModelManager()
        extra_body = (
            {"enable_thinking": False}
            if os.getenv("ENABLE_THINKING_PARAM", "true").strip().lower()
            not in ("false", "0", "no")
            else {}
        )
        return mgr.get_llm(
            provider=self.provider,
            api_key=self.api_key,
            base_url=self.base_url,
            model=self.model,
            temperature=self.temperature,
            stream=False,
            extra_body=extra_body,
        )

    def _build_code_execution(self, llm: Any) -> Any | None:
        if not ENABLE_CODE_EXEC or CodeExecution is None:
            return None
        return CodeExecution(llm=llm, max_retries=CODE_EXEC_MAX_RETRIES)

    def _init_sync(self) -> Optional["SkillRunner"]:
        if not LOCAL_SKILLS_ENABLED:
            logger.info("[CodeAgent][Skill] ENABLE_LOCAL_SKILLS=false — skip SkillRunner")
            return None
        if SkillRunner is None:
            logger.warning(
                "[CodeAgent][Skill] skill_sdk not importable — SkillRunner disabled"
            )
            return None

        logger.info(
            "[CodeAgent][Skill] bootstrapping SkillRunner dir=%s max_steps=%d timeout=%d",
            LOCAL_SKILLS_DIR or "(unset)",
            LOCAL_SKILL_MAX_STEPS,
            LOCAL_SKILL_CMD_TIMEOUT_SEC,
        )
        t0 = _time.perf_counter()
        try:
            llm = self._build_llm()
            code_execution = self._build_code_execution(llm)
            try:
                runner = SkillRunner(
                    llm=llm,
                    max_steps=LOCAL_SKILL_MAX_STEPS,
                    cmd_timeout_sec=LOCAL_SKILL_CMD_TIMEOUT_SEC,
                    max_concurrency=LOCAL_SKILL_MAX_CONCURRENCY,
                    code_execution=code_execution,
                )
            except TypeError:
                runner = SkillRunner(
                    llm=llm,
                    max_steps=LOCAL_SKILL_MAX_STEPS,
                    cmd_timeout_sec=LOCAL_SKILL_CMD_TIMEOUT_SEC,
                    code_execution=code_execution,
                )

            if LOCAL_SKILLS_DIR:
                loaded = runner.load_from_dir(LOCAL_SKILLS_DIR) or []
                names = [
                    str(getattr(s, "name", "") or "").strip()
                    for s in loaded
                    if str(getattr(s, "name", "") or "").strip()
                ]
                logger.info(
                    "[CodeAgent][Skill] load_from_dir: count=%d path=%s skills=%s",
                    len(loaded),
                    LOCAL_SKILLS_DIR,
                    ", ".join(names) if names else "(none)",
                )
            else:
                logger.warning("[CodeAgent][Skill] LOCAL_SKILLS_DIR empty — no skills loaded")

            logger.info(
                "[CodeAgent][Skill] ready in %dms (model=%s)",
                int((_time.perf_counter() - t0) * 1000),
                self.model,
            )
            return runner
        except Exception:  # noqa: BLE001
            logger.exception("[CodeAgent][Skill] SkillRunner init failed")
            return None

    def preload(self) -> Optional["SkillRunner"]:
        if self._initialised:
            return self._runner
        self._runner = self._init_sync()
        self._initialised = True
        return self._runner

    async def ensure(self) -> Optional["SkillRunner"]:
        if self._initialised:
            return self._runner
        async with self._lock:
            if self._initialised:
                return self._runner
            self._runner = await asyncio.to_thread(self._init_sync)
            self._initialised = True
        return self._runner

    def shutdown(self) -> None:
        runner, self._runner = self._runner, None
        self._initialised = True
        if runner is not None:
            logger.info("[CodeAgent][Skill] closing SkillRunner …")
            try:
                runner.close()
            except Exception:  # noqa: BLE001
                logger.exception("[CodeAgent][Skill] SkillRunner.close() raised")
