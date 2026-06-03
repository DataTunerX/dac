import os

import pytest

from agent.git_clone.gitlab_reader import GitLabReader

pytestmark = pytest.mark.integration


def test_repo_download_with_temp_dir():
    token = os.getenv("GITLAB_TOKEN")
    if not token:
        pytest.skip("GITLAB_TOKEN not set")

    config = {"token": token}
    test_repos = ["https://gitlab.com/gitlab-org/gitlab-test"]
    reader = GitLabReader(config)

    try:
        for repo_url in test_repos:
            repo_path = reader.query(repo_url, branch="main", overwrite=True)
            assert repo_path, f"Download failed for {repo_url}"
            assert os.path.exists(repo_path), "Downloaded repository path should exist"
    finally:
        reader.close()
