"""
代码仓库初始化模块

在 CodeAgent 服务启动时，根据配置自动 clone 代码仓库到本地。
"""

import json
import logging
import re
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class CodeConfig:
    """用于存储代码配置的对象，与 Go 端 CodeSourceConfig 结构对应"""
    
    def __init__(self):
        self.name: str = ""
        self.descriptor_type: str = ""
        self.code_repo_type: Optional[str] = None
        self.code_repo_path: Optional[str] = None
        self.code_repo_branch: Optional[str] = None
        self.code_repo_token: Optional[str] = None
    
    def __str__(self) -> str:
        """格式化输出对象内容"""
        token_info = f"'{self.code_repo_token}'" if self.code_repo_token else "None"
        return f"""CodeConfig(
    name='{self.name}',
    descriptor_type='{self.descriptor_type}',
    code_repo_type='{self.code_repo_type}',
    code_repo_path='{self.code_repo_path}',
    code_repo_branch='{self.code_repo_branch}',
    code_repo_token={token_info}
)"""
    
    def __repr__(self) -> str:
        return self.__str__()
    
    @classmethod
    def from_dict(cls, data: dict) -> 'CodeConfig':
        """从字典创建 CodeConfig 对象
        
        支持两种 JSON 格式：
        1. 扁平格式（旧格式）：
           {"name":"xx","descriptorType":"code","codeRepoPath":"...","codeRepoBranch":"...","codeRepoToken":"..."}
        2. 嵌套格式（新格式）：
           {"type":"code","metadata":{"codeRepoPath":"...","codeRepoBranch":"...","codeRepoToken":"..."},"enabled":true}
        """
        config = cls()
        
        # 检查是否是嵌套格式（有 type 和 metadata 字段）
        if 'type' in data and 'metadata' in data:
            # 嵌套格式
            config.name = data.get('name', '')
            config.descriptor_type = data.get('type', '')
            metadata = data.get('metadata', {})
            config.code_repo_type = metadata.get('codeRepoType') or None
            config.code_repo_path = metadata.get('codeRepoPath') or None
            config.code_repo_branch = metadata.get('codeRepoBranch') or None
            config.code_repo_token = metadata.get('codeRepoToken') or None
        else:
            # 扁平格式（旧格式）
            config.name = data.get('name', '')
            config.descriptor_type = data.get('descriptorType', '')
            config.code_repo_type = data.get('codeRepoType') or None
            config.code_repo_path = data.get('codeRepoPath') or None
            config.code_repo_branch = data.get('codeRepoBranch') or None
            config.code_repo_token = data.get('codeRepoToken') or None
        return config


def parse_descriptor_types_json(descriptor_types_str: str) -> List[CodeConfig]:
    """
    解析 DescriptorTypes 环境变量（JSON 格式）为 CodeConfig 对象列表
    
    Args:
        descriptor_types_str: JSON 格式的配置字符串，如:
            '[{"name":"dd-gitee","descriptorType":"code","codeRepoType":"git","codeRepoPath":"https://gitee.com/xxx/test.git","codeRepoBranch":"main","codeRepoToken":"xxx"}]'
    
    Returns:
        CodeConfig 对象列表
    """
    if not descriptor_types_str:
        return []
    
    descriptor_types_str = descriptor_types_str.strip()
    
    if not descriptor_types_str.startswith('['):
        logger.warning(f"DescriptorTypes 不是 JSON 数组格式: {descriptor_types_str[:100]}...")
        return []
    
    try:
        data_list = json.loads(descriptor_types_str)
        return [CodeConfig.from_dict(item) for item in data_list]
    except json.JSONDecodeError as e:
        logger.error(f"JSON 解析错误: {e}, 输入: {descriptor_types_str[:100]}...")
        return []


def get_git_reader_for_url(repo_url: str):
    """
    根据仓库 URL 判断并返回对应的 Git Reader 类
    
    Args:
        repo_url: 仓库 URL
    
    Returns:
        对应的 Reader 类 (GitHubReader, GiteeReader, 或 GitLabReader)
    """
    from .git_clone.github_reader import GitHubReader
    from .git_clone.gitee_reader import GiteeReader
    from .git_clone.gitlab_reader import GitLabReader
    
    if 'github.com' in repo_url:
        return GitHubReader
    elif 'gitee.com' in repo_url:
        return GiteeReader
    elif 'gitlab' in repo_url.lower():
        return GitLabReader
    else:
        # 默认使用 GitLab（支持自托管的 GitLab）
        return GitLabReader


def clone_code_repository(config: CodeConfig, base_path: str = "/app/code") -> Optional[str]:
    """
    根据 CodeConfig 配置使用对应的 Reader clone 代码仓库到本地
    
    Args:
        config: CodeConfig 配置对象
        base_path: 代码存放的基础路径，默认为 /app/code
    
    Returns:
        clone 后的代码路径，如果失败返回 None
    """
    if not config.code_repo_path:
        logger.error("code_repo_path 为空，无法 clone 代码")
        return None
    
    try:
        # 获取对应的 Reader 类
        ReaderClass = get_git_reader_for_url(config.code_repo_path)
        
        # 构建 Reader 的配置
        reader_config = {
            'codeRepoPath': config.code_repo_path,
            'codeRepoBranch': config.code_repo_branch or 'main',
            'token': config.code_repo_token,
            'download_dir': base_path,
        }
        
        # 如果是 GitLab 且 URL 不是 gitlab.com，设置 base_url
        if 'gitlab' in config.code_repo_path.lower() and 'gitlab.com' not in config.code_repo_path:
            # 从 URL 中提取 base_url
            match = re.match(r'(https?://[^/]+)', config.code_repo_path)
            if match:
                reader_config['base_url'] = match.group(1)
        
        logger.info(f"正在使用 {ReaderClass.__name__} clone 代码仓库: {config.code_repo_path}")
        
        # 创建 Reader 并下载代码
        reader = ReaderClass(reader_config)
        repo_path = reader.query_inner()
        
        logger.info(f"代码仓库 clone 成功: {repo_path}")
        return repo_path
        
    except Exception as e:
        logger.error(f"代码仓库 clone 失败 ({config.code_repo_path}): {e}")
        return None


def init_code_repositories(descriptor_types_str: str, base_path: str = "/app/code") -> Dict[str, str]:
    """
    在服务启动时初始化代码仓库，解析配置并 clone 所有 code 类型的仓库
    
    Args:
        descriptor_types_str: DescriptorTypes 环境变量的值（JSON 格式）
        base_path: 代码存放的基础路径，默认为 /app/code
    
    Returns:
        字典，key 为配置名称，value 为 clone 后的本地路径
    """
    result = {}
    
    configs = parse_descriptor_types_json(descriptor_types_str)
    
    if not configs:
        logger.warning("没有找到有效的代码配置")
        return result
    
    for config in configs:
        if config.descriptor_type != "code":
            logger.info(f"跳过非 code 类型的配置: {config.name} (type: {config.descriptor_type})")
            continue
        
        logger.info(f"正在处理代码配置: {config.name}")
        logger.info(f"  - repo_path: {config.code_repo_path}")
        logger.info(f"  - branch: {config.code_repo_branch}")
        logger.info(f"  - token: {'***' if config.code_repo_token else 'None'}")
        
        repo_path = clone_code_repository(config, base_path)
        
        if repo_path:
            result[config.name] = repo_path
        else:
            logger.error(f"代码仓库 clone 失败: {config.name}")
    
    return result
