"""审计日志接口（PRD 8 #16-17）：分页+筛选 / 导出 JSON。"""

from __future__ import annotations

import json

from fastapi import APIRouter, Request
from fastapi.responses import Response

from ...storage import repos

router = APIRouter(tags=["audit"])


@router.get("/audit-logs")
async def list_audit_logs(
    request: Request,
    page: int = 1,
    page_size: int = 50,
    action: str | None = None,
) -> dict:
    ctx = request.app.state.ctx
    return repos.list_audit(ctx.db.conn, page=page, page_size=min(page_size, 200), action=action)


@router.get("/audit-logs/export")
async def export_audit_logs(request: Request) -> Response:
    ctx = request.app.state.ctx
    items = repos.list_audit(ctx.db.conn, page=1, page_size=100000)["items"]
    payload = json.dumps(
        {"exported_at": repos.utc_now_iso(), "items": items}, ensure_ascii=False, indent=2
    )
    return Response(
        content=payload,
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="lingos-audit-logs.json"'},
    )
