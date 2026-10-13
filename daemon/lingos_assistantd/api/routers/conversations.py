"""会话接口（PRD 8 #2-5）：列表 / 新建（幂等）/ 重命名 / 软删除。"""

from __future__ import annotations


from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from ...storage import repos

router = APIRouter(tags=["conversations"])

ALLOWED_MODELS = {"qwen-plus", "qwen-max", "qwen-turbo", "gpt-4o-mini"}


class CreateConversationBody(BaseModel):
    title: str | None = Field(default=None, max_length=100)
    model: str | None = Field(default=None, max_length=64)

    @field_validator("model")
    @classmethod
    def _model_whitelist(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if v not in ALLOWED_MODELS and len(v) > 64:
            raise ValueError("model 不在白名单且超过 64 字符")
        return v


class RenameBody(BaseModel):
    title: str = Field(min_length=1, max_length=100)


@router.get("/conversations")
async def list_conversations(
    request: Request, page: int = 1, page_size: int = 50, q: str | None = None
) -> dict:
    if page_size < 1 or page_size > 200:
        raise HTTPException(status_code=400, detail="invalid_argument")
    ctx = request.app.state.ctx
    return repos.list_conversations(ctx.db.conn, page=page, page_size=page_size, q=q)


@router.post("/conversations", status_code=201)
async def create_conversation(
    request: Request,
    body: CreateConversationBody | None = None,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict:
    ctx = request.app.state.ctx
    body = body or CreateConversationBody()
    conv = ctx.chat.create_conversation(body.title, body.model, idempotency_key)
    return conv


@router.patch("/conversations/{cid}")
async def rename_conversation(cid: str, body: RenameBody, request: Request) -> dict:
    ctx = request.app.state.ctx
    if not repos.rename_conversation(ctx.db.conn, cid, body.title):
        raise HTTPException(status_code=404, detail="not_found")
    return repos.get_conversation(ctx.db.conn, cid)  # type: ignore[return-value]


@router.delete("/conversations/{cid}", status_code=204, response_model=None)
async def delete_conversation(cid: str, request: Request) -> None:
    ctx = request.app.state.ctx
    if not repos.soft_delete_conversation(ctx.db.conn, cid):
        raise HTTPException(status_code=404, detail="not_found")
    repos.add_audit(ctx.db.conn, "conversation_deleted", actor="user", detail={"id": cid})
