"""keyring 服务（PRD 5.5、10.1、11.5）。

- 生产：gnome-keyring（libsecret，schema com.lingos.assistant，属性 provider）
- 开发：文件后端 fallback（LINGOS_DEV_KEYRING=file，仅 dev 环境允许，打 WARN 日志）
- Key 仅驻内存；任何日志/错误信息中不得出现 Key 明文（CI secret-scan 兜底）
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Protocol

log = logging.getLogger("lingos.keyring")

SCHEMA = "com.lingos.assistant"
ATTRIBUTE = {"provider": "dashscope"}


class KeyringError(RuntimeError):
    pass


class KeyringService(Protocol):
    def get_api_key(self) -> str | None: ...
    def set_api_key(self, key: str, provider: str = "dashscope") -> None: ...
    def delete_api_key(self) -> bool: ...
    def has_api_key(self) -> bool: ...


class SecretServiceKeyring:
    """libsecret 后端（生产）。"""

    def __init__(self) -> None:
        import secretstorage  # 系统 python3-secretstorage（deb Depends）

        self._bus = None
        self._secretstorage = secretstorage
        self._coll = None

    def _collection(self):
        if self._coll is None:
            bus = self._secretstorage.dbus_init()
            coll = self._secretstorage.get_default_collection(bus)
            if coll.is_locked():
                coll.unlock()
            self._coll = coll
        return self._coll

    def get_api_key(self) -> str | None:
        items = list(self._collection().search_items(ATTRIBUTE))
        for item in items:
            if item.is_locked():
                item.unlock()
            return item.get_secret().decode("utf-8")
        return None

    def set_api_key(self, key: str, provider: str = "dashscope") -> None:
        attrs = {"provider": provider}
        for item in list(self._collection().search_items(attrs)):
            item.delete()
        label = f"LingOS Assistant API Key ({provider})"
        self._collection().create_item(label, attrs, key.encode("utf-8"), replace=True)

    def delete_api_key(self) -> bool:
        attrs = {"provider": "dashscope"}
        deleted = False
        for item in list(self._collection().search_items(attrs)):
            item.delete()
            deleted = True
        return deleted

    def has_api_key(self) -> bool:
        return self.get_api_key() is not None


class FileKeyring:
    """开发模式文件后端（0600，禁止用于生产）。"""

    def __init__(self, path: Path | None = None):
        self.path = path or (
            Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
            / "lingos"
            / "dev-api-key"
        )
        log.warning("使用开发模式文件 keyring（仅限 dev 环境，禁止生产使用）")

    def get_api_key(self) -> str | None:
        try:
            val = self.path.read_text(encoding="utf-8").strip()
            return val or None
        except OSError:
            return None

    def set_api_key(self, key: str, provider: str = "dashscope") -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(key, encoding="utf-8")
        os.chmod(self.path, 0o600)

    def delete_api_key(self) -> bool:
        if self.path.exists():
            self.path.unlink()
            return True
        return False

    def has_api_key(self) -> bool:
        return self.get_api_key() is not None


class EnvKeyring:
    """测试用内存后端。"""

    def __init__(self, key: str | None = None):
        self._key = key

    def get_api_key(self) -> str | None:
        return self._key

    def set_api_key(self, key: str, provider: str = "dashscope") -> None:
        self._key = key

    def delete_api_key(self) -> bool:
        had = self._key is not None
        self._key = None
        return had

    def has_api_key(self) -> bool:
        return self._key is not None


def build_keyring(env: str, dev_keyring: str, dev_api_key: str = "") -> KeyringService:
    """工厂：生产强制 libsecret；dev 可选 file 后端。"""
    if env == "dev" and dev_keyring == "file":
        kr: KeyringService = FileKeyring()
        if dev_api_key:
            kr.set_api_key(dev_api_key)
        return kr
    try:
        return SecretServiceKeyring()
    except Exception as e:  # noqa: BLE001 —— 无 gnome-keyring 环境
        if env == "dev":
            log.warning("libsecret 不可用（%s），dev 环境回退文件后端", e)
            kr = FileKeyring()
            if dev_api_key:
                kr.set_api_key(dev_api_key)
            return kr
        raise KeyringError(f"gnome-keyring 不可用: {e}") from e
