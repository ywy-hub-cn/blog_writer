"""混合执行引擎 - 支持 pure_code, llm_completion, agent_action 三种执行模式"""
import json
import re
import os
import sys
import asyncio
import logging
import subprocess
import tempfile
from typing import Dict, Any, List, Optional, Callable
from pathlib import Path

from blog_writer.agent.tools import ToolRegistry
from blog_writer.agent.executor import AgentExecutor
from blog_writer.agent.base_executor import BaseExecutor
from blog_writer.llm.base import BaseLLMProvider, Message, LLMResponse
from blog_writer.constants import SCRIPT_EXECUTION_TIMEOUT, VALID_EXEC_TYPES

logger = logging.getLogger(__name__)


class PureCodeExecutor(BaseExecutor):
    """纯代码执行器 - 执行Python脚本，不调用LLM
    
    继承 BaseExecutor 获得日志、文件列表、检查执行等通用功能。
    """
    
    def __init__(
        self,
        node_definition: Dict[str, Any],
        instance_dir: str,
        log_callback: Optional[Callable[[str], None]] = None
    ):
        super().__init__(node_definition, instance_dir, log_callback)
    
    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        self.log(f"📄 [pure_code] 执行节点: {self.node.get('name')}")
        self.log(f"   Node ID: {self.node.get('id')}")
        
        resources = self.node.get("resources", {})
        script = resources.get("script", "")
        
        if not script:
            self.log("   ⚠️ 未定义脚本，跳过执行")
            return {
                "status": "success",
                "node_id": self.node.get("id"),
                "node_name": self.node.get("name"),
                "iterations": 0,
                "checks_passed": True,
                "checks_results": [],
                "tool_calls": 0,
                "token_usage": {"total_tokens_used": 0, "prompt_tokens": 0, "completion_tokens": 0},
                "outputs": {}
            }
        
        # 准备执行环境
        env = {
            "INSTANCE_DIR": str(self.instance_dir),
            "PARAMS": json.dumps(params, ensure_ascii=False),
        }
        
        # 添加params到环境
        for key, value in params.items():
            env[f"PARAM_{key.upper()}"] = str(value)[:500]
        
        try:
            # 执行Python脚本
            result = await self._run_python_script(script, env, params)
            
            if result["success"]:
                self.log(f"   ✅ 脚本执行成功")
                self.outputs = result.get("outputs", {})
            else:
                self.log(f"   ❌ 脚本执行失败: {result.get('error', '')}")
                return {
                    "status": "error",
                    "node_id": self.node.get("id"),
                    "node_name": self.node.get("name"),
                    "error": result.get("error", "Script execution failed"),
                    "token_usage": {"total_tokens_used": 0, "prompt_tokens": 0, "completion_tokens": 0},
                    "outputs": {}
                }
        except Exception as e:
            self.log(f"   ❌ 执行异常: {e}")
            return {
                "status": "error",
                "node_id": self.node.get("id"),
                "node_name": self.node.get("name"),
                "error": str(e),
                "token_usage": {"total_tokens_used": 0, "prompt_tokens": 0, "completion_tokens": 0},
                "outputs": {}
            }
        
        # 运行检查
        checks_passed = await self._run_checks()
        
        return {
            "status": "success" if checks_passed else "partial",
            "node_id": self.node.get("id"),
            "node_name": self.node.get("name"),
            "iterations": 1,
            "checks_passed": checks_passed,
            "checks_results": self.checks_results,
            "tool_calls": 0,
            "token_usage": {"total_tokens_used": 0, "prompt_tokens": 0, "completion_tokens": 0},
            "outputs": self.outputs
        }
    
    async def _run_python_script(self, script: str, env: Dict[str, str], params: Dict[str, Any] = None) -> Dict[str, Any]:
        """执行Python脚本（带超时保护 + 共享沙箱策略）"""
        if params is None:
            params = {}

        from blog_writer.agent.sandbox import (
            SandboxPolicyError,
            build_child_env,
            build_pure_code_wrapper,
            validate_python_source,
        )

        script_path = None
        proc = None
        try:
            try:
                validate_python_source(script, filename="<pure_code>")
            except SandboxPolicyError as e:
                return {"success": False, "error": f"Sandbox policy denied: {e}"}

            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8') as f:
                f.write(script)
                script_path = f.name

            output_file = self.instance_dir / "_script_output.json"
            instance_resolved = Path(self.instance_dir).resolve()
            safe_env = build_child_env(
                instance_resolved,
                extra={
                    **{str(k): str(v) for k, v in (env or {}).items()},
                    "SCRIPT_PATH": script_path,
                    "OUTPUT_FILE": str(output_file),
                    "PARAMS_JSON": json.dumps(params, ensure_ascii=False),
                },
            )
            wrapper_script = build_pure_code_wrapper()

            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-I", "-c", wrapper_script,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(instance_resolved),
                env=safe_env,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=SCRIPT_EXECUTION_TIMEOUT
                )
            except asyncio.TimeoutError:
                if proc and proc.returncode is None:
                    proc.kill()
                    try:
                        await proc.wait()
                    except Exception:
                        pass
                self.log(f"   ❌ 脚本执行超时（{SCRIPT_EXECUTION_TIMEOUT}秒）")
                return {"success": False, "error": f"Script execution timed out after {SCRIPT_EXECUTION_TIMEOUT}s"}

            if output_file.exists():
                with open(output_file, 'r', encoding='utf-8') as f:
                    result = json.load(f)
                return result
            else:
                return {"success": False, "error": f"No output file. stdout: {stdout.decode()[:500]}"}

        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            if script_path and os.path.exists(script_path):
                try:
                    os.unlink(script_path)
                except Exception:
                    pass
    
    async def _evaluate_check(self, rule: str, target: str) -> bool:
        """简单规则检查（纯代码模式用简单规则）
        
        实现 BaseExecutor 抽象方法，处理 output 和 file 类型检查。
        """
        target_type, target_value, exec_cmd = self.parse_check_target(target)

        if exec_cmd and target_type == "file":
            abs_path = self._safe_resolve_file(target_value)
            if abs_path is None or not abs_path.exists():
                return False
            return await self._run_exec_check(exec_cmd)

        if target_type == "output":
            value = self.outputs.get(target_value)
            if "不为空" in rule:
                return value is not None and value != ""
            if "为真" in rule:
                return bool(value)
            if isinstance(value, (int, float)) and "大于" in rule:
                match = re.search(r'大于\s*(\d+)', rule)
                if match:
                    return value > float(match.group(1))
            return True
        
        elif target_type == "file":
            file_path = self._safe_resolve_file(target_value)
            if file_path and file_path.exists():
                content = file_path.read_text(encoding='utf-8')
                if "不为空" in rule:
                    return len(content.strip()) > 10
            return False
        
        return False


class LLMCompletionExecutor(BaseExecutor):
    """单次LLM执行器 - 简单的单轮LLM调用
    
    继承 BaseExecutor 获得日志、文件列表、检查执行等通用功能。
    """
    
    def __init__(
        self,
        llm_provider: BaseLLMProvider,
        node_definition: Dict[str, Any],
        instance_dir: str,
        log_callback: Optional[Callable[[str], None]] = None
    ):
        super().__init__(node_definition, instance_dir, log_callback)
        self.llm = llm_provider
    
    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        self.log(f"🤖 [llm_completion] 执行节点: {self.node.get('name')}")
        self.log(f"   Node ID: {self.node.get('id')}")
        
        resources = self.node.get("resources", {})
        prompt_template = resources.get("prompt_template", "")
        system_prompt = resources.get("system_prompt", "You are a helpful assistant.")
        
        if not prompt_template:
            self.log("   ⚠️ 未定义prompt_template")
            return {
                "status": "success",
                "node_id": self.node.get("id"),
                "node_name": self.node.get("name"),
                "iterations": 0,
                "checks_passed": True,
                "checks_results": [],
                "tool_calls": 0,
                "token_usage": {"total_tokens_used": 0, "prompt_tokens": 0, "completion_tokens": 0},
                "outputs": {}
            }
        
        # 构建prompt
        user_prompt = self._build_prompt(prompt_template, params)
        
        # 添加约束和操作信息
        constraints = self.node.get("constraints", {})
        actions = self.node.get("actions", [])
        
        if constraints.get("must"):
            user_prompt += "\n\n必须遵守的规则:\n"
            for rule in constraints["must"]:
                user_prompt += f"- {rule}\n"
        
        if actions:
            user_prompt += "\n\n输出要求:\n"
            for action in actions:
                output = action.get("output", {})
                if output:
                    user_prompt += f"- 输出到 {output.get('path', 'N/A')}\n"
        
        # 单轮LLM调用
        self.log(f"   调用LLM...")
        try:
            messages = [
                Message(role="system", content=system_prompt),
                Message(role="user", content=user_prompt)
            ]
            
            response = await self.llm.chat(messages=messages)
            
            self.log(f"   ✅ LLM调用成功")
            
            # 保存输出
            self._save_outputs(response.content)
            
        except Exception as e:
            self.log(f"   ❌ LLM调用失败: {e}")
            return {
                "status": "error",
                "node_id": self.node.get("id"),
                "node_name": self.node.get("name"),
                "error": str(e),
                "token_usage": {"total_tokens_used": 0, "prompt_tokens": 0, "completion_tokens": 0},
                "outputs": {}
            }
        
        # 获取token统计
        llm_stats = self.llm.get_stats()
        
        # 运行检查
        checks_passed = await self._run_checks()
        
        return {
            "status": "success" if checks_passed else "partial",
            "node_id": self.node.get("id"),
            "node_name": self.node.get("name"),
            "iterations": 1,
            "checks_passed": checks_passed,
            "checks_results": self.checks_results,
            "tool_calls": 0,
            "token_usage": llm_stats,
            "outputs": self.outputs
        }
    
    def _build_prompt(self, template: str, params: Dict[str, Any]) -> str:
        """用参数填充模板"""
        prompt = template
        for key, value in params.items():
            placeholder = f"{{{{{key}}}}}"
            prompt = prompt.replace(placeholder, str(value))
            # 也替换不带大括号的引用
            placeholder2 = f"__{key}__"
            prompt = prompt.replace(placeholder2, str(value))
        
        # 添加可用文件信息
        files_info = self._list_available_files()
        if files_info:
            prompt += f"\n\n可用文件:\n{files_info}"
        
        return prompt
    
    def _list_available_files(self) -> str:
        """列出实例目录中的可用文件（LLM版本，包含内容预览）
        
        重写基类方法，为LLM提供文件内容预览，帮助理解上下文。
        """
        lines = []
        if self.instance_dir.exists():
            files = list(self.instance_dir.iterdir())
            if files:
                for f in sorted(files):
                    if f.is_file():
                        try:
                            content_preview = f.read_text(encoding='utf-8')[:200]
                            lines.append(f"  {f.name}: {content_preview}...")
                        except Exception:
                            try:
                                size = f.stat().st_size
                                lines.append(f"  {f.name} ({size}B)")
                            except OSError:
                                lines.append(f"  {f.name}")
                    elif f.is_dir():
                        lines.append(f"  {f.name}/ (dir)")
        return "\n".join(lines)
    
    def _save_outputs(self, content: str):
        """保存LLM输出（路径必须落在 instance_dir 内）"""
        base = Path(self.instance_dir).resolve()

        def _safe_write(rel_path: str, file_content: str) -> Optional[Path]:
            try:
                output_path = (base / rel_path).resolve()
                output_path.relative_to(base)
            except (ValueError, OSError):
                self.log(f"   ⚠️ 拒绝越界输出路径: {rel_path}")
                return None
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(file_content, encoding='utf-8')
            return output_path

        actions = self.node.get("actions", [])
        if not actions:
            # 默认保存到output.md
            output_path = _safe_write("output.md", content)
            if output_path:
                self.outputs["output"] = str(output_path)
                self.log(f"   保存输出到 {output_path}")
            return
        
        for action in actions:
            output = action.get("output", {})
            path = output.get("path", "")
            if path:
                # 处理输出内容
                file_content = content
                if output.get("extract_json"):
                    try:
                        json_match = re.search(r'\{[\s\S]*\}|\[[\s\S]*\]', content)
                        if json_match:
                            file_content = json_match.group(0)
                    except Exception as e:
                        logger.warning(f"JSON提取失败: {e}")
                        pass
                
                output_path = _safe_write(path, file_content)
                if output_path:
                    self.outputs[action.get("name", "output")] = str(output_path)
                    self.log(f"   保存输出到 {output_path}")
    
    async def _evaluate_check(self, rule: str, target: str) -> bool:
        """实现 BaseExecutor 抽象方法，处理 file 和 self 类型检查。"""
        target_type, target_value, exec_cmd = self.parse_check_target(target)

        if exec_cmd and target_type == "file":
            abs_path = self._safe_resolve_file(target_value)
            if abs_path is None or not abs_path.exists():
                return False
            return await self._run_exec_check(exec_cmd)

        if target_type == "file":
            file_path = self._safe_resolve_file(target_value)
            if file_path and file_path.exists():
                content = file_path.read_text(encoding='utf-8')
                if "不为空" in rule:
                    return len(content.strip()) > 10
                if "包含" in rule:
                    keyword = rule.replace("包含", "").strip()
                    return keyword in content
                if "字数" in rule or "字符" in rule:
                    match = re.search(r'(\d+)\s*字', rule)
                    if match:
                        min_chars = int(match.group(1))
                        return len(content) >= min_chars
            return False
        
        elif target_type == "self":
            # LLM自检查
            try:
                check_messages = [
                    Message(role="system", content=f"Evaluate this check rule and return ONLY 'PASS' or 'FAIL':\nRule: {rule}"),
                    Message(role="user", content="Return PASS or FAIL only.")
                ]
                response = await self.llm.chat(messages=check_messages)
                return (response.content or "").strip().upper() == "PASS"
            except Exception as e:
                self.log(f"   ⚠️ LLM自检查异常: {e}", "warning")
                return False  # 异常时返回False，检查未通过
        
        return False


class NodeExecutorFactory:
    """节点执行器工厂 - 根据exec_type/kind类型创建对应执行器
    
    支持两种字段名（exec_type 为推荐字段，kind 为兼容字段）：
    - exec_type: 推荐使用，文档标准字段
    - kind: 旧版兼容字段
    
    执行类型定义在 constants.VALID_EXEC_TYPES 中
    """
    
    # 从常量定义自动生成映射（消除重复定义）
    EXEC_TYPE_MAP = {t: t for t in VALID_EXEC_TYPES}
    
    # 旧版 kind 值到新 exec_type 的兼容映射
    LEGACY_KIND_MAP = {
        "agent": "agent_action",
        "code": "pure_code",
        "review": "human_review",
        "system": "system_check",
    }
    
    # 有效的执行类型列表（从常量导出，便于外部引用）
    VALID_KINDS = VALID_EXEC_TYPES
    
    @staticmethod
    def get_exec_type(node_definition: Dict[str, Any]) -> str:
        """获取节点执行类型，优先使用 exec_type，回退到 kind"""
        exec_type = node_definition.get("exec_type")
        if exec_type and exec_type in NodeExecutorFactory.EXEC_TYPE_MAP:
            return exec_type
        kind = node_definition.get("kind", "agent_action")
        mapped = NodeExecutorFactory.EXEC_TYPE_MAP.get(kind)
        if mapped:
            return mapped
        # 兼容旧版 kind 值
        legacy = NodeExecutorFactory.LEGACY_KIND_MAP.get(kind)
        if legacy:
            return legacy
        return kind
    
    @staticmethod
    def create_executor(
        node_definition: Dict[str, Any],
        llm_provider: Optional[BaseLLMProvider],
        instance_dir: str,
        max_iterations: int = 20,
        log_callback: Optional[Callable[[str], None]] = None
    ):
        """
        根据节点的exec_type/kind字段创建对应的执行器
        
        Args:
            node_definition: 节点定义（支持 exec_type 或 kind 字段）
            llm_provider: LLM提供者（pure_code类型可为None）
            instance_dir: 实例目录
            max_iterations: 最大迭代次数（用于agent_action）
            log_callback: 日志回调
        
        Returns:
            对应类型的执行器实例
        
        Raises:
            ValueError: 当需要LLM提供者但未提供时抛出
        """
        exec_type = NodeExecutorFactory.get_exec_type(node_definition)
        node_id = node_definition.get("id", "unknown")
        
        if exec_type == "pure_code":
            return PureCodeExecutor(
                node_definition=node_definition,
                instance_dir=instance_dir,
                log_callback=log_callback
            )
        elif exec_type == "llm_completion":
            if not llm_provider:
                raise ValueError(
                    f"节点 {node_id} (exec_type=llm_completion) 需要LLM提供者，"
                    f"但未提供。请配置有效的LLM设置或更换执行类型。"
                )
            return LLMCompletionExecutor(
                llm_provider=llm_provider,
                node_definition=node_definition,
                instance_dir=instance_dir,
                log_callback=log_callback
            )
        elif exec_type == "agent_action":
            if not llm_provider:
                raise ValueError(
                    f"节点 {node_id} (exec_type=agent_action) 需要LLM提供者，"
                    f"但未提供。请配置有效的LLM设置或更换执行类型。"
                )
            return AgentExecutor(
                llm_provider=llm_provider,
                node_definition=node_definition,
                instance_dir=instance_dir,
                max_iterations=max_iterations,
                log_callback=log_callback,
            )
        elif exec_type in ("human_review", "system_check"):
            # 这些类型由工作流服务直接处理，不需要创建执行器
            return None
        else:
            raise ValueError(
                f"未知的执行类型: {exec_type} (节点 {node_id})。"
                f"有效类型: {list(VALID_EXEC_TYPES)}"
            )
