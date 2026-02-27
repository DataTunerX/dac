# client/gitlab.py
import os
import requests
from pathlib import Path
import tempfile
import shutil
from typing import Optional
import logging

logger = logging.getLogger("gitlab_client")

class GitLabClient:
    def __init__(self, token: Optional[str] = None, base_url: str = "https://gitlab.com"):
        self.base_url = base_url.rstrip('/')
        self.token = token
        self.session = requests.Session()
        
        if token:
            self.session.headers.update({"Authorization": f"Bearer {token}"})
    
    def download_repository(self, project_path: str, target_dir: str, 
                          branch: str = "main", overwrite: bool = False) -> str:
        """
        Download GitLab repository
        
        Args:
            project_path: Project path (e.g., owner/repo or group/subgroup/project)
            target_dir: Target directory
            branch: Branch name
            overwrite: Whether to overwrite existing directory
        
        Returns:
            Local path of the downloaded repository
        """
        project_path_encoded = project_path.replace('/', '%2F')
        repo_dir = Path(target_dir) / project_path.replace('/', '_')
        
        if repo_dir.exists():
            if overwrite:
                shutil.rmtree(repo_dir)
            else:
                logger.info(f"Repository already exists at {repo_dir}, skipping download")
                return str(repo_dir)
        
        # Create download URL
        archive_url = f"{self.base_url}/api/v4/projects/{project_path_encoded}/repository/archive.zip"
        params = {"sha": branch}
        
        try:
            response = self.session.get(archive_url, params=params, stream=True)
            response.raise_for_status()
            
            # Create temporary file to save zip
            with tempfile.NamedTemporaryFile(delete=False, suffix='.zip') as temp_file:
                for chunk in response.iter_content(chunk_size=8192):
                    temp_file.write(chunk)
                temp_path = temp_file.name
            
            # Extract to target directory
            import zipfile
            with zipfile.ZipFile(temp_path, 'r') as zip_ref:
                zip_ref.extractall(target_dir)
            
            # Rename extracted directory
            extracted_dirs = list(Path(target_dir).glob(f"{project_path.replace('/', '-')}-*"))
            if extracted_dirs:
                extracted_dir = extracted_dirs[0]
                shutil.move(str(extracted_dir), str(repo_dir))
            
            # Clean up temporary file
            os.unlink(temp_path)
            
            return str(repo_dir)
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to download repository {project_path}: {e}")
            raise
    
    def close(self):
        """Close session"""
        self.session.close()