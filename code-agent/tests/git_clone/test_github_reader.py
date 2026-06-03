import os

import pytest

from agent.git_clone.github_reader import GitHubReader

pytestmark = pytest.mark.integration


def test_repo_download_with_temp_dir():
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        pytest.skip("GITHUB_TOKEN not set")

    config = {"token": token}
    test_repos = ["https://github.com/octocat/Hello-World"]
    reader = GitHubReader(config)

    try:
        for repo_url in test_repos:
            reader.query(repo_url, branch="master", overwrite=True)
    finally:
        reader.close()
