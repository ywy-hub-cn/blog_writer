import json
import os
import re
import asyncio
import logging
from typing import Dict, Any, List, Optional, Callable

from blog_writer.agent.tools import ToolRegistry
from blog_writer.agent.base_executor import BaseExecutor
from blog_writer.llm.base import BaseLLMProvider, Message, ToolCall

logger = logging.getLogger(__name__)


def _wants_isolated_session(node_definition: Dict[str, Any]) -> bool:
    """是否启用隔离评审会话（不继承写作上下文、只读优先）。"""
    resources = node_definition.get("resources") or {}
    if resources.get("isolated_session") is True:
        return True
    node_id = str(node_definition.get("id") or "")
    # S008 自审 / S009 Gate：架构要求独立 session
    isolated_ids = (
        "step.blog.writer.review_draft",
        "step.blog.writer.gate",
    )
    return node_id in isolated_ids


class AgentExecutor(BaseExecutor):
    """Agent执行器 - 多轮LLM交互，支持工具调用
    
    继承 BaseExecutor 获得日志、文件列表、检查执行等通用功能。
    支持 isolated_session：全新 message 列表、禁止写入正文类工具提示、不预览产物内容。
    """
    
    def __init__(
        self,
        llm_provider: BaseLLMProvider,
        node_definition: Dict[str, Any],
        instance_dir: str,
        max_iterations: int = 20,
        log_callback: Optional[Callable[[str], None]] = None,
        isolated_session: Optional[bool] = None,
    ):
        super().__init__(node_definition, instance_dir, log_callback)
        self.llm = llm_provider
        self.max_iterations = max_iterations
        self.isolated_session = (
            _wants_isolated_session(node_definition)
            if isolated_session is None
            else bool(isolated_session)
        )
        
        try:
            max_tool_calls = int(os.environ.get("BLOG_WRITER_MAX_TOOL_CALLS", "100") or 100)
        except (TypeError, ValueError):
            max_tool_calls = 100
        self.tools = ToolRegistry(
            working_dir=str(self.instance_dir.parent),
            instance_dir=str(self.instance_dir),
            max_tool_calls=max_tool_calls,
        )
        
        self.messages: List[Message] = []
        self.iteration_count = 0

    @staticmethod
    def _unwrap_raw_args(raw_val: Any, tool_name: str) -> Dict[str, Any]:
        """展开 LLM function calling 可能包裹的 _raw 字段。

        三级降级策略：
        1. 标准 json.loads（正常情况）
        2. json_repair.loads（修复未闭合字符串、缺少引号等常见损坏）
        3. 正则提取（最后兜底，仅 write_file 工具）

        Args:
            raw_val: _raw 字段的值（str 或 dict）
            tool_name: 工具名称，用于最后兜底时的特殊处理

        Returns:
            解析后的参数字典；解析失败返回原始 {"_raw": raw_val}
        """
        # dict 类型直接使用
        if isinstance(raw_val, dict):
            return raw_val

        if not isinstance(raw_val, str):
            return {"_raw": raw_val}

        # 第一级：标准 JSON 解析
        try:
            parsed = json.loads(raw_val)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

        # 第二级：json-repair 修复（处理未闭合字符串、转义错误等）
        try:
            from json_repair import repair_json
            repaired = repair_json(raw_val, return_objects=True)
            if isinstance(repaired, dict):
                logger.info(f"[RAW] json-repair 修复成功: {list(repaired.keys())}")
                return repaired
        except Exception as e:
            logger.warning(f"[RAW] json-repair 修复失败: {e}")

        # 第三级：正则兜底（仅 write_file，提取 path 和 content）
        if tool_name == "write_file":
            try:
                import re
                path_match = re.search(r'"path"\s*:\s*"([^"]+)"', raw_val)
                if path_match:
                    path = path_match.group(1)
                    # content 提取：从 "content": " 开始，到字符串末尾
                    # 使用非贪婪匹配到最后一个 "} 或 " 结尾
                    content_match = re.search(
                        r'"content"\s*:\s*"((?:[^"\\]|\\.)*)', raw_val, re.DOTALL
                    )
                    if content_match:
                        content = content_match.group(1)
                        # 处理 JSON 转义：\" -> ", \\ -> \, \n -> 换行等
                        content = (
                            content.replace('\\"', '"')
                            .replace("\\\\", "\\")
                            .replace("\\n", "\n")
                            .replace("\\t", "\t")
                            .replace("\\r", "\r")
                        )
                        logger.info(f"[RAW] 正则兜底提取: path={path}, content_len={len(content)}")
                        return {"path": path, "content": content}
            except Exception as e:
                logger.warning(f"[RAW] 正则兜底失败: {e}")

        # 全部失败，返回原始值（工具层会报 unexpected keyword argument）
        return {"_raw": raw_val}

    def _build_system_prompt(self, params: Optional[Dict[str, Any]] = None) -> str:
        constraints = self.node.get("constraints", {})
        must_rules = constraints.get("must", [])
        forbidden_rules = constraints.get("forbidden", [])
        actions = self.node.get("actions", [])
        
        parts = []
        if self.isolated_session:
            parts.append(
                "## ISOLATED REVIEW SESSION\n"
                "This is a fresh session with NO prior conversation history from drafting.\n"
                "Evaluate artifacts solely from files you read in this session.\n"
                "Do not assume prior tool results or writing rationale.\n"
                "Prefer read_file / run_script / run_python; avoid rewriting draft content unless the node workflow requires it."
            )
        parts.append(f"You are executing the node: {self.node.get('name', 'Unknown')}")
        parts.append(f"Node ID: {self.node.get('id', 'unknown')}")
        
        if must_rules:
            parts.append("\n## MUST DO (These rules MUST be followed):")
            for i, rule in enumerate(must_rules, 1):
                parts.append(f"{i}. {rule}")
        
        if forbidden_rules:
            parts.append("\n## MUST NOT DO (These are FORBIDDEN):")
            for i, rule in enumerate(forbidden_rules, 1):
                parts.append(f"{i}. {rule}")
        
        if actions:
            parts.append("\n## WORKFLOW (Execute these steps in order):")
            for i, action in enumerate(actions, 1):
                workflow = action.get("workflow", "")
                output_info = action.get("output", {})
                parts.append(f"\nStep {i}: {action.get('name', 'Action')}")
                if workflow:
                    parts.append(f"  Instructions: {workflow}")
                if output_info:
                    parts.append(f"  Output: {output_info.get('path', 'N/A')}")
        
        parts.append("\n## AVAILABLE TOOLS:")
        parts.append("- read_file(path): Read file content")
        parts.append("- write_file(path, content): Write file")
        parts.append("- list_files(path): List directory contents")
        parts.append("- web_search(query): Search the web")
        parts.append("- run_python(code): Execute Python code (sandboxed; no subprocess)")
        parts.append(
            "- run_script(script, args): Run tools/blog-writer/*.py in this task directory "
            "(preferred for setup_brand / field_markup / generate_presentation / "
            "assemble_publish / publish_to_wp / validate_* / check_forbidden). "
            "Example: run_script(\"generate_presentation.py\", [\"--out-dir\", \".\"])"
        )
        
        parts.append("\n## IMPORTANT:")
        parts.append("- All file paths are relative to the task instance directory")
        parts.append(
            "- When workflow says `python3 ../../tools/blog-writer/X.py ...`, "
            "call run_script with script=X.py and the same CLI args"
        )
        parts.append("- After completing all tasks, respond with 'DONE'")
        parts.append("- If you need more information, ask for it")

        prompt = "\n".join(parts)
        # 将 Task Parameters 中的简单标量填入 workflow 占位符（如 {forbidden_whitelist_csv}）
        if params:
            for key, value in params.items():
                if isinstance(value, (str, int, float)) and not isinstance(value, bool):
                    prompt = prompt.replace("{" + str(key) + "}", str(value))
                elif isinstance(value, list) and all(isinstance(x, str) for x in value):
                    prompt = prompt.replace("{" + str(key) + "}", ",".join(value))
        return prompt

    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        # 每次 execute 强制新会话（隔离评审不复用任何历史）
        self.messages = []
        self.iteration_count = 0

        self.log(f"🚀 Starting execution of node: {self.node.get('name')}")
        self.log(f"   Node ID: {self.node.get('id')}")
        self.log(f"   Instance dir: {self.instance_dir}")
        if self.isolated_session:
            self.log("   🔒 Isolated review session enabled")
        
        system_prompt = self._build_system_prompt(params)
        self.messages.append(Message(role="system", content=system_prompt))
        
        initial_context = self._build_initial_context(params)
        self.messages.append(Message(role="user", content=initial_context))
        
        tools_schema = self.tools.get_tools_schema()
        
        while self.iteration_count < self.max_iterations:
            self.iteration_count += 1
            self.log(f"\n--- Iteration {self.iteration_count}/{self.max_iterations} ---")
            
            try:
                response = await self.llm.chat(
                    messages=self.messages,
                    tools=tools_schema
                )
            except Exception as e:
                self.log(f"❌ LLM call failed: {e}")
                return {
                    "status": "error",
                    "error": str(e),
                    "iteration": self.iteration_count
                }
            
            assistant_msg = Message(
                role="assistant",
                content=response.content,
                tool_calls=response.tool_calls
            )
            self.messages.append(assistant_msg)
            
            if response.content:
                self.log(f"   Assistant: {response.content[:200]}...")
            
            if not response.tool_calls:
                self.log("   ✅ No more tool calls, execution complete")
                break
            
            for tool_call in response.tool_calls:
                self.log(f"   🔧 Calling tool: {tool_call.name}({json.dumps(tool_call.arguments)[:100]})")
                
                # 预处理：展开 LLM 可能包裹的 _raw 字段（DeepSeek function calling 特性）
                args = tool_call.arguments
                if isinstance(args, dict) and "_raw" in args:
                    raw_val = args["_raw"]
                    args = self._unwrap_raw_args(raw_val, tool_call.name)
                
                tool_result = await self.tools.execute(tool_call.name, args)
                
                self.log(f"   ✅ Tool result: {str(tool_result.get('result', tool_result.get('error', '')))[:100]}...")
                
                tool_msg = Message(
                    role="tool",
                    content=json.dumps(tool_result),
                    tool_call_id=tool_call.call_id
                )
                self.messages.append(tool_msg)
        else:
            self.log(f"⚠️ Maximum iterations ({self.max_iterations}) reached")
        
        self.log("\n📋 Running checks...")
        checks_passed = await self._run_checks()
        
        tool_history = self.tools.get_call_history()
        llm_stats = self.llm.get_stats()
        
        result = {
            "status": "success" if checks_passed else "partial",
            "node_id": self.node.get("id"),
            "node_name": self.node.get("name"),
            "iterations": self.iteration_count,
            "checks_passed": checks_passed,
            "checks_results": self.checks_results,
            "tool_calls": len(tool_history),
            "tool_history": tool_history,
            "token_usage": llm_stats,
            "outputs": self.outputs
        }
        
        self.log(f"\n✅ Node execution completed: {json.dumps({k: v for k, v in result.items() if k not in ['tool_history', 'outputs']})}")
        
        return result

    def _build_initial_context(self, params: Dict[str, Any]) -> str:
        parts = []
        parts.append("## Task Parameters")
        for key, value in params.items():
            parts.append(f"- {key}: {value}")
        
        files_info = self._list_available_files()
        if files_info:
            parts.append("\n## Available Files")
            parts.append(files_info)
        
        outputs_info = self.node.get("actions", [])
        if outputs_info:
            parts.append("\n## Expected Outputs")
            for action in outputs_info:
                output = action.get("output", {})
                if output:
                    parts.append(f"- {output.get('path', 'N/A')}: {output.get('name', '')}")
        
        return "\n".join(parts)

    def _list_available_files(self) -> str:
        """列出实例目录中的可用文件。
        
        普通节点：附带内容预览以减少工具调用。
        隔离会话：仅列文件名/大小，避免把写作产物预读进评审上下文。
        """
        lines = []
        if self.instance_dir.exists():
            files = list(self.instance_dir.iterdir())
            if files:
                for f in sorted(files):
                    if f.is_file():
                        try:
                            size = f.stat().st_size
                        except OSError:
                            size = 0
                        if self.isolated_session:
                            lines.append(f"  {f.name} ({size}B)")
                        else:
                            try:
                                content_preview = f.read_text(encoding='utf-8')[:200]
                                lines.append(f"  {f.name}: {content_preview}...")
                            except Exception:
                                lines.append(f"  {f.name} ({size}B)")
                    elif f.is_dir():
                        lines.append(f"  {f.name}/ (dir)")
        return "\n".join(lines)

    async def _evaluate_check(self, rule: str, target: str) -> bool:
        """实现 BaseExecutor 抽象方法，处理 file/step/LLM/exec 类型检查。"""
        target_type, target_path, exec_cmd = self.parse_check_target(target)

        if exec_cmd and target_type == "file":
            # 先确保文件存在，再跑 exec 断言（如 post_id>0）
            abs_path = self._safe_resolve_file(target_path)
            if abs_path is None or not abs_path.exists():
                self.log(f"      File not found for exec check: {target_path}")
                return False
            return await self._run_exec_check(exec_cmd)

        if target_type == "file" and target_path:
            return await self._check_file_rule(rule, target_path)
        elif target_type == "step":
            return await self._check_step_rule(rule)
        else:
            # 未知 target 默认失败（避免假通过）
            if target_type not in ("", "self", "llm"):
                self.log(f"      Unknown check target type: {target_type}")
                return False
            return await self._check_with_llm(rule, target)

    async def _check_file_rule(self, rule: str, filepath: str) -> bool:
        abs_path = self._safe_resolve_file(filepath)
        if abs_path is None or not abs_path.exists():
            self.log(f"      File not found or path rejected: {filepath}")
            return False
        
        with open(abs_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        if "H2 数量" in rule:
            # 支持两种 H2 格式：
            # 1. 标准 Markdown H2: ## 标题
            # 2. 结构文件中的格式: ### H2 N: 标题（semantic_type: xxx）
            h2s_standard = re.findall(r'^## ', content, re.MULTILINE)
            h2s_structured = re.findall(r'^### H2 \d+:', content, re.MULTILINE)
            # 如果存在结构化格式，优先用结构化格式计数（排除节标题干扰）
            if h2s_structured:
                count = len(h2s_structured)
            else:
                count = len(h2s_standard)
            min_count = 4
            if "≥" in rule:
                match = re.search(r'≥\s*(\d+)', rule)
                if match:
                    min_count = int(match.group(1))
            passed = count >= min_count
            self.log(f"      H2 count: {count}, required: {min_count}")
            return passed
        
        if "FAQ" in rule:
            has_faq = "FAQ" in content or "## FAQ" in content
            return has_faq
        
        if "References" in rule:
            has_refs = "## References" in content
            if has_refs and "至少 2 条" in rule:
                ref_section = content[content.find('## References'):] if '## References' in content else ''
                ref_links = re.findall(r'\[([^\]]+)\]\(([^)]+)\)', ref_section)
                self.log(f"      References count: {len(ref_links)}")
                return len(ref_links) >= 2
            return has_refs
        
        if "不为空" in rule or "非空" in rule:
            return len(content.strip()) > 100
        
        return True

    async def _check_step_rule(self, rule: str) -> bool:
        """检查前一步骤的输出"""
        if "不为空" in rule or "非空" in rule:
            if self.outputs:
                return all(v is not None and v != "" for v in self.outputs.values())
            # outputs 为空时回退检查节点定义的输出文件是否存在且非空
            # （LLM 可能用 write_file 工具直接写文件，未设置 outputs）
            actions = self.node.get("actions", [])
            for action in actions:
                output = action.get("output", {})
                path = output.get("path", "")
                if path:
                    abs_path = self._safe_resolve_file(path)
                    if abs_path and abs_path.exists() and abs_path.stat().st_size > 10:
                        return True
            return False
        return True

    async def _check_with_llm(self, rule: str, target: str) -> bool:
        try:
            check_messages = [
                Message(role="system", content=f"Evaluate this check rule and return ONLY 'PASS' or 'FAIL':\nRule: {rule}\nTarget: {target}"),
                Message(role="user", content="Is this check passing? Answer with PASS or FAIL only.")
            ]
            
            response = await self.llm.chat(messages=check_messages)
            result = (response.content or "").strip().upper()
            return result == "PASS"
        except Exception as e:
            self.log(f"      LLM check failed: {e}, assuming FAIL")
            return False
