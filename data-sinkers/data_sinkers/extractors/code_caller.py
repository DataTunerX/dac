import os
from pathlib import Path
from typing import List, Dict, Optional, Any, Tuple, Set
from model_sdk import ModelManager
from langchain_core.messages import SystemMessage, HumanMessage
from ..api.base import DocumentModel
from datetime import datetime
import json
import re
import time
import ast
import logging
from a2a.types import AgentCard, AgentSkill
from dataclasses import dataclass, field, asdict
from collections import defaultdict
from ..llm_output_json import parse_llm_output_string
from .code_analysis_runtime import CodeAnalysisRuntime

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("code_caller")

DEFAULT_CODE_DOWNLOAD_DIR = "/app/download_dir"

manager = ModelManager()

# llm = manager.get_llm(
#     provider=os.getenv("PROVIDER","openai_compatible"),
#     api_key=os.getenv("API_KEY"),
#     base_url=os.getenv("BASE_URL"),
#     model=os.getenv("Model"),
#     temperature=0.01,
#     extra_body={
#         "enable_thinking": False
#     },
# )

llm = manager.get_llm(
    provider="openai_compatible",
    api_key="sk-xxx",
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    model="deepseek-v3.2",
    temperature=0.01,
    extra_body={
        "enable_thinking": False
    },
)

class CodeFileLister:
    def __init__(self, project_path: str, file_types: List[str] = None):
        self.project_path = Path(project_path)
        
        self.file_types = file_types or ['code', 'sql']
        
        self.target_extensions = {
            '.py', '.js', '.jsx', '.ts', '.tsx', '.java',
            '.cpp', '.c', '.h', '.hpp', '.cs', '.go',
            '.rs', '.php', '.rb', '.swift', '.kt', '.scala',
            '.sql',
            # 前端框架
            '.vue', '.svelte',
            # 移动端
            '.dart',
            # API 定义
            '.proto', '.graphql', '.gql',
        }

        self.readme_files = {
            'readme.md', 'readme.txt', 'readme', 
            'README.md', 'README.txt', 'README'
        }

        self.ignore_dirs = {
            '.git', '__pycache__', '.idea', 'node_modules', 
            'build', 'dist', 'venv', '.vscode', '.vs',
            'target', 'bin', 'obj', 'tmp', 'temp',
            'testdata', 'fixtures', 'mocks', "vendor"
            # 注意: test/tests 目录不再全局排除，由文件级 ignore_patterns 过滤测试文件
        }

        self.ignore_files = {
            '__pycache__', '.DS_Store', 'thumbs.db',
            '.gitignore', '.gitattributes', '.env', '.env.local'
        }

        self.ignore_patterns = [
            r'^__pycache__$',
            r'^\.',
            r'^#.*#$',
            r'~$',
            # 只匹配明确的测试文件命名模式，避免误杀 contest/latest/attestation 等业务文件
            r'^test_.*',           # test_xxx.py
            r'.*_test\.\w+$',     # xxx_test.py, xxx_test.go
            r'^tests?\.\w+$',     # test.py, tests.py
            r'.*\.test\.\w+$',    # xxx.test.ts, xxx.test.js
            r'.*\.spec\.\w+$',    # xxx.spec.ts, xxx.spec.js
        ]

    def find_target_files(self) -> List[Dict]:
        target_files = []
        
        for root, dirs, files in os.walk(self.project_path):
            dirs[:] = [d for d in dirs if not self._should_ignore_dir(d)]
            
            for file in files:
                file_path = Path(root) / file
                relative_path = file_path.relative_to(self.project_path)

                if self._is_target_file(file_path) and not self._should_ignore_file(file_path):
                    file_info = self._get_file_info(file_path, relative_path)
                    # 根据文件类型过滤
                    if self._should_include_file(file_info):
                        target_files.append(file_info)

        target_files.sort(key=lambda x: (
            0 if x['file_type'] == 'readme' else 
            1 if x['file_type'] == 'sql' else 2,
            x['file_path']
        ))
        
        return target_files

    def _should_include_file(self, file_info: Dict) -> bool:
        file_type = file_info.get('file_type', 'unknown')
        return file_type in self.file_types

    def _should_ignore_dir(self, dir_name: str) -> bool:
        return dir_name in self.ignore_dirs

    def _should_ignore_file(self, file_path: Path) -> bool:
        file_name = file_path.name

        if file_name in self.ignore_files:
            return True

        # __init__.py: 只忽略空的或极短的（<50字节，通常只有注释或空行）
        if file_name == '__init__.py':
            try:
                if file_path.stat().st_size < 50:
                    return True
            except OSError:
                return True
            return False

        for pattern in self.ignore_patterns:
            if re.match(pattern, file_name):
                return True
                
        return False

    def _is_target_file(self, file_path: Path) -> bool:
        file_name = file_path.name.lower()
        
        extension = file_path.suffix.lower()
        if extension in self.target_extensions:
            return True
        
        if file_name.endswith('.sql') or 'sql' in file_name.lower():
            return True
            
        return False

    def _get_file_info(self, file_path: Path, relative_path: Path) -> Dict:
        try:
            content = self._read_file_content(file_path)
            file_name = file_path.name.lower()
            file_extension = file_path.suffix.lower()

            if file_extension == '.sql':
                file_type = 'sql'
            else:
                file_type = 'code'
            
            return {
                'file_path': str(relative_path),
                'file_type': file_type,
                'size': file_path.stat().st_size,
                'lines': len(content.splitlines()),
                'content': content
            }
        except Exception as e:
            return {
                'file_path': str(relative_path),
                'file_type': 'unknown',
                'error': str(e),
                'content': ''
            }

    def _read_file_content(self, file_path: Path) -> str:
        encodings = ['utf-8', 'latin-1', 'cp1252']
        
        for encoding in encodings:
            try:
                with open(file_path, 'r', encoding=encoding) as f:
                    return f.read()
            except UnicodeDecodeError:
                continue
            except Exception as e:
                return f"Error reading file: {str(e)}"
        
        return "Unable to read file with any encoding"


class CodeSplitter:
    """代码文件智能分割器
    
    将过长的代码文件按结构边界（类、函数）分割为多个块，确保：
    1. 每个块是完整的代码结构单元（不会在函数/类中间断开）
    2. 依赖信息（import/package 声明）在所有块中共享
    3. 保留原始行号，确保 LLM 返回的行号准确
    4. 超大类按方法边界二级拆分，每个子块携带类定义上下文
    """
    
    DEFAULT_MAX_CHUNK_SIZE = 60000  # 每块最大字符数（预留 prompt 空间）
    
    # 各语言的头部（import/package）匹配模式
    _HEADER_PATTERNS = {
        '.py':    r'^\s*(import\s+|from\s+\S+\s+import\s+|#|"""|\'\'\')' ,
        '.java':  r'^\s*(package\s+|import\s+|/[/*])',
        '.go':    r'^\s*(package\s+|import\s+|//)',
        '.js':    r'^\s*(import\s+|const\s+\w+\s*=\s*require|var\s+\w+\s*=\s*require|let\s+\w+\s*=\s*require|//|/\*|"use\s)',
        '.jsx':   r'^\s*(import\s+|const\s+\w+\s*=\s*require|//|/\*|"use\s)',
        '.ts':    r'^\s*(import\s+|const\s+\w+\s*=\s*require|//|/\*)',
        '.tsx':   r'^\s*(import\s+|const\s+\w+\s*=\s*require|//|/\*)',
        '.cs':    r'^\s*(using\s+|namespace\s+|//|/\*)',
        '.kt':    r'^\s*(package\s+|import\s+|//|/\*)',
        '.rs':    r'^\s*(use\s+|mod\s+|extern\s+crate|//|/\*)',
        '.swift': r'^\s*(import\s+|//|/\*)',
        '.cpp':   r'^\s*(#\s*include|#\s*define|#\s*pragma|//|/\*|using\s+)',
        '.c':     r'^\s*(#\s*include|#\s*define|#\s*pragma|//|/\*)',
        '.h':     r'^\s*(#\s*include|#\s*define|#\s*pragma|#\s*ifndef|#\s*ifdef|//|/\*)',
        '.hpp':   r'^\s*(#\s*include|#\s*define|#\s*pragma|//|/\*|using\s+)',
        '.php':   r'^\s*(<\?php|namespace\s+|use\s+|//|/\*)',
        '.rb':    r'^\s*(require\s+|require_relative\s+|#)',
        '.scala': r'^\s*(package\s+|import\s+|//|/\*)',
        '.vue':   r'^\s*(<template|<script|import\s+|//|/\*)',
        '.dart':  r'^\s*(import\s+|part\s+|library\s+|export\s+|//|/\*)',
        '.svelte': r'^\s*(<script|<style|import\s+|//|/\*)',
        '.sql':   r'^\s*(--|/\*|SET\s+|USE\s+)',
    }
    
    # 使用大括号界定块的语言
    _BRACE_LANGUAGES = frozenset((
        '.java', '.ts', '.tsx', '.js', '.jsx', '.cs', '.kt',
        '.swift', '.cpp', '.c', '.h', '.hpp', '.php', '.scala',
        '.go', '.rs', '.dart', '.vue',
    ))
    
    # ==================== 公开接口 ====================
    
    @classmethod
    def needs_splitting(cls, content: str, max_chunk_size: int = None) -> bool:
        """判断文件是否需要分块"""
        if max_chunk_size is None:
            max_chunk_size = cls.DEFAULT_MAX_CHUNK_SIZE
        return len(content) > max_chunk_size
    
    @classmethod
    def split_file(cls, content: str, file_path: str,
                   max_chunk_size: int = None) -> List[Dict]:
        """将代码文件按结构边界分割为多个块。
        
        Args:
            content: 完整的文件内容
            file_path: 文件路径（用于判断语言类型）
            max_chunk_size: 每块最大字符数
        
        Returns:
            List[Dict], 每个 dict 包含:
            - chunk_index: 块索引（从 0 开始）
            - total_chunks: 总块数
            - numbered_content: 带原始行号的块内容（已包含共享头部）
            - is_chunked: 是否经过分块
        """
        if max_chunk_size is None:
            max_chunk_size = cls.DEFAULT_MAX_CHUNK_SIZE
        
        if len(content) <= max_chunk_size:
            return [{
                'chunk_index': 0,
                'total_chunks': 1,
                'content': content,
                'is_chunked': False,
            }]
        
        lines = content.split('\n')
        ext = Path(file_path).suffix.lower()
        
        # Step 1: 分析文件结构 — 找出头部和顶层代码块
        header_end, blocks = cls._analyze_structure(content, lines, ext)
        
        if not blocks:
            logger.info(f"CodeSplitter: 无法识别 {file_path} 的代码结构，使用按行分割")
            return cls._split_by_lines(lines, header_end, max_chunk_size)
        
        # Step 2: 拆分超大块（如巨型类）
        header_size = sum(len(lines[i]) + 1 for i in range(header_end)) + 300
        blocks = cls._split_oversized_blocks(blocks, lines, ext, max_chunk_size, header_size)
        
        # Step 3: 将块贪心分组到 chunks
        chunk_groups = cls._group_blocks(blocks, lines, max_chunk_size, header_size)
        
        # Step 4: 构建每个 chunk 的带行号内容
        total_chunks = len(chunk_groups)
        result = []
        for i, group in enumerate(chunk_groups):
            numbered = cls._build_numbered_content(lines, header_end, group, i, total_chunks)
            result.append({
                'chunk_index': i,
                'total_chunks': total_chunks,
                'numbered_content': numbered,
                'is_chunked': True,
            })
        
        logger.info(f"CodeSplitter: {file_path} -> {total_chunks} 块 "
                     f"(原始 {len(lines)} 行, {len(content)} 字符)")
        return result
    
    # ==================== 结构分析 ====================
    
    @classmethod
    def _analyze_structure(cls, content: str, lines: List[str], ext: str) -> Tuple[int, List[Dict]]:
        """分析文件结构，返回 (header_end, blocks)。
        
        header_end: 头部结束位置（0-indexed, exclusive），lines[:header_end] 为头部
        blocks: [{'start': 0-indexed, 'end': 0-indexed inclusive, 'name': str}]
        """
        if ext == '.py':
            return cls._analyze_python(content, lines)
        else:
            return cls._analyze_generic(lines, ext)
    
    @classmethod
    def _analyze_python(cls, content: str, lines: List[str]) -> Tuple[int, List[Dict]]:
        """使用 AST 精确分析 Python 文件结构"""
        try:
            tree = ast.parse(content)
        except SyntaxError:
            logger.warning("CodeSplitter: Python AST 解析失败，使用通用分析")
            return cls._analyze_generic(lines, '.py')
        
        blocks = []
        first_block_line = None  # 0-indexed
        
        for node in tree.body:
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                start = node.lineno - 1  # 转为 0-indexed
                if node.decorator_list:
                    start = node.decorator_list[0].lineno - 1
                end = getattr(node, 'end_lineno', node.lineno) - 1  # 0-indexed inclusive
                
                if first_block_line is None:
                    first_block_line = start
                
                blocks.append({
                    'start': start,
                    'end': end,
                    'name': node.name,
                })
        
        if not blocks:
            return len(lines), []
        
        header_end = first_block_line
        
        # 调整：将块之间的间隙代码（全局变量等）合并到下一个块
        adjusted = []
        for i, block in enumerate(blocks):
            if i == 0:
                adj_start = header_end
            else:
                adj_start = blocks[i - 1]['end'] + 1
            adjusted.append({
                'start': adj_start,
                'end': block['end'],
                'name': block['name'],
            })
        
        # 确保文件尾部不丢失：将最后一个块延伸到文件末尾
        if adjusted:
            adjusted[-1]['end'] = len(lines) - 1
        
        return header_end, adjusted
    
    @classmethod
    def _analyze_generic(cls, lines: List[str], ext: str) -> Tuple[int, List[Dict]]:
        """通用语言结构分析（基于正则和括号匹配）"""
        header_end = cls._find_header_end_generic(lines, ext)
        
        # 构建通配符模式（把 {name} 替换成 \w+ 来匹配任意名称）
        class_pat_tpl = CodebaseIndexer._CLASS_PATTERNS.get(ext)
        func_pat_tpl = CodebaseIndexer._FUNC_PATTERNS.get(ext)
        
        class_pat = re.compile(class_pat_tpl.replace('{name}', r'(\w+)')) if class_pat_tpl else None
        func_pat = re.compile(func_pat_tpl.replace('{name}', r'(\w+)')) if func_pat_tpl else None
        
        use_braces = ext in cls._BRACE_LANGUAGES
        
        blocks = []
        i = header_end
        in_block_comment = False
        
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()
            
            # 跳过块注释 /* ... */ 区域（避免注释中的 class/function 被误匹配）
            if in_block_comment:
                if '*/' in stripped:
                    in_block_comment = False
                i += 1
                continue
            if stripped.startswith('/*') or stripped.startswith('/**'):
                if '*/' not in stripped[2:]:  # 非同行闭合
                    in_block_comment = True
                i += 1
                continue
            
            if not stripped or stripped.startswith('//') or stripped.startswith('#'):
                i += 1
                continue
            
            # 只匹配顶层声明（缩进不超过 4 个字符）
            indent = len(line) - len(line.lstrip()) if stripped else 999
            if indent > 4:
                i += 1
                continue
            
            matched = False
            name = f"block_{i}"
            
            if class_pat:
                m = class_pat.search(line)
                if m:
                    name = m.group(m.lastindex) if m.lastindex else f"class_{i}"
                    matched = True
            
            if not matched and func_pat:
                m = func_pat.search(line)
                if m:
                    name = m.group(m.lastindex) if m.lastindex else f"func_{i}"
                    matched = True
            
            if matched:
                block_start = i
                if use_braces:
                    block_end = cls._find_brace_block_end(lines, i) - 1  # 转为 0-indexed inclusive
                elif ext == '.rb':
                    block_end = cls._find_ruby_block_end(lines, i) - 1
                elif ext == '.py':
                    block_end = cls._find_python_block_end(lines, i) - 1
                else:
                    block_end = len(lines) - 1
                
                block_end = min(block_end, len(lines) - 1)
                blocks.append({'start': block_start, 'end': block_end, 'name': name})
                i = block_end + 1
            else:
                i += 1
        
        if not blocks:
            return header_end, []
        
        # 调整间隙
        adjusted = []
        for idx, block in enumerate(blocks):
            if idx == 0:
                adj_start = header_end
            else:
                adj_start = blocks[idx - 1]['end'] + 1
            adjusted.append({
                'start': adj_start,
                'end': block['end'],
                'name': block['name'],
            })
        
        # 确保文件尾部不丢失：将最后一个块延伸到文件末尾
        if adjusted:
            adjusted[-1]['end'] = len(lines) - 1
        
        return header_end, adjusted
    
    @classmethod
    def _find_header_end_generic(cls, lines: List[str], ext: str) -> int:
        """找到文件头部（import/package 声明区域）的结束位置（0-indexed, exclusive）"""
        pat_str = cls._HEADER_PATTERNS.get(ext, r'^\s*(import\s+|#|//|/\*)')
        pat = re.compile(pat_str)
        
        header_end = 0
        in_multiline_comment = False
        in_multiline_import = False
        
        for i, line in enumerate(lines):
            stripped = line.strip()
            
            # 处理多行注释 /* ... */
            if in_multiline_comment:
                header_end = i + 1
                if '*/' in stripped:
                    in_multiline_comment = False
                continue
            
            if '/*' in stripped and '*/' not in stripped:
                in_multiline_comment = True
                header_end = i + 1
                continue
            
            # 处理多行 import：Go 的 import (...), Rust 的 use std::{...}, Python 的 from x import (...)
            if in_multiline_import:
                header_end = i + 1
                if ')' in stripped or '}' in stripped:
                    in_multiline_import = False
                continue
            
            # 空行或匹配 import 模式 → 仍在头部
            if stripped == '' or pat.match(stripped):
                header_end = i + 1
                # 检测多行 import/use 开始（支持 () 和 {} 两种分组语法）
                has_open_paren = '(' in stripped and ')' not in stripped
                has_open_brace = '{' in stripped and '}' not in stripped
                if has_open_paren or has_open_brace:
                    if re.match(r'^\s*(import|from|use)\s+', stripped):
                        in_multiline_import = True
                continue
            
            # 遇到非头部行，停止
            break
        
        return header_end
    
    # ==================== 块边界检测 ====================
    
    @classmethod
    def _find_brace_block_end(cls, lines: List[str], start_0idx: int) -> int:
        """通过大括号匹配找到块结束行，返回 1-indexed
        
        正确处理：字符串字面量、行注释 //、块注释 /* */、转义序列、空大括号 {}
        """
        depth = 0
        found_open = False
        in_str = False
        str_char = None
        in_block_comment = False
        
        for i in range(start_0idx, len(lines)):
            line = lines[i]
            j = 0
            
            # 单/双引号字符串通常不跨行（多数 C 系语言），在行首重置
            # 仅保留反引号（JS/Go 模板字面量）的跨行状态
            if in_str and str_char != '`':
                in_str = False
            
            while j < len(line):
                ch = line[j]
                
                # --- 块注释 /* ... */ ---
                if in_block_comment:
                    if ch == '*' and j + 1 < len(line) and line[j + 1] == '/':
                        in_block_comment = False
                        j += 2
                        continue
                    j += 1
                    continue
                
                # --- 字符串状态 ---
                if in_str:
                    if ch == '\\':
                        j += 2  # 跳过转义序列（\", \\, \n 等）
                        continue
                    if ch == str_char:
                        in_str = False
                    j += 1
                    continue
                
                # --- 正常状态 ---
                if ch in ('"', "'", '`'):
                    in_str = True
                    str_char = ch
                elif ch == '/' and j + 1 < len(line):
                    next_ch = line[j + 1]
                    if next_ch == '/':
                        break  # 行注释，跳过本行剩余
                    elif next_ch == '*':
                        in_block_comment = True
                        j += 2
                        continue
                elif ch == '{':
                    if j + 1 < len(line) and line[j + 1] == '}':
                        j += 2  # 跳过空大括号 {} (Go interface{} 等)
                        continue
                    depth += 1
                    found_open = True
                elif ch == '}':
                    depth -= 1
                    if found_open and depth <= 0:
                        return i + 1
                
                j += 1
        return len(lines)
    
    @classmethod
    def _find_ruby_block_end(cls, lines: List[str], start_0idx: int) -> int:
        """Ruby 块结束检测，返回 1-indexed"""
        OPENERS = re.compile(
            r'^(class|module|def|do|if|unless|while|until|for|case|begin)\b')
        depth = 0
        for i in range(start_0idx, len(lines)):
            stripped = lines[i].strip()
            if not stripped or stripped.startswith('#'):
                continue
            first_word = stripped.split()[0] if stripped.split() else ''
            if OPENERS.match(first_word):
                depth += 1
            elif first_word == 'end':
                depth -= 1
                if depth <= 0:
                    return i + 1
        return len(lines)
    
    @classmethod
    def _find_python_block_end(cls, lines: List[str], start_0idx: int) -> int:
        """Python 块结束检测（基于缩进），用于 AST 解析失败时的 fallback，返回 1-indexed
        
        Python 的顶层定义（class/def）在遇到下一个同级或更低缩进的非空行时结束。
        """
        start_line = lines[start_0idx]
        start_indent = len(start_line) - len(start_line.lstrip())
        
        last_content_line = start_0idx
        in_multiline_str = False
        
        for i in range(start_0idx + 1, len(lines)):
            stripped = lines[i].strip()
            
            # 跟踪三引号多行字符串（避免字符串内容的缩进干扰判断）
            triple_count = stripped.count('"""') + stripped.count("'''")
            if triple_count % 2 == 1:
                in_multiline_str = not in_multiline_str
            if in_multiline_str:
                last_content_line = i
                continue
            
            if not stripped or stripped.startswith('#'):
                continue  # 跳过空行和注释行
            
            current_indent = len(lines[i]) - len(lines[i].lstrip())
            if current_indent <= start_indent:
                # 遇到同级或更低缩进的非空行 → 前一个内容行即为块结束
                return last_content_line + 1  # 1-indexed
            
            last_content_line = i
        
        return len(lines)
    
    # ==================== 超大块拆分 ====================
    
    @classmethod
    def _split_oversized_blocks(cls, blocks: List[Dict], lines: List[str],
                                 ext: str, max_chunk_size: int, header_size: int) -> List[Dict]:
        """拆分超过大小限制的单个代码块（如巨型类）"""
        result = []
        
        for block in blocks:
            block_size = sum(len(lines[i]) + 1
                            for i in range(block['start'], min(block['end'] + 1, len(lines))))
            
            if block_size + header_size <= max_chunk_size:
                result.append(block)
                continue
            
            logger.info(f"CodeSplitter: 块 '{block['name']}' 过大 ({block_size} 字符)，尝试按方法拆分")
            sub_blocks = cls._split_block_by_methods(block, lines, ext)
            if sub_blocks and len(sub_blocks) > 1:
                result.extend(sub_blocks)
            else:
                # 无法按方法拆分，按行边界做子拆分（保证不超限）
                logger.info(f"CodeSplitter: 块 '{block['name']}' 无法按方法拆分，使用行边界子拆分")
                sub_blocks = cls._split_block_by_line_boundary(
                    block, lines, max_chunk_size, header_size)
                result.extend(sub_blocks)
        
        return result
    
    @classmethod
    def _split_block_by_methods(cls, block: Dict, lines: List[str], ext: str) -> Optional[List[Dict]]:
        """将大型类/结构体按方法边界拆分为子块"""
        if ext == '.py':
            return cls._split_python_class_methods(block, lines)
        else:
            return cls._split_generic_class_methods(block, lines, ext)
    
    @classmethod
    def _split_python_class_methods(cls, block: Dict, lines: List[str]) -> Optional[List[Dict]]:
        """将大型 Python 类按方法边界拆分"""
        content = '\n'.join(lines)
        try:
            tree = ast.parse(content)
        except SyntaxError:
            return None
        
        # 找到对应的 ClassDef 节点
        target_class = None
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                node_start = node.lineno - 1
                if node.decorator_list:
                    node_start = node.decorator_list[0].lineno - 1
                if node_start >= block['start'] and node_start <= block['end']:
                    target_class = node
                    break
        
        if not target_class or not target_class.body:
            return None
        
        methods = []
        for item in target_class.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                start = item.lineno - 1
                if item.decorator_list:
                    start = item.decorator_list[0].lineno - 1
                end = getattr(item, 'end_lineno', item.lineno) - 1
                methods.append({
                    'start': start,
                    'end': end,
                    'name': f"{target_class.name}.{item.name}",
                })
        
        if len(methods) < 2:
            return None
        
        # 类头部：从块起始到第一个方法之前
        class_header_start = block['start']
        class_header_end = methods[0]['start'] - 1
        
        # 每个方法（含其前面的间隙）作为一个子块
        sub_blocks = []
        for i, method in enumerate(methods):
            if i == 0:
                actual_start = methods[0]['start']
            else:
                actual_start = methods[i - 1]['end'] + 1
            
            sub_blocks.append({
                'start': actual_start,
                'end': method['end'],
                'name': method['name'],
                'class_header_start': class_header_start,
                'class_header_end': class_header_end,
            })
        
        return sub_blocks
    
    @classmethod
    def _split_generic_class_methods(cls, block: Dict, lines: List[str], ext: str) -> Optional[List[Dict]]:
        """将其他语言的大型类按方法边界拆分"""
        func_pat_tpl = CodebaseIndexer._FUNC_PATTERNS.get(ext)
        if not func_pat_tpl:
            return None
        
        func_pat = re.compile(func_pat_tpl.replace('{name}', r'(\w+)'))
        use_braces = ext in cls._BRACE_LANGUAGES
        
        methods = []
        i = block['start'] + 1  # 跳过类定义行
        
        while i <= block['end']:
            m = func_pat.search(lines[i])
            if m:
                method_start = i
                if use_braces:
                    method_end = min(cls._find_brace_block_end(lines, i) - 1, block['end'])
                else:
                    method_end = block['end']
                name_str = m.group(m.lastindex) if m.lastindex else f"method_{i}"
                methods.append({
                    'start': method_start,
                    'end': method_end,
                    'name': name_str,
                })
                i = method_end + 1
            else:
                i += 1
        
        if len(methods) < 2:
            return None
        
        class_header_start = block['start']
        class_header_end = methods[0]['start'] - 1
        
        sub_blocks = []
        for idx, method in enumerate(methods):
            if idx == 0:
                actual_start = methods[0]['start']
            else:
                actual_start = methods[idx - 1]['end'] + 1
            
            sub_blocks.append({
                'start': actual_start,
                'end': method['end'],
                'name': method['name'],
                'class_header_start': class_header_start,
                'class_header_end': class_header_end,
            })
        
        return sub_blocks
    
    @classmethod
    def _split_block_by_line_boundary(cls, block: Dict, lines: List[str],
                                       max_chunk_size: int, header_size: int) -> List[Dict]:
        """对无法按方法拆分的超大块，按行边界做子拆分（尽量在空行处断开）"""
        block_start = block['start']
        block_end = block['end']
        available = max_chunk_size - header_size
        
        # 根据平均行长估算每个子块的行数
        block_lines = lines[block_start:block_end + 1]
        avg_len = sum(len(l) + 1 for l in block_lines) / max(len(block_lines), 1)
        lines_per_sub = max(int(available / max(avg_len, 1)), 50)
        
        sub_blocks = []
        i = block_start
        while i <= block_end:
            sub_end = min(i + lines_per_sub - 1, block_end)
            
            # 尝试在空行处断开，避免在代码中间切割
            if sub_end < block_end:
                best_break = None
                for j in range(sub_end, max(i, sub_end - 40) - 1, -1):
                    if not lines[j].strip():
                        best_break = j
                        break
                if best_break is not None:
                    sub_end = best_break
            
            sub_blocks.append({
                'start': i,
                'end': sub_end,
                'name': f"{block['name']}_part{len(sub_blocks)}",
            })
            i = sub_end + 1
        
        return sub_blocks if sub_blocks else [block]
    
    # ==================== 分组与内容构建 ====================
    
    @classmethod
    def _group_blocks(cls, blocks: List[Dict], lines: List[str],
                      max_chunk_size: int, header_size: int) -> List[List[Dict]]:
        """将代码块贪心分组，每组总大小不超过 max_chunk_size"""
        chunks: List[List[Dict]] = []
        current_group: List[Dict] = []
        current_size = header_size
        
        for block in blocks:
            block_size = sum(len(lines[i]) + 1
                            for i in range(block['start'], min(block['end'] + 1, len(lines))))
            
            # 如果有类头部引用（大类拆分），需要额外计算类头部大小
            if 'class_header_start' in block:
                ch_size = sum(len(lines[i]) + 1
                              for i in range(block['class_header_start'],
                                             min(block['class_header_end'] + 1, len(lines))))
                block_size += ch_size + 80  # 80 for separator text
            
            # 当前组加上这个块会超限，且当前组非空 → 开启新组
            if current_size + block_size > max_chunk_size and current_group:
                chunks.append(current_group)
                current_group = []
                current_size = header_size
            
            current_group.append(block)
            current_size += block_size
        
        if current_group:
            chunks.append(current_group)
        
        return chunks if chunks else [[]]
    
    @classmethod
    def _build_numbered_content(cls, lines: List[str], header_end: int,
                                 block_group: List[Dict],
                                 chunk_idx: int, total_chunks: int) -> str:
        """构建带原始行号的 chunk 内容。
        
        格式：
          1|import os
          2|from typing import List
           |
           | ========== [文件分块 1/3，以下为本块代码] ==========
           |
         50|class UserService:
         51|    def __init__(self):
           | ... (第 100-199 行见其他块) ...
        200|class PaymentService:
        """
        total_lines = len(lines)
        width = len(str(total_lines))
        output: List[str] = []
        
        # 1. 共享头部（import/依赖）
        for i in range(header_end):
            output.append(f"{i + 1:>{width}}|{lines[i]}")
        
        # 2. 分块标记
        output.append(f"{'':>{width}}|")
        output.append(f"{'':>{width}}| ========== [文件分块 {chunk_idx + 1}/{total_chunks}，以下为本块代码] ==========")
        output.append(f"{'':>{width}}|")
        
        # 3. 本块的代码
        prev_end = header_end - 1  # 上一段结束行（0-indexed inclusive）
        seen_class_headers: Set[Tuple[int, int]] = set()
        
        for block in block_group:
            # 处理大类拆分的类头部引用
            if 'class_header_start' in block:
                header_key = (block['class_header_start'], block['class_header_end'])
                if header_key not in seen_class_headers:
                    seen_class_headers.add(header_key)
                    ch_start = block['class_header_start']
                    ch_end = block['class_header_end']
                    
                    # 显示省略标记（头部与上段之间的间隙）
                    if ch_start > prev_end + 1:
                        output.append(
                            f"{'':>{width}}| ... (第 {prev_end + 2}-{ch_start} 行见其他块) ...")
                    
                    for i in range(ch_start, ch_end + 1):
                        output.append(f"{i + 1:>{width}}|{lines[i]}")
                    
                    output.append(f"{'':>{width}}|    ... (类的其他方法见其他块) ...")
                    prev_end = ch_end
            
            block_start = block['start']
            block_end = min(block['end'], total_lines - 1)
            
            # 显示省略标记（与上一段之间的间隙）
            if block_start > prev_end + 1:
                output.append(
                    f"{'':>{width}}| ... (第 {prev_end + 2}-{block_start} 行见其他块) ...")
            
            for i in range(block_start, block_end + 1):
                output.append(f"{i + 1:>{width}}|{lines[i]}")
            
            prev_end = block_end
        
        # 4. 尾部省略标记
        if block_group and prev_end < total_lines - 1:
            output.append(
                f"{'':>{width}}| ... (第 {prev_end + 2}-{total_lines} 行见其他块) ...")
        
        return '\n'.join(output)
    
    # ==================== 回退方案 ====================
    
    @classmethod
    def _split_by_lines(cls, lines: List[str], header_end: int,
                        max_chunk_size: int) -> List[Dict]:
        """回退方案：无法识别结构时，按行数均分（尽量在空行处断开）"""
        total_lines = len(lines)
        header_text = '\n'.join(lines[:header_end])
        header_size = len(header_text) + 300
        
        avg_line_len = sum(len(l) for l in lines) / max(len(lines), 1)
        lines_per_chunk = int((max_chunk_size - header_size) / max(avg_line_len + 1, 1))
        lines_per_chunk = max(lines_per_chunk, 100)
        
        chunk_groups: List[List[Dict]] = []
        i = header_end
        while i < total_lines:
            chunk_end = min(i + lines_per_chunk, total_lines)
            
            # 尝试在空行处断开，避免在代码中间切割
            if chunk_end < total_lines:
                for j in range(chunk_end - 1, max(i, chunk_end - 50) - 1, -1):
                    if not lines[j].strip():
                        chunk_end = j + 1
                        break
            
            chunk_groups.append([{
                'start': i,
                'end': chunk_end - 1,
                'name': f'lines_{i + 1}_{chunk_end}',
            }])
            i = chunk_end
        
        if not chunk_groups:
            chunk_groups = [[{
                'start': header_end,
                'end': total_lines - 1,
                'name': 'all',
            }]]
        
        total_chunks = len(chunk_groups)
        result = []
        for idx, group in enumerate(chunk_groups):
            numbered = cls._build_numbered_content(lines, header_end, group, idx, total_chunks)
            result.append({
                'chunk_index': idx,
                'total_chunks': total_chunks,
                'numbered_content': numbered,
                'is_chunked': True,
            })
        
        return result


def _json_repair_candidates(json_str: str):
    """生成多种 JSON 修复候选，从最保守到最激进。"""
    s = json_str.rstrip()
    
    # 统计缺失的括号
    open_braces = s.count('{') - s.count('}')
    open_brackets = s.count('[') - s.count(']')
    
    if open_braces <= 0 and open_brackets <= 0:
        # 括号已平衡，可能是其他问题
        yield "original", s
        return
    
    # 策略1：直接在末尾补全括号（处理最后的值是完整的情况）
    suffix = ']' * max(open_brackets, 0) + '}' * max(open_braces, 0)
    yield "direct_close", s + suffix
    
    # 策略2：回退到最后一个完整的 , 或 [ 或 { 然后补全
    # 找到最后一个逗号位置，截断到这里（丢掉最后一个不完整的元素）
    for i in range(len(s) - 1, max(0, len(s) - 500), -1):
        ch = s[i]
        if ch == ',':
            truncated = s[:i]
            ob = truncated.count('{') - truncated.count('}')
            ol = truncated.count('[') - truncated.count(']')
            sfx = ']' * max(ol, 0) + '}' * max(ob, 0)
            yield f"truncate_at_comma_{len(s)-i}", truncated + sfx
            break
    
    # 策略3：回退到最后一个 } 或 ] 然后补全
    for i in range(len(s) - 1, max(0, len(s) - 2000), -1):
        ch = s[i]
        if ch in ('}', ']'):
            truncated = s[:i+1]
            ob = truncated.count('{') - truncated.count('}')
            ol = truncated.count('[') - truncated.count(']')
            if ob >= 0 and ol >= 0:
                sfx = ']' * ol + '}' * ob
                yield f"truncate_at_close_{len(s)-i}", truncated + sfx
                break


class CodebaseIndexer:
    def __init__(
        self,
        llm,
        max_workers: int = 5,
        batch_size: int = 10,
        runtime: CodeAnalysisRuntime | None = None,
    ):
        self.llm = llm
        self.analysis_results = []
        self.runtime = runtime or CodeAnalysisRuntime.from_env(
            default_max_workers=max_workers,
            default_batch_size=batch_size,
        )
        self.max_workers = self.runtime.max_workers
        self.batch_size = self.runtime.batch_size
        
    def _get_system_prompt(self, file_type: str) -> str:
        base_prompt = f"""请你扮演一名资深的开发工程师、擅长所有的开发语言。你的任务是深度分析代码仓库中的代码，构建一个代码的索引能力。

        ## 背景与挑战
        1. **命名模糊**：表名/字段可能包含缩写、过时术语或纯技术命名。
        2. **逻辑隐晦**：核心业务逻辑分散在代码实现中，而非显式定义。
        3. **完整性**：对分析的代码文件要详细的分析，保证分析的完整性，尤其是保证entities中每一个concept中的attributes和functions完整性，不要漏掉一些attributes和functions。
        4. **api_endpoints**: 如果文件中涉及了api endpoint的定义的，一定要在api_endpoints字段中体现出来。

        ## 严格遵守的原则（行号定位）
        1. **代码已添加行号前缀**（格式：`行号|代码内容`），请直接读取每行开头的行号数字，不要自己计算或估算。
           例如看到 `  42|    def create_user(...)` 就知道这是第42行。
        2. `line_no` 字段必须直接引用代码行号前缀中的数字，严禁凭感觉填写。

        ## 函数调用关系提取规则（calls_to 字段）
        1. **仅记录业务相关调用**：只记录当前代码库中定义的函数/方法调用，忽略标准库（os、fmt、System.out）和第三方库（Django、Spring、React）的调用。
        2. **格式要求**：如果是同一个类内部的方法调用，直接写方法名（如 `validate`）；如果是调用其他类/对象的方法，使用 `类名.方法名` 格式（如 `OrderRepository.save`）；如果是调用全局函数，直接写函数名（如 `calculate_total`）。
        3. **不要遗漏**：仔细检查函数体中的每一行代码，找出所有对其他业务函数/方法的调用。
        4. **没有调用时**：如果函数内部没有调用任何其他业务方法，`calls_to` 设为空列表 `[]`。

        ## 需要忽略的内容
        1. 日志类（Logger, System.out）
        2. 监控埋点类（Metrics, Actuator）
        3. 纯技术层面的权限校验（除非涉及业务准入规则）
        4. 通用工具类（DateUtil, StringUtil）
        5. 单元测试代码

        ## 请严格按照以下JSON格式返回分析结果：

        {{
            "file_summary": "从业务角度概述文件的核心职责（2-3句话）。例如：'本文件负责处理用户下单的核心流程，包括库存预扣减和订单状态初始化。'",
            "file_path": "当前分析的文件的全路径，类似dao/user/create.py",
            "dependence": "代码文件中import进来的信息，用于分析代码之间的依赖关系",
            "has_api_endpoints":"代表当前文件是不是包含了api endpoint的定义，是的话就是true，没有就是false（true/false）",
            "entities": [
                {{
                    "name": "代码中对象或者类的真正的名称,不能自己编出来的（如：Order, User, OrderItem）",
                    "business_meaning": "详细的业务含义解释",
                    "details": "如果对应数据库表，列出关键字段的中文业务含义；如果是代码对象，列出核心属性的业务含义。",
                    "line_no": "这个entity在文件中行号的范围，比如100-160是定义了这个entity的，表达形式就是开始的行号-结束的行号（100-160类似这种）",
                    "attributes": [
                      {{
                        "name": "属性名",
                        "type": "数据类型",
                        "business_meaning": "属性的业务含义",
                        "is_identifier": "是否是唯一标识符（true/false）",
                        "constraints": "业务约束（如：必填、唯一、范围等）",
                        "line_no": "在文件中行号，比如100行是定义了这个字段的"
                      }}
                    ],
                    "functions": [
                      {{
                        "name": "方法/函数名",
                        "purpose": "方法的业务目的",
                        "input_semantics": "输入参数的业务含义",
                        "output_semantics": "返回值的业务含义",
                        "business_action": "执行的核心业务动作（如：创建用户、验证订单、计算费用）",
                        "line_no": "在文件中行号的范围，比如100-160是定义了这个方法的，表达形式就是开始的行号-结束的行号（100-160类似这种）",
                        "calls_to": ["该方法内部调用的其他方法/函数名列表（仅限当前代码库内的调用，不包括标准库和第三方库的调用）。例如：['validate_order', 'OrderRepository.save', 'send_notification']。如果没有调用其他方法，则为空列表[]"]
                      }}
                    ]
                }}
            ],
            "global_functions":[
                {{
                        "name": "当前文件中的全局方法，方法/函数名",
                        "purpose": "方法的业务目的",
                        "input_semantics": "输入参数的业务含义",
                        "output_semantics": "返回值的业务含义",
                        "business_action": "执行的核心业务动作（如：创建用户、验证订单、计算费用）",
                        "line_no": "在文件中行号的范围，比如100-160是定义了这个方法的，表达形式就是开始的行号-结束的行号（100-160类似这种）",
                        "calls_to": ["该方法内部调用的其他方法/函数名列表（仅限当前代码库内的调用，不包括标准库和第三方库的调用）。例如：['process_data', 'ConfigManager.load']。如果没有调用其他方法，则为空列表[]"]
                }}
            ],
            "api_endpoints": [
                {{
                  "method": "使用大写的形式记录http的方法，比如GET, POST, PUT, DELETE等",
                  "path": "归一化后的路径，参数要固定，避免每次处理出来的结果不一样",
                  "request": "这个api的请求参数结构体",
                  "response": "这个api的响应结构体",
                  "business_summary": "该接口的业务功能描述",
                  "file": "当前api所在的文件全路径，类似api/user/create.py",
                  "line_no": "在文件中多少行到多少行定义了这个api，表达形式就是开始的行号-结束的行号（100-160类似这种）"
                }}
            ]
        }}

        ## 分析与输出要求：
        1. **真实性原则**：分析必须基于提供的代码和表名，严禁臆造不存在的逻辑。
        2. **业务概念提取规则**：
           - `entities.name`：必须是代码中**实际定义**的对象/类/数据结构名称
           - 对于API参数，提取实际的请求/响应对象（如 `UserCreateRequest`）
           - 对于服务层方法参数，提取实际的DTO/VO对象
           - 对于领域层，提取实际的实体类或值对象
           - **严禁将数据库表名直接作为对象名**，除非代码中有对应的实体类定义
        3. **表操作判定**：在 `database_tables` 中，仅记录**当前代码文件中直接进行增删改查操作**的表。仅仅作为引用或类型定义的表不要列入此字段。
        4. **格式严格**：必须返回标准的、可解析的 JSON 格式字符串，不包含 Markdown 标记（如 ```json），不包含额外文本。

        """
        
        return base_prompt
    
    def analyze_file(self, file_info: Dict) -> Dict:
        """分析单个代码文件。对于过长的文件，自动按结构边界分块分析再合并结果。"""
        file_path = file_info['file_path']
        file_type = file_info['file_type']
        original_content = file_info['content']
        
        logger.info(f"CodebaseIndexer, 正在分析文件: {file_path}")

        if not original_content or len(original_content.strip()) < 10:
            logger.info(f"跳过空文件: {file_path}")
            return {
                'file_path': file_path,
                'file_type': file_type,
                'analysis_time': 0,
                'analysis_result': {'skip_reason': '文件内容为空或过短'},
                'status': 'skipped'
            }

        # 检查是否需要分块处理（使用 CodeSplitter 默认的 60000 字符阈值）
        # 安全保障：JSON 截断修复 + raw_response 重试 + 合并日志
        if CodeSplitter.needs_splitting(original_content):
            return self._analyze_file_chunked(file_info, original_content)

        # 普通文件：直接分析
        numbered_content = self._add_line_numbers(original_content)
        return self._analyze_single_chunk(
            file_info, original_content, numbered_content,
            is_chunked=False, chunk_index=0, total_chunks=1
        )
    
    def _analyze_file_chunked(self, file_info: Dict, original_content: str) -> Dict:
        """分块分析大型代码文件：分割 → 并行逐块分析 → 合并结果"""
        file_path = file_info['file_path']
        file_type = file_info['file_type']

        chunks = CodeSplitter.split_file(original_content, file_path)
        num_chunks = len(chunks)
        logger.info(
            f"文件 {file_path} 分割为 {num_chunks} 块，将按文件内顺序分析"
        )

        # 准备每块的分析参数
        chunk_tasks = []
        for chunk in chunks:
            if chunk.get('is_chunked'):
                numbered_content = chunk['numbered_content']
            else:
                numbered_content = self._add_line_numbers(chunk['content'])
            chunk_tasks.append({
                'numbered_content': numbered_content,
                'is_chunked': chunk.get('is_chunked', False),
                'chunk_index': chunk.get('chunk_index', 0),
                'total_chunks': chunk.get('total_chunks', 1),
            })

        chunk_results = [None] * num_chunks  # 保持顺序
        total_time = 0

        for idx, task in enumerate(chunk_tasks):
            try:
                result = self._analyze_single_chunk(
                    file_info, original_content, task['numbered_content'],
                    is_chunked=task['is_chunked'],
                    chunk_index=task['chunk_index'],
                    total_chunks=task['total_chunks'],
                )
                if result.get('status') == 'success':
                    ar = result['analysis_result']
                    if 'raw_response' in ar:
                        logger.warning(
                            f"块 {idx + 1}/{num_chunks} 返回 raw_response "
                            f"(JSON 解析失败)，将重试: {file_path}")
                        chunk_results[idx] = None  # 标记为需要重试
                    else:
                        chunk_results[idx] = ar
                    total_time += result.get('analysis_time', 0)
                else:
                    logger.warning(
                        f"块 {idx + 1}/{num_chunks} 分析失败: {file_path}")
            except Exception as e:
                logger.warning(
                    f"块 {idx + 1}/{num_chunks} 分析异常: {file_path} - {e}")

        # 对 raw_response 的块进行单独重试（最多 2 次）
        for retry_round in range(1, 3):
            failed_indices = [i for i, r in enumerate(chunk_results) if r is None]
            if not failed_indices:
                break
            logger.info(f"重试第 {retry_round} 轮: {len(failed_indices)} 块 ({file_path})")
            for idx in failed_indices:
                try:
                    task = chunk_tasks[idx]
                    result = self._analyze_single_chunk(
                        file_info, original_content, task['numbered_content'],
                        is_chunked=task['is_chunked'],
                        chunk_index=task['chunk_index'],
                        total_chunks=task['total_chunks'],
                    )
                    if result.get('status') == 'success':
                        ar = result['analysis_result']
                        if 'raw_response' not in ar:
                            chunk_results[idx] = ar
                            total_time += result.get('analysis_time', 0)
                            logger.info(f"块 {idx + 1}/{num_chunks} 重试成功")
                        else:
                            logger.warning(
                                f"块 {idx + 1}/{num_chunks} 重试仍返回 raw_response")
                except Exception as e:
                    logger.warning(
                        f"块 {idx + 1}/{num_chunks} 重试异常: {e}")

        # 过滤掉失败的块（None）
        valid_results = [r for r in chunk_results if r is not None]

        if not valid_results:
            return {
                'file_path': file_path,
                'file_type': file_type,
                'analysis_time': round(total_time, 2),
                'analysis_result': {'error': '所有分块分析均失败'},
                'status': 'error',
                'chunked': True,
            }

        # 合并所有分块的分析结果
        merged = self._merge_chunk_results(valid_results)

        # 使用静态分析修正行号（基于完整的原始内容）
        merged = self._correct_line_numbers(merged, original_content, file_path)

        logger.info(f"CodebaseIndexer 完成分块分析: {file_path} "
                     f"({num_chunks} 块并行, 总耗时: {total_time:.2f}s)")

        return {
            'file_path': file_path,
            'file_type': file_type,
            'analysis_time': round(total_time, 2),
            'analysis_result': merged,
            'status': 'success',
            'chunked': True,
            'chunk_count': num_chunks,
        }
    
    def _analyze_single_chunk(self, file_info: Dict, original_content: str,
                               numbered_content: str, is_chunked: bool = False,
                               chunk_index: int = 0, total_chunks: int = 1) -> Dict:
        """分析单个代码块（可能是完整文件或文件的一个分块）"""
        file_path = file_info['file_path']
        file_type = file_info['file_type']
        chunk_label = f" (块 {chunk_index + 1}/{total_chunks})" if is_chunked else ""
        
        max_retries = 3
        last_error = None
        
        for attempt in range(1, max_retries + 1):
            try:
                prompt = self._get_system_prompt(file_type)
                
                # 分块文件：在 prompt 中添加分块说明
                if is_chunked:
                    chunk_notice = f"""

        ## 特别说明（文件分块）
        当前文件较大，已按代码结构边界分割为 {total_chunks} 块，当前是第 {chunk_index + 1} 块。
        - 文件的 import/依赖信息已完整保留在每块的开头
        - 请只分析当前块中包含的代码，不要臆造不在当前块中的内容
        - 行号是原始文件的行号，请准确引用
        - dependence 字段请提取当前块头部的 import 信息
        """
                    prompt = prompt + chunk_notice
                
                logger.debug(f"analyze_single_chunk, prompt = {prompt}")
                system_message = SystemMessage(content=prompt)
                human_message = HumanMessage(
                    content=f"请分析以下文件{chunk_label}:\n\n"
                            f"文件路径: {file_path}\n文件类型: {file_type}\n\n"
                            f"文件内容:\n```\n{numbered_content}\n```"
                )

                start_time = time.time()
                response = self.runtime.invoke_llm(
                    self.llm,
                    [system_message, human_message],
                    label=f"code-index:{file_path}",
                )
                analysis_time = time.time() - start_time

                analysis_result = self._parse_llm_response(response.content)

                # 非分块文件直接修正行号；分块文件在合并后统一修正
                if not is_chunked:
                    analysis_result = self._correct_line_numbers(
                        analysis_result, original_content, file_path)
                
                result = {
                    'file_path': file_path,
                    'file_type': file_type,
                    'analysis_time': round(analysis_time, 2),
                    'analysis_result': analysis_result,
                    'status': 'success',
                }
                
                logger.info(f"完成分析: {file_path}{chunk_label} (耗时: {analysis_time:.2f}s)")
                return result
                
            except Exception as e:
                last_error = e
                if attempt < max_retries:
                    wait_time = 2 ** attempt
                    logger.warning(
                        f"分析失败 (第{attempt}次): {file_path}{chunk_label} "
                        f"- {str(e)}，{wait_time}秒后重试...")
                    time.sleep(wait_time)
                else:
                    logger.info(
                        f"分析失败 (已重试{max_retries}次): {file_path}{chunk_label} "
                        f"- {str(e)}")

        return {
            'file_path': file_path,
            'file_type': file_type,
            'analysis_time': 0,
            'analysis_result': {'error': str(last_error)},
            'status': 'error',
        }
    
    def _merge_chunk_results(self, chunk_results: List[Dict]) -> Dict:
        """合并多个分块的 LLM 分析结果。

        分层合并策略：
        ─────────────────────────────────────────────────────────
        技术字段（名称来自代码，确定性高）→ 标准化 + 精确匹配
          - entities: 按 name 精确匹配，同名合并 functions/attributes
          - global_functions: 按 name 精确匹配
          - api_endpoints: 按 method(大写)+path(strip) 精确匹配
          - dependence: 字符串去重
          - has_api_endpoints: OR 逻辑

        语义字段（LLM 自由发挥，不同块可能描述不一致）→ LLM 二次合并
          - file_summary: 收集后用 LLM 合并为统一摘要
        ─────────────────────────────────────────────────────────
        """
        merged = {
            'file_summary': '',
            'file_path': '',
            'dependence': '',
            'has_api_endpoints': 'false',
            'entities': [],
            'global_functions': [],
            'api_endpoints': [],
        }

        summaries = []
        all_dependencies = []

        skipped = 0
        for result in chunk_results:
            if not result or 'error' in result or 'raw_response' in result:
                reason = 'empty' if not result else ('error' if 'error' in result else 'raw_response')
                logger.warning(f"合并时跳过无效块 (原因: {reason})")
                skipped += 1
                continue

            # file_path
            if result.get('file_path') and not merged['file_path']:
                merged['file_path'] = result['file_path']

            # file_summary: 收集所有块的摘要（后续 LLM 合并）
            if result.get('file_summary'):
                summaries.append(result['file_summary'])

            # dependence: 收集去重
            if result.get('dependence'):
                dep = result['dependence'].strip()
                if dep and dep not in all_dependencies:
                    all_dependencies.append(dep)

            # has_api_endpoints: 任一块有 API 即为 true
            if str(result.get('has_api_endpoints', '')).lower() == 'true':
                merged['has_api_endpoints'] = 'true'

            # entities: 按 name 精确匹配去重，同名合并 functions/attributes
            # （prompt 要求 name 必须是代码中实际定义的类/对象名，确定性高）
            existing_entity_names = {e['name'] for e in merged['entities']}
            for entity in result.get('entities', []):
                ename = entity.get('name', '')
                if not ename:
                    continue
                if ename not in existing_entity_names:
                    merged['entities'].append(entity)
                    existing_entity_names.add(ename)
                else:
                    for existing in merged['entities']:
                        if existing['name'] == ename:
                            # 合并 functions（按 name 去重）
                            existing_func_names = {
                                f.get('name') for f in existing.get('functions', [])}
                            for func in entity.get('functions', []):
                                if func.get('name') and func['name'] not in existing_func_names:
                                    existing.setdefault('functions', []).append(func)
                                    existing_func_names.add(func['name'])
                            # 合并 attributes（按 name 去重）
                            existing_attr_names = {
                                a.get('name') for a in existing.get('attributes', [])}
                            for attr in entity.get('attributes', []):
                                if attr.get('name') and attr['name'] not in existing_attr_names:
                                    existing.setdefault('attributes', []).append(attr)
                                    existing_attr_names.add(attr['name'])
                            # 合并 business_meaning（取更长的描述）
                            new_bm = entity.get('business_meaning', '')
                            old_bm = existing.get('business_meaning', '')
                            if len(new_bm) > len(old_bm):
                                existing['business_meaning'] = new_bm
                            break

            # global_functions: 按 name 精确匹配去重
            existing_gf_names = {
                f.get('name', '').strip() for f in merged['global_functions']}
            for func in result.get('global_functions', []):
                fname = func.get('name', '').strip()
                if fname and fname not in existing_gf_names:
                    merged['global_functions'].append(func)
                    existing_gf_names.add(fname)

            # api_endpoints: 按 method(大写)+path(strip) 去重
            existing_eps = {
                (e.get('method', '').upper().strip(),
                 e.get('path', '').strip())
                for e in merged['api_endpoints']}
            for ep in result.get('api_endpoints', []):
                key = (ep.get('method', '').upper().strip(),
                       ep.get('path', '').strip())
                if key not in existing_eps:
                    merged['api_endpoints'].append(ep)
                    existing_eps.add(key)

        if skipped > 0:
            logger.warning(f"合并统计: {len(chunk_results)} 块中 {skipped} 块无效被跳过，"
                           f"{len(chunk_results) - skipped} 块有效参与合并")

        # ─── 语义字段：LLM 二次合并 ───
        if len(summaries) == 1:
            merged['file_summary'] = summaries[0]
        elif len(summaries) > 1:
            merged['file_summary'] = self._llm_consolidate_summaries(summaries)

        # 组合依赖
        merged['dependence'] = '\n'.join(all_dependencies) if all_dependencies else ''

        return merged

    # ──────────────────────────────────────────────────────────────
    #  LLM 语义合并辅助方法（仅在分块大文件合并时调用）
    # ──────────────────────────────────────────────────────────────

    def _llm_consolidate_summaries(self, summaries: List[str],
                                    max_retries: int = 3) -> str:
        """用 LLM 将多个分块摘要合并为一个统一的文件摘要。

        由于大文件被分块分析，每块独立产生摘要，内容可能有重叠或视角不同。
        通过一次轻量 LLM 调用将它们整合为一个简洁、完整、不重复的摘要。
        失败时自动重试，最多 max_retries 次。
        """
        parts = []
        for i, s in enumerate(summaries, 1):
            parts.append(f"【第{i}块摘要】\n{s}")
        all_summaries = '\n\n'.join(parts)

        prompt = f"""以下是对同一个代码文件不同部分的分析摘要。由于文件较大被分块分析，产生了多段摘要。
请将它们合并为一个简洁、完整、不重复的文件总结（2-3句话，从业务角度概述文件的核心职责）。

{all_summaries}

要求：
- 直接输出合并后的摘要文本
- 不要包含任何 JSON、Markdown 标记或额外格式
- 不要出现"第X块"之类的分块痕迹
- 去除重复内容，保留最完整的描述"""

        for attempt in range(1, max_retries + 1):
            try:
                response = self.runtime.invoke_llm(
                    self.llm,
                    [
                        SystemMessage(content="你是一名资深开发工程师，擅长从业务角度总结代码文件的职责。"),
                        HumanMessage(content=prompt),
                    ],
                    label="code-index-summary-consolidate",
                )
                consolidated = response.content.strip()
                if consolidated and len(consolidated) > 10:
                    logger.info(f"LLM 摘要合并成功: {len(summaries)} 块 → {len(consolidated)} 字符")
                    return consolidated
                logger.warning(f"LLM 摘要合并返回内容过短 (第{attempt}次)，重试...")
            except Exception as e:
                logger.warning(f"LLM 摘要合并失败 (第{attempt}/{max_retries}次): {e}")
                if attempt < max_retries:
                    time.sleep(2 ** attempt)

        # 所有重试都失败后，最终 fallback
        logger.error(f"LLM 摘要合并重试 {max_retries} 次均失败，使用简单拼接")
        return ' '.join(summaries)
    
    def _add_line_numbers(self, content: str) -> str:
        """给代码的每一行添加行号前缀，帮助 LLM 准确定位行号。
        
        格式示例:
          1|import os
          2|from pathlib import Path
         10|class DatabaseManager:
        100|    def connect(self):
        """
        lines = content.split('\n')
        width = len(str(len(lines)))
        return '\n'.join(f"{i+1:>{width}}|{line}" for i, line in enumerate(lines))

    def _parse_llm_response(self, response: str) -> Dict:
        try:
            # Normalize Unicode smart quotes to ASCII quotes (LLM may produce these)
            response = response.replace('\u201c', '"').replace('\u201d', '"')
            response = response.replace('\u2018', "'").replace('\u2019', "'")

            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                json_str = json_match.group()
                return json.loads(json_str)
            else:
                return {'raw_response': response}
        except json.JSONDecodeError:
            # ── 尝试修复截断的 JSON（LLM 输出 token 超限时常见）──
            if json_match:
                repaired = self._try_repair_truncated_json(json_match.group())
                if repaired is not None:
                    logger.info("JSON 截断已修复，成功解析")
                    return repaired
            logger.warning(f"LLM 返回内容无法解析为 JSON (长度={len(response)})")
            return {'raw_response': response}

    @staticmethod
    def _try_repair_truncated_json(json_str: str) -> Optional[Dict]:
        """尝试修复被截断的 JSON。
        
        LLM 输出 token 超限时，JSON 会在中间断开，例如：
        {"entities": [{"name": "Foo", "functions": [{"name": "bar"   ← 截断
        
        策略：
        1. 去掉最后一个不完整的 key-value 对
        2. 补全缺失的 ], } 使 JSON 闭合
        """
        # 先清除末尾不完整的字符串值
        # 例如 "name": "bar  ← 没有闭合的引号
        cleaned = json_str.rstrip()
        
        # 检查是否以未闭合的字符串结尾
        if cleaned.endswith('"') or cleaned.endswith('\\'):
            pass  # 可能是正常闭合
        
        # 尝试多种截断修复策略
        for attempt_name, candidate in _json_repair_candidates(cleaned):
            try:
                result = json.loads(candidate)
                if isinstance(result, dict):
                    logger.debug(f"JSON 修复成功 (策略: {attempt_name})")
                    return result
            except json.JSONDecodeError:
                continue
        
        return None

    # ========================================================================
    # 行号修正：使用静态分析修正 LLM 返回的行号
    # ========================================================================

    def _correct_line_numbers(self, analysis_result: Dict, content: str, file_path: str) -> Dict:
        """根据文件类型选择合适的静态分析方式修正行号"""
        if not analysis_result or 'raw_response' in analysis_result or 'error' in analysis_result:
            return analysis_result

        ext = Path(file_path).suffix.lower()

        if ext == '.py':
            return self._correct_line_numbers_python(analysis_result, content)
        else:
            return self._correct_line_numbers_generic(analysis_result, content, ext)

    # ---------- Python: 使用 AST 精确修正 ----------

    def _correct_line_numbers_python(self, analysis_result: Dict, content: str) -> Dict:
        """使用 Python AST 精确修正行号（Python 3.8+ 支持 end_lineno）"""
        try:
            tree = ast.parse(content)
        except SyntaxError:
            logger.warning("Python AST 解析失败，跳过行号修正")
            return analysis_result

        line_map = self._build_python_line_map(tree)

        # 修正 entities（类）
        for entity in analysis_result.get("entities", []):
            name = entity.get("name", "")
            key = f"class:{name}"
            if key in line_map:
                start, end = line_map[key]
                old = entity.get("line_no", "")
                entity["line_no"] = f"{start}-{end}"
                if old != entity["line_no"]:
                    logger.debug(f"修正 entity {name}: {old} -> {entity['line_no']}")

            # 修正 attributes
            for attr in entity.get("attributes", []):
                attr_key = f"attr:{name}.{attr.get('name', '')}"
                if attr_key in line_map:
                    start, _ = line_map[attr_key]
                    attr["line_no"] = str(start)

            # 修正 functions
            for func in entity.get("functions", []):
                func_key = f"func:{name}.{func.get('name', '')}"
                if func_key in line_map:
                    start, end = line_map[func_key]
                    func["line_no"] = f"{start}-{end}"

        # 修正 global_functions
        for func in analysis_result.get("global_functions", []):
            func_key = f"global_func:{func.get('name', '')}"
            if func_key in line_map:
                start, end = line_map[func_key]
                func["line_no"] = f"{start}-{end}"

        # 修正 api_endpoints（通过装饰器函数匹配）
        for endpoint in analysis_result.get("api_endpoints", []):
            ep_path = endpoint.get("path", "")
            ep_method = endpoint.get("method", "").lower()
            matched = self._find_api_endpoint_lines_python(tree, content, ep_path, ep_method)
            if matched:
                endpoint["line_no"] = f"{matched[0]}-{matched[1]}"

        return analysis_result

    def _build_python_line_map(self, tree: ast.Module) -> Dict[str, Tuple[int, int]]:
        """从 AST 构建 {标识key: (start_line, end_line)} 映射"""
        line_map: Dict[str, Tuple[int, int]] = {}

        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                end_line = getattr(node, 'end_lineno', None) or node.lineno
                line_map[f"class:{node.name}"] = (node.lineno, end_line)

                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        end = getattr(item, 'end_lineno', None) or item.lineno
                        line_map[f"func:{node.name}.{item.name}"] = (item.lineno, end)

                        # __init__ 中的 self.xxx = ... 赋值
                        if item.name == '__init__':
                            for stmt in ast.walk(item):
                                if isinstance(stmt, ast.Assign):
                                    for target in stmt.targets:
                                        if (isinstance(target, ast.Attribute) and
                                                isinstance(target.value, ast.Name) and
                                                target.value.id == 'self'):
                                            line_map[f"attr:{node.name}.{target.attr}"] = (stmt.lineno, stmt.lineno)

                    # 类级别的注解属性（Pydantic BaseModel、dataclass 等）
                    if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                        line_map[f"attr:{node.name}.{item.target.id}"] = (item.lineno, item.lineno)
                    elif isinstance(item, ast.Assign):
                        for target in item.targets:
                            if isinstance(target, ast.Name):
                                line_map[f"attr:{node.name}.{target.id}"] = (item.lineno, item.lineno)

            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                end_line = getattr(node, 'end_lineno', None) or node.lineno
                line_map[f"global_func:{node.name}"] = (node.lineno, end_line)

        return line_map

    def _find_api_endpoint_lines_python(self, tree: ast.Module, content: str,
                                         ep_path: str, ep_method: str) -> Optional[Tuple[int, int]]:
        """通过 AST + 源码搜索定位 FastAPI/Flask 等装饰器路由的行号"""
        lines = content.split('\n')
        
        for node in tree.body:
            # 顶层的路由函数
            nodes_to_check = [node]
            if isinstance(node, ast.ClassDef):
                nodes_to_check = node.body

            for item in nodes_to_check:
                if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if not item.decorator_list:
                    continue

                for dec in item.decorator_list:
                    dec_line_idx = dec.lineno - 1  # 0-indexed
                    if dec_line_idx < len(lines):
                        dec_text = lines[dec_line_idx]
                        # 标准化路径匹配：忽略 {param} 差异
                        path_prefix = ep_path.split('{')[0].rstrip('/')
                        if (ep_method in dec_text.lower() and
                                (path_prefix in dec_text or ep_path in dec_text)):
                            end_line = getattr(item, 'end_lineno', None) or item.lineno
                            return (dec.lineno, end_line)
        return None

    # ---------- 通用语言：使用正则修正 ----------

    _CLASS_PATTERNS = {
        '.java': r'^\s*(public|private|protected)?\s*(abstract|final|static)?\s*(class|interface|enum)\s+{name}\b',
        '.ts':   r'^\s*(export\s+)?(default\s+)?(abstract\s+)?(class|interface)\s+{name}\b',
        '.tsx':  r'^\s*(export\s+)?(default\s+)?(abstract\s+)?(class|interface)\s+{name}\b',
        '.js':   r'^\s*(export\s+)?(default\s+)?class\s+{name}\b',
        '.jsx':  r'^\s*(export\s+)?(default\s+)?class\s+{name}\b',
        '.go':   r'^\s*type\s+{name}\s+(struct|interface)\b',
        '.cs':   r'^\s*(public|private|protected|internal)?\s*(abstract|sealed|static|partial)?\s*(class|interface|struct|record)\s+{name}\b',
        '.kt':   r'^\s*(open|abstract|data|sealed|enum)?\s*(class|interface|object)\s+{name}\b',
        '.rs':   r'^\s*(pub\s+)?(struct|enum|trait)\s+{name}\b',
        '.swift': r'^\s*(public|private|internal|open)?\s*(final\s+)?(class|struct|enum|protocol)\s+{name}\b',
        '.cpp':  r'^\s*(class|struct)\s+{name}\b',
        '.c':    r'^\s*(typedef\s+)?struct\s+{name}\b',
        '.h':    r'^\s*(class|struct)\s+{name}\b',
        '.hpp':  r'^\s*(class|struct)\s+{name}\b',
        '.php':  r'^\s*(abstract\s+|final\s+)?(class|interface|trait)\s+{name}\b',
        '.rb':   r'^\s*class\s+{name}\b',
        '.scala': r'^\s*(case\s+|abstract\s+|sealed\s+|final\s+|implicit\s+|lazy\s+)*(class|object|trait)\s+{name}\b',
        '.vue':  r'^\s*(export\s+)?(default\s+)?class\s+{name}\b',
    }

    _FUNC_PATTERNS = {
        '.java': r'^\s*(public|private|protected)?\s*(static|abstract|final|synchronized)?\s*[\w<>\[\],\s]+\s+{name}\s*\(',
        '.ts':   r'^\s*(export\s+)?(async\s+)?function\s+{name}\s*[\(<]|^\s*(public|private|protected)?\s*(static\s+)?(async\s+)?{name}\s*[\(<]',
        '.tsx':  r'^\s*(export\s+)?(async\s+)?function\s+{name}\s*[\(<]|^\s*(public|private|protected)?\s*(static\s+)?(async\s+)?{name}\s*[\(<]',
        '.js':   r'^\s*(export\s+)?(async\s+)?function\s+{name}\s*\(|^\s*(const|let|var)\s+{name}\s*=|^\s*(static\s+)?(async\s+)?#?{name}\s*\(',
        '.jsx':  r'^\s*(export\s+)?(async\s+)?function\s+{name}\s*\(|^\s*(const|let|var)\s+{name}\s*=|^\s*(static\s+)?(async\s+)?#?{name}\s*\(',
        '.go':   r'^\s*func\s+(\([^)]+\)\s+)?{name}\s*\(',
        '.cs':   r'^\s*(public|private|protected|internal)?\s*(static|virtual|override|abstract|async)?\s*[\w<>\[\],\s]+\s+{name}\s*[\(<]',
        '.kt':   r'^\s*(?:\w+\s+)*fun\s+{name}\s*[\(<]',
        '.rs':   r'^\s*(pub\s+)?(async\s+)?fn\s+{name}\s*[\(<]',
        '.swift': r'^\s*(public|private|internal|open)?\s*(static|class)?\s*func\s+{name}\s*[\(<]',
        '.cpp':  r'^\s*[\w:<>\s\*&]+\s+{name}\s*\(',
        '.c':    r'^\s*[\w\s\*]+\s+{name}\s*\(',
        '.h':    r'^\s*[\w:<>\s\*&]+\s+{name}\s*\(',
        '.hpp':  r'^\s*[\w:<>\s\*&]+\s+{name}\s*\(',
        '.php':  r'^\s*(public|private|protected)?\s*(static\s+)?function\s+{name}\s*\(',
        '.rb':   r'^\s*def\s+{name}\b',
        '.scala': r'^\s*(?:\w+\s+)*def\s+{name}\s*[\[\(]',
        '.vue':  r'^\s*(async\s+)?{name}\s*\(',
    }

    def _correct_line_numbers_generic(self, analysis_result: Dict, content: str, ext: str) -> Dict:
        """使用正则匹配修正非 Python 文件的行号，支持所有目标语言"""
        lines = content.split('\n')
        class_pattern = self._CLASS_PATTERNS.get(ext)
        func_pattern = self._FUNC_PATTERNS.get(ext)

        if not class_pattern and not func_pattern:
            return analysis_result

        def find_line(pattern_tpl, name, start=0, end=None):
            """查找匹配行号（1-indexed），未找到返回 None"""
            if not pattern_tpl or not name:
                return None
            pat = pattern_tpl.replace('{name}', re.escape(name))
            boundary = end if end else len(lines)
            for i in range(start, boundary):
                if re.search(pat, lines[i]):
                    return i + 1
            return None

        def find_brace_block_end(start_0):
            """通过大括号嵌套层级找到代码块结束行（1-indexed）"""
            depth = 0
            found_open = False
            in_str = False
            str_char = None
            for i in range(start_0, len(lines)):
                line = lines[i]
                j = 0
                while j < len(line):
                    ch = line[j]
                    if in_str:
                        if ch == str_char and (j == 0 or line[j - 1] != '\\'):
                            in_str = False
                    else:
                        if ch in ('"', "'", '`'):
                            in_str = True
                            str_char = ch
                        elif ch == '/' and j + 1 < len(line) and line[j + 1] == '/':
                            break  # 行注释，跳过本行剩余
                        elif ch == '{':
                            # 跳过 Go 类型字面量 interface{}, struct{} 等空大括号对
                            if j + 1 < len(line) and line[j + 1] == '}':
                                j += 1  # 跳过紧邻的 }
                            else:
                                depth += 1
                                found_open = True
                        elif ch == '}':
                            depth -= 1
                            if found_open and depth <= 0:
                                return i + 1
                    j += 1
            return len(lines)

        def find_ruby_end(start_0):
            """Ruby: 通过 class/def/do/if 等开启词与 end 匹配找到块结束行"""
            OPENERS = re.compile(
                r'^(class|module|def|do|if|unless|while|until|for|case|begin)\b')
            depth = 0
            for i in range(start_0, len(lines)):
                stripped = lines[i].strip()
                if not stripped or stripped.startswith('#'):
                    continue
                first_word = stripped.split()[0] if stripped.split() else ''
                if OPENERS.match(first_word):
                    depth += 1
                elif first_word == 'end':
                    depth -= 1
                    if depth <= 0:
                        return i + 1
            return len(lines)

        def find_block_end(start_0):
            """根据语言选择合适的块结束检测方式"""
            if ext == '.rb':
                return find_ruby_end(start_0)
            elif use_braces:
                return find_brace_block_end(start_0)
            else:
                return len(lines)

        use_braces = ext in ('.java', '.ts', '.tsx', '.js', '.jsx', '.cs', '.kt',
                             '.swift', '.cpp', '.c', '.h', '.hpp', '.php', '.scala', '.go', '.rs',
                             '.dart', '.vue')

        # 收集所有 entity 的 start 行用于划分范围
        entity_starts = []
        for entity in analysis_result.get("entities", []):
            name = entity.get("name", "")
            start = find_line(class_pattern, name)
            if start:
                entity_starts.append((name, start))
        entity_starts.sort(key=lambda x: x[1])

        # 修正 entity
        for entity in analysis_result.get("entities", []):
            name = entity.get("name", "")
            start = find_line(class_pattern, name)
            if not start:
                continue

            if use_braces or ext == '.rb':
                end = find_block_end(start - 1)
            else:
                next_starts = [s for n, s in entity_starts if s > start]
                end = (min(next_starts) - 1) if next_starts else len(lines)
                while end > start and not lines[end - 1].strip():
                    end -= 1

            entity["line_no"] = f"{start}-{end}"

            # ---------- 修正 entity 内的 functions ----------
            if func_pattern:
                if ext == '.go':
                    # Go: 方法通过 receiver 定义在 struct 外部
                    for func in entity.get("functions", []):
                        fn = func.get("name", "")
                        recv_pat = rf'^\s*func\s+\(\s*\w+\s+\*?{re.escape(name)}\s*\)\s+{re.escape(fn)}\s*[\[\(]'
                        for i in range(len(lines)):
                            if re.search(recv_pat, lines[i]):
                                func["line_no"] = f"{i + 1}-{find_brace_block_end(i)}"
                                break

                elif ext == '.rs':
                    # Rust: 方法在 impl 块中定义
                    impl_pat = rf'^\s*(pub(\s*\(crate\))?\s+)?impl(\s*<[^>]*>)?\s+{re.escape(name)}\b'
                    impl_ranges = []
                    i = 0
                    while i < len(lines):
                        if re.search(impl_pat, lines[i]):
                            ie = find_brace_block_end(i)
                            impl_ranges.append((i, ie))
                            i = ie
                        else:
                            i += 1

                    for func in entity.get("functions", []):
                        fn = func.get("name", "")
                        fn_pat = func_pattern.replace('{name}', re.escape(fn))
                        for impl_s, impl_e in impl_ranges:
                            found = False
                            for j in range(impl_s, impl_e):
                                if re.search(fn_pat, lines[j]):
                                    func["line_no"] = f"{j + 1}-{min(find_brace_block_end(j), impl_e)}"
                                    found = True
                                    break
                            if found:
                                break

                else:
                    # 标准: 在 entity 行号范围内搜索
                    for func in entity.get("functions", []):
                        fn = func.get("name", "")
                        fstart = find_line(func_pattern, fn, start - 1, end)
                        if fstart:
                            fend = min(find_block_end(fstart - 1), end)
                            func["line_no"] = f"{fstart}-{fend}"

            # ---------- 修正 entity 内的 attributes ----------
            for attr in entity.get("attributes", []):
                attr_name = attr.get("name", "")
                if not attr_name:
                    continue
                attr_pat = rf'\b{re.escape(attr_name)}\b'
                for i in range(start - 1, min(end, len(lines))):
                    if re.search(attr_pat, lines[i]):
                        attr["line_no"] = str(i + 1)
                        break

        # 修正 global_functions
        if func_pattern:
            for func in analysis_result.get("global_functions", []):
                fn = func.get("name", "")
                fstart = find_line(func_pattern, fn)
                if fstart:
                    fend = find_block_end(fstart - 1)
                    func["line_no"] = f"{fstart}-{fend}"

        return analysis_result
    
    def analyze_files_sequential(self, file_list: List[Dict]) -> List[Dict]:
        logger.info(f"CodebaseIndexer, 开始顺序分析 {len(file_list)} 个文件...")
        
        for i, file_info in enumerate(file_list, 1):
            logger.info(f"\n进度: {i}/{len(file_list)}")

            analysis_result = self.analyze_file(file_info)
            self.analysis_results.append(analysis_result)

            if i < len(file_list):
                time.sleep(1)
        
        logger.info(f"\n所有文件分析完成！共分析 {len(self.analysis_results)} 个文件")
        return self.analysis_results
    
    def analyze_files_concurrent(self, file_list: List[Dict]) -> List[Dict]:
        logger.info(f"CodebaseIndexer ,开始并发分析 {len(file_list)} 个文件...")
        logger.info(f"批次大小: {self.batch_size}, 最大并发数: {self.max_workers}")

        batches = [file_list[i:i + self.batch_size] for i in range(0, len(file_list), self.batch_size)]
        
        total_batches = len(batches)
        total_processed = 0
        
        for batch_num, batch in enumerate(batches, 1):
            logger.info(f"\n处理第 {batch_num}/{total_batches} 批次 ({len(batch)} 个文件)")
            
            batch_results = self._process_batch(batch)
            self.analysis_results.extend(batch_results)
            
            total_processed += len(batch)
            logger.info(f"总体进度: {total_processed}/{len(file_list)} ({total_processed/len(file_list)*100:.1f}%)")

            if batch_num < total_batches:
                logger.info("批次间等待...")
                time.sleep(2)
        
        logger.info(f"\n所有文件分析完成！共分析 {len(self.analysis_results)} 个文件")
        return self.analysis_results
    
    def _process_batch(self, batch: List[Dict]) -> List[Dict]:
        batch_results = []

        completed_count = 0
        for file_info, result, exc in self.runtime.map_unordered(
            batch,
            self.analyze_file,
            label="code-index-files",
        ):
            if exc is None and result is not None:
                batch_results.append(result)
                completed_count += 1
                logger.info(f"批次进度: {completed_count}/{len(batch)}")
                continue

            error_result = {
                'file_path': file_info['file_path'],
                'file_type': file_info['file_type'],
                'analysis_time': 0,
                'analysis_result': {'error': str(exc)},
                'status': 'error'
            }
            batch_results.append(error_result)
            completed_count += 1
            logger.info(f"批次进度: {completed_count}/{len(batch)} - 分析失败: {file_info['file_path']}")
        
        return batch_results
    
    def analyze_files(self, file_list: List[Dict], concurrent: bool = True) -> List[Dict]:
        if concurrent:
            return self.analyze_files_concurrent(file_list)
        else:
            return self.analyze_files_sequential(file_list)

    def format_llm_output(self, answer) -> dict:
        logger.info(f"code -> format_llm_output, answer: {answer}")
        return parse_llm_output_string(
            answer.content,
            use_single_key_fallback=True,
        )

    def index_codebase(self, local_repo_dir):
        if not local_repo_dir:
            return "", "", ""

        coder_file_lister = CodeFileLister(local_repo_dir, file_types=['code'])

        all_code_files = coder_file_lister.find_target_files()

        logger.debug(f" all_code_files = {all_code_files}")

        self.analyze_files(all_code_files, concurrent=True)

        formatted_code_analyse_result = json.dumps(self.analysis_results, ensure_ascii=False, indent=4)

        logger.info(f"index_codebase result: {formatted_code_analyse_result}")

        return self.analysis_results


def convert_to_code_analyzer_format(codebase_index_results: List[Dict]) -> List[Dict]:
    """
    将 CodebaseIndexer 的分析结果转换为 CodeAnalyzer 格式，
    避免对代码文件进行两次 LLM 分析。
    
    CodebaseIndexer 输出格式:
        - file_summary, file_path, dependence, has_api_endpoints
        - entities (with line_no, attributes, functions)
        - global_functions
        - api_endpoints (with line_no)
    
    CodeAnalyzer 期望格式:
        - file_summary, key_functions, business_concepts
        - api_endpoints, database_tables
    """
    converted_results = []
    
    for result in codebase_index_results:
        if result.get("status") != "success":
            converted_results.append(result)
            continue
            
        analysis = result.get("analysis_result", {})
        
        # 从 entities 和 global_functions 提取 key_functions
        key_functions = []
        for entity in analysis.get("entities", []):
            for func in entity.get("functions", []):
                purpose = func.get("purpose", "")
                business_action = func.get("business_action", "")
                func_name = func.get("name", "")
                desc = purpose if purpose else business_action
                if desc:
                    key_functions.append(f"{entity.get('name', '')}.{func_name}: {desc}")
                    
        for func in analysis.get("global_functions", []):
            purpose = func.get("purpose", "")
            business_action = func.get("business_action", "")
            func_name = func.get("name", "")
            desc = purpose if purpose else business_action
            if desc:
                key_functions.append(f"{func_name}: {desc}")
        
        # 将 entities 转换为 business_concepts（保留 line_no 以供下游定位代码）
        business_concepts = []
        for entity in analysis.get("entities", []):
            attributes = [attr.copy() for attr in entity.get("attributes", [])]
            functions = [func.copy() for func in entity.get("functions", [])]
            
            concept = {
                "name": entity.get("name", ""),
                "type": "Entity",
                "description": entity.get("business_meaning", ""),
                "business_meaning": entity.get("business_meaning", ""),
                "details": entity.get("details", ""),
                "attributes": attributes,
                "functions": functions,
                "line_no": entity.get("line_no", ""),
            }
            business_concepts.append(concept)
        
        # 转换 api_endpoints（保留 line_no，移除冗余的 file 字段）
        api_endpoints = []
        for endpoint in analysis.get("api_endpoints", []):
            endpoint_copy = {k: v for k, v in endpoint.items() if k != "file"}
            api_endpoints.append(endpoint_copy)
        
        converted_analysis = {
            "file_summary": analysis.get("file_summary", ""),
            "key_functions": key_functions,
            "business_concepts": business_concepts,
            "api_endpoints": api_endpoints,
            "database_tables": []  # CodebaseIndexer 不产生这个字段
        }
        
        converted_item = {
            "file_path": result.get("file_path"),
            "file_type": result.get("file_type"),
            "analysis_time": result.get("analysis_time"),
            "analysis_result": converted_analysis,
            "status": result.get("status"),
        }
        if result.get("truncated"):
            converted_item["truncated"] = True
        if result.get("chunked"):
            converted_item["chunked"] = True
            converted_item["chunk_count"] = result.get("chunk_count", 0)
        converted_results.append(converted_item)
    
    logger.info(f"Converted {len(converted_results)} CodebaseIndexer results to CodeAnalyzer format")
    return converted_results
