import os
import tempfile
from pathlib import Path
from ..gitlab_reader import GitLabReader

# python -m data_sinkers.readers.code.gitlab_reader_test

def test_repo_download_with_temp_dir():
    print("\n=== Testing GitLab repo download with temp directory ===")
    
    config = {
        'token': os.getenv('GITLAB_TOKEN')
    }

    test_repos = [
        'https://gitlab.com/gitlab-org/gitlab-test'
    ]
    
    reader = GitLabReader(config)
    
    try:
        for repo_url in test_repos:
            print(f"\nTesting repository: {repo_url}")
            
            repo_path = reader.query(repo_url, branch='main', overwrite=True)
            
            if repo_path:
                print(f"Download completed: {repo_path}")
                assert os.path.exists(repo_path), "Downloaded repository path should exist"
                print("✓ Repository download successful")
            else:
                print("✗ Download failed")
    finally:
        reader.close()
        print("\nConnection closed and temp directories cleaned up")

def main():
    print("=== Starting GitLabReader Tests ===")

    token = os.getenv('GITLAB_TOKEN')
    if not token:
        print("Warning: GITLAB_TOKEN environment variable not set")
        print("Please set GITLAB_TOKEN environment variable to run tests")
        return

    test_repo_download_with_temp_dir()

    print("\n=== All tests completed ===")

if __name__ == "__main__":
    main()