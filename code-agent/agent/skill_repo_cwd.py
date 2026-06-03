"""Run read-code skill tools with CWD at the cloned repo root (code-agent only).

skill_sdk grep/glob use ``os.getcwd()`` as search root. In containers the process
CWD is often ``/``; we temporarily chdir to ``code_paths`` under a lock so
concurrent requests do not clobber each other's CWD.
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Sequence

logger = logging.getLogger(__name__)

_skill_repo_cwd_lock = asyncio.Lock()


def resolve_primary_repo_root(code_paths: Sequence[str]) -> str | None:
    for raw in code_paths:
        if not raw:
            continue
        p = Path(raw).expanduser().resolve()
        if p.is_dir():
            return str(p)
    return None


@asynccontextmanager
async def use_code_repo_cwd(code_paths: Sequence[str]):
    """Temporarily chdir to the primary clone root for skill_sdk tool calls."""
    repo = resolve_primary_repo_root(code_paths)
    if not repo:
        yield None
        return

    async with _skill_repo_cwd_lock:
        original = os.getcwd()
        prev_workspace = os.environ.get("WORKSPACE_FOLDER")
        try:
            os.chdir(repo)
            os.environ["WORKSPACE_FOLDER"] = repo
            logger.debug("[SkillRepoCwd] chdir -> %s", repo)
            yield repo
        finally:
            os.chdir(original)
            if prev_workspace is None:
                os.environ.pop("WORKSPACE_FOLDER", None)
            else:
                os.environ["WORKSPACE_FOLDER"] = prev_workspace
            logger.debug("[SkillRepoCwd] chdir restored -> %s", original)
