"""
从文件中读取指定行范围的代码

提供按行号范围读取代码文件内容的能力，用于 CodeAgent 在回答用户问题时精确定位和展示代码片段。
支持代码完整性验证和自动扩展，确保读取的代码是语法完整的代码块。

本模块提供 8 个核心函数：

┌──────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                    基础读取函数 (1-5)                                                     │
├──────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ 函数名                     │ 作用                           │ 典型场景                                    │
├──────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ 1. read_file_lines         │ 读取文件指定行范围的代码        │ 用户问"显示第100-150行代码"                  │
│ 2. read_file_with_context  │ 读取目标行及其上下文            │ 用户问"函数foo在哪里"，展示函数上下文          │
│ 3. get_file_total_lines    │ 获取文件总行数                  │ 判断行号范围是否有效、分页读取大文件           │
│ 4. read_file_from_code_repo│ 从代码仓库读取指定文件          │ 结合CodeAgent的code_paths读取clone的代码      │
│ 5. search_and_read_lines   │ 搜索匹配文件并读取指定行        │ 用户问"找所有test_*.py文件的前10行"           │
├──────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│                                    代码完整性验证与智能扩展 (6-8)                                          │
├──────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ 6. check_code_completeness │ 检查代码片段是否语法完整        │ 验证读取的代码是否截断在函数/类中间            │
│ 7. read_file_lines_complete│ 读取代码并自动扩展至完整        │ 读取可能不完整的代码，自动补全到语法完整        │
│ 8. read_complete_function  │ 从函数起始行读取完整函数        │ 已知函数开始位置，自动读取整个函数体            │
└──────────────────────────────────────────────────────────────────────────────────────────────────────────┘

使用示例：

    ┌─────────────────────────────────────────────────────────────────────────────┐
    │ 1. read_file_lines - 读取指定行范围                                          │
    └─────────────────────────────────────────────────────────────────────────────┘
    >>> from agent.tools.extract_code_by_lines import read_file_lines
    >>> content, start, end = read_file_lines("/path/to/file.py", 10, 20)
    >>> print(content)
    10| def hello():
    11|     print("Hello")
    ...
    
    # 不带行号
    >>> content, _, _ = read_file_lines("/path/to/file.py", 10, 20, include_line_numbers=False)

    ┌─────────────────────────────────────────────────────────────────────────────┐
    │ 2. read_file_with_context - 读取目标行及上下文                                │
    └─────────────────────────────────────────────────────────────────────────────┘
    >>> from agent.tools.extract_code_by_lines import read_file_with_context
    >>> content, start, end = read_file_with_context("/path/to/file.py", target_line=50, context_lines=5)
    # 返回第 45-55 行（目标行 50 的前后各 5 行）

    ┌─────────────────────────────────────────────────────────────────────────────┐
    │ 3. get_file_total_lines - 获取文件总行数                                     │
    └─────────────────────────────────────────────────────────────────────────────┘
    >>> from agent.tools.extract_code_by_lines import get_file_total_lines
    >>> total = get_file_total_lines("/path/to/file.py")
    >>> print(f"文件共 {total} 行")
    文件共 256 行

    ┌─────────────────────────────────────────────────────────────────────────────┐
    │ 4. read_file_from_code_repo - 从代码仓库读取文件（CodeAgent 专用）            │
    └─────────────────────────────────────────────────────────────────────────────┘
    >>> from agent.tools.extract_code_by_lines import read_file_from_code_repo
    >>> code_base = "/app/code/repo"  # clone 的代码仓库路径
    >>> content, start, end, rel_path = read_file_from_code_repo(
    ...     code_base, "src/main.py", start_line=1, end_line=50
    ... )
    # 内置路径安全检查，防止 ../../../etc/passwd 攻击

    ┌─────────────────────────────────────────────────────────────────────────────┐
    │ 5. search_and_read_lines - 按文件名模式搜索并读取                             │
    └─────────────────────────────────────────────────────────────────────────────┘
    >>> from agent.tools.extract_code_by_lines import search_and_read_lines
    >>> results = search_and_read_lines("/app/code/repo", "test_*.py", start_line=1, end_line=20)
    >>> for r in results:
    ...     print(f"文件: {r['path']}")
    ...     print(r['content'])
    文件: tests/test_user.py
    1| import pytest
    ...

    ┌─────────────────────────────────────────────────────────────────────────────┐
    │ 6. check_code_completeness - 检查代码是否语法完整                             │
    └─────────────────────────────────────────────────────────────────────────────┘
    >>> from agent.tools.extract_code_by_lines import check_code_completeness
    
    # 完整代码
    >>> result = check_code_completeness("func main() { return }", "go")
    >>> print(result['is_complete'])  # True
    
    # 不完整代码
    >>> result = check_code_completeness("func main() {", "go")
    >>> print(result['is_complete'])  # False
    >>> print(result['issues'])       # ['未闭合的括号: {', '大括号未闭合，缺少 1 个 }']
    >>> print(result['suggest_expand'])  # 'down' (建议向下扩展读取)
    
    # 支持的语言: go, python, java, c, cpp, csharp, javascript, rust, ruby

    ┌─────────────────────────────────────────────────────────────────────────────┐
    │ 7. read_file_lines_complete - 读取代码并自动扩展至完整                        │
    └─────────────────────────────────────────────────────────────────────────────┘
    >>> from agent.tools.extract_code_by_lines import read_file_lines_complete
    >>> content, start, end, check_result = read_file_lines_complete(
    ...     "/path/to/file.go", 
    ...     start_line=100, 
    ...     end_line=110, 
    ...     language="go",
    ...     max_expand_lines=50  # 最多扩展 50 行
    ... )
    >>> if check_result['is_complete']:
    ...     print(f"读取了第 {start}-{end} 行，代码完整")
    ... else:
    ...     print("代码可能仍不完整，达到扩展上限")

    ┌─────────────────────────────────────────────────────────────────────────────┐
    │ 8. read_complete_function - 从函数起始行读取完整函数                          │
    └─────────────────────────────────────────────────────────────────────────────┘
    >>> from agent.tools.extract_code_by_lines import read_complete_function
    
    # 先通过搜索找到函数位置
    >>> # grep "func HandleRequest" -> 第 150 行
    
    # 读取完整函数
    >>> content, start, end, check_result = read_complete_function(
    ...     "/path/to/handler.go",
    ...     function_start_line=150,
    ...     language="go",
    ...     max_lines=200  # 函数最大行数限制
    ... )
    >>> print(f"函数从第 {start} 行到第 {end} 行")
    函数从第 150 行到第 185 行
"""

import os
import logging
from typing import Optional, Tuple, List

logger = logging.getLogger(__name__)


def _normalize_language(language: str) -> str:
    """
    规范化语言名称，支持常见别名
    
    支持的语言及别名映射：
    - nodejs, node, js, typescript, ts -> javascript
    - c++ -> cpp
    - rs -> rust
    - rb -> ruby
    - c#, cs -> csharp
    
    支持的语言列表：
    - 大括号语言: go, java, c, cpp, javascript, rust, csharp
    - 缩进语言: python
    - end 关键字语言: ruby
    
    Args:
        language: 原始语言名称
    
    Returns:
        规范化后的语言名称
    """
    lang_lower = language.lower().strip()
    
    # JavaScript/Node.js 别名
    if lang_lower in ("nodejs", "node", "js", "typescript", "ts"):
        return "javascript"
    
    # C++ 别名
    if lang_lower in ("c++",):
        return "cpp"
    
    # Rust 别名
    if lang_lower in ("rs",):
        return "rust"
    
    # Ruby 别名
    if lang_lower in ("rb",):
        return "ruby"
    
    # C# 别名
    if lang_lower in ("c#", "cs"):
        return "csharp"
    
    return lang_lower


# =============================================================================
# 函数 1: read_file_lines - 基础行范围读取
# =============================================================================

def read_file_lines(
    file_path: str,
    start_line: int = 1,
    end_line: int = None,
    include_line_numbers: bool = True
) -> Tuple[str, int, int]:
    """
    从文件中读取指定行范围的代码
    
    【作用】
    这是最基础的行范围读取函数，支持精确指定起始行和结束行，读取文件中的代码片段。
    输出可以选择是否带行号，方便用户定位代码位置。
    
    【使用场景】
    1. 用户明确指定行号范围：
       - "显示 main.py 的第 100 到 150 行"
       - "读取配置文件的前 20 行"
    
    2. LLM 需要展示代码片段给用户时：
       - 回答"这个函数的实现是什么"时，精确展示函数代码
       - 代码审查时展示特定代码段
    
    3. 分页读取大文件：
       - 文件太大无法一次性读取，按行号范围分批读取
    
    Args:
        file_path: 文件的绝对路径或相对路径
        start_line: 起始行号（从 1 开始，默认为 1）
        end_line: 结束行号（包含，默认为 None 表示读到文件末尾）
        include_line_numbers: 是否在输出中包含行号（默认 True）
    
    Returns:
        Tuple[str, int, int]: (代码内容, 实际起始行, 实际结束行)
    
    Raises:
        FileNotFoundError: 文件不存在
        ValueError: 行号参数无效
    
    Example:
        >>> content, start, end = read_file_lines("/path/to/file.py", 10, 20)
        >>> print(content)
        10| def foo():
        11|     return "bar"
        ...
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"文件不存在: {file_path}")
    
    if not os.path.isfile(file_path):
        raise ValueError(f"路径不是文件: {file_path}")
    
    if start_line < 1:
        raise ValueError(f"起始行号必须 >= 1，当前: {start_line}")
    
    if end_line is not None and end_line < start_line:
        raise ValueError(f"结束行号必须 >= 起始行号，当前: start={start_line}, end={end_line}")
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            all_lines = f.readlines()
    except UnicodeDecodeError:
        # 尝试其他编码
        with open(file_path, 'r', encoding='latin-1') as f:
            all_lines = f.readlines()
    
    total_lines = len(all_lines)
    
    if total_lines == 0:
        return "", 0, 0
    
    # 调整行号范围
    actual_start = min(start_line, total_lines)
    actual_end = min(end_line, total_lines) if end_line else total_lines
    
    # 提取指定范围的行（转换为 0-based 索引）
    selected_lines = all_lines[actual_start - 1:actual_end]
    
    if include_line_numbers:
        # 计算行号的最大宽度，用于对齐
        max_line_num_width = len(str(actual_end))
        result_lines = []
        for i, line in enumerate(selected_lines):
            line_num = actual_start + i
            # 移除行末的换行符，统一处理
            line_content = line.rstrip('\n\r')
            result_lines.append(f"{line_num:>{max_line_num_width}}| {line_content}")
        content = '\n'.join(result_lines)
    else:
        content = ''.join(selected_lines)
    
    return content, actual_start, actual_end


# =============================================================================
# 函数 2: read_file_with_context - 带上下文的行读取
# =============================================================================

def read_file_with_context(
    file_path: str,
    target_line: int,
    context_lines: int = 5,
    include_line_numbers: bool = True
) -> Tuple[str, int, int]:
    """
    读取目标行及其上下文
    
    【作用】
    当知道某个关键行号时，自动读取该行前后的上下文代码，帮助理解代码的完整语境。
    比如知道某个函数定义在第 50 行，可以同时展示函数的上下文。
    
    【使用场景】
    1. 搜索结果定位后展示上下文：
       - grep/搜索找到某关键字在第 N 行，展示该行前后代码
       - "找到 'TODO' 在第 128 行，显示上下文"
    
    2. 错误堆栈定位：
       - 报错显示 "line 256"，展示第 256 行及其上下文
       - 调试时快速查看出错位置的代码
    
    3. 代码审查/解释：
       - "解释第 100 行这个函数调用"，同时展示调用上下文
       - 需要理解某行代码的前因后果
    
    Args:
        file_path: 文件路径
        target_line: 目标行号
        context_lines: 上下文行数（目标行前后各取多少行，默认 5）
        include_line_numbers: 是否包含行号
    
    Returns:
        Tuple[str, int, int]: (代码内容, 实际起始行, 实际结束行)
    
    Example:
        >>> content, start, end = read_file_with_context("/path/to/file.py", 50, context_lines=3)
        >>> # 返回第 47-53 行的代码（目标行 50 前后各 3 行）
    """
    start_line = max(1, target_line - context_lines)
    end_line = target_line + context_lines
    
    return read_file_lines(file_path, start_line, end_line, include_line_numbers)


# =============================================================================
# 函数 3: get_file_total_lines - 获取文件总行数
# =============================================================================

def get_file_total_lines(file_path: str) -> int:
    """
    获取文件总行数
    
    【作用】
    快速获取文件的总行数，不读取文件内容，性能较好。
    用于在读取前判断行号范围是否有效，或计算分页参数。
    
    【使用场景】
    1. 验证用户输入的行号范围：
       - 用户说"读取第 1000-2000 行"，先检查文件是否有这么多行
       - 避免无效的行号请求
    
    2. 分页读取大文件：
       - 先获取总行数，计算需要分多少页
       - "文件共 5000 行，每次读取 100 行，需要 50 次"
    
    3. 文件信息展示：
       - "这个文件有 xxx 行代码"
       - 代码统计、文件概览
    
    Args:
        file_path: 文件路径
    
    Returns:
        文件总行数
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"文件不存在: {file_path}")
    
    with open(file_path, 'r', encoding='utf-8') as f:
        return sum(1 for _ in f)


# =============================================================================
# 函数 4: read_file_from_code_repo - 从代码仓库读取文件
# =============================================================================

def read_file_from_code_repo(
    code_base_path: str,
    relative_path: str,
    start_line: int = 1,
    end_line: int = None,
    include_line_numbers: bool = True
) -> Tuple[str, int, int, str]:
    """
    从代码仓库中读取指定文件的指定行范围
    
    【作用】
    这是专为 CodeAgent 设计的函数，结合启动时 clone 的代码仓库使用。
    接收代码仓库根路径和文件相对路径，自动拼接完整路径并读取。
    内置路径安全检查，防止路径遍历攻击（如 ../../../etc/passwd）。
    
    【使用场景】
    1. CodeAgent 回答代码相关问题（最常用）：
       - 用户问"UserService 类的实现是什么"
       - CodeAgent 从 clone 的代码中读取对应文件
       
       ```python
       # 在 CodeAgent 中使用
       code_path = self.get_code_path()  # 获取 /app/code/my-repo
       content, start, end, _ = read_file_from_code_repo(
           code_path, 
           "src/services/user_service.py",  # 相对路径
           10, 100
       )
       ```
    
    2. 安全地访问仓库内文件：
       - 只能访问 code_base_path 内的文件
       - 自动拒绝访问仓库外的文件
    
    3. 多仓库场景：
       - CodeAgent 可能管理多个代码仓库
       - 根据不同的 code_base_path 访问不同仓库
    
    Args:
        code_base_path: 代码仓库的本地根路径（如 /app/code/dce5-docs）
        relative_path: 文件在仓库中的相对路径（如 src/main.py）
        start_line: 起始行号
        end_line: 结束行号
        include_line_numbers: 是否包含行号
    
    Returns:
        Tuple[str, int, int, str]: (代码内容, 实际起始行, 实际结束行, 完整文件路径)
    
    Example:
        >>> content, start, end, full_path = read_file_from_code_repo(
        ...     "/app/code/my-repo", 
        ...     "src/utils/helper.py", 
        ...     10, 
        ...     30
        ... )
    """
    # 构建完整路径
    full_path = os.path.join(code_base_path, relative_path)
    
    # 规范化路径，防止路径遍历攻击
    full_path = os.path.normpath(full_path)
    code_base_path = os.path.normpath(code_base_path)
    
    if not full_path.startswith(code_base_path):
        raise ValueError(f"非法路径，不允许访问代码仓库外的文件: {relative_path}")
    
    content, actual_start, actual_end = read_file_lines(
        full_path, start_line, end_line, include_line_numbers
    )
    
    return content, actual_start, actual_end, full_path


# =============================================================================
# 函数 5: search_and_read_lines - 搜索并读取多个文件
# =============================================================================

def search_and_read_lines(
    code_base_path: str,
    file_pattern: str,
    start_line: int = 1,
    end_line: int = None
) -> List[dict]:
    """
    搜索匹配的文件并读取指定行范围
    
    【作用】
    当不知道文件的确切路径，只知道文件名模式时，可以使用通配符搜索匹配的文件，
    并批量读取这些文件的指定行范围。支持递归搜索子目录。
    
    【使用场景】
    1. 批量查看同类文件：
       - "显示所有测试文件的前 20 行" → file_pattern="test_*.py"
       - "查看所有配置文件" → file_pattern="*.yaml"
    
    2. 不确定文件位置时搜索：
       - "找到 UserService 相关的文件" → file_pattern="*user*service*"
       - 模糊搜索，返回所有匹配文件
    
    3. 代码审查/统计：
       - "检查所有 __init__.py 文件的内容"
       - "查看所有 README 文件"
    
    4. 对比多个文件的相同部分：
       - 读取多个类似文件的同一行范围进行对比
    
    【返回格式】
    返回列表，每个元素是一个字典：
    {
        'path': 'src/services/user.py',      # 相对路径
        'full_path': '/app/code/.../user.py', # 完整路径
        'content': '1| import ...\n2| ...',   # 代码内容
        'start_line': 1,                      # 实际起始行
        'end_line': 20                        # 实际结束行
    }
    
    Args:
        code_base_path: 代码仓库根路径
        file_pattern: 文件名或路径模式（支持简单的通配符 *）
        start_line: 起始行号
        end_line: 结束行号
    
    Returns:
        匹配文件的列表，每个元素为 dict，包含 path, content, start_line, end_line
    
    Example:
        >>> results = search_and_read_lines("/app/code/repo", "test_*.py", 1, 10)
        >>> for r in results:
        ...     print(f"文件: {r['path']}")
        ...     print(r['content'])
    """
    import glob
    
    # 构建搜索模式
    if '*' in file_pattern:
        search_pattern = os.path.join(code_base_path, '**', file_pattern)
    else:
        search_pattern = os.path.join(code_base_path, '**', f'*{file_pattern}*')
    
    results = []
    
    for file_path in glob.glob(search_pattern, recursive=True):
        if os.path.isfile(file_path):
            try:
                content, actual_start, actual_end = read_file_lines(
                    file_path, start_line, end_line
                )
                relative_path = os.path.relpath(file_path, code_base_path)
                results.append({
                    'path': relative_path,
                    'full_path': file_path,
                    'content': content,
                    'start_line': actual_start,
                    'end_line': actual_end
                })
            except Exception as e:
                logger.warning(f"读取文件失败 {file_path}: {e}")
    
    return results


# =============================================================================
# 函数 6: check_code_completeness - 代码完整性验证
# =============================================================================

def check_code_completeness(code: str, language: str = "auto") -> dict:
    """
    检查代码片段是否完整
    
    【作用】
    验证读取的代码片段是否是完整的代码块，通过检查括号匹配、大括号平衡等语法特征
    判断代码是否被截断。返回详细的检查结果，包括问题描述和建议的扩展方向。
    
    【使用场景】
    1. 读取代码后验证完整性：
       - 按行读取了 100-120 行，检查是否截断在函数中间
       - 如果不完整，根据 suggest_expand 决定向上还是向下扩展
    
    2. 智能代码展示的前置判断：
       - 在展示代码给用户前，先检查是否完整
       - 不完整则提示"代码可能被截断"或自动扩展
    
    3. 代码片段质量检查：
       - 验证从搜索结果提取的代码片段是否可用
       - 过滤掉明显不完整的代码块
    
    4. 调试代码读取问题：
       - 查看具体哪些括号未匹配
       - 了解代码在哪个方向被截断
    
    【检查规则】
    - 括号匹配: (), [], {} 必须成对出现
    - Go/Java/C/JavaScript: 重点检查 {} 大括号平衡
    - 自动检测语言: 根据代码特征判断语言类型
    - 忽略字符串和注释中的括号（避免误判）
    
    【返回结果说明】
    - is_complete: True 表示代码语法完整
    - issues: 具体问题列表，如 "未闭合的括号: {"
    - suggest_expand: 
        - 'down': 需要向下读取更多行
        - 'up': 需要向上读取更多行  
        - 'both': 两个方向都需要
        - None: 代码完整，无需扩展
    - bracket_balance: 各类括号的差值，正数表示未闭合，负数表示多余
    
    Args:
        code: 代码片段
        language: 语言类型 (auto/python/go/java/javascript/nodejs/c/cpp/rust/ruby/csharp/c#)
    
    Returns:
        dict: {
            'is_complete': bool,       # 是否完整
            'issues': list[str],       # 问题列表
            'suggest_expand': str,     # 建议扩展方向: 'up'/'down'/'both'/None
            'bracket_balance': dict    # 各类括号的平衡情况
        }
    
    Example:
        >>> result = check_code_completeness("func foo() {", "go")
        >>> print(result['is_complete'])  # False
        >>> print(result['issues'])       # ['未闭合的括号: {', '大括号未闭合，缺少 1 个 }']
        >>> print(result['suggest_expand'])  # 'down'
    """
    result = {
        'is_complete': True,
        'issues': [],
        'suggest_expand': None,
        'bracket_balance': {'()': 0, '[]': 0, '{}': 0}
    }
    
    if not code or not code.strip():
        result['is_complete'] = False
        result['issues'].append('代码为空')
        return result
    
    # 规范化语言名称
    language = _normalize_language(language)
    
    # 自动检测语言
    if language == "auto":
        if 'def ' in code or 'class ' in code or 'import ' in code:
            language = "python"
        elif 'func ' in code or 'package ' in code:
            language = "go"
        elif 'function ' in code or 'const ' in code or 'let ' in code:
            language = "javascript"
        else:
            language = "generic"
    
    # 移除字符串和注释（简化版，避免误判）
    clean_code = _remove_strings_and_comments(code, language)
    
    # 检查括号匹配
    bracket_pairs = {'(': ')', '[': ']', '{': '}'}
    stack = []
    
    for char in clean_code:
        if char in '([{':
            stack.append(char)
        elif char in ')]}':
            if not stack:
                result['issues'].append(f'多余的闭合括号: {char}')
                result['suggest_expand'] = 'up'
            else:
                expected = bracket_pairs.get(stack[-1])
                if char == expected:
                    stack.pop()
                else:
                    result['issues'].append(f'括号不匹配: 期望 {expected}，实际 {char}')
    
    # 统计括号平衡
    result['bracket_balance']['()'] = clean_code.count('(') - clean_code.count(')')
    result['bracket_balance']['[]'] = clean_code.count('[') - clean_code.count(']')
    result['bracket_balance']['{}'] = clean_code.count('{') - clean_code.count('}')
    
    if stack:
        result['issues'].append(f'未闭合的括号: {"".join(stack)}')
        result['suggest_expand'] = 'down'
    
    # Python 特殊检查：缩进
    if language == "python":
        lines = code.split('\n')
        if lines:
            # 检查最后一行是否在缩进块中
            last_non_empty = None
            for line in reversed(lines):
                if line.strip():
                    last_non_empty = line
                    break
            
            if last_non_empty:
                indent = len(last_non_empty) - len(last_non_empty.lstrip())
                if indent > 0 and not last_non_empty.strip().startswith(('return', 'pass', 'break', 'continue', 'raise')):
                    # 可能在函数/类中间
                    if result['bracket_balance']['()'] == 0 and result['bracket_balance']['{}'] == 0:
                        # 括号平衡但缩进非零，可能需要继续向下读
                        pass  # 不一定是问题，Python 函数可以在任意缩进结束
    
    # Go/Java/C/Rust 特殊检查：大括号
    if language in ("go", "java", "c", "cpp", "javascript", "rust", "csharp"):
        brace_balance = result['bracket_balance']['{}']
        if brace_balance > 0:
            result['issues'].append(f'大括号未闭合，缺少 {brace_balance} 个 }}')
            result['suggest_expand'] = 'down'
        elif brace_balance < 0:
            result['issues'].append('多余的 }，可能需要向上读取')
            result['suggest_expand'] = 'up'
    
    # C++ 特殊检查：模板角括号
    if language == "cpp":
        import re
        # 检测 template 关键字后的角括号平衡
        # 先找到所有 template< 模式，然后检查对应的 > 是否存在
        template_matches = list(re.finditer(r'\btemplate\s*<', clean_code))
        for match in template_matches:
            start_pos = match.end() - 1  # < 的位置
            angle_depth = 0
            found_closing = False
            i = start_pos
            while i < len(clean_code):
                char = clean_code[i]
                if char == '<':
                    angle_depth += 1
                elif char == '>':
                    angle_depth -= 1
                    if angle_depth == 0:
                        found_closing = True
                        break
                i += 1
            
            if not found_closing:
                result['issues'].append('模板声明未闭合，缺少 >')
                result['suggest_expand'] = 'down'
                break
    
    # C# 特殊检查：event/delegate 声明需要分号结尾
    if language == "csharp":
        import re
        code_stripped = code.strip()
        # event 声明模式: [修饰符] event EventType EventName (不以分号结尾则不完整)
        # 例如: public event EventHandler E
        if re.match(r'^(?:public|private|protected|internal|static|\s)*\bevent\s+\w+(?:<[^>]+>)?\s+\w+\s*$', code_stripped):
            if not code_stripped.endswith(';'):
                result['issues'].append('event 声明缺少分号')
                result['suggest_expand'] = 'down'
        
        # delegate 声明模式: [修饰符] delegate ReturnType DelegateName[<TypeParams>](params) (不以分号结尾则不完整)
        # 例如: public delegate void D(int x)
        # 例如: public delegate TResult Func<T, TResult>(T arg)
        if re.match(r'^(?:public|private|protected|internal|\s)*\bdelegate\s+\w+\s+\w+(?:<[^>]+>)?\s*\([^)]*\)\s*$', code_stripped):
            if not code_stripped.endswith(';'):
                result['issues'].append('delegate 声明缺少分号')
                result['suggest_expand'] = 'down'
    
    # Ruby 特殊检查：end 关键字匹配
    if language == "ruby":
        import re
        # Ruby 块关键字
        block_starts = len(re.findall(r'\b(def|class|module|do|begin|if|unless|case|while|until|for)\b', clean_code))
        block_ends = len(re.findall(r'\bend\b', clean_code))
        
        # Ruby 3.0+ endless method 语法: def method_name = expression (不需要 end)
        # 模式: def name = expr, def name(args) = expr, def self.name = expr
        endless_methods = len(re.findall(r'\bdef\s+(?:self\.)?\w+(?:\s*\([^)]*\))?\s*=', clean_code))
        block_starts -= endless_methods  # endless method 不需要 end
        
        if block_starts > block_ends:
            result['issues'].append(f'缺少 {block_starts - block_ends} 个 end')
            result['suggest_expand'] = 'down'
        elif block_ends > block_starts:
            result['issues'].append(f'多余 {block_ends - block_starts} 个 end')
            result['suggest_expand'] = 'up'
    
    result['is_complete'] = len(result['issues']) == 0
    
    return result


def _remove_strings_and_comments(code: str, language: str) -> str:
    """
    移除代码中的字符串和注释（简化版）
    避免字符串/注释中的括号影响匹配检查
    """
    import re
    
    # Rust 特殊处理：先移除生命周期标注（'a, 'static 等），避免与字符字面量混淆
    if language == "rust":
        # 生命周期模式: 'identifier（后跟字母/下划线，不是闭合的单引号）
        # 例如: 'a, 'static, 'lifetime
        code = re.sub(r"'[a-z_][a-z0-9_]*", "", code)
    
    # 移除多行字符串（Python）
    if language == "python":
        code = re.sub(r'"""[\s\S]*?"""', '', code)
        code = re.sub(r"'''[\s\S]*?'''", '', code)
    
    # 移除单行字符串
    code = re.sub(r'"[^"\\]*(?:\\.[^"\\]*)*"', '""', code)
    code = re.sub(r"'[^'\\]*(?:\\.[^'\\]*)*'", "''", code)
    
    # 移除单行注释
    if language in ("python", "ruby"):
        code = re.sub(r'#.*$', '', code, flags=re.MULTILINE)
    else:
        code = re.sub(r'//.*$', '', code, flags=re.MULTILINE)
    
    # 移除多行注释
    code = re.sub(r'/\*[\s\S]*?\*/', '', code)
    
    return code


# =============================================================================
# 函数 7: read_file_lines_complete - 智能读取完整代码
# =============================================================================

def read_file_lines_complete(
    file_path: str,
    start_line: int,
    end_line: int,
    language: str = "auto",
    max_expand_lines: int = 50,
    include_line_numbers: bool = True
) -> Tuple[str, int, int, dict]:
    """
    读取代码并自动扩展直到代码完整
    
    【作用】
    这是智能代码读取的核心函数。读取指定行范围的代码后，自动检查完整性，
    如果代码被截断（如函数只读了一半），会自动向上/向下扩展行范围重试，
    直到代码完整或达到最大扩展限制。
    
    【使用场景】
    1. 读取函数定义确保完整（最常用）：
       - 用户问"显示 handleRequest 函数"
       - 初步定位函数在 100-120 行，但函数可能更长
       - 自动扩展到函数结束的 } 为止
    
    2. 读取类/结构体定义：
       - Go 的 struct 或 Java 的 class 可能跨越很多行
       - 自动扩展到定义结束
    
    3. 容错的代码展示：
       - 用户给了一个大概的行范围
       - 自动调整到语法完整的边界
       - 避免展示"半截"的代码给用户
    
    4. 代码片段提取：
       - 从大文件中提取某个代码块
       - 确保提取的是完整的、可独立理解的代码
    
    【扩展策略】
    - 根据 check_code_completeness 的 suggest_expand 决定扩展方向
    - 每次扩展 10 行，逐步尝试
    - 向上扩展: 当有多余的闭合括号 ) ] } 时
    - 向下扩展: 当有未闭合的开括号 ( [ { 时
    - 最大扩展限制: 防止无限扩展（如代码本身有语法错误）
    
    【返回的检查结果包含】
    - is_complete: 最终代码是否完整
    - issues: 如果不完整，具体问题是什么
    - expanded: 扩展信息
        - up: 向上扩展了多少行
        - down: 向下扩展了多少行
        - original_range: 原始请求的行范围
        - reached_limit: 是否达到扩展上限
    
    Args:
        file_path: 文件路径
        start_line: 起始行号
        end_line: 结束行号
        language: 语言类型 (auto/python/go/java/javascript/nodejs/c/cpp/rust/ruby/csharp/c#)
        max_expand_lines: 最大扩展行数（向上和向下各自的限制，默认 50）
        include_line_numbers: 是否包含行号
    
    Returns:
        Tuple[str, int, int, dict]: (代码内容, 实际起始行, 实际结束行, 完整性检查结果)
    
    Example:
        >>> # 请求读取 100-110 行，但代码不完整
        >>> content, start, end, check = read_file_lines_complete(
        ...     "/path/to/file.go", 
        ...     100, 110,
        ...     language="go"
        ... )
        >>> # 自动扩展到 100-135 行，代码完整
        >>> print(f"原始范围: 100-110, 实际范围: {start}-{end}")
        >>> print(f"向下扩展了 {check['expanded']['down']} 行")
    """
    # 规范化语言名称
    language = _normalize_language(language)
    
    total_lines = get_file_total_lines(file_path)
    
    current_start = start_line
    current_end = end_line
    expanded_up = 0
    expanded_down = 0
    
    while True:
        # 读取当前范围
        content, actual_start, actual_end = read_file_lines(
            file_path, current_start, current_end, include_line_numbers=False
        )
        
        # 检查完整性
        check_result = check_code_completeness(content, language)
        
        if check_result['is_complete']:
            # 代码完整，格式化输出
            if include_line_numbers:
                content, actual_start, actual_end = read_file_lines(
                    file_path, current_start, current_end, include_line_numbers=True
                )
            check_result['expanded'] = {
                'up': expanded_up,
                'down': expanded_down,
                'original_range': (start_line, end_line)
            }
            return content, actual_start, actual_end, check_result
        
        # 需要扩展
        expanded = False
        suggest = check_result.get('suggest_expand', 'both')
        
        # 向下扩展
        if suggest in ('down', 'both', None) and expanded_down < max_expand_lines:
            expand_amount = min(10, max_expand_lines - expanded_down, total_lines - current_end)
            if expand_amount > 0:
                current_end += expand_amount
                expanded_down += expand_amount
                expanded = True
        
        # 向上扩展
        if suggest in ('up', 'both') and expanded_up < max_expand_lines:
            expand_amount = min(10, max_expand_lines - expanded_up, current_start - 1)
            if expand_amount > 0:
                current_start -= expand_amount
                expanded_up += expand_amount
                expanded = True
        
        if not expanded:
            # 无法继续扩展，返回当前结果
            if include_line_numbers:
                content, actual_start, actual_end = read_file_lines(
                    file_path, current_start, current_end, include_line_numbers=True
                )
            check_result['expanded'] = {
                'up': expanded_up,
                'down': expanded_down,
                'original_range': (start_line, end_line),
                'reached_limit': True
            }
            return content, actual_start, actual_end, check_result


# =============================================================================
# 函数 8: read_complete_function - 读取完整函数
# =============================================================================

def read_complete_function(
    file_path: str,
    function_start_line: int,
    language: str = "auto",
    max_lines: int = 200,
    include_line_numbers: bool = True
) -> Tuple[str, int, int, dict]:
    """
    从函数起始行读取完整函数
    
    【作用】
    这是一个便捷函数，专门用于读取完整的函数/方法定义。
    给定函数定义的起始行号，自动向下（和向上）扩展直到获取完整的函数体。
    
    【使用场景】
    1. 搜索定位后读取完整函数（最常用）：
       - 先用 grep 搜索 "func HandleRequest" 找到在第 150 行
       - 调用此函数获取完整的 HandleRequest 函数代码
       
       ```python
       # 搜索找到函数位置
       results = grep_search("func HandleRequest", file_path)
       line_num = results[0]['line']  # 150
       
       # 读取完整函数
       content, start, end, _ = read_complete_function(file_path, line_num, "go")
       ```
    
    2. 代码解释/分析：
       - 用户问"解释 process_data 函数是做什么的"
       - 读取完整函数后发送给 LLM 分析
    
    3. 代码审查：
       - 需要审查某个特定函数
       - 确保获取完整的函数实现
    
    4. 函数提取/重构：
       - 提取某个函数的完整代码
       - 用于迁移或重构
    
    【与 read_file_lines_complete 的区别】
    - read_file_lines_complete: 通用的行范围读取 + 自动扩展
    - read_complete_function: 专门针对函数，只需提供函数起始行
      - 内部调用 read_file_lines_complete
      - 初始读取 20 行，然后根据需要扩展
      - max_lines 默认 200，适合大多数函数
    
    Args:
        file_path: 文件路径
        function_start_line: 函数定义的起始行（如 "func foo()" 所在行）
        language: 语言类型 (auto/python/go/java/javascript/nodejs/c/cpp/rust/ruby/csharp/c#)
        max_lines: 最大读取行数（默认 200，足够大多数函数）
        include_line_numbers: 是否包含行号
    
    Returns:
        Tuple[str, int, int, dict]: (代码内容, 起始行, 结束行, 检查结果)
    
    Example:
        >>> # grep 找到 "func GenerateDeployment" 在第 45 行
        >>> content, start, end, check = read_complete_function(
        ...     "/path/to/dac.go",
        ...     45,  # 函数起始行
        ...     language="go"
        ... )
        >>> print(f"函数范围: {start}-{end}")
        >>> print(f"代码完整: {check['is_complete']}")
    """
    import re
    
    # 规范化语言名称
    language = _normalize_language(language)
    
    total_lines = get_file_total_lines(file_path)
    
    # 读取足够的行来分析（从函数起始行到 max_lines 范围内）
    read_end = min(function_start_line + max_lines, total_lines)
    content_raw, _, _ = read_file_lines(
        file_path, function_start_line, read_end, include_line_numbers=False
    )
    lines = content_raw.split('\n')
    
    # 使用智能函数边界检测
    function_end_line = _find_function_end_line(lines, language, function_start_line)
    
    # 读取检测到的函数范围
    content, actual_start, actual_end = read_file_lines(
        file_path, function_start_line, function_end_line,
        include_line_numbers=include_line_numbers
    )
    
    # 验证完整性
    content_for_check, _, _ = read_file_lines(
        file_path, function_start_line, function_end_line, include_line_numbers=False
    )
    check_result = check_code_completeness(content_for_check, language)
    check_result['expanded'] = {
        'up': 0,
        'down': function_end_line - function_start_line,
        'original_range': (function_start_line, function_start_line),
        'detected_end': function_end_line
    }
    
    return content, actual_start, actual_end, check_result


def _find_function_end_line(lines: List[str], language: str, start_line: int) -> int:
    """
    智能检测函数结束位置
    
    【作用】
    根据语言特性检测函数的结束行号：
    - Go/Java/C/C++/JavaScript/Rust/C#: 使用大括号 {} 匹配
    - Python: 使用缩进检测
    - Ruby: 使用 end 关键字检测
    
    Args:
        lines: 代码行列表（从函数起始行开始）
        language: 语言类型 (支持 nodejs/node/js/rs/rb 等别名)
        start_line: 函数起始行号（用于计算返回值）
    
    Returns:
        函数结束的行号
    """
    import re
    
    if not lines:
        return start_line
    
    # 规范化语言名称
    language = _normalize_language(language)
    
    if language in ("go", "java", "c", "cpp", "javascript", "rust", "csharp"):
        # 使用大括号匹配检测函数边界
        brace_count = 0
        found_first_brace = False
        
        for i, line in enumerate(lines):
            # 移除字符串和注释中的内容
            clean_line = line
            clean_line = re.sub(r'"[^"\\]*(?:\\.[^"\\]*)*"', '', clean_line)
            clean_line = re.sub(r"'[^'\\]*(?:\\.[^'\\]*)*'", '', clean_line)
            clean_line = re.sub(r'//.*$', '', clean_line)
            clean_line = re.sub(r'`[^`]*`', '', clean_line)  # Go 的原始字符串
            
            for char in clean_line:
                if char == '{':
                    brace_count += 1
                    found_first_brace = True
                elif char == '}':
                    brace_count -= 1
            
            # 当大括号平衡且已经找到过开括号时，函数结束
            if found_first_brace and brace_count == 0:
                return start_line + i
        
        # 没有找到完整函数，返回最后一行
        return start_line + len(lines) - 1
    
    elif language == "python":
        # Python: 基于缩进检测函数边界
        if not lines:
            return start_line
        
        # 获取函数定义行的缩进
        first_line = lines[0]
        base_indent = len(first_line) - len(first_line.lstrip())
        
        # 检查是否是函数定义
        stripped_first = first_line.strip()
        if not (stripped_first.startswith('def ') or stripped_first.startswith('async def ')):
            # 不是函数定义，返回起始行
            return start_line
        
        # 找到函数体的最后一行
        last_body_line = 0
        
        for i, line in enumerate(lines[1:], 1):
            stripped = line.strip()
            
            # 跳过空行
            if not stripped:
                continue
            
            current_indent = len(line) - len(line.lstrip())
            
            # 如果遇到缩进 <= base_indent 的非空行
            if current_indent <= base_indent:
                # 检查是否是新的定义（def, class, @装饰器）
                if stripped.startswith(('def ', 'async def ', 'class ', '@')):
                    # 函数在上一个非空行结束
                    return start_line + last_body_line if last_body_line > 0 else start_line + i - 1
            
            # 更新最后一个函数体行
            if current_indent > base_indent:
                last_body_line = i
        
        # 没有找到结束标志，返回最后一个函数体行
        return start_line + (last_body_line if last_body_line > 0 else len(lines) - 1)
    
    elif language == "ruby":
        # Ruby: 使用 end 关键字检测函数边界
        # Ruby 块开始关键字: def, class, module, do, if, unless, case, while, until, for, begin
        block_keywords = ('def ', 'class ', 'module ', 'do', 'if ', 'unless ', 
                         'case ', 'while ', 'until ', 'for ', 'begin')
        block_count = 0
        found_first_block = False
        
        for i, line in enumerate(lines):
            stripped = line.strip()
            
            # 移除字符串和注释
            clean_line = re.sub(r'"[^"\\]*(?:\\.[^"\\]*)*"', '', stripped)
            clean_line = re.sub(r"'[^'\\]*(?:\\.[^'\\]*)*'", '', clean_line)
            clean_line = re.sub(r'#.*$', '', clean_line)  # Ruby 单行注释
            
            # 检查块开始关键字
            for kw in block_keywords:
                if clean_line.startswith(kw) or f' {kw}' in clean_line:
                    # 排除单行 if/unless (后置条件)
                    if kw in ('if ', 'unless ') and not clean_line.endswith(('then', 'do')):
                        # 检查是否是后置条件 (如 return x if condition)
                        if ' if ' in clean_line or ' unless ' in clean_line:
                            if not clean_line.startswith(kw):
                                continue
                    block_count += 1
                    found_first_block = True
                    break
            
            # 检查 end 关键字
            if clean_line == 'end' or clean_line.startswith('end ') or clean_line.endswith(' end'):
                block_count -= 1
            
            # 当 end 匹配完成时，函数结束
            if found_first_block and block_count == 0:
                return start_line + i
        
        # 没有找到完整函数，返回最后一行
        return start_line + len(lines) - 1
    
    else:
        # 通用：返回最后一行
        return start_line + len(lines) - 1


# 便捷别名
extract_lines = read_file_lines
read_lines = read_file_lines
read_complete = read_file_lines_complete


# =============================================================================
# 函数 9: detect_language - 根据文件扩展名检测语言
# =============================================================================

def detect_language(filepath: str) -> str:
    """
    根据文件扩展名返回语言类型
    
    【作用】
    供智能代码读取函数（read_complete_function、read_file_lines_complete 等）使用，
    自动检测文件语言以便进行正确的语法边界检测。
    
    Args:
        filepath: 文件路径（相对或绝对路径均可）
    
    Returns:
        语言类型字符串，如 'python', 'go', 'java' 等，未知扩展名返回 'auto'
    
    Example:
        >>> detect_language("src/services/order_service.py")
        'python'
        >>> detect_language("internal/handler.go")
        'go'
        >>> detect_language("config.yaml")
        'auto'
    """
    ext_map = {
        '.py': 'python',
        '.go': 'go',
        '.java': 'java',
        '.js': 'javascript',
        '.ts': 'javascript',
        '.tsx': 'javascript',
        '.jsx': 'javascript',
        '.rs': 'rust',
        '.rb': 'ruby',
        '.c': 'c',
        '.cpp': 'cpp',
        '.cc': 'cpp',
        '.cxx': 'cpp',
        '.h': 'c',
        '.hpp': 'cpp',
        '.cs': 'csharp',
    }
    ext = os.path.splitext(filepath)[1].lower()
    return ext_map.get(ext, 'auto')


# =============================================================================
# 函数 10: find_nearest_function_start - 向上查找函数定义行
# =============================================================================

def find_nearest_function_start(
    file_path: str,
    line_no: int,
    max_scan_lines: int = 50
) -> Optional[int]:
    """
    从指定行向上扫描，找到最近的函数/方法定义行
    
    【作用】
    当 local grep（ripgrep）匹配到代码中间的某一行时，该行可能在函数体内部
    （如 `return self.service.create_order(data)`），无法直接读取完整函数。
    此函数从匹配行向上扫描，找到最近的函数定义行（如 `def create_order_api(request):`），
    然后可以配合 read_complete_function 读取完整的函数体。
    
    【使用场景】
    1. local grep 匹配到函数体内部的某行代码：
       - 匹配行: 第 42 行 `return self.order_service.create_order(request.json)`
       - 向上扫描找到: 第 35 行 `def create_order_api(request):`
       - 然后用 read_complete_function(file, 35) 读取完整函数
    
    2. 搜索结果只有行号没有函数信息时，定位函数边界
    
    【支持的语言模式】
    - Python: def, async def, class
    - Go: func
    - Java/C#: public/private/protected/static + 返回类型 + 方法名
    - JavaScript/TypeScript: function, const/let/var + arrow function, class method
    - Rust: fn, pub fn, pub(crate) fn
    - Ruby: def
    - C/C++: 返回类型 + 函数名 + 参数列表
    
    Args:
        file_path: 文件的绝对路径
        line_no: 当前匹配行号（从 1 开始）
        max_scan_lines: 最多向上扫描多少行（默认 50）
    
    Returns:
        找到的函数定义行号（从 1 开始），找不到返回 None
    
    Example:
        >>> find_nearest_function_start("/code/order_service.py", 42)
        35  # 找到第 35 行的 def create_order_api(request):
        
        >>> find_nearest_function_start("/code/utils.py", 5)
        None  # 前 5 行没有函数定义
    """
    import re
    
    if not os.path.exists(file_path) or not os.path.isfile(file_path):
        return None
    
    # 函数定义的正则模式（覆盖主流语言）
    # 注意顺序：更精确的模式放在前面，避免宽泛模式误匹配函数体内部的代码
    func_patterns = [
        # Python: def foo(...), async def foo(...)
        re.compile(r'^\s*(async\s+)?def\s+\w+\s*\('),
        # Go: func foo(...), func (r *Receiver) foo(...)
        re.compile(r'^\s*func\s+(\(\s*\w+\s+\*?\w+\s*\)\s*)?\w+\s*\('),
        # JavaScript/TypeScript: function foo(...), async function foo(...)
        re.compile(r'^\s*(async\s+)?function\s+\w+\s*\('),
        # JavaScript/TypeScript: const/let/var foo = (...) => （仅匹配箭头函数）
        re.compile(r'^\s*(export\s+)?(const|let|var)\s+\w+\s*=\s*(async\s+)?(\([^)]*\)|[a-zA-Z_]\w*)\s*=>'),
        # JavaScript/TypeScript: class method - foo(...) { | async foo(...) {
        # 排除 if/for/while/switch/catch 等控制流语句
        re.compile(r'^\s*(async\s+)?(?!if\b|for\b|while\b|switch\b|catch\b|return\b|const\b|let\b|var\b|new\b)\w+\s*\([^)]*\)\s*\{'),
        # Java/C#: 修饰符 + 返回类型 + 方法名 + (参数) — 必须有完整的方法签名
        re.compile(r'^\s*(public|private|protected|internal)\s+(static\s+)?(final\s+|abstract\s+|override\s+|virtual\s+|async\s+|synchronized\s+)*[\w<>\[\]]+\s+\w+\s*\('),
        # Rust: fn foo(...), pub fn foo(...), pub(crate) fn, pub async fn foo(...)
        re.compile(r'^\s*(pub(\s*\([^)]*\))?\s+)?(async\s+)?fn\s+\w+'),
        # Ruby: def foo
        re.compile(r'^\s*def\s+\w+'),
        # C/C++: 返回类型 + 函数名 + ( —— 非缩进的（顶层或类内方法）
        re.compile(r'^[a-zA-Z_]\w*[\s\*]+\w+\s*\('),
    ]
    
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            all_lines = f.readlines()
    except Exception as e:
        logger.debug(f"Failed to read {file_path}: {e}")
        return None
    
    # 从 line_no 向上扫描（line_no 是 1-based）
    start_scan = max(0, line_no - 1)  # 转为 0-based，从当前行开始
    end_scan = max(0, line_no - 1 - max_scan_lines)
    
    for i in range(start_scan, end_scan - 1, -1):
        if i < 0 or i >= len(all_lines):
            continue
        line = all_lines[i]
        
        # 跳过空行和纯注释行
        stripped = line.strip()
        if not stripped or stripped.startswith('#') or stripped.startswith('//') or stripped.startswith('/*'):
            continue
        
        for pattern in func_patterns:
            if pattern.search(line):
                return i + 1  # 转回 1-based
    
    return None


# =============================================================================
# 函数 11: smart_read_code - 智能代码读取入口
# =============================================================================

def smart_read_code(
    code_base_path: str,
    filepath: str,
    line_no: str,
    match_type: str = "unknown",
    max_lines: int = 150
) -> str:
    """
    根据匹配类型智能读取代码
    
    【作用】
    统一的智能代码读取入口函数，根据 grep 匹配的类型和行号格式，自动选择最合适的
    读取策略。主要解决 local grep（ripgrep）返回的单行匹配只有 1 行代码内容的问题，
    通过向上查找函数定义并读取完整函数体来获取有意义的代码上下文。
    
    【策略分发】
    1. match_type == "code_text"（local grep 单行匹配）:
       - 向上查找最近的函数定义行（find_nearest_function_start）
       - 如果找到: 用 read_complete_function 读取完整函数体
       - 如果没找到: 用 read_file_lines_complete 读取 +/-15 行并自动扩展到语法完整
    
    2. line_no 是范围格式（如 "25-62"，元数据 grep 的 function/entity/api_endpoint）:
       - 直接读取该行号范围，已是完整的代码块
    
    3. 其他单行格式（元数据 grep 的单行标记）:
       - 读取 +/-5 行上下文（保持原有行为）
    
    Args:
        code_base_path: 代码仓库的本地根路径
        filepath: 文件在仓库中的相对路径
        line_no: 行号，可以是 "42"（单行）或 "25-62"（范围）
        match_type: 匹配类型，如 "code_text", "function", "entity", "api_endpoint" 等
        max_lines: 智能读取时函数体的最大行数限制（默认 150）
    
    Returns:
        读取到的代码内容字符串（带行号标注）
    
    Return Sample:
        # match_type="code_text", line_no="42", 向上找到函数头在第35行
        # 返回完整函数体:
        "35| def create_order_api(request):\\n"
        "36|     \\"\\"\\"创建订单接口\\"\\"\\"\\n"
        "37|     order_data = request.json\\n"
        "38|     validator = OrderValidator()\\n"
        "39|     validator.validate(order_data)\\n"
        "40|     order = OrderService()\\n"
        "41|     result = order.create(order_data)\\n"
        "42|     return jsonify(result), 201\\n"
        
        # match_type="function", line_no="25-62"
        # 直接读取第25-62行的完整函数
    
    Example:
        >>> # local grep 匹配到函数体内部的一行
        >>> code = smart_read_code("/app/code/repo", "order_service.py", "42", "code_text")
        
        >>> # 元数据 grep 匹配到带范围的函数
        >>> code = smart_read_code("/app/code/repo", "order_service.py", "25-62", "function")
        
        >>> # 元数据 grep 单行标记
        >>> code = smart_read_code("/app/code/repo", "models/order.py", "15", "entity")
    """
    if not code_base_path or not filepath:
        return ""
    
    full_path = os.path.join(code_base_path, filepath)
    
    # 规范化路径，防止路径遍历
    full_path = os.path.normpath(full_path)
    code_base_path = os.path.normpath(code_base_path)
    if not full_path.startswith(code_base_path):
        logger.warning(f"非法路径: {filepath}")
        return ""
    
    if not os.path.exists(full_path) or not os.path.isfile(full_path):
        logger.debug(f"File not found: {full_path}")
        return ""
    
    try:
        if match_type == "code_text":
            # ===== local grep 单行匹配：智能扩展到完整函数 =====
            int_line = int(line_no)
            language = detect_language(filepath)
            
            # 1. 向上查找最近的函数定义行
            func_start = find_nearest_function_start(full_path, int_line)
            
            if func_start:
                # 2a. 找到函数头 -> 读取完整函数体
                content, _, _, _ = read_complete_function(
                    full_path, func_start, language, max_lines
                )
                return content
            else:
                # 2b. 找不到函数头 -> 用 read_file_lines_complete 自动扩展
                content, _, _, _ = read_file_lines_complete(
                    full_path,
                    max(1, int_line - 15),
                    int_line + 15,
                    language,
                    max_expand_lines=30
                )
                return content
        
        elif "-" in str(line_no):
            # ===== 范围格式（元数据 grep 的 function/entity/api_endpoint）=====
            # 直接读取该范围，已是完整代码块
            parts = str(line_no).split("-")
            start_line = int(parts[0].strip())
            end_line = int(parts[1].strip())
            content, _, _ = read_file_lines(full_path, start_line, end_line)
            return content
        
        else:
            # ===== 其他单行（元数据 grep 的单行标记）=====
            # +/-5 行上下文，保持原有行为
            int_line = int(line_no)
            content, _, _ = read_file_with_context(full_path, int_line, context_lines=5)
            return content
    
    except FileNotFoundError:
        logger.warning(f"File not found: {filepath}")
        return f"[文件不存在: {filepath}]"
    except ValueError as e:
        logger.warning(f"Invalid line_no '{line_no}' for {filepath}: {e}")
        return f"[行号无效: {line_no}]"
    except Exception as e:
        logger.error(f"Error in smart_read_code for {filepath}: {e}")
        return f"[读取出错: {e}]"
