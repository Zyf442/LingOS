"""进程内事件总线 → WS /ws 广播（PRD 8.1 WS 事件）。

事件类型（type 字段区分）：
- message.delta      {message_id, content_chunk}
- message.done       {message_id, tokens}
- message.error      {message_id, code, message}
- tool_call.requested {tool_call_id, tool_name, arguments, risk, preview}
- tool_call.resolved {tool_call_id, decision, result_summary}
- status.changed     {circuit, has_key}
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

log = logging.getLogger("lingos.events")


class EventBus:
    def __init__(self) -> None:
        # queue -> 订阅时所在的事件循环（跨线程 publish 用 call_soon_threadsafe 唤醒）
        self._subscribers: dict[asyncio.Queue[dict[str, Any]], asyncio.AbstractEventLoop | None] = (
            {}
        )

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1000)
        try:
            loop: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        self._subscribers[q] = loop
        return q

    def unsubscribe(self, q: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.pop(q, None)

    def publish(self, event: dict[str, Any]) -> None:
        """线程安全广播；队列满则丢弃最旧事件（UI 以 REST 对账兜底，PRD 15）。"""
        try:
            current: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()
        except RuntimeError:
            current = None
        for q, loop in list(self._subscribers.items()):
            if loop is None or loop.is_closed() or loop is current:
                self._put(q, event)
            else:
                try:
                    loop.call_soon_threadsafe(self._put, q, event)
                except RuntimeError:  # loop 关闭竞态
                    self._subscribers.pop(q, None)

    @staticmethod
    def _put(q: asyncio.Queue[dict[str, Any]], event: dict[str, Any]) -> None:
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            try:
                q.get_nowait()
                q.put_nowait(event)
            except (asyncio.QueueEmpty, asyncio.QueueFull):
                pass

    # ---- 便捷构造 ----
    @staticmethod
    def delta(message_id: str, chunk: str) -> dict[str, Any]:
        return {"type": "message.delta", "message_id": message_id, "content_chunk": chunk}

    @staticmethod
    def message_done(message_id: str, tokens: int | None) -> dict[str, Any]:
        return {"type": "message.done", "message_id": message_id, "tokens": tokens}

    @staticmethod
    def message_error(message_id: str, code: str, message: str) -> dict[str, Any]:
        return {"type": "message.error", "message_id": message_id, "code": code, "message": message}

    @staticmethod
    def tool_requested(
        tool_call_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        risk: str,
        preview: str,
    ) -> dict[str, Any]:
        return {
            "type": "tool_call.requested",
            "tool_call_id": tool_call_id,
            "tool_name": tool_name,
            "arguments": arguments,
            "risk": risk,
            "preview": preview,
        }

    @staticmethod
    def tool_resolved(
        tool_call_id: str,
        decision: str,
        result_summary: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "type": "tool_call.resolved",
            "tool_call_id": tool_call_id,
            "decision": decision,
            "result_summary": result_summary,
        }

    @staticmethod
    def status_changed(circuit: str, has_key: bool) -> dict[str, Any]:
        return {"type": "status.changed", "circuit": circuit, "has_key": has_key}
