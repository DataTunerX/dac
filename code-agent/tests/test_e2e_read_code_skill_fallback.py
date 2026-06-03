"""Tests for E2E-only read-code.zip fallback (not production skill_download)."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

from scripts.e2e_read_code_skill_gitee import (
    E2E_READ_CODE_ZIP_FALLBACK,
    ensure_read_code_skill_for_e2e,
)


def test_e2e_fallback_zip_path_exists():
    assert E2E_READ_CODE_ZIP_FALLBACK.name == "read-code.zip"
    assert E2E_READ_CODE_ZIP_FALLBACK.is_file(), f"missing {E2E_READ_CODE_ZIP_FALLBACK}"


def test_ensure_read_code_skill_for_e2e_uses_local_zip_when_hub_fails():
    if not E2E_READ_CODE_ZIP_FALLBACK.is_file():
        return

    with tempfile.TemporaryDirectory() as tmp:
        dest_dir = Path(tmp)
        with patch(
            "agent.skill_download.download_skills",
            return_value=[],
        ):
            paths = ensure_read_code_skill_for_e2e(
                dest_dir,
                skill_hub_url="http://127.0.0.1:1",
                timeout=1.0,
            )
        assert len(paths) == 1
        assert paths[0] == dest_dir / "read-code.zip"
        assert paths[0].stat().st_size == E2E_READ_CODE_ZIP_FALLBACK.stat().st_size
