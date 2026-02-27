import os
import tempfile
from pathlib import Path
from data_sinkers.readers.code.github_reader import GitHubReader

# python -m data_sinkers.readers.code.github_reader_test

def test_repo_download_with_temp_dir():
    print("\n=== Testing repo download with temp directory ===")
    
    config = {
        'token': os.getenv('GITHUB_TOKEN')
    }

    test_repos = [
        'https://github.com/octocat/Hello-World'
    ]
    
    reader = GitHubReader(config)
    
    try:
        for repo_url in test_repos:
            print(f"\nTesting repository: {repo_url}")
            
            docs = reader.query(repo_url, branch='master', overwrite=True)
            
            print(f"Download completed")
    finally:
        reader.close()
        print("\nConnection closed and temp directories cleaned up")

def main():
    print("=== Starting GitHubReader Tests ===")

    token = os.getenv('GITHUB_TOKEN')
    if not token:
        print("Warning: GITHUB_TOKEN environment variable not set")
        print("Some tests may fail due to rate limiting")

    test_repo_download_with_temp_dir()

    print("\n=== All tests completed ===")

if __name__ == "__main__":
    main()