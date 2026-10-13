"""工具确认接口（PRD 8 #9-10）：pending 列表 / 提交决策。"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ...executor.guard import classify_risk

router = APIRouter(tags=["tool-calls"])


class DecisionBody(BaseModel):
    decision: str = Field(pattern="^(allow|deny|allow_batch)$")
    remember_scope: str | None = None  # allow_batch 时建议提供，格式 tool:路径前缀


@router.get("/tool-calls/pending")
async def pending_tool_calls(request: Request) -> dict:
    ctx = request.app.state.ctx
    p = ctx.chat.pending
    if p is None:
        return {"items": []}
    return {
        "items": [
            {
                "tool_call_id": p.tool_call_id,
                "tool_name": p.tool_name,
                "arguments": p.arguments,
                "risk": classify_risk(str(p.arguments.get("command", ""))),
            }
        ]
    }


@router.post("/tool-calls/{tcid}/decision", status_code=202)
async def submit_decision(tcid: str, body: DecisionBody, request: Request) -> JSONResponse:
    ctx = request.app.state.ctx
    ok = ctx.chat.decide(tcid, body.decision, body.remember_scope or "")
    if not ok:
        return JSONResponse(
            status_code=423,
            content={
                "error": {"code": "tool_pending", "message": "该确认不存在或已处理", "detail": None}
            },
        )
    return JSONResponse(status_code=202, content={"status": "accepted"})
