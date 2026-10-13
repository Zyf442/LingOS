"""5 个工具的 OpenAI function-calling schema（PRD 5.4 M4、8.3）。"""

from __future__ import annotations

from typing import Any

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "shell",
            "description": "在用户桌面会话中执行一条 shell 命令。危险命令会被系统直接拒绝。执行前需用户确认。",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "要执行的完整命令"},
                    "timeout_sec": {"type": "integer", "minimum": 1, "maximum": 120, "default": 30},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "file_read",
            "description": "读取一个文本文件（≤256KB）。敏感路径会被拒绝。执行前需用户确认。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件的绝对路径"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "file_write",
            "description": "写入或覆盖一个文本文件，自动创建父目录，写前系统自动备份原文件。敏感路径会被拒绝。执行前需用户确认。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "目标文件的绝对路径"},
                    "content": {"type": "string", "description": "要写入的完整文本内容"},
                    "mode": {"type": "string", "enum": ["overwrite"], "default": "overwrite"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "file_delete",
            "description": "把文件或目录移入回收站（FreeDesktop Trash，永不真删）。敏感路径会被拒绝。执行前需用户确认。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "要删除的文件/目录的绝对路径"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "system_info",
            "description": "获取系统摘要（OS/内核/CPU/内存/磁盘）。只读操作，无需确认。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "gsettings_set",
            "description": "修改一个 GNOME 桌面设置项（仅限白名单：主题/深浅色/壁纸/鼠标等）。执行前需用户确认。",
            "parameters": {
                "type": "object",
                "properties": {
                    "schema": {
                        "type": "string",
                        "description": "gsettings schema，如 org.gnome.desktop.interface",
                    },
                    "key": {"type": "string", "description": "设置键名，如 color-scheme"},
                    "value": {"type": "string", "description": "新值（字符串形式）"},
                },
                "required": ["schema", "key", "value"],
            },
        },
    },
]

TOOL_NAMES = {t["function"]["name"] for t in TOOL_SCHEMAS}
