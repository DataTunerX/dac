import os
from pathlib import Path

from .gitlab_reader import GitLabReader

# Run from repo `dac/data-sinkers`:
#   PYTHONPATH=. python -m data_sinkers.readers.code.gitlab_reader_test
#
# Requires GITLAB_TOKEN if the project is private.

DEFAULT_REPO_URL = "http://10.17.0.41:31519/root/test-code"

# Tests only: same role as container /app/download_dir, but use this script's directory so
# local runs don't need /app. Production leaves DEFAULT_CODE_DOWNLOAD_DIR unset → /app/download_dir.


def _apply_test_download_dir() -> None:
    os.environ["DEFAULT_CODE_DOWNLOAD_DIR"] = str(Path(__file__).resolve().parent)


def test_repo_download_with_temp_dir(repo_url: str = DEFAULT_REPO_URL) -> None:
    print("\n=== Testing GitLab repo download with temp directory ===")

    _apply_test_download_dir()

    # codeRepoPath must match the GitLab instance so API base URL is derived correctly.
    config = {
        "codeRepoPath": repo_url,
        "token": os.getenv("GITLAB_TOKEN") or "",
    }

    reader = GitLabReader(config)

    try:
        print(f"\nTesting repository: {repo_url}")

        repo_path = reader.query(repo_url, branch="main", overwrite=True)

        if repo_path:
            print(f"Download completed: {repo_path}")
            assert os.path.exists(repo_path), "Downloaded repository path should exist"
            print("✓ Repository download successful")
        else:
            print("✗ Download failed")
    finally:
        reader.close()
        print("\nConnection closed and temp directories cleaned up")


def main() -> None:
    print("=== Starting GitLabReader Tests ===")

    _apply_test_download_dir()

    repo_url = os.getenv("GITLAB_TEST_REPO_URL", DEFAULT_REPO_URL)
    print(f"Repo URL: {repo_url}")

    token = os.getenv("GITLAB_TOKEN")
    if not token:
        print(
            "Warning: GITLAB_TOKEN not set — private repos will fail; "
            "set GITLAB_TOKEN if needed."
        )

    test_repo_download_with_temp_dir(repo_url)

    print("\n=== All tests completed ===")


if __name__ == "__main__":
    main()
