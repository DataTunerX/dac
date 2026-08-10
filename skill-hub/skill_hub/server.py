"""Skill-Hub HTTP service entrypoint.

Creates the FastAPI app, wires up the lifespan (index init + auto-watch), and
registers the HTTP routes from :mod:`skill_hub.api`. The CLI entrypoint
(``skill-hub``) lives here.

Environment variables
---------------------
SKILLS_DIR
    Directory holding ``{namespace}/{name}-{version}.zip`` skill packs.
    Defaults to ``/app/skills/``.
SKILLS_AUTO_RELOAD
    When ``1`` (default), watch ``SKILLS_DIR`` and auto-rescan on change.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager

import click
import uvicorn
from fastapi import FastAPI
from uvicorn.config import LOGGING_CONFIG

from .api import register_exception_handlers, router
from .index import SkillIndex
from .watcher import watch_skills_dir

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

DEFAULT_SKILLS_DIR = "/app/skills/"

# Global index instance, populated during lifespan startup.
index: SkillIndex | None = None


def _env_bool(name: str, default: bool) -> bool:
    """Parse a boolean from an environment variable (``1/0|true/false|yes/no``)."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    global index
    skills_dir = os.getenv("SKILLS_DIR", DEFAULT_SKILLS_DIR)
    index = SkillIndex(skills_dir)
    index.reload()
    watcher: asyncio.Task[None] | None = None
    if _env_bool("SKILLS_AUTO_RELOAD", True):
        watcher = asyncio.create_task(watch_skills_dir(index))
    else:
        logger.info("[SkillHub] auto-reload is disabled (SKILLS_AUTO_RELOAD=0)")
    try:
        yield
    finally:
        if watcher is not None:
            watcher.cancel()
            try:
                await watcher
            except asyncio.CancelledError:
                pass
        if index is not None:
            index.close()
        logger.info("[SkillHub] shutdown complete")


def create_app() -> FastAPI:
    """Build the FastAPI app with routes and exception handlers."""
    app = FastAPI(title="skill-hub", version="0.1.0", lifespan=lifespan)
    app.include_router(router)
    register_exception_handlers(app)
    return app


app = create_app()


@click.command()
@click.option("--host", default="0.0.0.0", help="Host to bind")
@click.option("--port", default=8000, type=int, help="Port to bind")
@click.option(
    "--skills-dir",
    default=None,
    help="Directory containing skill *.zip packs (overrides SKILLS_DIR env)",
)
def main(host: str, port: int, skills_dir: str | None) -> None:
    if skills_dir:
        os.environ["SKILLS_DIR"] = skills_dir

    log_config = LOGGING_CONFIG
    log_config["formatters"]["access"]["fmt"] = (
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    log_config["formatters"]["default"]["fmt"] = (
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    logger.info(
        "[SkillHub] starting on %s:%d skills_dir=%s",
        host,
        port,
        os.getenv("SKILLS_DIR", DEFAULT_SKILLS_DIR),
    )
    try:
        uvicorn.run(app, host=host, port=port, log_config=log_config)
    except Exception:
        logger.exception("[SkillHub] server startup failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
