import os
import requests
import zipfile
import io
import shutil
from typing import Optional, Dict, Any
import json
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


class GitHubClient:
    """
    GitHub client for downloading repository code
    """
    
    def __init__(self, token: Optional[str] = None, base_url: str = "https://api.github.com"):
        """
        Initialize GitHub client
        
        Args:
            token: GitHub personal access token for private repos or higher API limits
            base_url: GitHub API base URL
        """
        self.base_url = base_url.rstrip('/')
        self.headers = {
            'Accept': 'application/vnd.github.v3+json',
            'User-Agent': 'GitHub-Client/1.0'
        }
        
        if token:
            self.headers['Authorization'] = f'token {token}'
    
    def download_repository(self, owner: str, repo: str, target_dir: str, 
                          branch: str = "main", overwrite: bool = True) -> str:
        """
        Download GitHub repository to specified directory
        
        Args:
            owner: Repository owner
            repo: Repository name
            target_dir: Target directory path
            branch: Branch name, defaults to main
            overwrite: Whether to overwrite existing directory
            
        Returns:
            Full path to downloaded content
            
        Raises:
            Exception: Raises exception when download fails
        """
        # Create target directory
        target_path = Path(target_dir) / f"{repo}-{branch}"
        
        # Check if directory exists
        if target_path.exists():
            if overwrite:
                shutil.rmtree(target_path)
            else:
                return str(target_path)
        
        target_path.mkdir(parents=True, exist_ok=True)
        
        try:
            # Method 1: Download via zip (recommended)
            return self._download_via_zip(owner, repo, branch, target_path)
        except Exception as e:
            logger.warning(f"Zip download failed: {e}, trying git clone method...")
            # Method 2: Via git clone (fallback)
            return self._download_via_git(owner, repo, branch, target_path)
    
    def _download_via_zip(self, owner: str, repo: str, branch: str, target_path: Path) -> str:
        """
        Download repository via zip file
        """
        # GitHub zip download URL
        zip_url = f"https://github.com/{owner}/{repo}/archive/refs/heads/{branch}.zip"
        
        logger.info(f"[CODE DOWNLOAD] Downloading repository from {zip_url}...")
        
        temp_dir = None
        try:
            response = requests.get(zip_url, headers=self.headers, stream=True, timeout=30)
            response.raise_for_status()

            temp_dir = target_path.parent / f"temp-{repo}"
            temp_dir.mkdir(parents=True, exist_ok=True)

            with zipfile.ZipFile(io.BytesIO(response.content)) as zip_file:
                if zip_file.testzip() is not None:
                    raise zipfile.BadZipFile("Downloaded zip file is corrupted")
                
                zip_file.extractall(temp_dir)
                
                extracted_dirs = list(temp_dir.iterdir())
                if len(extracted_dirs) == 1 and extracted_dirs[0].is_dir():
                    actual_dir = extracted_dirs[0]
                    if target_path.exists():
                        shutil.rmtree(target_path)
                    shutil.move(str(actual_dir), str(target_path))
                    logger.info(f"[CODE DOWNLOAD] Repository successfully downloaded to: {target_path}")
                    return str(target_path)
                else:
                    raise Exception(f"Unexpected directory structure in zip file. Found: {[str(d) for d in extracted_dirs]}")
                    
        except requests.exceptions.RequestException as e:
            logger.error(f"[CODE DOWNLOAD] Network error during download: {e}")
            raise Exception(f"Failed to download repository: {e}")
        
        except zipfile.BadZipFile as e:
            logger.warning(f"[CODE DOWNLOAD] Invalid zip file: {e}")
            raise Exception(f"Downloaded file is not a valid zip archive: {e}")
        
        except OSError as e:
            logger.error(f"[CODE DOWNLOAD] File system error: {e}")
            raise Exception(f"File operation failed: {e}")
        
        except Exception as e:
            logger.error(f"[CODE DOWNLOAD] Unexpected error during zip download: {e}")
            raise Exception(f"Zip download failed: {e}")
        
        finally:
            if temp_dir and temp_dir.exists():
                try:
                    shutil.rmtree(temp_dir)
                    logger.debug(f"[CODE DOWNLOAD] Cleaned up temporary directory: {temp_dir}")
                except Exception as e:
                    logger.warning(f"[CODE DOWNLOAD] Failed to clean up temporary directory {temp_dir}: {e}")
    
    def _download_via_git(self, owner: str, repo: str, branch: str, target_path: Path) -> str:
        """
        Download repository via git clone (requires git installed on system)
        """
        import subprocess
        
        repo_url = f"https://github.com/{owner}/{repo}.git"
        
        logger.info(f"[CODE DOWNLOAD] Downloading repository via git clone from {repo_url}...")
        
        try:
            # Use subprocess to execute git command
            result = subprocess.run([
                'git', 'clone', '--branch', branch, '--depth', '1', 
                repo_url, str(target_path)
            ], capture_output=True, text=True, check=True)
            
            logger.info(f"[CODE DOWNLOAD] Git clone successful: {target_path}")
            return str(target_path)
            
        except subprocess.CalledProcessError as e:
            raise Exception(f"Git clone failed: {e.stderr}")
        except FileNotFoundError:
            raise Exception("Git command not found in system, please install git or use another download method")
    
    def get_repository_info(self, owner: str, repo: str) -> Dict[str, Any]:
        """
        Get repository information
        
        Args:
            owner: Repository owner
            repo: Repository name
            
        Returns:
            Repository information dictionary
        """
        url = f"{self.base_url}/repos/{owner}/{repo}"
        
        response = requests.get(url, headers=self.headers)
        response.raise_for_status()
        
        return response.json()
    
    def list_branches(self, owner: str, repo: str) -> list:
        """
        Get all branches of a repository
        
        Args:
            owner: Repository owner
            repo: Repository name
            
        Returns:
            List of branches
        """
        url = f"{self.base_url}/repos/{owner}/{repo}/branches"
        
        response = requests.get(url, headers=self.headers)
        response.raise_for_status()
        
        branches = response.json()
        return [branch['name'] for branch in branches]
    
    def download_latest_release(self, owner: str, repo: str, target_dir: str) -> str:
        """
        Download latest release
        
        Args:
            owner: Repository owner
            repo: Repository name
            target_dir: Target directory
            
        Returns:
            Full path to downloaded content
        """
        # Get latest release information
        url = f"{self.base_url}/repos/{owner}/{repo}/releases/latest"
        response = requests.get(url, headers=self.headers)
        response.raise_for_status()
        
        release_info = response.json()
        
        # Download source code zip
        zipball_url = release_info['zipball_url']
        
        target_path = Path(target_dir) / f"{repo}-{release_info['tag_name']}"
        target_path.mkdir(parents=True, exist_ok=True)
        
        return self._download_zip_from_url(zipball_url, target_path)
    
    def _download_zip_from_url(self, zip_url: str, target_path: Path) -> str:
        """
        Download zip file from URL and extract
        """
        response = requests.get(zip_url, headers=self.headers, stream=True)
        response.raise_for_status()
        
        with zipfile.ZipFile(io.BytesIO(response.content)) as zip_file:
            zip_file.extractall(target_path)
        
        logger.info(f"[CODE DOWNLOAD] Files downloaded to: {target_path}")
        return str(target_path)


# Usage examples and utility functions
def create_github_client(token: Optional[str] = None) -> GitHubClient:
    """
    Create GitHub client, supports reading token from environment variables
    
    Returns:
        GitHubClient instance
    """
    if not token:
        # Try to read from environment variable
        token = os.getenv('GITHUB_TOKEN')
    
    return GitHubClient(token=token)


def download_repo_simple(repo_url: str, target_dir: str, 
                        branch: str = "main", token: Optional[str] = None) -> str:
    """
    Simplified repository download function
    
    Args:
        repo_url: GitHub repository URL (e.g., https://github.com/owner/repo)
        target_dir: Target directory
        branch: Branch name
        token: GitHub token
        
    Returns:
        Full path to downloaded content
    """
    # Parse owner and repo from URL
    parts = repo_url.rstrip('/').split('/')
    if len(parts) < 2:
        raise ValueError("Invalid GitHub repository URL")
    
    owner = parts[-2]
    repo = parts[-1]
    
    client = create_github_client(token)
    return client.download_repository(owner, repo, target_dir, branch)


# Usage example
if __name__ == "__main__":
    # Example usage
    client = create_github_client()
    
    # Download public repository
    try:
        # Method 1: Use client directly
        download_path = client.download_repository(
            owner="octocat", 
            repo="Hello-World", 
            target_dir="./downloads",
            branch="master"
        )
        logger.info(f"[CODE DOWNLOAD] Code downloaded to: {download_path}")
        
        # # Method 2: Use simplified function
        # download_path = download_repo_simple(
        #     repo_url="https://github.com/octocat/Hello-World",
        #     target_dir="./downloads",
        #     branch="master"
        # )
        # print(f"Code downloaded to: {download_path}")
        
        # # Get repository info
        # repo_info = client.get_repository_info("octocat", "Hello-World")
        # print(f"Repository description: {repo_info.get('description', 'No description')}")
        
        # # Get branch list
        # branches = client.list_branches("octocat", "Hello-World")
        # print(f"Available branches: {branches}")
        
    except Exception as e:
        logger.error(f"[CODE DOWNLOAD] Download failed: {e}")