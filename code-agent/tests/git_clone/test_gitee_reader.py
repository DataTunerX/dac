import os

import pytest

from agent.git_clone.gitee_reader import GiteeReader

pytestmark = pytest.mark.integration


def test_repo_download_with_temp_dir():
    token = os.getenv("GITEE_TOKEN") or os.getenv("GITHUB_TOKEN")
    if not token:
        pytest.skip("GITEE_TOKEN or GITHUB_TOKEN not set")

    config = {"token": token}
    test_repos = ["https://gitee.com/jamesxiong888/test-code.git"]
    reader = GiteeReader(config)

    try:
        for repo_url in test_repos:
            reader.query(repo_url, branch="main", overwrite=True)
    finally:
        reader.close()
