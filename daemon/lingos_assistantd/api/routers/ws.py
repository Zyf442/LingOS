"""WS /ws —— 事件流（PRD 8 #18、8.1）。

- 鉴权：浏览器 WS 无法带 Header，支持 ?token= 查询参数（也可 Header）
- 事件类型见 events.py
- WS 客户端消息 ≤ 10/s（防 UI Bug 风暴，PRD 9.3）；客户端消息仅支持 ping
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter(tags=["ws"])

MAX_WS_IN_RATE = 10.0  # 条/秒


@router.websocket("/ws")
async def ws_events(websocket: WebSocket) -> None:
    token = websocket.query_params.get("token", "")
    ctx = websocket.app.state.ctx
    if token != ctx.token:
        await websocket.close(code=4401, reason="unauthorized")
        return
    await websocket.accept()

    queue = ctx.bus.subscribe()
    last_in = asyncio.get_event_loop().time()
    in_count = 0

    async def pump_out():
        while True:
            event = await queue.get()
            await websocket.send_json(event)

    async def pump_in():
        nonlocal in_count, last_in
        while True:
            msg = await websocket.receive_text()
            now = asyncio.get_event_loop().time()
            if now - last_in > 1.0:
                last_in, in_count = now, 0
            in_count += 1
            if in_count > MAX_WS_IN_RATE:
                await websocket.close(code=4429, reason="rate_limited")
                return
            if msg == "ping":
                await websocket.send_json({"type": "pong"})

    out_task = asyncio.create_task(pump_out())
    in_task = asyncio.create_task(pump_in())
    try:
        done, _ = await asyncio.wait({out_task, in_task}, return_when=asyncio.FIRST_EXCEPTION)
        for t in done:
            t.exception()  # 吞掉正常的连接关闭异常
    except WebSocketDisconnect:
        pass
    finally:
        out_task.cancel()
        in_task.cancel()
        ctx.bus.unsubscribe(queue)
        try:
            await websocket.close()
        except Exception:  # noqa: BLE001
            pass
