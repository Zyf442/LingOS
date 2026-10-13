"""消息接口（PRD 8 #6-8）：历史 / 发送（202+WS 推流）/ 取消。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from ...storage import repos

router = APIRouter(tags=["messages"])


class SendMessageBody(BaseModel):
    content: str = Field(min_length=1, max_length=32000)
    attachments: list[str] | None = Field(default=None, max_length=5)

    @field_validator("content")
    @classmethod
    def _nonblank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("内容不能为空白")
        return v


@router.get("/conversations/{cid}/messages")
async def list_messages(request: Request, cid: str, page: int = 1, page_size: int = 50) -> dict:
    ctx = request.app.state.ctx
    if repos.get_conversation(ctx.db.conn, cid) is None:
        raise HTTPException(status_code=404, detail="not_found")
    return repos.list_messages(ctx.db.conn, cid, page=page, page_size=page_size)


@router.post("/conversations/{cid}/messages", status_code=202)
async def send_message(cid: str, body: SendMessageBody, request: Request) -> JSONResponse:
    ctx = request.app.state.ctx
    status = ctx.chat.status()
    if not status["has_key"]:
        return JSONResponse(
            status_code=400,
            content={
                "error": {"code": "no_api_key", "message": "尚未配置 API Key", "detail": None}
            },
        )
    message_id = ctx.chat.send_message(cid, body.content, body.attachments)
    if message_id is None:
        raise HTTPException(status_code=404, detail="not_found")
    return JSONResponse(
        status_code=202,
        content={"message_id": message_id, "status": "accepted"},
    )


@router.post("/conversations/{cid}/cancel", status_code=202)
async def cancel_generation(cid: str, request: Request) -> dict:
    ctx = request.app.state.ctx
    if repos.get_conversation(ctx.db.conn, cid) is None:
        raise HTTPException(status_code=404, detail="not_found")
    ok = ctx.chat.cancel(cid)
    return {"status": "cancelling" if ok else "idle"}
