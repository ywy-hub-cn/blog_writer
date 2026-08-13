import os
import sys
import json
import time
import asyncio
import subprocess
import logging
from typing import Any, Callable, Dict, List, Optional
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class Tool:
    name: str
    description: str
    func: Callable
    parameters: Dict[str, Any] = field(default_factory=dict)
    required_params: List[str] = field(default_factory=list)

    def to_schema(self) -> Dict[str, Any]:
        properties = {}
        for param_name, param_info in self.parameters.items():
            properties[param_name] = param_info

        required = [p for p in self.required_params if p in properties]

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required
                }
            }
        }


class ToolRegistry:
    def __init__(
        self,
        working_dir: str,
        instance_dir: str,
        max_tool_calls: int = 100,
    ):
        self.working_dir = Path(working_dir).resolve()
        self.instance_dir = Path(instance_dir).resolve()
        self._tools: Dict[str, Tool] = {}
        self._call_history: List[Dict[str, Any]] = []
        self._max_tool_calls = max(1, int(max_tool_calls or 100))
        self._register_default_tools()

    def _validate_path(self, path: str) -> Path:
        resolved = (self.instance_dir / path).resolve()
        try:
            resolved.relative_to(self.instance_dir)
        except ValueError:
            raise PermissionError(f"Access denied: path {path} is outside instance directory")
        return resolved

    def _register_default_tools(self):
        self.register(Tool(
            name="read_file",
            description="Read the content of a file. Returns the file content as text.",
            func=self._read_file,
            parameters={
                "path": {"type": "string", "description": "Relative path of the file to read"}
            },
            required_params=["path"]
        ))

        self.register(Tool(
            name="write_file",
            description="Write content to a file. Creates directories if they don't exist.",
            func=self._write_file,
            parameters={
                "path": {"type": "string", "description": "Relative path of the file to write"},
                "content": {"type": "string", "description": "Content to write to the file"}
            },
            required_params=["path", "content"]
        ))

        self.register(Tool(
            name="list_files",
            description="List files and directories in a given path.",
            func=self._list_files,
            parameters={
                "path": {"type": "string", "description": "Relative path of the directory to list"}
            },
            required_params=["path"]
        ))

        self.register(Tool(
            name="web_search",
            description="Search the web for information using DuckDuckGo. Returns a list of results with titles, URLs, and snippets.",
            func=self._web_search,
            parameters={
                "query": {"type": "string", "description": "Search query string"},
                "num_results": {"type": "integer", "description": "Number of results to return (default: 5)"}
            },
            required_params=["query"]
        ))

        self.register(Tool(
            name="run_python",
            description="Execute Python code and return the output (stdout/stderr). Timeout is 10 seconds.",
            func=self._run_python,
            parameters={
                "code": {"type": "string", "description": "Python code to execute"}
            },
            required_params=["code"]
        ))

        self.register(Tool(
            name="run_script",
            description=(
                "Run a deterministic script from tools/blog-writer/ in the task instance directory. "
                "Use this for setup_brand.py, field_markup.py, generate_presentation.py, "
                "assemble_publish.py, publish_to_wp.py, validate_*.py, check_rankmath.py, etc. "
                "Pass argv as a list of strings (without python / script name)."
            ),
            func=self._run_script,
            parameters={
                "script": {
                    "type": "string",
                    "description": "Script filename only, e.g. generate_presentation.py",
                },
                "args": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "CLI arguments, e.g. [\"--out-dir\", \".\"]",
                },
            },
            required_params=["script"],
        ))

    def register(self, tool: Tool):
        self._tools[tool.name] = tool

    def get_tool(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def get_all_tools(self) -> Dict[str, Tool]:
        return self._tools.copy()

    def get_tools_schema(self) -> List[Dict[str, Any]]:
        return [tool.to_schema() for tool in self._tools.values()]

    def get_call_history(self) -> List[Dict[str, Any]]:
        return self._call_history.copy()

    async def execute(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        if len(self._call_history) >= self._max_tool_calls:
            logger.warning(
                "Tool call limit exceeded (%s) for tool=%s",
                self._max_tool_calls,
                name,
            )
            return {
                "status": "error",
                "error": f"工具调用次数超限（最多 {self._max_tool_calls} 次/任务）",
            }

        # 处理 LLM 可能把参数包在 _raw 字段里的情况（如 DeepSeek function calling）
        try:
            raw_val = None
            if isinstance(arguments, dict):
                raw_val = arguments.get("_raw")
            elif hasattr(arguments, "get"):
                try:
                    raw_val = arguments.get("_raw")
                except Exception:
                    pass
            if raw_val is not None:
                logger.error(f"[RAW_DEBUG] tool={name} detected _raw, type={type(raw_val).__name__}")
                if isinstance(raw_val, str):
                    parsed = json.loads(raw_val)
                    if isinstance(parsed, dict):
                        arguments = parsed
                        logger.error(f"[RAW_DEBUG] tool={name} parsed into {list(parsed.keys())}")
                elif isinstance(raw_val, dict):
                    arguments = raw_val
                    logger.error(f"[RAW_DEBUG] tool={name} used _raw dict directly")
        except Exception as e:
            logger.error(f"[RAW_DEBUG] tool={name} _raw parse failed: {e}")

        tool = self._tools.get(name)
        if not tool:
            return {"status": "error", "error": f"Tool '{name}' not found"}

        start_time = time.time()
        try:
            if asyncio.iscoroutinefunction(tool.func):
                result = await tool.func(**arguments)
            else:
                # 同步函数放到线程池执行，避免阻塞事件循环
                result = await asyncio.to_thread(tool.func, **arguments)
            
            elapsed = time.time() - start_time
            call_record = {
                "tool": name,
                "arguments": arguments,
                "result": str(result)[:2000] if len(str(result)) > 2000 else result,
                "elapsed": round(elapsed, 2),
                "status": "success"
            }
            self._call_history.append(call_record)
            logger.info(f"Tool {name} executed in {elapsed:.2f}s")
            
            return {"status": "success", "result": result}
        except PermissionError as e:
            return {"status": "error", "error": str(e)}
        except Exception as e:
            elapsed = time.time() - start_time
            call_record = {
                "tool": name,
                "arguments": arguments,
                "error": str(e),
                "elapsed": round(elapsed, 2),
                "status": "error"
            }
            self._call_history.append(call_record)
            logger.error(f"Tool {name} failed: {e}")
            return {"status": "error", "error": str(e)}

    def _read_file(self, path: str) -> Dict[str, Any]:
        try:
            abs_path = self._validate_path(path)
            if not abs_path.exists():
                return {"error": f"File not found: {path}"}
            
            with open(abs_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            return {"content": content, "path": path}
        except PermissionError as e:
            return {"error": str(e)}
        except Exception as e:
            return {"error": f"Failed to read file: {e}"}

    def _write_file(self, path: str, content: str) -> Dict[str, Any]:
        try:
            abs_path = self._validate_path(path)
            abs_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(abs_path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            return {"success": True, "path": path, "size": len(content)}
        except PermissionError as e:
            return {"error": str(e)}
        except Exception as e:
            return {"error": f"Failed to write file: {e}"}

    def _list_files(self, path: str = ".") -> Dict[str, Any]:
        try:
            abs_path = self._validate_path(path)
            if not abs_path.exists():
                return {"error": f"Directory not found: {path}"}
            
            if not abs_path.is_dir():
                return {"error": f"Path is not a directory: {path}"}
            
            items = []
            for item in abs_path.iterdir():
                relative = item.relative_to(self.instance_dir)
                items.append({
                    "name": item.name,
                    "path": str(relative),
                    "is_directory": item.is_dir(),
                    "size": item.stat().st_size if item.is_file() else 0
                })
            
            return {"files": items, "count": len(items)}
        except PermissionError as e:
            return {"error": str(e)}
        except Exception as e:
            return {"error": f"Failed to list files: {e}"}

    def _web_search(self, query: str, num_results: int = 5) -> Dict[str, Any]:
        try:
            # 优先使用新版 ddgs（旧版 duckduckgo-search 已废弃且内部调 Bing 国内不可达）
            try:
                from ddgs import DDGS
            except ImportError:
                from duckduckgo_search import DDGS
            
            results = []
            with DDGS() as ddgs:
                for r in ddgs.text(query, max_results=num_results):
                    results.append({
                        "title": r.get("title", ""),
                        "url": r.get("href", ""),
                        "snippet": r.get("body", "")
                    })
            
            return {"results": results, "count": len(results)}
        except ImportError:
            return {"error": "搜索依赖未安装。运行: pip install ddgs"}
        except Exception as e:
            return {"error": f"Search failed: {e}"}

    def _run_python(self, code: str) -> Dict[str, Any]:
        try:
            from blog_writer.agent.sandbox import (
                SandboxPolicyError,
                run_python_sync,
            )

            return run_python_sync(
                code,
                instance_dir=Path(self.instance_dir).resolve(),
                timeout=10.0,
            )
        except SandboxPolicyError as e:
            return {"error": f"Sandbox policy denied: {e}"}
        except subprocess.TimeoutExpired:
            return {"error": "Python execution timed out (10s)"}
        except Exception as e:
            return {"error": f"Python execution failed: {e}"}

    # 仅允许执行仓库内 tools/blog-writer 白名单脚本
    _ALLOWED_SCRIPTS = frozenset(
        {
            "setup_brand.py",
            "validate_bid.py",
            "validate_content.py",
            "validate_config.py",
            "field_markup.py",
            "generate_presentation.py",
            "assemble_publish.py",
            "publish_to_wp.py",
            "check_rankmath.py",
            "write_step_output.py",
            "check_forbidden.py",
        }
    )

    def _tools_blog_writer_dir(self) -> Path:
        # blog_writer/agent/tools.py → 项目根 / tools / blog-writer
        return Path(__file__).resolve().parents[2] / "tools" / "blog-writer"

    def _run_script(self, script: str, args: Optional[List[Any]] = None) -> Dict[str, Any]:
        name = Path(str(script or "")).name
        if name not in self._ALLOWED_SCRIPTS:
            return {
                "error": (
                    f"Script not allowed: {script}. "
                    f"Allowed: {', '.join(sorted(self._ALLOWED_SCRIPTS))}"
                )
            }

        script_path = (self._tools_blog_writer_dir() / name).resolve()
        tools_root = self._tools_blog_writer_dir().resolve()
        try:
            script_path.relative_to(tools_root)
        except ValueError:
            return {"error": f"Script path escape blocked: {script}"}
        if not script_path.is_file():
            return {"error": f"Script not found: {name}"}

        argv = [str(a) for a in (args or [])]
        # 常见相对 out-dir=. 在 instance cwd 下执行
        cmd = [sys.executable, str(script_path), *argv]
        # 使用沙箱环境，过滤敏感变量
        from blog_writer.agent.sandbox import build_child_env
        child_env = build_child_env(Path(self.instance_dir))
        try:
            completed = subprocess.run(
                cmd,
                cwd=str(Path(self.instance_dir).resolve()),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=180,
                env=child_env,
            )
            stdout = (completed.stdout or "")[-8000:]
            stderr = (completed.stderr or "")[-4000:]
            ok = completed.returncode == 0
            result: Dict[str, Any] = {
                "success": ok,
                "returncode": completed.returncode,
                "script": name,
                "stdout": stdout,
                "stderr": stderr,
            }
            if not ok:
                result["error"] = (
                    f"{name} exited {completed.returncode}: "
                    f"{(stderr or stdout or 'no output')[:500]}"
                )
            return result
        except subprocess.TimeoutExpired:
            return {"error": f"Script timed out (180s): {name}"}
        except Exception as e:
            return {"error": f"Script execution failed: {e}"}
