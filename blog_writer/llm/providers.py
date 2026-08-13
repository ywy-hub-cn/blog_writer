import json
import logging
import asyncio
import httpx
from typing import List, Dict, Any, Optional, AsyncIterator

from .base import BaseLLMProvider, LLMResponse, ToolCall, Message

logger = logging.getLogger(__name__)


class LLMProviderError(RuntimeError):
    """LLM 调用失败（含 HTTP 状态与响应摘要）。"""

    def __init__(self, message: str, status_code: Optional[int] = None, body: str = ""):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class OpenAICompatibleProvider(BaseLLMProvider):
    """OpenAI 兼容协议客户端（DeepSeek / 通义 / 本地 vLLM 等）。"""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.base_url = self._normalize_base_url(
            config.get("base_url", "https://api.deepseek.com/v1")
        )
        self.api_key = (config.get("api_key") or "").strip()
        self.model = config.get("model", "deepseek-v4-flash")
        self.temperature = config.get("temperature", 0.7)
        self.max_tokens = config.get("max_tokens", 8192)
        self.timeout = config.get("timeout", 120)
        self.retry_config = config.get("retry", {"max_retries": 3, "retry_delay": 2})
        # DeepSeek V4 默认开启 thinking，会额外产生按 output 计费的推理 token；
        # 博客多轮 Agent + 工具调用场景默认关闭，性价比更高。
        # 配置 thinking: true / "enabled" 可打开。
        thinking_cfg = config.get("thinking", False)
        if isinstance(thinking_cfg, dict):
            self.thinking_enabled = str(thinking_cfg.get("type", "disabled")).lower() == "enabled"
        else:
            self.thinking_enabled = bool(thinking_cfg) in (True,) or str(thinking_cfg).lower() in (
                "1",
                "true",
                "enabled",
                "on",
            )

    @staticmethod
    def _normalize_base_url(url: str) -> str:
        """去掉末尾斜杠，避免 //chat/completions。"""
        return (url or "https://api.deepseek.com/v1").strip().rstrip("/")

    def _ensure_api_key(self) -> None:
        if not self.api_key:
            raise LLMProviderError(
                "LLM API Key 未配置。请设置环境变量 LLM_API_KEY，"
                "或在 config.json / 管理后台填写 llm.models.default.api_key"
            )

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _chat_url(self) -> str:
        return f"{self.base_url}/chat/completions"

    async def chat(
        self,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None
    ) -> LLMResponse:
        self._ensure_api_key()
        api_messages = self._convert_messages(messages)

        payload = {
            "model": self.model,
            "messages": api_messages,
            "temperature": self.temperature if temperature is None else temperature,
            "max_tokens": self.max_tokens if max_tokens is None else max_tokens,
            # OpenAI 兼容扩展字段：关闭默认 thinking，控制博客流水线成本
            "thinking": {"type": "enabled" if self.thinking_enabled else "disabled"},
        }

        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        response_data = await self._request_with_retry(payload)
        return self._parse_response(response_data)

    async def chat_stream(
        self,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None
    ) -> AsyncIterator[str]:
        self._ensure_api_key()
        api_messages = self._convert_messages(messages)

        payload = {
            "model": self.model,
            "messages": api_messages,
            "temperature": self.temperature if temperature is None else temperature,
            "max_tokens": self.max_tokens if max_tokens is None else max_tokens,
            "stream": True,
            "thinking": {"type": "enabled" if self.thinking_enabled else "disabled"},
        }

        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        async for chunk in self._stream_request(payload):
            yield chunk

    def _convert_messages(self, messages: List[Message]) -> List[Dict[str, Any]]:
        api_messages = []
        for msg in messages:
            if msg.role == "tool":
                api_messages.append({
                    "role": "tool",
                    "content": msg.content or "",
                    "tool_call_id": msg.tool_call_id or ""
                })
            elif msg.tool_calls:
                api_msg = {
                    "role": msg.role,
                    "content": msg.content or "",
                    "tool_calls": [
                        {
                            "id": tc.call_id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.arguments)
                            }
                        }
                        for tc in msg.tool_calls
                    ]
                }
                api_messages.append(api_msg)
            else:
                api_messages.append({
                    "role": msg.role,
                    "content": msg.content or ""
                })
        return api_messages

    def _format_http_error(self, response: httpx.Response) -> LLMProviderError:
        status = response.status_code
        body = (response.text or "")[:500]
        if status in (401, 403):
            msg = (
                f"LLM 认证失败 (HTTP {status})：请检查 LLM_API_KEY 是否有效。"
                f" base_url={self.base_url} model={self.model}"
            )
        elif status == 402:
            msg = (
                "LLM 账户余额不足 (HTTP 402)：请前往 DeepSeek 控制台充值后再试。"
                f" model={self.model}"
            )
        elif status == 404:
            msg = (
                f"LLM 接口不存在 (HTTP 404)：请检查 base_url 是否正确 "
                f"(当前 {self.base_url}/chat/completions)"
            )
        elif status == 429:
            msg = f"LLM 触发限流 (HTTP 429)：{body or '请稍后重试'}"
        else:
            msg = f"LLM 请求失败 (HTTP {status}): {body or response.reason_phrase}"
        return LLMProviderError(msg, status_code=status, body=body)

    async def _request_with_retry(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        max_retries = self.retry_config.get("max_retries", 3)
        retry_delay = self.retry_config.get("retry_delay", 2)

        last_error: Optional[BaseException] = None
        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(
                        self._chat_url(),
                        headers=self._headers(),
                        json=payload,
                    )
                    if response.status_code >= 400:
                        err = self._format_http_error(response)
                        # 客户端/鉴权/余额类错误不重试
                        if response.status_code in (400, 401, 402, 403, 404):
                            raise err
                        # 429 / 5xx 可重试
                        if response.status_code == 429 or response.status_code >= 500:
                            last_error = err
                            wait_time = retry_delay * (2 ** attempt)
                            logger.warning(
                                "LLM HTTP %s, retrying in %ss... (attempt %s/%s)",
                                response.status_code,
                                wait_time,
                                attempt + 1,
                                max_retries,
                            )
                            await asyncio.sleep(wait_time)
                            continue
                        raise err

                    data = response.json()

                    self.total_calls += 1
                    if "usage" in data:
                        usage = data["usage"]
                        self.total_tokens_used += usage.get("total_tokens", 0)
                        self.total_prompt_tokens += usage.get("prompt_tokens", 0)
                        self.total_completion_tokens += usage.get("completion_tokens", 0)

                    return data
            except LLMProviderError:
                raise
            except httpx.HTTPStatusError as e:
                last_error = e
                status = e.response.status_code if e.response is not None else 0
                if status in (400, 401, 402, 403, 404):
                    raise self._format_http_error(e.response) from e
                if status == 429 or status >= 500:
                    wait_time = retry_delay * (2 ** attempt)
                    logger.warning("HTTP %s, waiting %ss...", status, wait_time)
                    await asyncio.sleep(wait_time)
                else:
                    raise
            except Exception as e:
                last_error = e
                if attempt < max_retries - 1:
                    wait_time = retry_delay * (2 ** attempt)
                    logger.warning(
                        "Request failed (%s), retrying in %ss...",
                        type(e).__name__,
                        wait_time,
                    )
                    await asyncio.sleep(wait_time)
                else:
                    raise

        if last_error is not None:
            raise last_error
        raise LLMProviderError("LLM 请求失败：未知错误")

    async def _stream_request(self, payload: Dict[str, Any]) -> AsyncIterator[str]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream(
                "POST",
                self._chat_url(),
                headers=self._headers(),
                json=payload,
            ) as response:
                if response.status_code >= 400:
                    # 消费响应体以便错误信息可读
                    await response.aread()
                    raise self._format_http_error(response)

                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str == "[DONE]":
                            break
                        try:
                            data = json.loads(data_str)
                            if "choices" in data and len(data["choices"]) > 0:
                                delta = data["choices"][0].get("delta", {})
                                content = delta.get("content", "")
                                if content:
                                    yield content
                        except json.JSONDecodeError:
                            continue

    def _parse_response(self, data: Dict[str, Any]) -> LLMResponse:
        choices = data.get("choices", [])
        if not choices:
            return LLMResponse(content="", usage=data.get("usage", {}))

        choice = choices[0]
        message = choice.get("message", {})
        content = message.get("content", "")
        finish_reason = choice.get("finish_reason", "stop")

        tool_calls = []
        if "tool_calls" in message:
            for tc in message["tool_calls"]:
                try:
                    arguments = tc["function"]["arguments"]
                    if isinstance(arguments, str):
                        try:
                            parsed_arguments = json.loads(arguments)
                        except json.JSONDecodeError:
                            parsed_arguments = {"_raw": arguments}
                    else:
                        parsed_arguments = arguments

                    tool_calls.append(ToolCall(
                        name=tc["function"]["name"],
                        arguments=parsed_arguments,
                        call_id=tc.get("id", "")
                    ))
                except (KeyError, TypeError) as e:
                    logger.warning("Skipping invalid tool_call: %s", e)
                    continue

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            usage=data.get("usage", {}),
            finish_reason=finish_reason
        )
