import tempfile
import os
from typing import Any, Dict, Optional, List
from abc import ABC, abstractmethod
from langchain_core.documents import Document
from ..base.base_reader import BaseDataReader
import logging
from pathlib import Path
import shutil
from ...client.gitee import GiteeClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("gitee_reader")

class GiteeReader(BaseDataReader):
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.config['download_dir'] = os.getenv("DEFAULT_CODE_DOWNLOAD_DIR", "/app/download_dir")
        self._validate_config()
        self._client = self._connect()
        self._temp_dirs = []
    
    def _validate_config(self) -> None:
        if 'download_dir' in self.config:
            download_dir = Path(self.config['download_dir'])
            if not download_dir.parent.exists():
                raise ValueError(f"The parent directory of the download directory does not exist: {download_dir.parent}")
    
    def _connect(self) -> GiteeClient:
        token = self.config.get('token') or os.getenv('GITEE_TOKEN')
        return GiteeClient(token=token)
    
    def _get_download_dir(self) -> str:
        """
        获取下载目录，在download_dir下创建临时子目录
        确保每次下载都使用新的临时文件夹，避免使用旧代码
        """
        import uuid
        from datetime import datetime
        
        if 'download_dir' in self.config:
            base_download_dir = Path(self.config['download_dir'])
            base_download_dir.mkdir(parents=True, exist_ok=True)
            
            # 在base_download_dir下创建临时子目录
            # 使用时间戳+UUID确保唯一性
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            unique_id = str(uuid.uuid4())[:8]
            temp_subdir = base_download_dir / f"temp_{timestamp}_{unique_id}"
            temp_subdir.mkdir(parents=True, exist_ok=True)
            
            self._temp_dirs.append(str(temp_subdir))
            logger.info(f"Created temporary download directory: {temp_subdir}")
            return str(temp_subdir)
        else:
            temp_dir = tempfile.mkdtemp(prefix="gitee_reader_")
            self._temp_dirs.append(temp_dir)
            return temp_dir
    
    def _parse_repo_url(self, repo_url: str) -> tuple[str, str]:
        parts = repo_url.rstrip('/').split('/')

        if 'gitee.com' not in repo_url:
            raise ValueError(f"Invalid Gitee URL: {repo_url}, expected URL containing 'gitee.com'")
        
        try:
            if repo_url.startswith('https://'):
                repo_url = repo_url[8:]
            elif repo_url.startswith('http://'):
                repo_url = repo_url[7:]
            
            parts = repo_url.rstrip('/').split('/')

            gitee_index = parts.index('gitee.com')
            if len(parts) < gitee_index + 3:
                raise ValueError(f"Invalid Gitee repository URL: {repo_url}")
            
            owner = parts[gitee_index + 1]
            repo = parts[gitee_index + 2]
            
        except (ValueError, IndexError):
            parts = repo_url.rstrip('/').split('/')
            if len(parts) < 2:
                raise ValueError(f"Failed to parse owner and repo from URL: {repo_url}")

            owner = parts[-2]
            repo = parts[-1]

        if repo.endswith('.git'):
            repo = repo[:-4]
            
        return owner, repo
    
    def query(self, repo_url: str, **kwargs) -> str:
        branch = kwargs.get('branch', 'master')
        
        overwrite = kwargs.get('overwrite', False)
        
        owner, repo = self._parse_repo_url(repo_url)
        
        download_dir = self._get_download_dir()
        
        try:
            # 使用临时文件夹时，总是覆盖（因为临时文件夹是新的，不会有冲突）
            overwrite = True if 'download_dir' in self.config else overwrite
            
            repo_path = self._client.download_repository(
                owner=owner,
                repo=repo,
                target_dir=download_dir,
                branch=branch,
                overwrite=overwrite
            )
            
            logger.info(f"Repository download completed: {repo_path}")
            return repo_path
        except Exception as e:
            logger.error(f"Failed to process Gitee repository {repo_url}: {e}")
            raise ValueError(f"handle Gitee repo fail {repo_url}: {e}")
        finally:
            if 'download_dir' not in self.config:
                self._cleanup_temp_dirs()
    
    def query_inner(self, **kwargs) -> str:
        if 'codeRepoPath' not in self.config:
            raise ValueError("codeRepoPath is required in config for query_inner")
        
        repo_url = self.config['codeRepoPath']
        
        # 从config获取分支，默认为master
        branch = self.config.get('codeRepoBranch', 'master')
        
        overwrite = kwargs.get('overwrite', False)
        
        owner, repo = self._parse_repo_url(repo_url)
        
        download_dir = self._get_download_dir()
        
        try:
            # 使用临时文件夹时，总是覆盖（因为临时文件夹是新的，不会有冲突）
            overwrite = True if 'download_dir' in self.config else overwrite
            
            repo_path = self._client.download_repository(
                owner=owner,
                repo=repo,
                target_dir=download_dir,
                branch=branch,
                overwrite=overwrite
            )
            
            logger.info(f"Repository download completed: {repo_path}")
            return repo_path
        except Exception as e:
            logger.error(f"Failed to process Gitee repository {repo_url}: {e}")
            raise ValueError(f"handle Gitee repo fail {repo_url}: {e}")
        finally:
            if 'download_dir' not in self.config:
                self._cleanup_temp_dirs()
    
    def _cleanup_temp_dirs(self):
        """
        清理临时目录
        注意：如果使用配置的download_dir，临时文件夹会保留以便后续使用
        只有在使用系统临时目录时才会自动清理
        """
        for temp_dir in self._temp_dirs:
            try:
                if os.path.exists(temp_dir):
                    shutil.rmtree(temp_dir)
                    logger.info(f"Cleaned up temporary directory: {temp_dir}")
            except Exception as e:
                logger.warning(f"Failed to clean up temporary directory {temp_dir}: {e}")
        
        self._temp_dirs.clear()
    
    def cleanup_old_temp_dirs(self, max_age_hours: int = 24):
        """
        清理超过指定时间的临时文件夹（可选功能）
        
        Args:
            max_age_hours: 最大保留时间（小时），超过此时间的临时文件夹会被清理
        """
        if 'download_dir' not in self.config:
            return
        
        base_download_dir = Path(self.config['download_dir'])
        if not base_download_dir.exists():
            return
        
        import time
        current_time = time.time()
        max_age_seconds = max_age_hours * 3600
        
        # 查找所有临时文件夹
        for temp_dir in base_download_dir.glob("temp_*"):
            try:
                # 检查文件夹修改时间
                dir_mtime = temp_dir.stat().st_mtime
                age_seconds = current_time - dir_mtime
                
                if age_seconds > max_age_seconds:
                    shutil.rmtree(temp_dir)
                    logger.info(f"Cleaned up old temporary directory: {temp_dir} (age: {age_seconds/3600:.1f} hours)")
            except Exception as e:
                logger.warning(f"Failed to clean up old temporary directory {temp_dir}: {e}")
    
    def close(self) -> None:
        if hasattr(self, '_client') and self._client is not None:
            if hasattr(self._client, 'close'):
                self._client.close()
            self._client = None
        
        self._cleanup_temp_dirs()