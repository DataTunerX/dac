import os
import tempfile
from pathlib import Path
from data_sinkers.readers.code.gitee_reader import GiteeReader

# python -m data_sinkers.readers.code.gitee_reader_test

def test_repo_download_with_temp_dir():
    print("\n=== Testing repo download with temp directory ===")
    
    os.environ['DEFAULT_CODE_DOWNLOAD_DIR'] = '/Users/james/daocloud/code/test'

    config = {
        'token': os.getenv('GITHUB_TOKEN','')
    }

    test_repos = [
        'https://gitee.com/jamesxiong888/test-code.git'
    ]
    
    reader = GiteeReader(config)
    
    try:
        for repo_url in test_repos:
            print(f"\nTesting repository: {repo_url}")
            
            docs = reader.query(repo_url, branch='main', overwrite=True)
            
            print(f"Download completed")
    finally:
        reader.close()
        print("\nConnection closed and temp directories cleaned up")

def main():
    print("=== Starting GiteeReader Tests ===")

    token = os.getenv('GITHUB_TOKEN')
    if not token:
        print("Warning: GITHUB_TOKEN environment variable not set")
        print("Some tests may fail due to rate limiting")

    test_repo_download_with_temp_dir()

    print("\n=== All tests completed ===")

if __name__ == "__main__":
    main()