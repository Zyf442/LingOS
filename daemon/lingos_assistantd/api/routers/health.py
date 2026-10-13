"""GET /healthz（无需鉴权，PRD 8 #1：版本/熔断器状态/是否已配 Key）。"""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz(request: Request) -> dict:
    ctx = request.app.state.ctx
    return ctx.chat.status()
