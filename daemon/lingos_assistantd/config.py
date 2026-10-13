"""pydantic-settings 配置（PRD 19：环境变量前缀 LINGOS_；生产不用 .env 走 dconf/keyring）。"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class DaemonSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LINGOS_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # 环境：dev|staging|prod
    env: Literal["dev", "staging", "prod"] = "dev"
    # 只允许 127.0.0.1，代码中硬校验（PRD 10.1）
    host: str = "127.0.0.1"
    port: int = 47831
    port_max: int = 47841
    # 为空则使用默认 XDG 路径
    db_path: str = ""
    log_level: str = "INFO"
    # 开发模式：不依赖 systemd user session / keyring（PRD 11.5）
    no_systemd: bool = False
    dev_keyring: Literal["file", ""] = ""
    # 仅开发调试用；生产 Key 一律存 gnome-keyring
    llm_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    llm_model: str = "qwen-plus"
    dev_api_key: str = ""

    @field_validator("host")
    @classmethod
    def _host_must_be_loopback(cls, v: str) -> str:
        if v not in ("127.0.0.1", "localhost"):
            raise ValueError("LINGOS_HOST 只允许 127.0.0.1/localhost（安全硬约束）")
        return "127.0.0.1"

    # ---------- XDG 路径（禁止硬编码 /home/xxx，PRD 11.5） ----------
    def data_dir(self) -> Path:
        p = Path(self.db_path).parent if self.db_path else _xdg_data_home() / "lingos"
        return p

    def db_file(self) -> Path:
        if self.db_path:
            return Path(self.db_path)
        return _xdg_data_home() / "lingos" / "assistant.db"

    def backups_dir(self) -> Path:
        return self.data_dir() / "backups"

    def runtime_dir(self) -> Path:
        import os

        xdg = os.environ.get("XDG_RUNTIME_DIR")
        if xdg:
            return Path(xdg) / "lingos"
        # 开发模式 fallback（无 systemd user session 的容器/Win/macOS）
        import tempfile

        return Path(tempfile.gettempdir()) / "lingos-runtime"

    def token_file(self) -> Path:
        return self.runtime_dir() / "assistant.token"

    def port_file(self) -> Path:
        return self.runtime_dir() / "port"


def _xdg_data_home() -> Path:
    import os

    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg)
    return Path.home() / ".local" / "share"
