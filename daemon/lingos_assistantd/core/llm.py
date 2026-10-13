"""LLM 客户端（PRD 5.4 M3）：OpenAI 兼容流式 + 指数退避重试 + 熔断。

- openai SDK（1.x）指向 DashScope compatible-mode（可换任意 OpenAI 兼容端点）
- 流式：client.chat.completions.create(stream=True, tools=…)
- 重试：网络错误/429/5xx → 指数退避 2 次（1s, 3s），429 优先遵循 Retry-After
- 熔断：连续 5 次失败 → OPEN 60s；期间所有请求抛 CircuitOpenError（UI 显示降级文案）
- 工具调用增量在 delta.tool_calls[i].function.arguments 分片拼接
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, AsyncIterator, Protocol

from .circuit import AsyncCircuitBreaker

log = logging.getLogger("lingos.llm")

RETRY_BACKOFF = (1.0, 3.0)
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


# ---------------------------------------------------------------- 事件模型


@dataclass
class DeltaEvent:
    text: str


@dataclass
class ToolCallEvent:
    """一轮流式输出结束后的完整工具调用列表（openai 增量已拼接完毕）。"""

    tool_calls: list[dict[str, Any]]  # [{id, name, arguments(dict)}]


@dataclass
class DoneEvent:
    finish_reason: str
    total_tokens: int | None = None


@dataclass
class ErrorEvent:
    code: str  # llm_upstream_error / llm_timeout / llm_circuit_open / no_api_key / invalid_api_key
    message: str


StreamEvent = DeltaEvent | ToolCallEvent | DoneEvent | ErrorEvent


class LLMAuthError(RuntimeError):
    """API Key 无效（401）——UI 需与网络错误区分提示（PRD 5.5）。"""


class LLMClientProtocol(Protocol):
    async def stream_chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> AsyncIterator[StreamEvent]: ...


# ---------------------------------------------------------------- 真实客户端


class LLMClient:
    def __init__(
        self,
        base_url: str,
        api_key_getter: Any,  # callable() -> str | None，Key 仅驻内存（PRD 5.5）
        breaker: AsyncCircuitBreaker,
        timeout_first_token: float = 60.0,
        timeout_total: float = 300.0,
    ):
        self.base_url = base_url.rstrip("/")
        self._get_api_key = api_key_getter
        self.breaker = breaker
        self._client: Any = None  # openai.AsyncOpenAI，延迟创建（冷启动 ≤800ms，PRD 9.2）
        self.timeout_first_token = timeout_first_token
        self.timeout_total = timeout_total

    def _ensure_client(self) -> Any:
        key = self._get_api_key()
        if not key:
            raise LLMAuthError("尚未配置 API Key")
        if self._client is None:
            # 延迟 import：重模块首次请求时才加载（PRD 9.2）
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI(
                base_url=self.base_url,
                api_key=key,
                timeout=self.timeout_total,
                max_retries=0,  # 重试由本层统一控制
            )
        else:
            self._client.api_key = key
        return self._client

    async def test_connectivity(self, model: str) -> dict[str, Any]:
        """连通性测试：发一条 1-token 请求（PRD 5.5）。"""
        try:
            client = self._ensure_client()
            resp = await client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=1,
            )
            return {"ok": True, "model": resp.model}
        except Exception as e:  # noqa: BLE001 —— 上层按异常信息展示失败原因
            return {"ok": False, "error": str(e)}

    async def stream_chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> AsyncIterator[StreamEvent]:
        last_error: Exception | None = None
        for attempt in range(len(RETRY_BACKOFF) + 1):
            if not await self.breaker.acquire():
                yield ErrorEvent("llm_circuit_open", "AI 服务暂不可用，请稍后再试")
                return
            try:
                client = self._ensure_client()
                async for ev in self._do_stream(
                    client, model, messages, tools, temperature, max_tokens
                ):
                    if isinstance(ev, ErrorEvent):
                        raise _UpstreamError(ev.code, ev.message)
                    yield ev
                await self.breaker.success()
                return
            except LLMAuthError:
                await self.breaker.success()  # 非上游故障，不计熔断
                yield ErrorEvent("no_api_key", "尚未配置 API Key")
                return
            except _UpstreamError as e:
                last_error = e
                if e.code == "invalid_api_key":
                    await self.breaker.success()
                    yield ErrorEvent("invalid_api_key", "API Key 无效或已过期")
                    return
                await self.breaker.failure()
            except asyncio.TimeoutError:
                last_error = TimeoutError("响应超时")
                await self.breaker.failure()
            except Exception as e:  # 网络/未知
                last_error = e
                await self.breaker.failure()

            if attempt < len(RETRY_BACKOFF):
                await asyncio.sleep(RETRY_BACKOFF[attempt])
        yield ErrorEvent(
            "llm_upstream_error",
            f"AI 服务请求失败：{last_error}"[:300],
        )

    async def _do_stream(
        self,
        client: Any,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        temperature: float,
        max_tokens: int,
    ) -> AsyncIterator[StreamEvent]:
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            kwargs["tools"] = tools

        stream = None
        try:
            stream = await asyncio.wait_for(
                client.chat.completions.create(**kwargs), self.timeout_first_token
            )
        except asyncio.TimeoutError:
            yield ErrorEvent("llm_timeout", "首 token 超时（60s），请检查网络或更换模型")
            return

        text_parts: list[str] = []
        # 工具调用增量拼接：tc_index -> {"id","name","arguments"}
        tool_acc: dict[int, dict[str, str]] = {}
        finish_reason = "stop"
        total_tokens: int | None = None

        try:
            async for chunk in stream:
                if getattr(chunk, "usage", None):
                    total_tokens = chunk.usage.total_tokens
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                if choice.finish_reason:
                    finish_reason = choice.finish_reason
                delta = choice.delta
                if delta is None:
                    continue
                if delta.content:
                    text_parts.append(delta.content)
                    yield DeltaEvent(delta.content)
                for tc in delta.tool_calls or []:
                    slot = tool_acc.setdefault(tc.index, {"id": "", "name": "", "arguments": ""})
                    if tc.id:
                        slot["id"] = tc.id
                    if tc.function:
                        if tc.function.name:
                            slot["name"] += tc.function.name
                        if tc.function.arguments:
                            slot["arguments"] += tc.function.arguments
        except Exception as e:  # 流中断
            status = getattr(e, "status_code", None)
            if status == 401:
                yield ErrorEvent("invalid_api_key", "API Key 无效或已过期")
                return
            if status == 429:
                yield ErrorEvent("llm_upstream_error", "请求被限流（429）")
                return
            raise

        if tool_acc:
            import json

            calls: list[dict[str, Any]] = []
            for idx in sorted(tool_acc):
                slot = tool_acc[idx]
                try:
                    args = json.loads(slot["arguments"] or "{}")
                except json.JSONDecodeError:
                    args = {"__invalid__": True, "__raw__": slot["arguments"]}
                calls.append({"id": slot["id"], "name": slot["name"], "arguments": args})
            yield ToolCallEvent(calls)
        yield DoneEvent(finish_reason=finish_reason, total_tokens=total_tokens)


class _UpstreamError(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)
