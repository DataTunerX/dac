import tempfile
import os
from typing import Any, Dict, Optional
from ..base.base_reader import BaseDataReader
import logging
from pathlib import Path
import shutil
from ..client.gitlab import GitLabClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("gitlab_reader")

class GitLabReader(BaseDataReader):
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        # 只在没有传入 download_dir 时才使用环境变量或默认值
        if 'download_dir' not in self.config or not self.config['download_dir']:
            self.config['download_dir'] = os.getenv("DEFAULT_CODE_DOWNLOAD_DIR", "/app/download_dir")
        self._validate_config()
        self._client = self._connect()
        self._temp_dirs = []
    
    def _validate_config(self) -> None:
        if 'download_dir' in self.config:
            download_dir = Path(self.config['download_dir'])
            if not download_dir.parent.exists():
                raise ValueError(f"The parent directory of the download directory does not exist: {download_dir.parent}")
    
    def _connect(self) -> GitLabClient:
        token = self.config.get('token') or os.getenv('GITLAB_TOKEN')
        base_url = self.config.get('base_url', 'https://gitlab.com')
        return GitLabClient(token=token, base_url=base_url)
    
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
            temp_dir = tempfile.mkdtemp(prefix="gitlab_reader_")
            self._temp_dirs.append(temp_dir)
            return temp_dir
    
    def _parse_project_url(self, project_url: str) -> str:
        parts = project_url.rstrip('/').split('/')

        gitlab_domains = ['gitlab.com']
        if 'base_url' in self.config:
            base_url_parts = self.config['base_url'].rstrip('/').split('/')
            if len(base_url_parts) >= 3:
                gitlab_domains.append(base_url_parts[2])
        
        gitlab_index = -1
        for domain in gitlab_domains:
            try:
                gitlab_index = parts.index(domain)
                break
            except ValueError:
                continue
        
        if gitlab_index == -1 or len(parts) <= gitlab_index + 1:
            raise ValueError(f"invalid GitLab URL: {project_url}")
        
        try:
            project_path_parts = parts[gitlab_index + 1:]
            project_path = '/'.join(project_path_parts)

            if project_path.endswith('.git'):
                project_path = project_path[:-4]
                
            if not project_path:
                raise ValueError(f"Failed to extract project path from URL: {project_url}")
                
            return project_path
            
        except Exception as e:
            raise ValueError(f"Failed to parse project path from URL: {project_url}, error: {e}")
    
    def query(self, project_url: str, **kwargs) -> str:
        branch = kwargs.get('branch', 'main')
        overwrite = kwargs.get('overwrite', False)
        
        project_path = self._parse_project_url(project_url)
        download_dir = self._get_download_dir()
        
        try:
            # 使用临时文件夹时，总是覆盖（因为临时文件夹是新的）
            overwrite = True if 'download_dir' in self.config else overwrite
            
            repo_path = self._client.download_repository(
                project_path=project_path,
                target_dir=download_dir,
                branch=branch,
                overwrite=overwrite
            )
            
            logger.info(f"GitLab repository download complete: {repo_path}")
            return repo_path
        except Exception as e:
            logger.error(f"Failed to handle GitLab repository {project_url}: {e}")
            raise ValueError(f"handle GitLab repo fail {project_url}: {e}")
        finally:
            if 'download_dir' not in self.config:
                self._cleanup_temp_dirs()

    def query_inner(self, **kwargs) -> str:
        if 'codeRepoPath' not in self.config:
            raise ValueError("codeRepoPath is required in config for query_inner")
        
        project_url = self.config['codeRepoPath']
        branch = self.config.get('codeRepoBranch', 'main')
        overwrite = kwargs.get('overwrite', True)  # 默认覆盖，因为使用临时文件夹
        
        project_path = self._parse_project_url(project_url)
        download_dir = self._get_download_dir()
        
        try:
            # 使用临时文件夹时，总是覆盖（因为临时文件夹是新的，不会有冲突）
            overwrite = True if 'download_dir' in self.config else overwrite
            
            repo_path = self._client.download_repository(
                project_path=project_path,
                target_dir=download_dir,
                branch=branch,
                overwrite=overwrite
            )
            
            logger.info(f"repo download complete: {repo_path}")
            return repo_path
        except Exception as e:
            logger.error(f"handle GitLab repo fail {project_url}: {e}")
            raise ValueError(f"handle GitLab repo fail {project_url}: {e}")
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
    
    @property
    def client(self) -> GitLabClient:
        return self._client