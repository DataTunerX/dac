import os
import re
import json
import asyncio
import hashlib
import secrets
import importlib
import importlib.util
import logging
import datetime
import multiprocessing
import pickle
import traceback
from typing import Any, Dict, List, Optional, Tuple
from langfuse import get_client, Langfuse
from langfuse.langchain import CallbackHandler
from langchain_core.prompts.chat import (
    ChatPromptTemplate,
    HumanMessagePromptTemplate,
    SystemMessagePromptTemplate,
)
from langchain_core.messages import SystemMessage, HumanMessage
from model_sdk import ModelManager

try:
    from json_repair import repair_json as _json_repair
except Exception:
    _json_repair = None

logger = logging.getLogger(__name__)

# =============================================================================
# Sandbox primitives
# =============================================================================

# --- Safe builtins whitelist (strict mode) ----------------------------------
_SAFE_BUILTINS_NAMES: Tuple[str, ...] = (
    # pure functions / constructors
    "abs", "all", "any", "ascii", "bin", "bool", "bytearray", "bytes",
    "callable", "chr", "complex", "dict", "divmod", "enumerate", "filter",
    "float", "format", "frozenset", "getattr", "hasattr", "hash", "hex",
    "id", "int", "isinstance", "issubclass", "iter", "len", "list", "map",
    "max", "min", "next", "object", "oct", "ord", "pow", "print", "range",
    "repr", "reversed", "round", "set", "setattr", "slice", "sorted", "str",
    "sum", "tuple", "type", "vars", "zip",
    # exception classes (used for try/except in generated code)
    "Exception", "ArithmeticError", "AssertionError", "AttributeError",
    "IndexError", "KeyError", "LookupError", "NameError", "OverflowError",
    "RuntimeError", "StopIteration", "TypeError", "ValueError",
    "ZeroDivisionError",
    # sentinels
    "True", "False", "None",
)

# Explicitly blocked even if accidentally whitelisted above.
# 注意：__import__ 不在这里——我们用 _build_safe_import 给一个"白名单 import"
# 来替代原生 __import__，否则标准库内部的 lazy import（如 datetime.strptime
# 内部会 `import _strptime`）会直接挂，导致合法的 Python 代码跑不通。
_ALWAYS_DENY: Tuple[str, ...] = (
    "open", "eval", "exec", "compile",
    "input", "breakpoint", "exit", "quit", "help", "copyright", "credits",
    "license", "memoryview",
)

# 允许沙箱内 import 的模块**顶层名**白名单。
# 两类：
#   (A) stdlib 内部 lazy 引用的辅助模块——必须允许，否则 str/datetime/re 等
#       常用功能会在运行时挂；
#   (B) 我们本来就以"预加载别名"形式对 LLM 暴露的安全库——允许用户写
#       `import json` 等冗余写法，容错但无新能力。
# 任何不在此集合的 import（subprocess / socket / sys / ctypes / ...）
# 都会被 `_build_safe_import` 返回的包装器直接拒绝。
_SAFE_IMPORT_WHITELIST: frozenset = frozenset({
    # (A) stdlib 内部 lazy 依赖
    "_strptime",        # datetime.strptime / strftime
    "time",             # datetime 会 import time
    "_collections_abc",
    "_locale", "locale",
    "_bisect", "bisect",
    "_heapq", "heapq",
    "_random",
    "_string",
    "encodings", "codecs",
    "unicodedata",
    "_hashlib",         # hashlib C 实现
    "_io",              # io 模块 C 实现
    "_csv",             # csv 模块 C 加速
    "_ast",             # ast 模块 C 加速
    "_opcode",          # opcode 模块 C 加速
    "_socket",          # logging 等偶尔引用但不使用，安全占位
    "_zlib",            # zlib C 实现

    # (B) 预加载的安全库
    "math", "statistics", "datetime", "json", "re",
    "collections", "itertools", "functools",
    "numbers", "decimal", "fractions",
    "string", "textwrap",
    "copy", "typing",
    "operator",
    "random",
    "secrets",
    "numpy", "pandas",
    "array", "struct",
    "binascii", "base64",
    "zlib",
    "os",
    "cmath",
    "hashlib", "hmac",
    "enum", "dataclasses", "types",
    "pprint", "reprlib",
    "difflib",
    "html",
    "colorsys",
    "zoneinfo",
    "calendar",
    "stringprep",
    "uu", "quopri",
    "idna",
    "keyword",
    "token", "tokenize",
    "ast",
    "opcode", "dis",
    "warnings",
    "contextlib",
    "atexit",
    "logging",
    "getpass",
    "configparser",
    "csv",
    "io",
})


def _harden_sandbox_environ() -> None:
    """在**当前解释器**内禁止对进程环境做写操作。

    子进程沙箱会继承父进程完整环境（可能含 DASHCOPE_API_KEY 等）；虽然允许
    ``import os``，但标准库/第三方在 ``sys.modules`` 里**可能
    已经**加载了 ``os``。因此必须在执行用户代码前打补丁，确保：

    * ``os.environ`` 为当前快照的**只读**映射（在常见 CPython 上通过
      ``types.MappingProxyType`` 包一层，赋值 / del / clear 会失败）；
    * ``os.putenv`` / ``os.unsetenv``（如存在）恒抛出 ``OSError``，防止旁路
      修改底层 C 环境。

    仅进程内、内存侧防护；不替代系统级 cgroups/容器隔离。

    注意：在**父进程**的 ``_exec_inline`` 中调用时，**必须**用
    ``_environ_mutation_guard`` 在 ``finally`` 中恢复，否则会影响宿主进程。
    """
    import types
    try:
        import os
    except Exception:
        return

    def _deny(*_a: Any, **_k: Any) -> None:  # noqa: ANN401
        raise OSError("在沙箱中禁止通过 putenv / unsetenv 修改环境变量")

    # 1) 拦截 putenv / unsetenv（C 层也能改 env，比只封 Mapping 更稳）
    try:
        os.putenv = _deny  # type: ignore[assignment]
    except Exception:
        pass
    if hasattr(os, "unsetenv"):
        try:
            os.unsetenv = _deny  # type: ignore[assignment]
        except Exception:
            pass
    # 2) 尝试让 ``os.environ`` 本身不可变
    try:
        snap = dict(os.environ)
        ro = types.MappingProxyType(snap)
        # CPython: 可整体替换为任意 mapping-like（若失败则仅依赖上面 putenv 补丁）
        os.environ = ro  # type: ignore[assignment]
    except Exception:
        pass


class _environ_mutation_guard:
    """在 ``_exec_inline`` 的 ``exec`` 周围临时打补丁，**退出后恢复**父进程
    的 ``os`` 原状，避免一次用户代码把宿主服务的环境污染。"""
    __slots__ = ("_os", "_ok", "_environ_old", "_putenv_old", "_unsetenv_old")

    def __enter__(self) -> "_environ_mutation_guard":
        try:
            import os as _o
        except Exception:
            return self
        self._os = _o
        self._environ_old = _o.environ
        self._putenv_old = _o.putenv
        self._unsetenv_old = getattr(_o, "unsetenv", None)
        self._ok = True
        _harden_sandbox_environ()
        return self

    def __exit__(self, *exc) -> None:
        if not self._ok or self._os is None:
            return
        o = self._os
        try:
            o.environ = self._environ_old
        except Exception:
            pass
        try:
            o.putenv = self._putenv_old
        except Exception:
            pass
        if self._unsetenv_old is not None and hasattr(o, "unsetenv"):
            try:
                o.unsetenv = self._unsetenv_old
            except Exception:
                pass


def _build_safe_builtins() -> Dict[str, Any]:
    import builtins as _b
    ns: Dict[str, Any] = {
        name: getattr(_b, name)
        for name in _SAFE_BUILTINS_NAMES
        if hasattr(_b, name)
    }
    for danger in _ALWAYS_DENY:
        ns.pop(danger, None)
    # 用白名单版 __import__ 替换掉默认的 __import__。
    ns["__import__"] = _build_safe_import()
    return ns


def _build_safe_import():
    """构造一个受限的 ``__import__``：只允许白名单里的模块通过。"""
    import builtins as _b
    real_import = _b.__import__

    def _safe_import(name, globals=None, locals=None, fromlist=(), level=0):
        if level != 0:
            raise ImportError(
                f"相对导入在沙箱中被禁止 (name={name!r}, level={level})"
            )
        root = (name or "").split(".")[0]
        if root not in _SAFE_IMPORT_WHITELIST:
            raise ImportError(
                f"模块 {name!r} 不在沙箱允许导入的白名单中"
            )
        return real_import(name, globals, locals, fromlist, level)

    return _safe_import


# --- Pre-imported libraries --------------------------------------------------
# ``EAGER_LIBS`` 是极轻量的标准库，首次 import 成本可忽略，直接 eager。
# ``LAZY_LIBS`` 是体量大的第三方库（numpy / pandas），首次 import 在 macOS ARM
# 上可达 1~3s；每次 fork 子进程都扛这个开销显然不值得 —— 因此在父进程用
# ``importlib.util.find_spec`` 只做可用性探测，真正 import 延迟到 user code
# 第一次访问属性时（见 :class:`_LazyModule`）。
EAGER_LIBS: Tuple[Tuple[str, str], ...] = (
    ("math", "math"),
    ("statistics", "statistics"),
    ("datetime", "datetime"),
    ("json", "json"),
    ("re", "re"),
    ("collections", "collections"),
    ("itertools", "itertools"),
    ("functools", "functools"),
)
LAZY_LIBS: Tuple[Tuple[str, str], ...] = (
    ("np", "numpy"),
    ("pd", "pandas"),
)


class _LazyModule:
    """Tiny proxy that imports ``module_name`` on first attribute access."""

    __slots__ = ("_module_name", "_mod")

    def __init__(self, module_name: str) -> None:
        self._module_name = module_name
        self._mod: Any = None

    def _load(self) -> Any:
        if self._mod is None:
            self._mod = importlib.import_module(self._module_name)
        return self._mod

    def __getattr__(self, item: str) -> Any:
        return getattr(self._load(), item)

    def __repr__(self) -> str:  # pragma: no cover
        state = "loaded" if self._mod is not None else "lazy"
        return f"<LazyModule {self._module_name} ({state})>"


def _probe_available(module_name: str) -> bool:
    try:
        return importlib.util.find_spec(module_name) is not None
    except Exception:
        return False


def _detect_available_libs() -> Tuple[Dict[str, Any], List[str]]:
    """Return ``(alias -> module-or-lazy, human-readable names)``."""
    loaded: Dict[str, Any] = {}
    names: List[str] = []
    for alias, mod_name in EAGER_LIBS:
        try:
            loaded[alias] = importlib.import_module(mod_name)
            names.append(
                f"{mod_name} as {alias}" if alias != mod_name else mod_name
            )
        except Exception:
            continue
    for alias, mod_name in LAZY_LIBS:
        if _probe_available(mod_name):
            loaded[alias] = _LazyModule(mod_name)
            names.append(
                f"{mod_name} as {alias} (lazy)"
                if alias != mod_name
                else f"{mod_name} (lazy)"
            )
    return loaded, names


def _available_libs_names() -> List[str]:
    """Cheap probe from the parent process to build prompt hints."""
    _, names = _detect_available_libs()
    return names


def _sandbox_target(queue, code: str, data_bytes: bytes, strict: bool) -> None:
    """Worker entry invoked inside the child process.

    Must remain a *module-level* function so ``multiprocessing`` (both fork
    and spawn) can reference it by qualified name.
    """
    try:
        data = pickle.loads(data_bytes) if data_bytes else None
    except Exception:
        data = None

    try:
        # 预热 stdlib 的 lazy 依赖，避免用户代码第一次调用 strptime/strftime 时
        # 触发 `import _strptime` —— 虽然我们的 safe __import__ 允许它通过，但
        # 预热后能少一次内部 import，也对子进程 spawn 更友好。
        try:
            import _strptime  # noqa: F401  (pre-warm for datetime.strptime/strftime)
        except Exception:
            pass

        libs, _ = _detect_available_libs()
        if strict:
            globals_ns: Dict[str, Any] = {"__builtins__": _build_safe_builtins()}
        else:
            import builtins as _b
            globals_ns = {"__builtins__": _b.__dict__.copy()}
        globals_ns.update(libs)

        # datetime 模块预加载时顺带暴露常用子类作为顶层别名。
        # 动机：LLM 的"肌肉记忆"是 `from datetime import datetime, timedelta`
        # → 直接写 `datetime(...)`、`timedelta(...)`。但沙箱禁 import，导致它
        # 反复写 import 后被拦→evaluator 提示→再 import 的死循环。
        # 把这些类顶层暴露后两种直觉写法都能工作：
        #   datetime.datetime.fromisoformat(s)   # 通过模块
        #   datetime_cls.fromisoformat(s)        # 通过顶层类别名
        #   timedelta(days=30)                   # 顶层类别名
        dt_mod = globals_ns.get("datetime")
        if dt_mod is not None and hasattr(dt_mod, "datetime"):
            # 顶层别名不覆盖 "datetime" 模块名，以免破坏 datetime.date 等路径
            globals_ns.setdefault("timedelta", dt_mod.timedelta)
            globals_ns.setdefault("timezone", dt_mod.timezone)
            globals_ns.setdefault("date", dt_mod.date)
            globals_ns.setdefault("time_cls", dt_mod.time)
            globals_ns.setdefault("datetime_cls", dt_mod.datetime)

        # 关键：用**单一命名空间**执行用户代码（globals 与 locals 指向同一个 dict）。
        #
        # 原因：当 exec(code, globals, locals) 传两个不同 dict 时，推导式/生成器
        # 表达式会以"隐式函数"的形式编译，其自由变量只从 **globals** 解析——
        # 这会导致 LLM 写出的完全合法的 Python 代码挂掉，例如：
        #
        #     mu = sum(xs) / n                                   # 进 local_vars
        #     var = sum((x - mu) ** 2 for x in xs) / n           # 生成器里查 globals → NameError
        #
        # 让 globals == locals 就能让 exec 行为与"模块顶层代码"一致，推导式和生成器
        # 都能正确看到用户自己声明的名字。输入数据 `data` / 结果 `result` 同样放进
        # 这个共享命名空间。
        globals_ns["data"] = data
        globals_ns["result"] = None
        # 防止依赖库已加载 ``os`` 时，用户/库旁路改进程环境或泄露/篡改敏感变量
        _harden_sandbox_environ()
        exec(compile(code, "<sandbox>", "exec"), globals_ns)
        result = globals_ns.get("result")

        try:
            payload = pickle.dumps(result)
        except Exception:
            payload = pickle.dumps(repr(result))
        queue.put(("ok", payload, None))
    except Exception:
        queue.put(("error", None, traceback.format_exc()))


# ---------------------------------------------------------------------------
# Prompt 常量
# ---------------------------------------------------------------------------

GENERATE_CODE = """你是一位严谨的 Python 数据处理专家。你产出的代码会在一个**受限沙箱**中执行。

# 硬约束（违反任何一条都会导致执行失败）
1. 【优先用预注入名字，避免 import】下面列出的库已经以顶层名注入全局，**直接使用即可**。
   若必须 import，**仅允许**纯计算类标准库（math/statistics/datetime/json/re/collections/
   itertools/functools/decimal/fractions 等）以及图片生成常用的 zlib/struct/base64，
   以及 numpy/pandas。
   `os` 模块仅在容器内允许，用于文件读写等 I/O，但 `subprocess`、`socket`、`sys`、`ctypes` 等
   仍然会被**直接拒绝**。
2. 【白名单 builtins】禁止 `open`、`eval`、`exec`、`compile`、`input`，以及任何
   文件 / 网络 / 子进程 / 环境变量 IO。禁止用 ``os.putenv`` / ``os.unsetenv`` 或
   对 ``os.environ[...]`` 赋值来修改进程环境（沙箱内已硬拦截，代码若尝试会失败）。
3. 【输入/输出契约】输入数据在变量 `data` 中（可能为 `None`）；必须把最终结果赋给变量 `result`。
4. 【数字类型稳定】当题目要求某字段为 `int` / `float`，结果里**必须**是真正的数字类型。
   - 保留 2 位小数用 `round(x, 2)`（仍然是 float）
   - **禁止**用 `f"{{x:.2f}}"` / `str(...)` / `format(x, ...)` 等方式产出"看起来像数字的字符串"
5. 【复杂度】避免死循环；避免 O(N^2) 以上的嵌套遍历；对除零/空值/缺字段做好防御。

# 预注入的库与顶层名字（直接使用，**不要 import**）
{available_libs_hint}

# 正确用法示例
```python
# 日期时间（datetime 是模块；datetime.datetime 才是类）
cutoff = datetime.datetime.fromisoformat("2026-04-22T12:00:00") - timedelta(days=30)
for o in data:
    ts = datetime.datetime.fromisoformat(o["created_at"])
    if ts >= cutoff:
        ...

# 集合/分组
counter = collections.Counter(x["city"] for x in data)
grouped = collections.defaultdict(list)
```

# 错误用法（会被沙箱拒绝）
```python
import subprocess                              # ❌ IO 模块被白名单拒绝
import socket                                  # ❌ 同上
import sys                                     # ❌ 同上
import ctypes                                  # ❌ 同上
open("/etc/passwd")                            # ❌ 白名单 builtins 拦截
```

# 输出格式
仅输出一个 Python 代码块，形如：
```python
# your code here
result = ...
```
**不要** 输出任何自然语言说明、前言或结论。
"""

OBSERVER = """你是一位严谨的 Python 代码审查与结果评估专家。
你将收到：用户问题、已执行的 Python 代码、代码的**执行状态**（ok/error/timeout），以及结果或 traceback。
请严格区分“执行崩溃（error/timeout）”与“结果不符（ok 但语义不对）”，分别给出针对性的修复方向。
必须返回一个严格的 JSON，仅包含 `reason` 与 `conclusion` 两个字段，`conclusion` 取值为 `terminate` 或 `continue`。
"""

# Python 专属 Observer prompt — 替代原先复用 SQL 占位符的版本。
OBSERVE_PYTHON_PROMPT_ZH = """
**当前时间**
{current_time}

**已执行的 Python 代码**
```python
{code}
```

**执行状态**
{status_label}

**结果 / 错误信息**
{answer}

**核心原则（非常重要）**
当 `status == ok` 时，**默认倾向 `terminate`**。只有当你能**明确指出具体错误点**
（字段缺失、数量错、数值明显不合理、类型与题意要求不符、排序错位等）才给 `continue`。
不要基于"可能、疑似、也许、不确定"给 `continue`——那会把正确答案拖进无谓的重试循环。

**判断规则（请严格按状态区分）**
1. `ok` 且结果在**结构/字段/数量/数值范围**上都能自洽回答问题 → `conclusion=terminate`。
   - 结构正确但数值你无法核对 → 也应 `terminate`（你没有原始数据，不要凭感觉否定）。
2. `error`（含 Traceback）→ `conclusion=continue`。`reason` 必须以"执行崩溃："开头，并：
   - 指出具体异常类型（如 `KeyError`、`ZeroDivisionError`、`TypeError`、`SyntaxError`…）；
   - 指向代码的哪一行或哪一段逻辑导致；
   - 给出明确可执行的修复建议（例如"字段名应为 amount 而非 amout""对分母为 0 的情况加 if 保护"）。
3. `timeout` → `conclusion=continue`。`reason` 必须以"执行超时："开头，指出疑似死循环或高复杂度点，并建议降复杂度的改法。
4. `ok` 但结果**确凿不符**（有明确证据的：数值错 / 遗漏字段 / 维度错 / 排序错 / 类型错）→ `conclusion=continue`。
   `reason` 必须以"结果不符："开头，**具体引用**错误点（例如"gmv 应为 float 但输出是 str"），并给出修复方向。
   ⚠️ 只对"能精确指认的错误"给 continue，不要对"可能有问题"的情况给 continue。

**输出格式**
- 必须返回可被 `json.loads()` 直接解析的 JSON 字符串
- 只包含 `reason`、`conclusion` 两个字段
- 不要使用 markdown 代码块包裹

**few-shot 示例**
- ok + 正确: {{"reason": "代码正确汇总 amount 字段，结果与示例期望一致", "conclusion": "terminate"}}
- error： {{"reason": "执行崩溃：KeyError: 'amout' —— data 中正确字段名为 amount，修复：将 item['amout'] 改为 item['amount']", "conclusion": "continue"}}
- timeout： {{"reason": "执行超时：使用了双重 for 循环在 list 内两两配对，建议改为一次遍历 + 字典累加以降至 O(N)", "conclusion": "continue"}}
- ok 但不符： {{"reason": "结果不符：仅汇总了前 3 条记录，可能误用了 data[:3]，应改为遍历整个 data", "conclusion": "continue"}}
"""

OBSERVE_PROMPT_ZH = OBSERVE_PYTHON_PROMPT_ZH

# ---------------------------------------------------------------------------
# 上下文摘要：避免把整坨 context_data 塞进 prompt 造成 token 爆炸
# ---------------------------------------------------------------------------

_DEFAULT_CONTEXT_MAX_CHARS = 10000

# Initialize Langfuse client
langfuse = get_client()

langfuse_auth_check = os.getenv('LANGFUSE_AUTH_CHECK',"disable")
if langfuse_auth_check == "enable":
    # Verify connection
    if langfuse.auth_check():
        logger.info("Langfuse client is authenticated and ready!")
    else:
        logger.error("Authentication failed. Please check your credentials and host.")

# Initialize Langfuse CallbackHandler for Langchain (tracing)
langfuse_handler = CallbackHandler()

def _safe_json_dumps(obj: Any) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False, default=str)
    except Exception:
        return repr(obj)

def _infer_schema(v: Any) -> str:
    if isinstance(v, dict):
        parts = []
        for k in list(v.keys())[:8]:
            parts.append(f"{k}: {type(v[k]).__name__}")
        more = "" if len(v) <= 8 else f", ...(+{len(v) - 8} keys)"
        return "dict{" + ", ".join(parts) + more + "}"
    if isinstance(v, (list, tuple)):
        if not v:
            return f"{type(v).__name__}(empty)"
        return f"{type(v).__name__}[{type(v[0]).__name__}], len={len(v)}"
    return type(v).__name__

def summarize_context(context_data: Any, max_chars: int = _DEFAULT_CONTEXT_MAX_CHARS) -> str:
    """Produce a short, LLM-friendly description of ``context_data``.

    If the data stringifies below ``max_chars``, it is inlined verbatim.
    Otherwise we emit type + length + schema + a small head(10) preview so the
    LLM can still reason about shape without exploding the token budget.
    """
    if context_data is None:
        return "None"

    # pandas DataFrame 走专用路径
    try:
        import pandas as _pd  # type: ignore
        if isinstance(context_data, _pd.DataFrame):
            df = context_data
            dtypes = ", ".join(f"{c}: {t}" for c, t in df.dtypes.astype(str).items())
            head_str = df.head(10).to_dict(orient="records")
            return (
                f"pandas.DataFrame shape={df.shape}, columns(dtype): {{{dtypes}}}\n"
                f"head(10) = {_safe_json_dumps(head_str)}"
            )
    except Exception:
        pass

    as_str = _safe_json_dumps(context_data)
    if len(as_str) <= max_chars:
        return as_str

    lines = [f"[摘要：原始数据序列化后共 {len(as_str)} 字符，已压缩为 schema+head]"]
    if isinstance(context_data, list):
        lines.append(f"type=list, length={len(context_data)}")
        if context_data:
            lines.append(f"schema(item[0]): {_infer_schema(context_data[0])}")
            head = context_data[:10]
            lines.append(f"head(10) = {_safe_json_dumps(head)}")
    elif isinstance(context_data, dict):
        keys = list(context_data.keys())
        lines.append(f"type=dict, keys(n={len(keys)}): {keys[:20]}")
        for k in keys[:5]:
            lines.append(f"  - {k}: {_infer_schema(context_data[k])}")
    else:
        preview = str(context_data)
        lines.append(f"type={type(context_data).__name__}, repr_head: {preview[:max_chars]}")
    return "\n".join(lines)

_KNOWN_STRING_FIELDS_WITH_INNER_QUOTES = (
    "reason",
    "description",
    "thought_process",
    "rationale",
    "final_answer",
)

def _escape_known_string_field_inner_quotes(text: str) -> str:
    """对白名单字段内未转义的双引号做最佳努力的修复，便于后续 json.loads。"""
    if not text or '"' not in text:
        return text

    pattern_fields = "|".join(re.escape(f) for f in _KNOWN_STRING_FIELDS_WITH_INNER_QUOTES)
    pattern = re.compile(
        rf'("(?:{pattern_fields})"\s*:\s*")'
        r'(.*?)'
        r'((?<!\\)"[ \t]*,?[ \t]*$)',
        re.MULTILINE,
    )

    def _repl(m: "re.Match[str]") -> str:
        head, body, tail = m.group(1), m.group(2), m.group(3)
        fixed_chars: List[str] = []
        i = 0
        while i < len(body):
            ch = body[i]
            if ch == "\\" and i + 1 < len(body):
                fixed_chars.append(body[i : i + 2])
                i += 2
                continue
            if ch == '"':
                fixed_chars.append('\\"')
                i += 1
                continue
            fixed_chars.append(ch)
            i += 1
        return head + "".join(fixed_chars) + tail

    return pattern.sub(_repl, text)

def log_size_trace(stage: str, **metrics: Any) -> None:
    lines = [f"[CodeExecution][SizeTrace] {stage}"]
    for key, value in metrics.items():
        lines.append(f"  {key}={value}")
    logger.info("\n".join(lines))

class CodeExecution(object):
    """LLM-driven "generate → execute → evaluate → retry" loop for Python code.

    Sandbox / safety knobs (env overridable)
    ----------------------------------------
    * ``CODE_EXEC_STRICT_BUILTINS`` (default ``true``): 子进程使用白名单 builtins。
    * ``CODE_EXEC_ENABLE_SANDBOX`` (default ``true``): 在独立子进程中执行；
      关闭时退化到 in-process exec（仅推荐用于调试）。
    * ``CODE_EXEC_TIMEOUT_SEC`` (default ``10``): 每次执行的硬超时。
    * ``CODE_EXEC_CONTEXT_MAX_CHARS`` (default ``2000``): 注入 prompt 前
      对 ``context_data`` 做 schema/head 压缩的阈值。
    """

    def __init__(
        self,
        llm: Any | None = None,
        exec_timeout_sec: Optional[float] = None,
        enable_sandbox: Optional[bool] = None,
        strict_builtins: Optional[bool] = None,
        context_max_chars: Optional[int] = None,
        max_retries: int = 5,
        no_progress_abort: Optional[bool] = None,
        stagnation_llm_judge: Optional[bool] = None,
    ):
        self.llm = llm

        # 沙箱与重试配置（支持构造参数 / 环境变量 / 默认值三级回退）
        self.exec_timeout_sec: float = (
            float(exec_timeout_sec)
            if exec_timeout_sec is not None
            else float(os.getenv("CODE_EXEC_TIMEOUT_SEC", "10"))
        )
        self.enable_sandbox: bool = (
            bool(enable_sandbox)
            if enable_sandbox is not None
            else os.getenv("CODE_EXEC_ENABLE_SANDBOX", "true").strip().lower() not in ("false", "0", "no")
        )
        self.strict_builtins: bool = (
            bool(strict_builtins)
            if strict_builtins is not None
            else os.getenv("CODE_EXEC_STRICT_BUILTINS", "true").strip().lower() not in ("false", "0", "no")
        )
        self.context_max_chars: int = (
            int(context_max_chars)
            if context_max_chars is not None
            else int(os.getenv("CODE_EXEC_CONTEXT_MAX_CHARS", str(_DEFAULT_CONTEXT_MAX_CHARS)))
        )
        self.max_retries: int = max(0, int(max_retries))
        # 防"原地踏步"：连续两次失败签名或生成代码完全一致 → 提前退出重试。
        # 默认关闭——让 LLM 自主决策是否继续重试；可通过 CODE_EXEC_NO_PROGRESS_ABORT=true 开启。
        self.no_progress_abort: bool = (
            bool(no_progress_abort)
            if no_progress_abort is not None
            else os.getenv("CODE_EXEC_NO_PROGRESS_ABORT", "false").strip().lower()
            not in ("false", "0", "no")
        )
        # 辅助判官：在**指纹不同但疑似相似**时再让 LLM 裁决一次"根因是否一致"。
        # 默认开启（token 成本由使用方承担）；关闭路径通过环境变量
        # ``CODE_EXEC_STAGNATION_LLM_JUDGE=false``。
        self.stagnation_llm_judge: bool = (
            bool(stagnation_llm_judge)
            if stagnation_llm_judge is not None
            else os.getenv("CODE_EXEC_STAGNATION_LLM_JUDGE", "true").strip().lower()
            not in ("false", "0", "no")
        )

        # 提前在父进程探测可用库，拼成 prompt 提示；子进程会再各自 import。
        self._available_libs: List[str] = _available_libs_names()

    # ------------------------------------------------------------------
    # Prompt helpers
    # ------------------------------------------------------------------
    def _available_libs_hint(self) -> str:
        if not self._available_libs:
            return "  （当前环境未预加载任何第三方库，请仅使用 Python 内建类型与运算。）"
        lines = [f"  - {name}" for name in self._available_libs]
        # datetime 是高频"反直觉"陷阱：预加载的是**模块** datetime，不是类。
        # 显式告知 LLM 两种可用写法，避免它写 `from datetime import datetime` 被拦。
        if "datetime" in self._available_libs:
            lines.append(
                "    · 注意：`datetime` 是**模块**。若需 datetime 类请用 "
                "`datetime.datetime(...)` 或 `datetime.datetime.fromisoformat(s)`。"
            )
            lines.append(
                "    · 另外，`timedelta`、`timezone`、`date` 已作为**顶层名**注入，"
                "可直接写 `timedelta(days=30)`、`date(2026,1,1)`，**无需 import**。"
            )
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 1) 代码生成
    # ------------------------------------------------------------------
    async def generate_code_logic(
        self,
        query: str,
        context_data: Any,
        last_error: str = "",
        user_id: str = "",
        run_id: str = "",
        trace_id: str = "",
    ) -> Optional[str]:
        """Generate Python code via LLM with Langfuse tracing."""
        system_template = GENERATE_CODE
        human_template = (
            "问题: {query}\n"
            "数据上下文（已按需压缩）:\n{context_summary}\n"
            "{retry_info}"
        )

        retry_info = (
            f"\n[上一次执行的失败反馈，请据此修正代码]\n{last_error}" if last_error else ""
        )

        # 对 context_data 做摘要以避免 token 爆炸
        context_summary = summarize_context(context_data, max_chars=self.context_max_chars)

        system_prompt = SystemMessagePromptTemplate.from_template(template=system_template)
        human_prompt = HumanMessagePromptTemplate.from_template(human_template)
        chat_prompt = ChatPromptTemplate.from_messages([system_prompt, human_prompt])

        chain = chat_prompt | self.llm

        answer = None
        with langfuse.start_as_current_span(
            name="code_execution-generate_code",
            trace_context={"trace_id": trace_id},
        ) as span:
            span.update_trace(
                user_id=user_id,
                session_id=run_id,
                input={
                    "query": query,
                    "context_summary": context_summary,
                    "last_error": last_error,
                },
            )

            log_size_trace(
                "code_gen-input",
                query_chars=len(str(query or "")),
                context_raw_chars=len(str(context_data or "")),
                context_summary_chars=len(context_summary),
                last_error_chars=len(last_error or ""),
            )

            answer = await chain.ainvoke(
                {
                    "query": query,
                    "available_libs_hint": self._available_libs_hint(),
                    "context_summary": context_summary,
                    "retry_info": retry_info,
                },
                config={"callbacks": [langfuse_handler]},
            )

            span.update_trace(output={"answer": answer.content})

        langfuse.flush()

        log_size_trace(
            "code_gen-output",
            llm_output_chars=len(str(getattr(answer, "content", "") or "")),
        )

        raw_out = str(getattr(answer, "content", "") or "")
        logger.info(" === CodeExecution.generate_code_logic, llm result = %s", raw_out)

        clean = self._extract_clean_code(raw_out)
        if clean and clean.strip():
            logger.info(
                "[CodeExecution] generated code after fence strip (%d chars):\n%s",
                len(clean),
                clean,
            )
        else:
            logger.info(
                "[CodeExecution] no non-empty code after fence strip (raw len=%d)",
                len(raw_out),
            )

        return clean

    def _extract_clean_code(self, content: str) -> str:
        raw = (content or "").strip()
        if "```python" in raw:
            raw = raw.split("```python", 1)[1].split("```", 1)[0].strip()
        elif "```" in raw:
            raw = raw.split("```", 1)[1].split("```", 1)[0].strip()
        return raw

    # ------------------------------------------------------------------
    # 2) 代码执行（沙箱 + 超时 + 状态化返回）
    # ------------------------------------------------------------------
    async def execute_code(self, code: str, context_data: Any) -> Dict[str, Any]:
        """Execute ``code`` in a sandbox subprocess with timeout.

        Returns a dict with ``status`` in ``{"ok", "error", "timeout"}``,
        plus ``result`` and ``error`` (traceback text) fields.
        """
        return await asyncio.to_thread(self._execute_code_sync, code, context_data)

    def _execute_code_sync(self, code: str, context_data: Any) -> Dict[str, Any]:
        if not self.enable_sandbox:
            return self._exec_inline(code, context_data)

        try:
            data_bytes = pickle.dumps(context_data)
        except Exception as e:
            logger.warning(
                "context_data 不可 pickle (%s)，退化到 in-process 执行。", e
            )
            return self._exec_inline(code, context_data)

        requested_ctx = os.getenv("CODE_EXEC_MP_CONTEXT", "fork").strip().lower()
        try:
            ctx = multiprocessing.get_context(requested_ctx)
        except Exception:
            try:
                ctx = multiprocessing.get_context("fork")
            except Exception:
                ctx = multiprocessing.get_context()
        queue = ctx.Queue(maxsize=1)
        proc = ctx.Process(
            target=_sandbox_target,
            args=(queue, code, data_bytes, self.strict_builtins),
            daemon=True,
        )

        try:
            proc.start()
            proc.join(self.exec_timeout_sec)

            if proc.is_alive():
                proc.terminate()
                proc.join(2)
                if proc.is_alive():
                    try:
                        proc.kill()
                    except Exception:
                        pass
                    proc.join(1)
                return {
                    "status": "timeout",
                    "result": None,
                    "error": f"Execution exceeded {self.exec_timeout_sec}s (hard killed)",
                    "code": code,
                }
            try:
                status, payload, err = queue.get(timeout=1.0)
            except Exception:
                return {
                    "status": "error",
                    "result": None,
                    "error": "sandbox 未返回任何结果（子进程异常退出）",
                    "code": code,
                }

            if status == "ok":
                try:
                    result_value = pickle.loads(payload) if payload is not None else None
                except Exception:
                    result_value = None
                return {"status": "ok", "result": result_value, "error": None, "code": code}
            return {"status": "error", "result": None, "error": err, "code": code}
        finally:
            try:
                queue.close()
                queue.join_thread()
            except Exception:
                pass
            try:
                if proc.is_alive():
                    try:
                        proc.kill()
                    except Exception:
                        pass
                    proc.join(1)
                try:
                    proc.close()
                except ValueError:
                    # 已 close 或进程仍存活；后者极端情况下留给 GC 回收
                    pass
            except Exception:
                pass

    def _exec_inline(self, code: str, context_data: Any) -> Dict[str, Any]:
        """Fallback path: run in-process with whitelisted builtins (best-effort)."""
        libs, _ = _detect_available_libs()
        globals_ns: Dict[str, Any] = {
            "__builtins__": _build_safe_builtins() if self.strict_builtins else __builtins__
        }
        globals_ns.update(libs)
        globals_ns["data"] = context_data
        globals_ns["result"] = None
        try:
            with _environ_mutation_guard():
                exec(compile(code, "<inline>", "exec"), globals_ns)
            return {
                "status": "ok",
                "result": globals_ns.get("result"),
                "error": None,
                "code": code,
            }
        except Exception:
            return {
                "status": "error",
                "result": None,
                "error": traceback.format_exc(),
                "code": code,
            }
        finally:
            globals_ns.clear()

    # ------------------------------------------------------------------
    # 3) 结果评估
    # ------------------------------------------------------------------
    async def evaluate_result(
        self,
        query: str,
        code: str,
        exec_result: Dict[str, Any],
        user_id: str,
        run_id: str,
        trace_id: str,
    ) -> Dict[str, Any]:
        """Evaluate execution outcome with a Python-aware observer prompt."""
        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        status = (exec_result or {}).get("status", "ok")
        if status == "error":
            status_label = "error（代码执行崩溃，以下为 Python traceback 原文）"
            answer_text = (exec_result or {}).get("error") or "(empty traceback)"
        elif status == "timeout":
            status_label = "timeout（代码执行超时，已被强制终止）"
            answer_text = (exec_result or {}).get("error") or f"exceeded {self.exec_timeout_sec}s"
        else:
            status_label = "ok（代码正常执行完成，以下为 result 变量的值）"
            answer_text = _safe_json_dumps((exec_result or {}).get("result"))

        # 避免过长 traceback / result 吞掉整个 context
        if len(answer_text) > 4000:
            answer_text = answer_text[:4000] + "\n...[truncated]"

        prompt_text = OBSERVE_PYTHON_PROMPT_ZH.format(
            current_time=current_time,
            code=code,
            status_label=status_label,
            answer=answer_text,
        )

        system_msg = SystemMessage(content=OBSERVER)
        human_msg = HumanMessage(content=f"用户问题: {query}\n{prompt_text}")

        response = await self.llm.ainvoke([system_msg, human_msg])
        return self.format_llm_ouput(response)

    # ------------------------------------------------------------------
    # 4) 主循环
    # ------------------------------------------------------------------
    async def run(
        self, query: str,
        context_data: Any = None,
        user_id: str = None,
        run_id: str = None,
        trace_id: str = None,
    ) -> Dict[str, Any]:
        """Main entry: generate → execute → evaluate → retry.

        停滞保护（"先升级后放弃"）：
          * 若本次与**上一次**的失败签名或生成代码完全一致（``streak=1``），
            并不放弃——在下一次 prompt 里注入 **[停滞告警]** 明确告诉 LLM
            "沿用同一思路已失败，必须换招"，并给出具体换招方向。
          * 若注入告警后的下一次（``streak>=2``，即连续第 3 次都相同）仍完全一致，
            说明模型确实无法跳出循环，此时才提前中止以免无效消耗 token。
          * 任何一次签名变化都会把 streak 重置为 0，回到正常重试节奏。
        """
        last_error = ""
        prev_err_sig: Optional[str] = None
        prev_code_sig: Optional[str] = None
        prev_digest: Optional[Dict[str, Any]] = None
        prev_code: Optional[str] = None
        stagnation_streak = 0  # 连续"与上一次根因相同"的次数
        last_stagnation_source: str = ""  # "fingerprint" / "judge:<reason>"

        for attempt in range(self.max_retries + 1):
            logger.info("--- Attempt %d ---", attempt + 1)
            code: Optional[str] = None
            exec_result: Optional[Dict[str, Any]] = None
            evaluation: Optional[Dict[str, Any]] = None
            # 提前声明给外层 used-for-next-round 的变量
            curr_digest: Optional[Dict[str, Any]] = None
            curr_code: Optional[str] = None
            try:
                code = await self.generate_code_logic(query, context_data, last_error, user_id=user_id, run_id=run_id, trace_id=trace_id)
                if not code:
                    return {"conclusion": "continue", "reason": "无法生成有效的 Python 代码"}

                exec_result = await self.execute_code(code, context_data)
                evaluation = await self.evaluate_result(query, code, exec_result, user_id=user_id, run_id=run_id, trace_id=trace_id)

                if evaluation and evaluation.get("conclusion") == "terminate":
                    return {
                        "conclusion": "terminate",
                        "code": code,
                        "status": exec_result.get("status"),
                        "result": exec_result.get("result"),
                        "reason": evaluation.get("reason", ""),
                    }

                # —— 停滞检测 —— 先算本次指纹与摘要
                err_sig = self._error_signature(exec_result)
                code_sig = self._code_signature(code)
                curr_digest = self._exec_digest(exec_result)
                curr_code = code

                # 主门：指纹完全相同（traceback 最后一行一样 / 代码字节一样 /
                # 或 ok 结果 JSON hash 一样）→ 0 成本判定为停滞
                err_same = prev_err_sig is not None and err_sig == prev_err_sig
                code_same = prev_code_sig is not None and code_sig == prev_code_sig
                fingerprint_match = err_same or code_same
                judge_match = False
                judge_reason = ""

                # 副门：指纹不同 + 候选筛选命中 → 调 LLM 判官
                if (
                    attempt > 0
                    and self.no_progress_abort
                    and self.stagnation_llm_judge
                    and not fingerprint_match
                    and self._digests_worth_judging(prev_digest, curr_digest)
                    and prev_code is not None
                ):
                    logger.info(
                        "[CodeExecution] fingerprints differ but digests look similar — consulting LLM judge"
                    )
                    try:
                        judge_match, judge_reason = await self._judge_same_root_cause_via_llm(
                            query, prev_code, prev_digest or {}, curr_code, curr_digest,
                        )
                    except Exception as e:  # judge 不应影响主流程
                        logger.warning("[CodeExecution] judge raised: %s", e)
                        judge_match, judge_reason = False, f"judge error: {e}"
                    logger.info(
                        "[CodeExecution] judge verdict: same=%s reason=%s",
                        judge_match, (judge_reason or "")[:120],
                    )

                if attempt > 0 and (fingerprint_match or judge_match):
                    stagnation_streak += 1
                    last_stagnation_source = (
                        "fingerprint" if fingerprint_match else f"judge: {judge_reason}"
                    )
                else:
                    stagnation_streak = 0
                    last_stagnation_source = ""

                prev_err_sig = err_sig
                prev_code_sig = code_sig
                prev_digest = curr_digest
                prev_code = curr_code

                # streak >= 2 即"已给过升级提示仍没换招"：此时才真正放弃
                if self.no_progress_abort and stagnation_streak >= 2:
                    reason_text = (
                        f"no-progress abort：已连续 {stagnation_streak + 1} 次"
                        f"被判定为同一根因（source={last_stagnation_source[:140]}）。"
                        "升级提示后仍未换思路，提前终止以避免无效消耗。"
                    )
                    logger.warning("[CodeExecution] %s", reason_text)
                    return {
                        "conclusion": "continue",
                        "code": code,
                        "status": (exec_result or {}).get("status"),
                        "result": (exec_result or {}).get("result"),
                        "reason": reason_text,
                        "aborted": "no_progress",
                        "stagnation_source": last_stagnation_source,
                    }

                base_last_error = self._build_retry_error(exec_result, evaluation)
                if stagnation_streak >= 1:
                    # streak == 1：首次判定为停滞（指纹相同或判官认为相同），
                    # **不放弃**，给 LLM 一次换招的强提示
                    nudge = self._stagnation_nudge(
                        stagnation_streak, err_sig, exec_result,
                        source=last_stagnation_source,
                    )
                    logger.info(
                        "[CodeExecution] stagnation detected (streak=%d, source=%s) — injecting escalation nudge",
                        stagnation_streak, last_stagnation_source[:80],
                    )
                    last_error = base_last_error + "\n\n" + nudge
                else:
                    last_error = base_last_error
            finally:
                # 主动清理，避免大 dict / DataFrame 在重试循环里堆积。
                # 注意：prev_digest / prev_code 已在上面保留的是**轻量摘要 + 已截断的代码字符串**，
                # 不会持有 exec_result 本体或 context_data 大对象。
                code = None
                exec_result = None
                evaluation = None

        return {
            "conclusion": "continue",
            "reason": f"Retry limit reached. Last error: {last_error}",
        }

    @staticmethod
    def _stagnation_nudge(
        streak: int,
        err_sig: str,
        exec_result: Optional[Dict[str, Any]],
        source: str = "",
    ) -> str:
        """Build the escalation message fed to the *next* code-gen call.

        核心意图：明确告诉 LLM "沿用同一思路已经连续失败，必须做出**可见的**
        实现差异"，并给出具体换招方向。这段文本会拼到 ``last_error`` 末尾、
        通过 ``retry_info`` 插槽进入下一次 prompt。

        ``source`` 说明这次停滞是被**指纹主门**抓到的（字节级完全相同），
        还是被 **LLM 判官**判定为根因相同（判官会附一句 reason）。
        """
        status = (exec_result or {}).get("status", "ok")
        status_hint = {
            "error": "上一次是**执行崩溃**——说明代码路径上某一步就过不去；",
            "timeout": "上一次是**执行超时**——通常是死循环或复杂度爆炸；",
            "ok": "上一次代码能跑完但结果仍被判定不对——说明逻辑本身偏了；",
        }.get(status, "")
        src_hint = f"（判定来源：{source[:160]}）" if source else ""
        return (
            f"[停滞告警] 这是连续第 {streak + 1} 次被判定为与上一次**同一根因**"
            f"{src_hint}。signature={err_sig[:80]}。{status_hint}"
            "继续沿用同一思路一定会再次失败，本次重写**必须**做出以下至少一项**可见的**调整："
            "\n  1. 换一种实现路径（如 collections.Counter / itertools / dict 累加，替换当前写法）；"
            "\n  2. 换一种数据访问方式（用 d.get(k, default) 替代 d[k]；用 enumerate 替代 data.index(x)）；"
            "\n  3. 把可疑表达式拆多行，并在关键变量上加 `print(...)` 以便诊断；"
            "\n  4. 如果上次 import 了被拒模块，请改用提示里列出的**预注入顶层名**（无需 import）；"
            "\n  5. 如果上次用了 f-string/字符串拼装导致类型不符，请改用 round/int/float 保持数值类型。"
            "\n请确保本次代码在关键步骤上与上次**肉眼可辨**的不同——否则将再次触发相同错误而被判定停滞。"
        )

    # ------------------------------------------------------------------
    # 防"原地踏步"：签名辅助
    # ------------------------------------------------------------------
    # 关键点：把 traceback 归一化 —— 不同次运行里 File "..."/line 号会变，
    # 但异常类型+异常信息通常是稳定的。以"最后一行非空 + 去路径/去行号"作为
    # 失败指纹；超时归一为 "timeout"；ok 则用结果 JSON 的 sha1，这样
    # "连续两次返回完全相同的错结果" 也能识别。
    _TB_PATH_RE = re.compile(r'File "[^"]+", line \d+(?:, in [^\n]+)?')

    @staticmethod
    def _error_signature(exec_result: Optional[Dict[str, Any]]) -> str:
        ex = exec_result or {}
        status = ex.get("status", "ok")
        if status == "timeout":
            return "timeout"
        if status == "error":
            err = (ex.get("error") or "").strip()
            lines = [ln for ln in err.splitlines() if ln.strip()]
            last = lines[-1] if lines else err
            last = CodeExecution._TB_PATH_RE.sub("", last).strip()
            return "error::" + last[:240]
        try:
            payload = json.dumps(
                ex.get("result"), ensure_ascii=False, sort_keys=True, default=str
            )
        except Exception:
            payload = repr(ex.get("result"))
        return "ok::" + hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _code_signature(code: Optional[str]) -> str:
        return hashlib.sha1((code or "").encode("utf-8")).hexdigest()[:16]

    # --- 供判官使用的"执行摘要"——轻量、可 JSON 化、不持有原始大对象 -------
    _EXC_LINE_RE = re.compile(
        r"^([A-Za-z_][A-Za-z0-9_]*(?:Error|Exception|Warning))\s*:\s*(.*)$"
    )

    @staticmethod
    def _exec_digest(exec_result: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Produce a small, JSON-safe summary of one attempt's execution.

        用于**下一轮**的判官输入，因此不保留 ``code`` / ``result`` 本体，
        只保留可用于根因比对的结构化特征（异常类型 + 消息 / 结果 type + 键
        摘要）。这样即使用户传入的是上万行 DataFrame，也不会在 retry 循环里
        长期驻留。
        """
        ex = exec_result or {}
        status = ex.get("status", "ok")
        d: Dict[str, Any] = {"status": status}
        if status == "timeout":
            d["error"] = (ex.get("error") or "")[:240]
            return d
        if status == "error":
            err = (ex.get("error") or "").strip()
            lines = [ln for ln in err.splitlines() if ln.strip()]
            last = lines[-1] if lines else err
            m = CodeExecution._EXC_LINE_RE.match(last)
            if m:
                d["exception_type"] = m.group(1)
                d["exception_msg"] = m.group(2)[:400]
            else:
                d["exception_type"] = "Unknown"
                d["exception_msg"] = last[:400]
            # 也带一点 traceback 底部上下文（最多 3 行），帮判官看位置
            d["tb_tail"] = "\n".join(lines[-4:])[:600]
            return d
        # status == ok
        res = ex.get("result")
        d["result_type"] = type(res).__name__
        try:
            if isinstance(res, (list, tuple, set)):
                d["result_len"] = len(res)
                if res:
                    first = next(iter(res))
                    d["result_item_type"] = type(first).__name__
                    if isinstance(first, dict):
                        d["result_item_keys"] = list(first.keys())[:16]
            elif isinstance(res, dict):
                d["result_keys"] = list(res.keys())[:16]
        except Exception:
            pass
        try:
            d["result_preview"] = json.dumps(
                res, ensure_ascii=False, default=str
            )[:600]
        except Exception:
            d["result_preview"] = repr(res)[:600]
        return d

    @staticmethod
    def _digests_worth_judging(
        prev: Optional[Dict[str, Any]],
        curr: Optional[Dict[str, Any]],
    ) -> bool:
        """Cheap filter：仅在"疑似相似"时才值得烧一次 LLM 判官。

        规则：
        * 状态必须一致（error-vs-ok 不送判官——两次状态不同说明代码路径已变）；
        * 两次都 error → 异常类型必须相同（``KeyError`` vs ``KeyError`` 才问）；
        * 两次都 ok   → 顶层结果类型必须相同（``list`` vs ``list``）。
        其余一概放行（不视作停滞）。
        """
        if not prev or not curr:
            return False
        ps, cs = prev.get("status"), curr.get("status")
        if ps != cs:
            return False
        if ps == "timeout":
            return True
        if ps == "error":
            return (
                prev.get("exception_type") == curr.get("exception_type")
                and prev.get("exception_type") not in (None, "Unknown")
            )
        if ps == "ok":
            return prev.get("result_type") == curr.get("result_type")
        return False

    async def _judge_same_root_cause_via_llm(
        self,
        query: str,
        prev_code: str,
        prev_digest: Dict[str, Any],
        curr_code: str,
        curr_digest: Dict[str, Any],
    ) -> Tuple[bool, str]:
        """Ask the planner LLM whether two failed attempts share the same root cause.

        **保守策略**：判官失败 / 非法 JSON / 超时 / 抛异常都返回 ``(False, ...)``，
        让主流程回落到"视为不同、继续重试"；只有判官明确给出 ``same=true`` 才
        触发停滞升级。这样 LLM 判官永远只会**增加 abort 灵敏度**，不会把能救
        的 retry 误杀。
        """
        judge_system = (
            "你是一位严谨的 Python 代码与错误审查专家。用户会给你同一个任务的"
            "两次失败尝试（上一次 / 这一次），包含它们各自的代码和执行摘要。"
            "请判断它们的**根因是否相同**（即：本次是否只是在沿用上次同样的错误路径，"
            "并没有做出有实质变化的换招）。\n"
            "判定口径：\n"
            "  1) error + 相同异常类型，且消息本质一样（例：两次都是 KeyError 且字段名都拼错）→ same=true；\n"
            "  2) ok 但结果都偏离同一处逻辑（如都漏算同一维度、都把 float 写成 str）→ same=true；\n"
            "  3) 代码实现路径只换了变量名/注释/空格/空行 → same=true；\n"
            "  4) 明显换了算法、换了数据结构、换了字段名或修复了上次的异常 → same=false；\n"
            "  5) 不确定/证据不足 → **保守回 same=false**，避免误终止重试。\n"
            "**严格**只返回 JSON：{\"same_root_cause\": true|false, \"reason\": \"一句话\"}，"
            "不要 markdown 代码块、不要任何其它文本。"
        )
        prev_code_trim = (prev_code or "")[:1500]
        curr_code_trim = (curr_code or "")[:1500]
        human = (
            f"任务: {query}\n\n"
            f"【上一次】\nstatus={prev_digest.get('status')}\n"
            f"digest={json.dumps(prev_digest, ensure_ascii=False, default=str)[:1200]}\n"
            f"code (截断 1500 字):\n```python\n{prev_code_trim}\n```\n\n"
            f"【这一次】\nstatus={curr_digest.get('status')}\n"
            f"digest={json.dumps(curr_digest, ensure_ascii=False, default=str)[:1200]}\n"
            f"code (截断 1500 字):\n```python\n{curr_code_trim}\n```"
        )
        try:
            resp = await asyncio.wait_for(
                self.llm.ainvoke([SystemMessage(content=judge_system), HumanMessage(content=human)]),
                timeout=max(4.0, min(20.0, self.exec_timeout_sec * 1.5)),
            )
        except Exception as e:
            logger.warning("[CodeExecution] stagnation judge call failed: %s", e)
            return False, f"judge transport error: {e}"

        parsed = self.format_llm_ouput(resp) if resp is not None else None
        if not isinstance(parsed, dict):
            logger.warning(
                "[CodeExecution] stagnation judge returned non-JSON: %r",
                getattr(resp, "content", "")[:200],
            )
            return False, "judge non-json"
        same = bool(parsed.get("same_root_cause"))
        reason = str(parsed.get("reason") or "")[:300]
        return same, reason

    @staticmethod
    def _build_retry_error(
        exec_result: Optional[Dict[str, Any]],
        evaluation: Optional[Dict[str, Any]],
    ) -> str:
        status = (exec_result or {}).get("status", "ok")
        err = (exec_result or {}).get("error")
        result = (exec_result or {}).get("result")
        eval_reason = (evaluation or {}).get("reason", "") or ""

        if status == "error":
            head = f"[执行崩溃] {err}"
        elif status == "timeout":
            head = f"[执行超时] {err}"
        else:
            head = f"[结果不符] result={result!r}"
        return f"{head}\n[评估反馈] {eval_reason}"

    def format_llm_ouput(self, answer) -> dict:
        """Parse the planner LLM output into a dict with heavy tolerance.

        See ``orchestrator_agent_semantic_group.PlannerAgent.format_llm_ouput``
        for the detailed recovery strategy — this implementation mirrors it.
        """
        raw = getattr(answer, "content", "") or ""

        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass

        cleaned_content = raw.strip()
        if cleaned_content.startswith('```json'):
            cleaned_content = cleaned_content[7:]
        elif cleaned_content.startswith('```'):
            cleaned_content = cleaned_content[3:]
        if cleaned_content.endswith('```'):
            cleaned_content = cleaned_content[:-3]
        cleaned_content = cleaned_content.strip()

        try:
            return json.loads(cleaned_content)
        except json.JSONDecodeError as e2:
            logger.error(f" === format_llm_ouput, Parsing failed after cleanup.: {e2}")

        escaped_content = _escape_known_string_field_inner_quotes(cleaned_content)
        if escaped_content != cleaned_content:
            try:
                parsed = json.loads(escaped_content)
                logger.info(" === format_llm_ouput, recovered via inner-quote field escaping")
                return parsed
            except json.JSONDecodeError as e_esc:
                logger.warning(f" === format_llm_ouput, field-escape pre-pass still invalid: {e_esc}")

        if _json_repair is not None:
            try:
                repaired = _json_repair(escaped_content, return_objects=True)
                if isinstance(repaired, dict):
                    logger.info(" === format_llm_ouput, recovered via json_repair")
                    return repaired
                if isinstance(repaired, str):
                    parsed = json.loads(repaired)
                    if isinstance(parsed, dict):
                        logger.info(" === format_llm_ouput, recovered via json_repair (string)")
                        return parsed
            except Exception as e_rep:
                logger.error(f" === format_llm_ouput, json_repair failed: {e_rep}")
        else:
            logger.warning(
                " === format_llm_ouput, json_repair not installed; "
                "add 'json-repair' to dependencies to improve LLM JSON tolerance"
            )

        try:
            import ast
            parsed = ast.literal_eval(cleaned_content)
            if isinstance(parsed, dict):
                return parsed
        except (ValueError, SyntaxError) as e3:
            logger.error(f" === format_llm_ouput, ast parsing fail: {e3}")
        except Exception as e5:
            logger.error(f" === format_llm_output, exception occurred during parsing: {e5}, using default value")

        try:
            parsed = json.loads(cleaned_content.replace("'", '"'))
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError as e4:
            logger.error(f" === format_llm_output, secondary parsing failed: {e4}, using default value")

        return None
