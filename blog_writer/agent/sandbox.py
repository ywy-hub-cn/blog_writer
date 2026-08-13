"""进程级 Python 沙箱公共策略（防御纵深，非绝对安全边界）。

用于 PureCodeExecutor 与 ToolRegistry.run_python，避免策略漂移。
不可信租户代码仍应依赖 OS/容器隔离。
"""
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# 禁止导入的顶层模块
BLOCKED_IMPORTS: Set[str] = {
    "subprocess",
    "socket",
    "ctypes",
    "multiprocessing",
    "shutil",
    "importlib",
    "pickle",
    "pathlib",
    "pty",
    "fcntl",
    "signal",
    "http",
    "urllib",
    "requests",
    "ftplib",
    "smtplib",
    "telnetlib",
    "os",
    "sys",
    "builtins",
    "code",
    "codeop",
    "webbrowser",
    "resource",
    "gc",
    "inspect",
    "types",
}

# 环境变量敏感关键字（过滤模式）
_SENSITIVE_ENV_MARKERS = (
    "KEY",
    "SECRET",
    "TOKEN",
    "PASSWORD",
    "CREDENTIAL",
    "ACCESS",
)

# 允许透传的环境变量白名单（再叠加调用方 env）
_ENV_ALLOWLIST = {
    "PATH",
    "PATHEXT",
    "SYSTEMROOT",
    "SYSTEMDRIVE",
    "WINDIR",
    "TEMP",
    "TMP",
    "TMPDIR",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "PYTHONIOENCODING",
    "PYTHONUTF8",
    "HOME",
    "USERPROFILE",
    "USERNAME",
    "USER",
    "COMSPEC",
    "NUMBER_OF_PROCESSORS",
}

MAX_CAPTURE_CHARS = 200_000


class SandboxPolicyError(ValueError):
    """静态策略校验失败。"""


def validate_python_source(source: str, *, filename: str = "<sandbox>") -> None:
    """AST 静态检查：拦截 dunder 属性逃逸与阻断导入。"""
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as e:
        raise SandboxPolicyError(f"syntax error: {e}") from e

    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            if isinstance(node.attr, str) and (
                node.attr.startswith("__") and node.attr.endswith("__")
            ):
                raise SandboxPolicyError(
                    f"dunder attribute access denied: {node.attr}"
                )
        if isinstance(node, ast.Name):
            if node.id.startswith("__") and node.id.endswith("__") and node.id not in (
                "__name__",
            ):
                # 允许极少见场景；默认拒绝常见逃逸入口
                if node.id in ("__builtins__", "__import__", "__loader__", "__spec__"):
                    raise SandboxPolicyError(f"dunder name denied: {node.id}")
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names: List[str] = []
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            else:
                if node.module:
                    names = [node.module.split(".")[0]]
            for root in names:
                if root in BLOCKED_IMPORTS:
                    raise SandboxPolicyError(f"import of {root!r} is not allowed")


def build_child_env(
    instance_dir: Path,
    extra: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    """构建子进程环境：白名单 + 过滤敏感键 + INSTANCE_DIR。"""
    env: Dict[str, str] = {}
    for key, value in os.environ.items():
        upper = key.upper()
        if any(m in upper for m in _SENSITIVE_ENV_MARKERS):
            continue
        if key in _ENV_ALLOWLIST or upper in _ENV_ALLOWLIST:
            env[key] = value
    # PATH 对启动解释器很重要
    if "PATH" in os.environ:
        env["PATH"] = os.environ["PATH"]
    env["INSTANCE_DIR"] = str(Path(instance_dir).resolve())
    env["PYTHONIOENCODING"] = "utf-8"
    if extra:
        for k, v in extra.items():
            if v is None:
                continue
            env[str(k)] = str(v)
    return env


def _blocked_repr() -> str:
    return repr(sorted(BLOCKED_IMPORTS))


def build_inline_wrapper(*, read_stdin: bool = True) -> str:
    """生成 -c 包装脚本：安全 builtins + open 限制在 INSTANCE_DIR。"""
    blocked = _blocked_repr()
    src = read_stdin
    return f"""
import json, sys, os
instance_dir = os.path.realpath(os.environ.get('INSTANCE_DIR', ''))
_BLOCKED = set({blocked})
def _safe_import(name, globals=None, locals=None, fromlist=(), level=0):
    root = name.split('.')[0]
    if root in _BLOCKED:
        raise ImportError('Import of %r is not allowed in sandbox' % (name,))
    return __import__(name, globals, locals, fromlist, level)
_real_open = open
def _safe_open(file, mode='r', *args, **kwargs):
    path = os.path.realpath(str(file))
    if instance_dir and not (path == instance_dir or path.startswith(instance_dir + os.sep)):
        raise PermissionError('open outside instance_dir denied: %s' % (file,))
    return _real_open(file, mode, *args, **kwargs)
_SAFE_BUILTINS = {{
    'abs': abs, 'all': all, 'any': any, 'bool': bool, 'dict': dict,
    'enumerate': enumerate, 'float': float, 'format': format, 'int': int,
    'isinstance': isinstance, 'len': len, 'list': list, 'max': max, 'min': min,
    'print': print, 'range': range, 'repr': repr, 'reversed': reversed,
    'round': round, 'set': set, 'sorted': sorted, 'str': str, 'sum': sum,
    'tuple': tuple, 'zip': zip, 'Exception': Exception, 'ValueError': ValueError,
    'TypeError': TypeError, 'KeyError': KeyError, 'True': True, 'False': False,
    'None': None, '__import__': _safe_import, 'open': _safe_open,
}}
ns = {{'__builtins__': _SAFE_BUILTINS}}
{"code = sys.stdin.read()" if src else "code = open(os.environ['SCRIPT_PATH'], 'r', encoding='utf-8').read()"}
exec(compile(code, '<sandbox>', 'exec'), ns, ns)
"""


def build_pure_code_wrapper() -> str:
    """PureCodeExecutor 包装：执行 SCRIPT_PATH 并将 outputs 写入 OUTPUT_FILE。"""
    blocked = _blocked_repr()
    return f"""
import json
import sys
import os

script_path = os.environ['SCRIPT_PATH']
output_file = os.environ['OUTPUT_FILE']
params_json = os.environ.get('PARAMS_JSON', '{{}}')
instance_dir = os.path.realpath(os.environ.get('INSTANCE_DIR', ''))

_BLOCKED = set({blocked})

def _safe_import(name, globals=None, locals=None, fromlist=(), level=0):
    root = name.split('.')[0]
    if root in _BLOCKED:
        raise ImportError('Import of %r is not allowed in pure_code sandbox' % (name,))
    return __import__(name, globals, locals, fromlist, level)

_real_open = open

def _safe_open(file, mode='r', *args, **kwargs):
    path = os.path.realpath(str(file))
    if instance_dir and not (path == instance_dir or path.startswith(instance_dir + os.sep)):
        if path != os.path.realpath(script_path):
            raise PermissionError('open outside instance_dir denied: %s' % (file,))
    return _real_open(file, mode, *args, **kwargs)

_SAFE_BUILTINS = {{
    'abs': abs, 'all': all, 'any': any, 'bool': bool, 'dict': dict,
    'enumerate': enumerate, 'float': float, 'format': format, 'int': int,
    'isinstance': isinstance, 'len': len, 'list': list, 'max': max, 'min': min,
    'print': print, 'range': range, 'repr': repr, 'reversed': reversed,
    'round': round, 'set': set, 'sorted': sorted, 'str': str, 'sum': sum,
    'tuple': tuple, 'zip': zip, 'Exception': Exception, 'ValueError': ValueError,
    'TypeError': TypeError, 'KeyError': KeyError, 'True': True, 'False': False,
    'None': None, '__import__': _safe_import, 'open': _safe_open,
}}

try:
    _params = json.loads(params_json)
    _globals = {{**_params, 'params': _params, '__builtins__': _SAFE_BUILTINS}}
    with _real_open(script_path, 'r', encoding='utf-8') as script_f:
        source = script_f.read()
    exec(compile(source, script_path, 'exec'), _globals, _globals)
    _outputs = {{
        k: v for k, v in _globals.items()
        if not k.startswith('_') and k not in (
            '__builtins__', 'params', 'json', 'sys', 'os'
        )
    }}
    with _real_open(output_file, 'w', encoding='utf-8') as _f:
        json.dump({{"success": True, "outputs": _outputs}}, _f, ensure_ascii=False, default=str)
except Exception as e:
    import traceback
    with _real_open(output_file, 'w', encoding='utf-8') as _f:
        json.dump({{"success": False, "error": str(e), "traceback": traceback.format_exc()}}, _f)
"""


def truncate_capture(text: str, limit: int = MAX_CAPTURE_CHARS) -> str:
    if text is None:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n...[truncated {len(text) - limit} chars]"


def run_python_sync(
    code: str,
    *,
    instance_dir: Path,
    timeout: float = 10.0,
) -> Dict[str, Any]:
    """同步执行 Agent run_python（stdin 传代码）。"""
    validate_python_source(code)
    abs_dir = Path(instance_dir).resolve()
    wrapper = build_inline_wrapper(read_stdin=True)
    env = build_child_env(abs_dir)
    result = subprocess.run(
        [sys.executable, "-I", "-c", wrapper],
        input=code,
        capture_output=True,
        text=True,
        cwd=str(abs_dir),
        timeout=timeout,
        env=env,
    )
    stdout = truncate_capture(result.stdout or "")
    stderr = truncate_capture(result.stderr or "")
    output: Dict[str, Any] = {
        "stdout": stdout,
        "stderr": stderr,
        "returncode": result.returncode,
    }
    if result.returncode != 0:
        output["warning"] = f"Python exited with code {result.returncode}"
    return output
