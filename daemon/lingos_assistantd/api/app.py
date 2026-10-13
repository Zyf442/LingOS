"""FastAPI 应用工厂 + 中间件（PRD 8、10.1）。

- 全部接口要求 Bearer token（/healthz 除外）
- 请求体 > 1MB → 413
- 令牌桶限流：20 req/s，突发 40；WS 消息 ≤ 10/s
- 无 CORS（浏览器网页无法调用）
- 错误统一结构 {"error": {"code","message","detail"}}
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse

from .. import __version__
from ..events import EventBus
from ..service.chat_service import ChatService
from ..storage import repos
from ..storage.db import Database
from .routers import (
    audit,
    conversations,
    health,
    messages,
    settings as settings_router,
    tool_calls,
    ws,
)


class AppContext:
    """应用依赖容器（单机单实例，PRD 2.5）。"""

    def __init__(
        self,
        db: Database,
        chat: ChatService,
        bus: EventBus,
        keyring: Any,
        token: str,
    ):
        self.db = db
        self.chat = chat
        self.bus = bus
        self.keyring = keyring
        self.token = token

    def settings(self) -> dict[str, Any]:
        return repos.get_settings(self.db.conn)


class TokenBucket:
    def __init__(self, rate: float = 20.0, burst: float = 40.0):
        self.rate = rate
        self.burst = burst
        self._tokens = burst
        self._last = time.monotonic()
        self._lock = asyncio.Lock()

    async def take(self, n: float = 1.0) -> bool:
        async with self._lock:
            now = time.monotonic()
            self._tokens = min(self.burst, self._tokens + (now - self._last) * self.rate)
            self._last = now
            if self._tokens >= n:
                self._tokens -= n
                return True
            return False


def error_json(status: int, code: str, message: str, detail: Any = None) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "detail": detail}},
    )


def create_app(ctx: AppContext) -> FastAPI:
    app = FastAPI(title="lingos-assistantd", version=__version__, docs_url=None, redoc_url=None)
    bucket = TokenBucket(rate=20.0, burst=40.0)

    # ---------- 鉴权依赖 ----------
    from fastapi import Header, HTTPException

    async def require_token(
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> None:
        if not await bucket.take():
            raise HTTPException(status_code=429, detail="rate_limited")
        supplied = (
            authorization[7:] if authorization and authorization.startswith("Bearer ") else ""
        )
        if supplied != ctx.token:
            raise HTTPException(status_code=401, detail="unauthorized")

    app.state.ctx = ctx
    app.state.require_token = require_token

    # ---------- 请求体大小限制（1MB → 413） ----------
    @app.middleware("http")
    async def size_limit_and_errors(request: Request, call_next: Any):
        cl = request.headers.get("content-length")
        if cl and int(cl) > 1024 * 1024:
            return error_json(413, "payload_too_large", "请求体超过 1MB 上限")
        try:
            return await call_next(request)
        except Exception:  # noqa: BLE001 —— 统一 500 结构，堆栈不含 Authorization 头
            import logging

            logging.getLogger("lingos.api").exception("未处理异常 path=%s", request.url.path)
            return error_json(500, "internal_error", "服务内部错误")

    # ---------- 路由 ----------
    app.include_router(health.router, prefix="/api/v1")
    app.include_router(
        conversations.router, prefix="/api/v1", dependencies=[Depends(require_token)]
    )
    app.include_router(messages.router, prefix="/api/v1", dependencies=[Depends(require_token)])
    app.include_router(tool_calls.router, prefix="/api/v1", dependencies=[Depends(require_token)])
    app.include_router(
        settings_router.router, prefix="/api/v1", dependencies=[Depends(require_token)]
    )
    app.include_router(audit.router, prefix="/api/v1", dependencies=[Depends(require_token)])
    app.include_router(ws.router, prefix="/api/v1")

    return app
