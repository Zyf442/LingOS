"""设置与 API Key 接口（PRD 8 #11-15）。

- GET /settings：Key 永不返回，仅 has_key: bool
- PUT /settings：部分字段更新（model/temperature/max_tokens/context_window/tools_enabled/theme）
- POST /settings/api-key：写入 keyring
- POST /settings/api-key/test：连通性测试（1-token 请求，超时 10s）
- DELETE /settings/api-key：删除
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ...storage import repos

router = APIRouter(tags=["settings"])

UPDATABLE = {
    "model",
    "temperature",
    "max_tokens",
    "context_window",
    "tools_enabled",
    "theme",
    "base_url",
    "provider",
}


def _settings_view(db) -> dict:
    s = repos.get_settings(db.conn)
    return {k: v for k, v in s.items() if k != "id"}


@router.get("/settings")
async def get_settings(request: Request) -> dict:
    ctx = request.app.state.ctx
    view = _settings_view(ctx.db)
    view["has_key"] = bool(ctx.keyring.get_api_key())
    return view


class UpdateSettingsBody(BaseModel):
    model_config = {"extra": "forbid"}
    model: str | None = Field(default=None, max_length=64)
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, ge=256, le=32768)
    context_window: int | None = Field(default=None, ge=4000, le=200000)
    tools_enabled: bool | None = None
    theme: str | None = Field(default=None, pattern="^(light|dark|system)$")
    base_url: str | None = Field(default=None, max_length=512)
    provider: str | None = Field(default=None, max_length=32)


@router.put("/settings")
async def update_settings(body: UpdateSettingsBody, request: Request) -> dict:
    ctx = request.app.state.ctx
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    unknown = set(patch) - UPDATABLE
    if unknown:
        raise HTTPException(status_code=400, detail=f"invalid_argument: {sorted(unknown)}")
    if not patch:
        raise HTTPException(status_code=400, detail="invalid_argument: 空更新")
    s = repos.update_settings(ctx.db.conn, patch)
    repos.add_audit(ctx.db.conn, "settings_changed", actor="user", detail=patch)
    view = {k: v for k, v in s.items() if k != "id"}
    view["has_key"] = bool(ctx.keyring.get_api_key())
    ctx.bus.publish(ctx.bus.status_changed(ctx.chat.breaker.state.value, view["has_key"]))
    return view


class ApiKeyBody(BaseModel):
    provider: str = Field(default="dashscope", max_length=32)
    api_key: str = Field(min_length=8, max_length=256)


@router.post("/settings/api-key", status_code=204, response_model=None)
async def write_api_key(body: ApiKeyBody, request: Request) -> None:
    ctx = request.app.state.ctx
    had_key = ctx.keyring.has_api_key()
    ctx.keyring.set_api_key(body.api_key, body.provider)
    repos.add_audit(
        ctx.db.conn,
        "key_written",
        actor="user",
        detail={"provider": body.provider, "overwritten": had_key},
    )


@router.post("/settings/api-key/test")
async def test_api_key(request: Request) -> dict:
    ctx = request.app.state.ctx
    if not ctx.keyring.has_api_key():
        return {"ok": False, "error": "尚未配置 API Key"}
    s = repos.get_settings(ctx.db.conn)
    llm = ctx.chat.get_llm()
    import asyncio

    try:
        result = await asyncio.wait_for(llm.test_connectivity(s["model"]), timeout=10.0)
    except asyncio.TimeoutError:
        return {"ok": False, "error": "测试请求超时（10s）"}
    if not result.get("ok") and "401" in str(result.get("error", "")):
        result["error"] = "API Key 无效或已过期"
    return result


@router.delete("/settings/api-key", status_code=204, response_model=None)
async def delete_api_key(request: Request) -> None:
    ctx = request.app.state.ctx
    if not ctx.keyring.has_api_key():
        raise HTTPException(status_code=404, detail="not_found")
    ctx.keyring.delete_api_key()
    repos.add_audit(ctx.db.conn, "key_deleted", actor="user")
    ctx.bus.publish(ctx.bus.status_changed(ctx.chat.breaker.state.value, False))
