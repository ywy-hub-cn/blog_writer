"""
blog_writer/agent/base_executor.py - 执行器基类

提供所有执行器共用的基础功能：
- 日志记录
- 文件列表获取（安全版本，不读取文件内容）
- 检查执行框架
- 路径安全验证（防止路径遍历攻击）
"""
import logging
import os
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, Callable
from pathlib import Path

logger = logging.getLogger(__name__)


class BaseExecutor(ABC):
    """执行器基类 - 提供通用功能
    
    所有执行器都必须继承此类并实现 _evaluate_check() 和 execute() 方法。
    """
    
    def __init__(
        self,
        node_definition: Dict[str, Any],
        instance_dir: str,
        log_callback: Optional[Callable[[str], None]] = None
    ):
        self.node = node_definition
        self.instance_dir = Path(instance_dir).resolve()
        self.log_callback = log_callback or (lambda x: None)
        self.outputs: Dict[str, Any] = {}
        self.checks_results: List[Dict[str, Any]] = []
    
    def _safe_resolve_file(self, relative_path: str) -> Optional[Path]:
        """安全解析相对路径，确保不会越界到 instance_dir 之外。

        用于执行器内部所有基于用户输入/节点配置的文件访问场景，
        防止 ``../`` 等路径遍历手段读取宿主机敏感文件。

        Args:
            relative_path: 相对 instance_dir 的路径

        Returns:
            解析后的安全 Path 对象；越界时返回 None 并记录警告
        """
        if not relative_path or not isinstance(relative_path, str):
            return None
        try:
            resolved = (self.instance_dir / relative_path).resolve()
            resolved.relative_to(self.instance_dir)
            return resolved
        except (ValueError, OSError) as e:
            logger.warning(
                "路径越界被拒绝: %s (instance_dir=%s, error=%s)",
                relative_path, self.instance_dir, e,
            )
            return None
    
    def log(self, message: str, level: str = "info"):
        """记录日志"""
        log_func = getattr(logger, level, logger.info)
        log_func(message)
        self.log_callback(message)
    
    def _list_available_files(self) -> str:
        """列出实例目录中的可用文件（安全版本，只显示文件名和大小）
        
        不读取文件内容，避免对大文件或二进制文件造成性能问题。
        """
        lines = []
        if self.instance_dir.exists():
            files = list(self.instance_dir.iterdir())
            if files:
                for f in sorted(files):
                    if f.is_file():
                        try:
                            size = f.stat().st_size
                            if size >= 1024 * 1024:  # >= 1MB
                                size_str = f"{size / (1024 * 1024):.1f}MB"
                            elif size >= 1024:  # >= 1KB
                                size_str = f"{size / 1024:.1f}KB"
                            else:
                                size_str = f"{size}B"
                            lines.append(f"  {f.name} ({size_str})")
                        except OSError:
                            lines.append(f"  {f.name}")
                    elif f.is_dir():
                        lines.append(f"  {f.name}/ (dir)")
            else:
                lines.append("  (empty directory)")
        return "\n".join(lines)
    
    def _normalize_output_files(self) -> None:
        """输出文件归一化：处理 LLM 未按提示词写入目标文件名的情况。

        常见场景：
        - S009 Gate 节点要求写入 "009 Gate结果.md"，但 LLM 可能写到 _gate_json.json
        - 其他节点可能有类似的文件名偏差

        策略：
        1. 检查节点定义的 actions[*].output.path 文件是否存在
        2. 如果不存在，在实例目录中查找已知的替代文件名
        3. 找到后自动转换/重命名为目标文件名
        """
        import json
        import shutil
        from pathlib import Path

        actions = self.node.get("actions", [])
        if not actions:
            return

        instance_dir = Path(self.instance_dir)
        if not instance_dir.exists():
            return

        # 已知的文件名映射：{节点ID: {替代文件名: 目标文件名}}
        filename_aliases = {
            "step.blog.writer.gate": {
                "_gate_json.json": "009 Gate结果.md",
                "gate_result.json": "009 Gate结果.md",
                "gate-result.json": "009 Gate结果.md",
            },
        }

        node_id = str(self.node.get("id", ""))
        aliases = filename_aliases.get(node_id, {})

        for alias_name, target_name in aliases.items():
            target_file = instance_dir / target_name
            alias_file = instance_dir / alias_name

            # 目标文件已存在，不需要处理
            if target_file.exists() and target_file.stat().st_size > 0:
                continue

            # 替代文件存在，进行转换
            if alias_file.exists() and alias_file.stat().st_size > 0:
                try:
                    # 读取替代文件内容
                    content = alias_file.read_text(encoding="utf-8")

                    # 如果是 JSON，尝试格式化为 Markdown（Gate 结果格式）
                    if alias_file.suffix == ".json":
                        try:
                            data = json.loads(content)
                            md_content = self._convert_gate_json_to_md(data)
                            target_file.write_text(md_content, encoding="utf-8")
                            self.log(f"   [NORMALIZE] {alias_name} → {target_name} (JSON转Markdown)")
                        except json.JSONDecodeError:
                            # JSON 解析失败，直接复制
                            shutil.copy2(alias_file, target_file)
                            self.log(f"   [NORMALIZE] {alias_name} → {target_name} (直接复制)")
                    else:
                        shutil.copy2(alias_file, target_file)
                        self.log(f"   [NORMALIZE] {alias_name} → {target_name} (直接复制)")
                except Exception as e:
                    self.log(f"   [NORMALIZE] 转换失败 {alias_name}: {e}")

    @staticmethod
    def _convert_gate_json_to_md(data: dict) -> str:
        """将 Gate JSON 结果转换为 Markdown 格式（write_step_output.py 的简化版）。

        Args:
            data: Gate 结果字典，应包含 passed, checklist, issues, note 等字段

        Returns:
            格式化的 Markdown 字符串
        """
        import json

        passed = data.get("passed", False)
        checklist = data.get("checklist", {})
        issues = data.get("issues", [])
        note = data.get("note", "")

        lines = [
            "# Gate 校验结果",
            "",
            f"- **结果**: {'✅ 通过' if passed else '❌ 不通过'}",
            f"- **passed**: `{str(passed).lower()}`",
            "",
            "## 检查清单",
            "",
        ]

        if isinstance(checklist, dict):
            for key, val in checklist.items():
                status = "✅" if val else "❌"
                lines.append(f"- {status} **{key}**: `{str(val).lower()}`")
        else:
            lines.append(f"- {checklist}")

        lines.extend(["", "## 问题列表", ""])

        if issues:
            for issue in issues:
                lines.append(f"- {issue}")
        else:
            lines.append("- 无")

        if note:
            lines.extend(["", "## 说明", "", note])

        lines.extend(["", "---", "", f"```json\n{json.dumps(data, ensure_ascii=False, indent=2)}\n```"])

        return "\n".join(lines)

    async def _run_checks(self) -> bool:
        """运行所有检查（通用框架）

        检查失败策略（由 check.on_fail 字段控制）：
        - "hard_fail"：失败则阻塞（all_passed=False）
        - "pass=false" 或 "warn"：失败仅记录警告，不阻塞流程
        - 未指定 on_fail：默认按 hard_fail 处理（fail-closed，安全优先）
        """
        # 输出文件归一化：处理 LLM 未按提示词写入目标文件名的情况
        # 例如 S009 Gate 节点要求写入 "009 Gate结果.md"，但 LLM 可能写到 _gate_json.json
        self._normalize_output_files()

        checks = self.node.get("checks", [])
        if not checks:
            self.log("   No checks defined")
            return True

        all_passed = True

        for check in checks:
            check_id = check.get("id", "?")
            rule = check.get("rule", "")
            target = check.get("target", "")
            on_fail = check.get("on_fail", "hard_fail")

            self.log(f"   Running check {check_id}: {rule} (on_fail={on_fail})")

            passed = await self._evaluate_check(rule, target)

            self.checks_results.append({
                "id": check_id,
                "rule": rule,
                "target": target,
                "on_fail": on_fail,
                "passed": passed
            })

            if passed:
                self.log(f"   ✅ Check {check_id} PASSED")
            else:
                if on_fail == "hard_fail":
                    self.log(f"   ❌ Check {check_id} FAILED (hard_fail, 阻塞)")
                    all_passed = False
                else:
                    self.log(f"   ⚠️  Check {check_id} FAILED (on_fail={on_fail}, 不阻塞)")

        return all_passed

    @staticmethod
    def parse_check_target(target: str):
        """解析 check target。

        支持：
        - ``file:xxx.md``
        - ``file:xxx.json::exec:python3 -c '...'``
        - ``output:key`` / ``step:...`` / ``self``

        Returns:
            (target_type, path_or_value, exec_command_or_None)
        """
        if not target:
            return "", "", None
        exec_cmd = None
        base = target
        if "::exec:" in target:
            base, exec_cmd = target.split("::exec:", 1)
            exec_cmd = exec_cmd.strip() or None
        if ":" in base:
            t, rest = base.split(":", 1)
            return t.strip(), rest.strip(), exec_cmd
        return base.strip(), base.strip(), exec_cmd

    async def _run_exec_check(self, command: str) -> bool:
        """在 instance_dir 下执行 check 附带的命令。

        安全策略：仅允许 ``python[3] -c <code>``（用当前解释器 subprocess_exec），
        禁止任意 shell，避免节点定义变成宿主机 RCE。
        """
        import asyncio
        import re
        import sys

        if not command:
            return False
        try:
            cmd = command.strip()
            # 稳定解析 python[3] -c <code>（避免 Windows shlex 引号问题）
            m = re.match(r"^(python3?)\s+-c\s+(.+)$", cmd, re.S)
            if not m:
                self.log(
                    "      exec check rejected: only 'python -c' / 'python3 -c' allowed "
                    "(shell disabled)"
                )
                return False

            code = m.group(2).strip()
            if len(code) >= 2 and code[0] == code[-1] and code[0] in ("'", '"'):
                code = code[1:-1]

            # AST 静态检查：拦截危险导入和 dunder 逃逸
            from blog_writer.agent.sandbox import validate_python_source, SandboxPolicyError

            try:
                validate_python_source(code, filename="<exec_check>")
            except SandboxPolicyError as e:
                self.log(f"      exec check rejected by sandbox policy: {e}")
                return False

            import os as _os

            safe_env = {
                k: v
                for k, v in _os.environ.items()
                if not any(
                    s in k.upper()
                    for s in ("KEY", "SECRET", "TOKEN", "PASSWORD", "CREDENTIAL", "ACCESS")
                )
            }
            safe_env["PYTHONIOENCODING"] = "utf-8"

            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                "-c",
                code,
                cwd=str(self.instance_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=safe_env,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
            ok = proc.returncode == 0
            if not ok:
                err = (stderr or b"").decode("utf-8", errors="replace")[:300]
                self.log(f"      exec check failed (code={proc.returncode}): {err}")
            return ok
        except Exception as e:
            self.log(f"      exec check error: {e}")
            return False
    
    @abstractmethod
    async def _evaluate_check(self, rule: str, target: str) -> bool:
        """评估单个检查规则（子类实现）"""
        pass
    
    @abstractmethod
    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """执行节点（子类实现）"""
        pass
