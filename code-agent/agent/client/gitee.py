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


class GiteeClient:
    """
    Gitee client for downloading repository code
    """
    
    def __init__(self, token: Optional[str] = None, base_url: str = "https://gitee.com/api/v5"):
        """
        Initialize Gitee client
        
        Args:
            token: Gitee personal access token for private repos or higher API limits
            base_url: Gitee API base URL
        """
        self.base_url = base_url.rstrip('/')
        self.headers = {
            'Content-Type': 'application/json;charset=UTF-8',
            'User-Agent': 'Gitee-Client/1.0'
        }
        
        if token:
            self.headers['Authorization'] = f'Bearer {token}'
    
    def download_repository(self, owner: str, repo: str, target_dir: str, 
                          branch: str = "master", overwrite: bool = True) -> str:
        """
        Download Gitee repository to specified directory
        
        Args:
            owner: Repository owner
            repo: Repository name
            target_dir: Target directory path
            branch: Branch name, defaults to master (Gitee usually uses master)
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
        # Gitee zip download URL
        zip_url = f"https://gitee.com/{owner}/{repo}/repository/archive/{branch}.zip"
        
        logger.info(f"[CODE DOWNLOAD] Downloading repository from {zip_url}...")
        
        temp_dir = None
        try:
            # Gitee doesn't require authentication for public repo zip downloads
            response = requests.get(zip_url, stream=True, timeout=30)
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
                    # Gitee might have different zip structure
                    # Move all extracted content directly
                    for item in temp_dir.iterdir():
                        dest = target_path / item.name
                        if item.is_dir():
                            shutil.move(str(item), str(dest))
                        else:
                            shutil.move(str(item), str(dest))
                    logger.info(f"[CODE DOWNLOAD] Repository successfully downloaded to: {target_path}")
                    return str(target_path)
                    
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
        
        repo_url = f"https://gitee.com/{owner}/{repo}.git"
        
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
    
    def list_tags(self, owner: str, repo: str) -> list:
        """
        Get all tags of a repository
        
        Args:
            owner: Repository owner
            repo: Repository name
            
        Returns:
            List of tags
        """
        url = f"{self.base_url}/repos/{owner}/{repo}/tags"
        
        response = requests.get(url, headers=self.headers)
        response.raise_for_status()
        
        tags = response.json()
        return [tag['name'] for tag in tags]
    
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
        
        # Get download URL from release assets
        if release_info.get('assets') and len(release_info['assets']) > 0:
            # Download the first asset (usually source code)
            download_url = release_info['assets'][0]['browser_download_url']
        else:
            # Fallback to tag zipball
            tag_name = release_info['tag_name']
            download_url = f"https://gitee.com/{owner}/{repo}/repository/archive/{tag_name}.zip"
        
        target_path = Path(target_dir) / f"{repo}-{release_info['tag_name']}"
        target_path.mkdir(parents=True, exist_ok=True)
        
        return self._download_zip_from_url(download_url, target_path)
    
    def download_tag(self, owner: str, repo: str, tag: str, target_dir: str) -> str:
        """
        Download specific tag
        
        Args:
            owner: Repository owner
            repo: Repository name
            tag: Tag name
            target_dir: Target directory
            
        Returns:
            Full path to downloaded content
        """
        zip_url = f"https://gitee.com/{owner}/{repo}/repository/archive/{tag}.zip"
        
        target_path = Path(target_dir) / f"{repo}-{tag}"
        target_path.mkdir(parents=True, exist_ok=True)
        
        return self._download_zip_from_url(zip_url, target_path)
    
    def _download_zip_from_url(self, zip_url: str, target_path: Path) -> str:
        """
        Download zip file from URL and extract
        """
        response = requests.get(zip_url, stream=True)
        response.raise_for_status()
        
        with zipfile.ZipFile(io.BytesIO(response.content)) as zip_file:
            zip_file.extractall(target_path)
        
        logger.info(f"[CODE DOWNLOAD] Files downloaded to: {target_path}")
        return str(target_path)
    
    def search_repositories(self, keyword: str, page: int = 1, per_page: int = 20) -> Dict[str, Any]:
        """
        Search repositories on Gitee
        
        Args:
            keyword: Search keyword
            page: Page number
            per_page: Items per page
            
        Returns:
            Search results
        """
        url = f"{self.base_url}/search/repositories"
        params = {
            'q': keyword,
            'page': page,
            'per_page': per_page,
            'order': 'desc',
            'sort': 'stars_count'
        }
        
        response = requests.get(url, headers=self.headers, params=params)
        response.raise_for_status()
        
        return response.json()


# Usage examples and utility functions
def create_gitee_client(token: Optional[str] = None) -> GiteeClient:
    """
    Create Gitee client, supports reading token from environment variables
    
    Returns:
        GiteeClient instance
    """
    if not token:
        # Try to read from environment variable
        token = os.getenv('GITEE_TOKEN')
    
    return GiteeClient(token=token)


def download_repo_simple(repo_url: str, target_dir: str, 
                        branch: str = "master", token: Optional[str] = None) -> str:
    """
    Simplified repository download function
    
    Args:
        repo_url: Gitee repository URL (e.g., https://gitee.com/owner/repo)
        target_dir: Target directory
        branch: Branch name (defaults to master for Gitee)
        token: Gitee token
        
    Returns:
        Full path to downloaded content
    """
    # Parse owner and repo from URL
    # Remove protocol and split
    if repo_url.startswith('https://'):
        repo_url = repo_url[8:]
    elif repo_url.startswith('http://'):
        repo_url = repo_url[7:]
    
    parts = repo_url.rstrip('/').split('/')
    if len(parts) < 2:
        raise ValueError("Invalid Gitee repository URL")
    
    # Find gitee.com position
    try:
        gitee_index = parts.index('gitee.com')
        if len(parts) < gitee_index + 3:
            raise ValueError("Invalid Gitee repository URL")
        owner = parts[gitee_index + 1]
        repo = parts[gitee_index + 2]
    except ValueError:
        # Try direct parsing if gitee.com is not in URL
        if len(parts) >= 2:
            owner = parts[-2]
            repo = parts[-1]
        else:
            raise ValueError("Invalid Gitee repository URL")
    
    client = create_gitee_client(token)
    return client.download_repository(owner, repo, target_dir, branch)


# Usage example
if __name__ == "__main__":
    # Example usage
    client = create_gitee_client()
    
    # Download public repository
    try:
        # Method 1: Use client directly
        download_path = client.download_repository(
            owner="openeuler", 
            repo="kernel", 
            target_dir="./downloads",
            branch="master"
        )
        logger.info(f"[CODE DOWNLOAD] Code downloaded to: {download_path}")
        
        # # Method 2: Use simplified function
        # download_path = download_repo_simple(
        #     repo_url="https://gitee.com/openeuler/kernel",
        #     target_dir="./downloads",
        #     branch="master"
        # )
        # print(f"Code downloaded to: {download_path}")
        
        # # Get repository info
        # repo_info = client.get_repository_info("openeuler", "kernel")
        # print(f"Repository description: {repo_info.get('description', 'No description')}")
        
        # # Get branch list
        # branches = client.list_branches("openeuler", "kernel")
        # print(f"Available branches: {branches}")
        
        # # Get tag list
        # tags = client.list_tags("openeuler", "kernel")
        # print(f"Available tags: {tags[:5]}")  # Show first 5 tags
        
    except Exception as e:
        logger.error(f"[CODE DOWNLOAD] Download failed: {e}")