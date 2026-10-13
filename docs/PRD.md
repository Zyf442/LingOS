# LingOS（灵犀 OS）— 基于 Ubuntu 24.04 LTS 的 AI 原生 Linux 定制发行版
# AI 编程工具（Trae）开发规范文档 v1.0

**文档版本**: v1.0
**创建日期**: 2026-10-13
**项目代号**: LingOS
**状态**: 已确认关键决策（项目形态：基于 Linux 的定制发行版；AI 接入：云端大模型 API），可直接进入开发
**开发工具**: Trae（AI IDE）
**PRD Generator 版本**: v4.0（按操作系统项目形态适配）

> **本文档是 Trae 开发的唯一真相源。** 任何未在此文档中定义的依赖、接口、行为，开发前必须先补充到本文档再实现。
> 项目根目录下的 `TRAE.md` 是 Trae 的项目入口文件，包含开发规范、关键命令与禁止事项。

---

## 1. 项目概述与目标

### 1.1 项目背景（为什么做）

当前主流操作系统（Windows/macOS/传统 Linux 发行版）中，AI 助手都是"外挂应用"——用户需要自己打开浏览器或某个 App 去用 AI，AI 与系统（文件、终端、设置、应用）之间没有原生打通。

LingOS 的目标是做一个 **AI 原生的 Linux 发行版**：

- 底座基于 **Ubuntu 24.04 LTS**（不自研内核，复用 Linux 成熟生态：apt 包管理、systemd、驱动体系）；
- 桌面环境基于 **GNOME 46**，做深度定制（主题、扩展、默认应用集），形成类似"Linux 生态"的完整可用性；
- **系统级 AI 助手**作为一等公民：一个常驻系统守护进程 + 全局快捷键唤起的桌面 UI，通过 OpenAI 兼容 API（默认通义千问 DashScope）调用云端大模型，能对话、能执行系统任务（操作文件、运行终端命令、修改系统设置），所有危险操作需用户确认；
- 提供 **自有 apt 软件仓库** 与 **可安装的 ISO 镜像**，用户可像装 Ubuntu 一样装 LingOS，也可以只装 `lingos-assistant` 软件包到任意 Ubuntu 24.04 上。

### 1.2 V1 核心目标

**一句话定位**：一个基于 Ubuntu 24.04 LTS + GNOME 46、内置可通过全局快捷键唤起并能安全执行系统任务的云端 AI 助手的可安装 Linux 发行版。

**量化指标（V1 验收线）**：

| 指标 | 目标值 |
|------|--------|
| ISO 可在 UEFI/BIOS 虚拟机（QEMU/VirtualBox）中完成安装并进入桌面 | 100% 通过 |
| 全局快捷键（Super+L）唤起 AI 助手面板 | 冷启动到可输入 ≤ 1.5s |
| AI 对话首 token 延迟（网络正常、DashScope qwen-plus） | P95 ≤ 3s |
| AI 助手工具调用（列目录/读文件/执行确认后的命令） | 成功率 ≥ 95%，危险命令 100% 弹确认 |
| 断网 / API Key 无效 / 云端超时 | UI 必须给出明确降级提示，不得白屏或崩溃 |
| `lingos-assistant` deb 包可独立安装到原生 Ubuntu 24.04 | 安装后 5 分钟内可完成首次配置并对话 |
| 自有 apt 仓库 `apt install lingos-assistant` 可用 | 通过 |

### 1.3 目标用户（角色表）

| 角色 | 标识 | 特征 | 核心需求 |
|------|------|------|----------|
| 最终用户（桌面使用者） | `user` | 开发者/学生/技术爱好者，会基本 Linux 操作 | 装好即用、AI 助手好用且不闯祸、日常软件生态完整（浏览器/办公/终端） |
| 系统管理员（本机） | `admin`（sudo 组） | 同一台机器的管理者 | 控制 AI 助手权限边界、管理 API Key、查看审计日志 |
| 发行版维护者（开发者） | `maintainer` | 本项目开发者，用 Trae 写代码 | 可复现的构建（deb + ISO）、CI 自动化、清晰的模块边界 |
| 云端 AI 服务 | `llm-provider` | DashScope（默认）/ 任意 OpenAI 兼容端点 | ——（外部依赖，见第 17 章） |

**首批用户量级**：V1 面向几十~几百名内测用户（自装 ISO 或 deb 包），无集中并发场景；并发设计目标见第 9 章。

### 1.4 架构设计要点

- **单机单用户架构**：AI 助手守护进程只监听 `127.0.0.1` 与用户会话内 D-Bus，天然单租户；不做多用户共享服务。
- **隔离策略**：
  - 守护进程 `lingos-assistantd` 以**普通用户权限**运行（systemd user service），绝不以 root 运行；需要提权的操作（如改系统设置）通过 PolicyKit（polkit）逐条授权，polkit 规则默认拒绝未列入白名单的动作。
  - AI 发起的所有 shell 命令、文件写入/删除，必须经用户在 UI 上点击确认后由独立的 **executor 模块**执行；executor 对命令做静态危险模式检测（见 5.4）。
  - LLM API Key 存于 gnome-keyring（libsecret），不落明文配置文件。
- **可拆卸性**：AI 助手是标准 deb 包，卸载后系统即回到干净的 Ubuntu 24.04 + GNOME 体验，不残留钩子。

---

## 2. 技术架构

### 2.1 技术栈（全部锁定版本）

| 层 | 选型 | 版本 |
|----|------|------|
| 基础发行版 | Ubuntu LTS | 24.04.3 (Noble) |
| 桌面环境 | GNOME Shell + 定制扩展/主题 | GNOME 46（Ubuntu 24.04 官方版本） |
| 守护进程 `lingos-assistantd` | Python | 3.12.3（Ubuntu 24.04 系统自带） |
| 守护进程 Web/IPC 层 | FastAPI + Uvicorn（仅绑定 127.0.0.1） | fastapi==0.115.6, uvicorn==0.32.1 |
| LLM 客户端 | openai 官方 SDK（OpenAI 兼容，指向 DashScope） | openai==1.58.1 |
| 数据模型/校验 | pydantic + pydantic-settings | pydantic==2.10.4, pydantic-settings==2.7.0 |
| 本地存储 | SQLite（stdlib sqlite3，WAL 模式） | SQLite 3.45（系统自带） |
| 桌面 UI | GTK4 + libadwaita + PyGObject（Python 绑定） | GTK 4.14 / libadwaita 1.5（系统仓库版本） |
| 全局快捷键/托盘集成 | GNOME Shell 扩展（JS, gjs） | GNOME 46 扩展 API |
| 进程间通信 | 本地 HTTP/WebSocket（127.0.0.1）+ systemd 通知 | — |
| 密钥存储 | libsecret / gnome-keyring | 系统自带 |
| 提权授权 | PolicyKit | polkit 124（系统自带） |
| deb 打包 | debhelper + dh_python3 | debhelper 13.14 |
| ISO 构建 | Debian live-build（Ubuntu 定制 profile） | live-build 20240823（Noble 仓库版本） |
| apt 仓库 | apt-ftparchive 生成索引，静态托管（GitHub Pages / 对象存储） | — |
| CI/CD | GitHub Actions（ubuntu-24.04 runner） | — |
| 测试 | pytest + pytest-asyncio + httpx | pytest==8.3.4, pytest-asyncio==0.24.0, httpx==0.28.1 |
| 代码质量 | ruff + black | ruff==0.8.4, black==24.10.0 |

### 2.2 技术选型理由

1. **Ubuntu 24.04 LTS 而非 Arch/Debian/Fedora**：LTS 支持到 2029 年，软件包新且稳，社区资料最多，live-build 定制路径成熟；Arch 滚动更新不可复现，不适合发行版交付。
2. **GNOME 46 而非 KDE/自研 Wayland 合成器**：Ubuntu 官方默认桌面，集成风险最低；自研合成器工程量是"造半个系统"，V1 明确不做（记录在 V2 规划）。定制通过 GNOME 扩展 + GTK 主题实现，改动面小、可升级。
3. **Python 守护进程 + GTK4 UI 而非 Electron**：Electron 会给 ISO 增加 ~200MB 体积且与 GNOME 视觉割裂；PyGObject + libadwaita 与桌面原生一致，Python 3.12 是系统自带解释器，无额外运行时。
4. **openai SDK 指向 DashScope 兼容端点**：DashScope 提供 OpenAI 兼容模式（`https://dashscope.aliyuncs.com/compatible-mode/v1`），换一个 `base_url` 即可切换到任何 OpenAI 兼容提供商（OpenAI/DeepSeek/Moonshot/本地 Ollama），不锁死单一供应商。
5. **FastAPI 仅绑 127.0.0.1**：UI 与守护进程解耦（未来可换 UI/加 CLI），同时 localhost-only + token 鉴权避免暴露网络攻击面。
6. **SQLite 而非 PostgreSQL**：单机单用户桌面场景，SQLite WAL 模式足够，零运维。
7. **live-build 而非 Cubic/手工 chroot**：声明式配置、可在 CI 中复现构建，这是发行版工程化的关键。

### 2.3 系统架构图（ASCII）

```
┌────────────────────────────────────────────────────────────────────┐
│                    LingOS 桌面会话（用户态, Wayland）                 │
│                                                                    │
│  ┌──────────────────────┐        ┌──────────────────────────────┐  │
│  │ GNOME Shell 扩展      │  唤起   │  lingos-assistant-ui (GTK4)  │  │
│  │ (全局快捷键 Super+L,  ├───────►│  聊天面板/确认对话框/设置窗口   │  │
│  │  托盘图标, 通知集成)   │        └──────────┬───────────────────┘  │
│  └──────────────────────┘                   │ HTTP/WebSocket       │
│                                             │ 127.0.0.1:47831      │
│  ┌──────────────────────────────────────────▼───────────────────┐  │
│  │        lingos-assistantd（systemd user service, Python）      │  │
│  │  ┌─────────┐ ┌─────────┐ ┌──────────┐ ┌───────────────────┐  │  │
│  │  │ API 网关 │ │ 会话引擎 │ │ 工具调度器 │ │ LLM 客户端(熔断/  │  │  │
│  │  │ FastAPI │ │ Context │ │ ToolCall │ │ 重试/流式)         │  │  │
│  │  └─────────┘ └────┬────┘ └────┬─────┘ └─────────┬─────────┘  │  │
│  │                   │      ┌────▼─────┐           │            │  │
│  │  ┌────────────────▼─┐   │ Executor │           │            │  │
│  │  │ SQLite 存储层     │   │ 沙箱执行+  │           │            │  │
│  │  │ ~/.local/share/  │   │ 危险检测+  │           │            │  │
│  │  │ lingos/          │   │ polkit 提权│          │            │  │
│  │  └──────────────────┘   └────┬─────┘           │            │  │
│  └──────────────────────────────┼─────────────────┼────────────┘  │
└─────────────────────────────────┼─────────────────┼───────────────┘
                                  │                 │ HTTPS(SSE 流式)
                    ┌─────────────▼──────┐   ┌──────▼───────────────┐
                    │ 本机系统资源         │   │ DashScope(默认)      │
                    │ 文件系统/子进程/     │   │ 或任意 OpenAI 兼容端点 │
                    │ gsettings/polkit   │   └──────────────────────┘
                    └────────────────────┘
```

**组件职责**：
- `lingos-assistant-ui`：纯展示与交互层，不含业务逻辑，所有能力经 HTTP/WS 调用守护进程。
- `lingos-assistantd`：会话管理、上下文组装、LLM 调用（流式）、工具调用循环、命令执行与确认流、审计日志。
- `gnome-shell-extension-lingos`：全局快捷键、托盘菜单、通知路由，通过 D-Bus/HTTP 与 UI 通信。
- Executor：命令白/黑名单检测、子进程隔离（`systemd-run --scope` 限制资源）、polkit 提权入口。

### 2.4 服务依赖关系与启动顺序

```
boot → systemd(user session 建立)
  → gnome-keyring（解锁密钥环）
  → lingos-assistantd.service（After=gnome-keyring；启动时绑定 127.0.0.1:47831，生成会话 token 写入 XDG_RUNTIME_DIR）
  → GNOME Shell 扩展加载（读取 token，就绪）
  → 用户按 Super+L → lingos-assistant-ui 拉起（读取 token 连接守护进程）
```

依赖链：UI → assistantd → (keyring, SQLite, 网络)。assistantd 未就绪时 UI 显示"服务启动中"并每 500ms 重试，最多 10s 后给出错误页。

### 2.5 有状态/无状态组件标注

| 组件 | 状态 | 说明 |
|------|------|------|
| lingos-assistantd | **有状态**（SQLite + 内存会话上下文） | 单机单实例，不支持水平扩展（V1 无需） |
| lingos-assistant-ui | 无状态 | 可随时重启，状态从守护进程拉取 |
| GNOME 扩展 | 无状态 | — |
| apt 仓库 / ISO 构建 | 静态产物 | CI 生成，GitHub Pages/对象存储托管 |

---

## 3. 权限体系

### 3.1 权限矩阵（角色 × 功能 × 范围）

| 功能 | user（普通用户） | admin（sudo 组） | AI 助手（代理 user 身份） |
|------|------------------|------------------|---------------------------|
| 对话/历史查看与删除 | ✅ 本人会话 | ✅ 本人会话 | ❌ 无独立身份 |
| 修改助手设置（模型/温度/主题） | ✅ | ✅ | ❌ |
| 写入/删除 API Key | ✅（写 keyring） | ✅ | ❌ 永远无法读取 Key 明文回显 |
| AI 读文件 | 需 UI 内展示将读取的路径清单，用户点确认 | 同左 | 仅能发起请求 |
| AI 写/删文件 | 逐条确认；`~/.config`、`~/.ssh` 等敏感目录默认**禁止**（黑名单，见 5.4） | 同左 | 仅能发起请求 |
| AI 执行 shell 命令 | 逐条确认；黑名单命令直接拒绝不可确认 | 同左 | 仅能发起请求 |
| AI 修改系统设置（gsettings 白名单键） | 逐条确认 | 同左 | 仅能发起请求 |
| AI 触发需 root 的操作 | 默认**拒绝**（V1 不开放 polkit 提权给 AI） | polkit 弹窗逐次授权，且仅限白名单 action | — |
| 查看审计日志 | ✅ 本机 | ✅ 本机 | ❌ |

**V1 硬性边界**：AI 代理执行的一切操作权限 ≤ 当前登录用户；AI 不能获得 sudo；`rm -rf /`、fork 炸弹、修改 `/etc`、动防火墙等黑名单命令**不提供确认按钮，直接拒绝**并记入审计日志。

### 3.2 数据过滤规则

单机单用户，无跨用户数据隔离需求；守护进程 API 全部要求 `Authorization: Bearer <session-token>`，token 每次 assistantd 启动重新随机生成（secrets.token_urlsafe(32)），仅写入 `$XDG_RUNTIME_DIR/lingos/assistant.token`（权限 0600）。无 token 或 token 错误 → 401。

### 3.3 关键权限逻辑伪代码

```python
# executor/guard.py
def evaluate_tool_call(call: ToolCall) -> Decision:
    if call.tool == "shell":
        if match_denylist(call.args["command"]):      # 正则+AST 双重检测
            return Decision.DENY(reason="blacklist")   # 不可确认，直接拒绝
        return Decision.CONFIRM(show=call.args["command"], risk=classify_risk(...))
    if call.tool in ("file_write", "file_delete"):
        if is_sensitive_path(call.args["path"]):        # ~/.ssh, ~/.config, /etc...
            return Decision.DENY(reason="sensitive_path")
        return Decision.CONFIRM(show=diff_preview(...))
    if call.tool == "file_read":
        if is_sensitive_path(call.args["path"]):
            return Decision.DENY(reason="sensitive_path")
        return Decision.CONFIRM(show=call.args["path"])
    if call.tool == "gsettings_set":
        if call.args["key"] not in GSETTINGS_WHITELIST:
            return Decision.DENY(reason="not_whitelisted")
        return Decision.CONFIRM(...)
    return Decision.DENY(reason="unknown_tool")        # 默认拒绝
```

### 3.4 敏感操作二次确认清单

| 操作 | 确认方式 |
|------|----------|
| AI 执行任意 shell 命令 | 模态确认框，完整展示命令原文 + 风险等级标签（低/中/高） |
| AI 写入/删除文件 | 模态确认框，展示路径 + diff 预览（写）或红色警示（删） |
| AI 修改 gsettings | 模态确认框，展示"设置项中文名：旧值 → 新值" |
| 清空全部会话历史 | 输入 `DELETE` 字面量确认 |
| 覆盖已存在的 API Key | 普通确认框 |
| 高危命令（命中黑名单） | 无确认入口，直接拒绝 + 通知说明原因 |

---

## 4. 数据模型

### 4.1 ER 关系图（ASCII）

```
conversations 1 ──── * messages 1 ──── * tool_calls
      │                                      │
      └── (settings 为单例表, 无外键)          └── audit_logs（tool_calls 的镜像留痕, SET NULL 松耦合）
```

数据库文件：`~/.local/share/lingos/assistant.db`（SQLite, WAL 模式, `PRAGMA foreign_keys=ON`）。
迁移策略：无 Alembic——使用内置 `schema_version` 表 + 启动时顺序执行 `migrations/NNN_*.sql`（简单、可测、SQLite 友好）。

### 4.2 完整 DDL

```sql
-- migrations/001_init.sql
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER PRIMARY KEY,
    applied_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE conversations (
    id          TEXT PRIMARY KEY,               -- UUIDv7 字符串
    title       TEXT NOT NULL DEFAULT '新对话',
    model       TEXT NOT NULL DEFAULT 'qwen-plus',
    created_at  TEXT NOT NULL,                  -- ISO8601 UTC
    updated_at  TEXT NOT NULL,
    deleted     INTEGER NOT NULL DEFAULT 0      -- 软删除标记
);

CREATE TABLE messages (
    id              TEXT PRIMARY KEY,           -- UUIDv7
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            TEXT NOT NULL CHECK (role IN ('user','assistant','system','tool')),
    content         TEXT NOT NULL DEFAULT '',
    tokens          INTEGER,                    -- 该消息估算 token 数
    created_at      TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'done' CHECK (status IN ('streaming','done','error','cancelled'))
);

CREATE TABLE tool_calls (
    id              TEXT PRIMARY KEY,           -- UUIDv7
    message_id      TEXT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    tool_name       TEXT NOT NULL,              -- shell / file_read / file_write / file_delete / gsettings_set
    arguments_json  TEXT NOT NULL,              -- 见 4.3
    decision        TEXT NOT NULL CHECK (decision IN ('pending','confirmed','denied_by_user','denied_by_guard','executed','failed','timeout')),
    result_json     TEXT,                       -- 执行结果（stdout/stderr/exit_code 或文件 diff）
    created_at      TEXT NOT NULL,
    executed_at     TEXT
);

CREATE TABLE settings (                          -- 单例表, 固定 id=1
    id              INTEGER PRIMARY KEY CHECK (id = 1),
    provider        TEXT NOT NULL DEFAULT 'dashscope',   -- dashscope / openai / custom
    base_url        TEXT NOT NULL DEFAULT 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    model           TEXT NOT NULL DEFAULT 'qwen-plus',
    temperature     REAL NOT NULL DEFAULT 0.7 CHECK (temperature BETWEEN 0 AND 2),
    max_tokens      INTEGER NOT NULL DEFAULT 4096,
    context_window  INTEGER NOT NULL DEFAULT 30000,      -- 上下文裁剪阈值(token 估算)
    tools_enabled   INTEGER NOT NULL DEFAULT 1,
    theme           TEXT NOT NULL DEFAULT 'system' CHECK (theme IN ('light','dark','system')),
    updated_at      TEXT NOT NULL
);
-- 注意: API Key 不入库, 存 gnome-keyring(schema: com.lingos.assistant, item: api-key)

CREATE TABLE audit_logs (
    id          TEXT PRIMARY KEY,
    ts          TEXT NOT NULL,
    actor       TEXT NOT NULL DEFAULT 'assistant',   -- assistant / user
    action      TEXT NOT NULL,                       -- tool_executed / tool_denied / key_written / settings_changed ...
    detail_json TEXT,
    tool_call_id TEXT REFERENCES tool_calls(id) ON DELETE SET NULL  -- 删会话不删审计
);

CREATE INDEX idx_messages_conv ON messages(conversation_id, created_at);
CREATE INDEX idx_toolcalls_conv ON tool_calls(conversation_id, created_at);
CREATE INDEX idx_audit_ts ON audit_logs(ts);
CREATE INDEX idx_conversations_updated ON conversations(updated_at DESC) WHERE deleted = 0;
```

### 4.3 JSON 字段结构示例

`tool_calls.arguments_json`：

```json
// shell
{"command": "df -h", "workdir": "/home/u", "timeout_sec": 30}
// file_write
{"path": "/home/u/notes/todo.md", "content": "...", "mode": "overwrite"}
// gsettings_set
{"schema": "org.gnome.desktop.interface", "key": "color-scheme", "value": "prefer-dark"}
```

`tool_calls.result_json`：

```json
{"exit_code": 0, "stdout": "...(截断至 8KB)...", "stderr": "", "duration_ms": 132}
```

### 4.4 数据增长预估与归档

单机场景：按每天 50 条消息、每条 2KB 估算，年增 < 100MB。策略：会话软删除后 30 天由守护进程每日定时任务物理清除；`audit_logs` 保留 180 天滚动删除。无大表在线 DDL 风险。

---

## 5. 功能模块详细说明

### 5.1 模块总览与 V1 范围裁剪

**P0（V1 必须）**：M1 守护进程与本地 API、M2 聊天 UI（流式）、M3 LLM 客户端（熔断/重试/降级）、M4 工具调用与确认执行（shell/文件/gsettings）、M5 API Key 管理（keyring）、M6 GNOME 扩展（快捷键/托盘）、M7 deb 打包、M8 ISO 构建、M9 apt 仓库、M10 审计日志。

**P1（V1 尽量）**：M11 会话历史侧栏与搜索、M12 首次开机引导（OOBE：选时区→配 Key→试用对话）、M13 系统上下文注入（"我的系统"工具：自动附 OS/硬件/磁盘摘要）、M14 LingOS 品牌定制（壁纸/主题/Plymouth 开机动画/默认应用集：Firefox、LibreOffice、GNOME Terminal）。

**P2（V2，不开发）**：本地 Ollama 模型接入与自动降级、AI 驱动的全局文件语义搜索（本地向量索引）、软件商店内 AI 装软件推荐、语音输入输出、多用户 Key 隔离、自研 Wayland 合成器、ARM64 ISO。

### 5.2 M1 守护进程与本地 API

- **功能**：systemd user service 常驻；启动时初始化 SQLite（跑迁移）、绑定 `127.0.0.1:47831`（端口被占用则 +1 递增重试至 47841，实际端口写入 `$XDG_RUNTIME_DIR/lingos/port`）、生成会话 token。
- **业务规则**：所有请求校验 Bearer token；请求体超过 1MB → 413；未知路径 → 404 JSON。
- **数据流向**：UI → `HTTP/WS 127.0.0.1` → FastAPI router → service 层 → SQLite/LLM/Executor → 流式回写 WS。
- **异常**：端口全部被占用 → 退出码 78 + systemd 通知 + 桌面通知"助手服务启动失败"；SQLite 损坏（integrity_check 失败）→ 将坏库改名 `.corrupt-<ts>` 备份、新建空库、通知用户"历史已重置，旧数据备份在…"。
- **幂等**：`POST /api/v1/conversations` 支持 `Idempotency-Key` 头，重复请求返回同一会话。

### 5.3 M2 聊天 UI（GTK4/libadwaita）

- **形态**：`Super+L` 唤起屏幕右上悬浮面板（600×720，可拖拽/最大化）；独立"助手"应用入口打开完整窗口（历史侧栏 + 聊天区 + 设置页）。
- **交互**：输入框支持多行（Enter 发送 / Shift+Enter 换行）；流式渲染 Markdown（代码块带"复制/在终端运行"按钮，运行按钮同样走确认流）；每条 AI 消息下：复制/重新生成/点赞点踩（仅本地存储）。
- **状态机（每个界面必须定义）**：
  - 加载中：消息气泡内打字指示动画；发送按钮禁用。
  - 失败：气泡下红色条"生成失败：<原因> [重试]"。
  - 超时：60s 无首 token → 自动取消 + "响应超时，请检查网络或更换模型"。
  - 空状态：新会话显示 4 张快捷卡片（"整理下载目录" / "解释一个报错" / "深色模式" / "系统信息"）。
  - 无 Key：整屏引导页"配置你的 API Key"，其余功能入口禁用。
  - 服务未就绪：见 2.4 重试逻辑。
- **弱网/离线兜底**：输入内容在发送失败时保留在输入框；草稿按会话 id 每 5s 暂存至 `$XDG_STATE_HOME/lingos/drafts/`，UI 重启后恢复。

### 5.4 M3 LLM 客户端 + M4 工具调用

**M3 LLM 客户端**：
- OpenAI 兼容 `chat.completions`，`stream=True`，携带 `tools` 定义（function calling）。
- 重试：网络错误/429/5xx → 指数退避重试 2 次（1s, 3s），429 优先遵循 `Retry-After`。
- 熔断：连续 5 次失败 → 熔断器 OPEN 60s，期间所有请求立即返回降级文案"AI 服务暂不可用，请稍后再试"，不发真实请求；半开态放 1 个探测请求。
- 上下文管理：消息 token 估算（`len(text)//2` 粗估 + 每消息固定开销 4）超过 `context_window` 时，保留 system prompt + 最近消息，中间历史压缩为一条摘要消息（由模型生成，失败则直接截断）。
- 输出容错：工具调用参数 JSON 解析失败 → 回传 `tool` 角色消息 `{"error":"invalid_arguments"}` 让模型自纠，最多 2 轮，仍失败则向用户展示"AI 请求的操作格式异常，已取消"。

**M4 工具集（V1 共 5 个，schema 见 8.4）**：

| 工具 | 说明 | 默认决策 |
|------|------|----------|
| `shell` | 在用户会话执行命令，超时 30s（可参数指定，上限 120s），stdout/stderr 各截断 8KB | 确认；黑名单拒绝 |
| `file_read` | 读文本文件，≤256KB，超限拒绝并提示 | 确认；敏感路径拒绝 |
| `file_write` | 写/覆盖文件，自动创建父目录，写前生成 diff 预览；原文件备份到 `~/.local/share/lingos/backups/`（保留最近 50 个） | 确认；敏感路径拒绝 |
| `file_delete` | 移入 `~/.local/share/Trash/`（遵循 FreeDesktop Trash 规范，**永不真删**） | 确认；敏感路径拒绝 |
| `system_info` | 返回 OS/内核/CPU/内存/磁盘摘要（只读，无需确认） | 自动放行 |

- **命令黑名单（正则 + shlex 解析双检，命中即 DENY 不可确认）**：`rm -rf /`、`rm -rf ~`、`mkfs`、`dd if=.*of=/dev/`、`:(){:|:&};:`（fork 炸弹模式）、`chmod -R 777 /`、`shutdown|reboot|halt`、`> /dev/sd`、`iptables|ufw|nft`、`sudo|su|pkexec` 前缀、`curl|wget` 管道到 `sh/bash`、对 `/etc`、`/boot`、`/usr`、`~/.ssh`、`~/.gnupg`、`~/.config` 的任何写操作。
- **敏感路径黑名单（文件工具）**：`~/.ssh`、`~/.gnupg`、`~/.config`、`~/.local/share/keyrings`、`/etc`、`/boot`、任何 `*.token`、`*.pem`、`id_rsa*`。
- **执行隔离**：命令经 `systemd-run --user --scope -p MemoryMax=1G -p CPUQuota=100% --pty` 执行，防止 AI 引发的失控进程耗尽资源。
- **并发控制**：同一时刻仅允许 1 个 pending 确认；工具串行执行；会话内消息写入用 SQLite 事务 + `messages.status` 字段做乐观状态流转（streaming→done/error/cancelled）。
- **取消**：UI"停止"按钮 → 守护进程取消 LLM 流 + kill 执行中的子进程组（`os.killpg`）。

### 5.5 M5 API Key 管理

- 存储在 gnome-keyring：schema `com.lingos.assistant`，属性 `provider`。
- UI 设置页：写入（粘贴掩码显示）、测试连通性（发一条 1-token 请求，显示成功/失败原因）、删除。
- 守护进程读取 Key 仅驻内存；任何日志/错误信息/LLM 请求中出现 Key 明文 = 事故级 Bug（CI 中加 secret-scan，见 13）。
- Key 无效（401）→ UI 明确提示"API Key 无效或已过期"，与网络错误区分。

### 5.6 M6 GNOME Shell 扩展

- 注册全局快捷键 `Super+L`（可在系统设置-键盘中改绑）唤起 UI；托盘图标显示状态（就绪=品牌色圆点 / 熔断降级=灰色 / 无 Key=黄色感叹号）；菜单项：打开助手、打开设置、暂停工具能力（快速开关 `tools_enabled`）、查看审计日志。
- 扩展 manifest 声明兼容 GNOME 46（`shell-version: ["46"]`）。

### 5.7 M7-M9 打包 / ISO / apt 仓库

- **deb 包**（3 个）：
  - `lingos-assistant_1.0.0_amd64.deb`：守护进程 + UI + Python 依赖（依赖 python3-fastapi 等系统包；无法系统化的用 vendored wheel 装入 `/usr/lib/lingos/venv`，由 postinst 创建 venv——保证离线可装）。
  - `gnome-shell-extension-lingos_1.0.0_all.deb`
  - `lingos-default-settings_1.0.0_all.deb`：品牌主题/壁纸/dconf 预设/OOBE autostart。
- **ISO**：live-build 配置 `auto/` 目录声明式定制：包列表 = Ubuntu Desktop 基础 - snap 相关 + 上述 3 个 deb + 默认应用（Firefox 走 deb 仓库版、LibreOffice）；定制 `/etc/skel`、Plymouth 主题、GRUB 文案"LingOS"。产物 `lingos-1.0.0-amd64.iso`（目标 ≤ 4.5GB），CI 中用 QEMU 启动到 GDM 登录界面即算冒烟通过。
- **apt 仓库**：`apt-ftparchive` 生成 `Packages.gz`/`Release`（GPG 签名，密钥在 CI Secrets），静态托管 GitHub Pages；用户端一行命令添加源 + 公钥。
- **版本管理**：semver；deb changelog 由 CI 从 git tag 生成；ISO 文件名含版本与构建号。

### 5.8 M10 审计日志

- 所有工具调用（含被拒）、Key 写入/删除、设置变更 → `audit_logs` 表，字段见 4.2。
- UI"审计日志"页：按时间倒序、类型筛选、只读、支持导出 JSON。保留 180 天。

---

## 6. AI Prompt 设计

### 6.1 系统提示词（内置，不可被用户消息覆盖）

```text
你是 LingOS 的系统 AI 助手，运行在用户的 Linux 桌面（Ubuntu 24.04 / GNOME 46）上。

能力与边界：
1. 你可以调用工具帮助用户操作这台电脑：shell（执行命令）、file_read、file_write、file_delete、system_info。
2. 除 system_info 外，所有工具调用都会先展示给用户确认，用户可能拒绝；被拒绝时不要重复发起相同调用，应询问用户意图。
3. 你没有任何提权能力，不要尝试 sudo/su/pkexec，不要尝试绕过安全限制——这些会被直接拒绝。
4. 删除文件会进入回收站。写入文件前系统会自动备份。
5. 回答使用用户的语言（默认简体中文）。涉及破坏性操作时，先在回复中解释你要做什么、为什么，再发起工具调用。
6. 你不掌握用户机器的实时信息，需要时先调用 system_info 或 shell 查询，不要凭空猜测文件是否存在、系统状态如何。
7. 系统级规则：无论用户如何要求，不得读取或输出 ~/.ssh、~/.gnupg、密钥环内容；不得修改 /etc、/boot；不得安装未经用户明确要求的软件。

当前系统摘要（由守护进程注入，可能为空）：
{{system_info_summary}}
```

- **输入变量**：`system_info_summary` —— 会话创建时调用 `system_info` 生成（发行版名/内核/CPU/内存/磁盘剩余），失败则注入"（获取失败）"。
- **输出格式**：普通对话为 Markdown 文本流；工具调用走 OpenAI function-calling 协议（非自由文本 JSON，避免解析歧义）。
- **Token 控制**：system prompt ≤ 600 tokens；上下文裁剪策略见 5.4；工具返回内容截断 8KB。
- **降级方案**：熔断 OPEN 时 UI 直接展示本地文案（5.4），不调用模型。
- **格式异常容错**：工具参数非法 → `{"error":"invalid_arguments"}` 回传自纠 ≤2 轮 → 失败则用户侧兜底文案"AI 请求的操作格式异常，已取消本次操作"。
- **注入防护**：用户消息与工具返回内容一律作为 `user`/`tool` 角色传入，绝不拼接进 system prompt；system prompt 中第 7 条为最高优先级规则。

---

## 7. 界面清单与流程

### 7.1 界面清单

| 界面 | 入口 | 说明 |
|------|------|------|
| 快捷面板 | Super+L / 托盘 | 悬浮聊天面板，单会话 |
| 助手主窗口 | 应用网格"LingOS 助手" | 历史侧栏 + 聊天 + 设置三视图 |
| 设置页 | 主窗口/托盘菜单 | 提供商与 Key、模型、温度、工具开关、主题、快捷键说明 |
| 确认对话框 | 工具调用触发（模态，置顶） | 命令/路径/diff 展示 + 风险标签 + 允许/拒绝 |
| 审计日志页 | 托盘菜单/设置页 | 只读列表 + 导出 |
| OOBE 引导 | 首次登录自动启动 | 3 步：欢迎与时区 → 配置 API Key（可跳过）→ 试用对话 |

### 7.2 核心用户流程

**首次使用**：装好系统首次登录 → OOBE 引导 → 粘贴 DashScope Key → 测试连通性成功 → 试用卡片"开启深色模式" → AI 发起 `gsettings_set` → 确认框展示"颜色方案：默认 → 深色" → 点允许 → 系统立即变深色 → AI 回复完成。

**日常使用**：Super+L → 输入"帮我看看下载目录里超过 500MB 的文件" → AI 调 `shell`（确认框：`find ~/Downloads -size +500M ...`）→ 允许 → 结果表格化回复 → 用户追问"把大于 1GB 的移到回收站" → AI 调 `file_delete` 逐文件确认（可勾选"本次全部允许"，仅限同一工具+同一目录前缀）。

### 7.3 路由/焦点守卫

- 确认对话框弹出时夺取焦点并置顶，未处理前禁止新的工具调用入队（队列显示"等待你确认上一个操作"）。
- 无 Key 状态下，聊天输入框禁用，占位文案引导去设置页。

---

## 8. 本地 API 接口清单（assistantd, 基址 `http://127.0.0.1:{port}/api/v1`）

鉴权：除 `GET /healthz` 外全部要求 `Authorization: Bearer <token>`。超时阈值统一：普通接口 5s，流式接口首 token 60s。

| # | 方法 | 路径 | 说明 |
|---|------|------|------|
| 1 | GET | /healthz | 健康检查（返回版本/熔断器状态/是否已配 Key） |
| 2 | GET | /conversations | 会话列表（分页） |
| 3 | POST | /conversations | 新建会话（支持 Idempotency-Key） |
| 4 | PATCH | /conversations/{id} | 重命名 |
| 5 | DELETE | /conversations/{id} | 软删除 |
| 6 | GET | /conversations/{id}/messages | 消息历史（分页） |
| 7 | POST | /conversations/{id}/messages | 发送用户消息（返回 message_id，随后经 WS 流式推送） |
| 8 | POST | /conversations/{id}/cancel | 取消当前流式生成/执行 |
| 9 | GET | /tool-calls/pending | 当前待确认的工具调用 |
| 10 | POST | /tool-calls/{id}/decision | 提交确认结果（allow / deny / allow_batch） |
| 11 | GET | /settings | 读取设置（Key 永不返回，仅返回 has_key: bool） |
| 12 | PUT | /settings | 更新设置（部分字段） |
| 13 | POST | /settings/api-key | 写入 API Key（body: {provider, api_key}）→ 存 keyring |
| 14 | POST | /settings/api-key/test | 连通性测试 |
| 15 | DELETE | /settings/api-key | 删除 Key |
| 16 | GET | /audit-logs | 审计日志（分页+筛选） |
| 17 | GET | /audit-logs/export | 导出 JSON |
| 18 | WS | /ws | 事件流：token 增量、工具调用请求、状态变更、错误 |

**API 总数：18**

### 8.1 关键 Schema 定义

`POST /conversations` 请求体：

| 字段 | 类型 | 必填 | 校验 |
|------|------|------|------|
| title | string | 否 | ≤100 字符，默认"新对话" |
| model | string | 否 | 白名单：qwen-plus/qwen-max/qwen-turbo/gpt-4o-mini/自定义（≤64字符） |

`POST /conversations/{id}/messages` 请求体：

| 字段 | 类型 | 必填 | 校验 |
|------|------|------|------|
| content | string | 是 | 1~32000 字符，去除首尾空白后非空 |
| attachments | string[] | 否 | 本机文件绝对路径，≤5 个，仅文本/图片，单文件 ≤10MB（V1 仅读文本注入上下文） |

`POST /tool-calls/{id}/decision` 请求体：

| 字段 | 类型 | 必填 | 校验 |
|------|------|------|------|
| decision | string | 是 | enum: allow / deny / allow_batch |
| remember_scope | string | 否 | allow_batch 时必填，格式 `tool:路径前缀` |

WS 事件（`type` 字段区分）：`message.delta {message_id, content_chunk}`、`message.done {message_id, tokens}`、`message.error {message_id, code, message}`、`tool_call.requested {tool_call_id, tool_name, arguments, risk, preview}`、`tool_call.resolved {tool_call_id, decision, result_summary}`、`status.changed {circuit: closed|open|half_open, has_key: bool}`。

### 8.2 关键请求/响应示例

`POST /api/v1/conversations/01927.../messages`

```json
// 请求
{"content": "帮我把 ~/Downloads 里所有 .zip 列出来"}
// 响应 202
{"message_id": "01927c02-...-u1", "status": "accepted"}
```

随后 WS 推送：

```json
{"type":"message.delta","message_id":"01927c03-...-a1","content_chunk":"好的，我需要执行一条命令："}
{"type":"tool_call.requested","tool_call_id":"01927c04-...","tool_name":"shell",
 "arguments":{"command":"ls -lh ~/Downloads/*.zip","timeout_sec":30},"risk":"low",
 "preview":"ls -lh ~/Downloads/*.zip"}
{"type":"tool_call.resolved","tool_call_id":"01927c04-...","decision":"confirmed",
 "result_summary":{"exit_code":0}}
{"type":"message.done","message_id":"01927c03-...-a1","tokens":812}
```

错误响应统一结构：

```json
{"error": {"code": "no_api_key", "message": "尚未配置 API Key", "detail": null}}
```

**错误码定义**：400 `invalid_argument` / 401 `unauthorized` / 404 `not_found` / 409 `conflict`（幂等冲突）/ 413 `payload_too_large` / 423 `tool_pending`（有未处理确认）/ 502 `llm_upstream_error` / 503 `llm_circuit_open` / 504 `llm_timeout`。

### 8.3 工具 Function Schema（发给 LLM 的 tools 定义，节选 shell）

```json
{"type":"function","function":{
  "name":"shell",
  "description":"在用户桌面会话中执行一条 shell 命令。危险命令会被系统直接拒绝。执行前需用户确认。",
  "parameters":{"type":"object",
    "properties":{
      "command":{"type":"string","description":"要执行的完整命令"},
      "timeout_sec":{"type":"integer","minimum":1,"maximum":120,"default":30}},
    "required":["command"]}}}
```

---

## 9. 性能与并发方案

### 9.1 峰值估算

单机单用户桌面系统，无多租户并发。真实并发 = 1 个用户 ×（1 条 LLM 流 + ≤1 个工具执行 + UI 若干 WS 心跳）。守护进程设计承载：**同一用户多面板连接 ≤ 4 个 WS + 20 req/s 本地 API**（远超实际，留余量）。

### 9.2 关键性能预算

| 环节 | 目标 | 方案 |
|------|------|------|
| 守护进程冷启动 | ≤ 800ms | 延迟导入重模块（openai SDK 首次请求时才 import） |
| UI 唤起 | ≤ 1.5s | 面板进程预热：GNOME 扩展在会话启动 30s 后 fork 一个隐藏 UI 进程待命 |
| 首 token | P95 ≤ 3s | 流式 + 上下文裁剪；system_info 摘要缓存 10min |
| SQLite 查询 | ≤ 50ms | 4.2 索引 + WAL；历史消息分页 page_size=50 |
| 工具执行 | 命令超时 30s（上限 120s） | systemd-run scope 资源限制 |

### 9.3 限流与防护

本地 API 令牌桶：单 token 20 req/s，突发 40；WS 消息 ≤ 10/s（防 UI Bug 风暴）。LLM 调用遵循提供商 RPM/TPM 限额，429 时读 `Retry-After`。缓存：`system_info` 结果内存缓存 TTL 600s；会话列表缓存于 UI 内存，WS 事件驱动失效（无穿透/雪崩场景——单机无共享缓存）。

---

## 10. 安全设计

### 10.1 五层防护

| 层 | 威胁 | 具体措施 |
|----|------|----------|
| 网络 | 本地其他进程/局域网访问守护进程 | 仅绑 127.0.0.1；Bearer token（每次启动随机 256bit）；token 文件 0600；无 CORS 允许跨源（FastAPI 不配置 CORSMiddleware，浏览器网页无法调用） |
| 应用 | Prompt 注入诱导执行危险操作 | 工具白名单（仅 5 个）；黑名单不可确认；一切写/执行操作人工确认；system prompt 规则 7 不可覆盖；工具返回内容截断且不经 system 角色注入 |
| 数据 | API Key 泄露 | gnome-keyring 加密存储；进程内存驻留；日志脱敏（正则替换 `sk-[A-Za-z0-9]{8,}` → `sk-***`）；错误堆栈不含 Authorization 头；CI secret-scan（gitleaks）拦截提交 |
| 系统 | AI 失控破坏系统 | 守护进程非 root；systemd-run 资源限制；文件删除走回收站；写文件自动备份；敏感路径黑名单；V1 不向 AI 开放 polkit 提权 |
| 供应链 | 恶意包/被篡改 ISO | deb 全量 GPG 签名；apt Release 签名；ISO 附 SHA256SUMS 与签名；CI 锁定 runner 镜像版本 `ubuntu-24.04`；Python 依赖锁版本 + `pip-audit` 扫描 |

### 10.2 日志规范

- 结构化 JSON Lines：`{"ts","level","logger","event","conv_id","tool_call_id","msg"}`，级别 DEBUG/INFO/WARN/ERROR。
- 位置：`journalctl --user -u lingos-assistantd`（journald 托管，自动轮转，上限 50MB）。
- 链路：每个用户消息生成 `trace_id` 贯穿 LLM 请求与工具调用。
- 脱敏：命令原文可记录（审计需要），但 Key/token/文件内容正文不入库日志。

---

## 11. 开发规约与已知陷阱（Trae 动手前必读）

### 11.1 类型统一规约

- 时间：数据库与 API 一律 **ISO8601 UTC 字符串**（`...Z` 结尾）；Python 内一律 `datetime.now(timezone.utc)`（aware），禁止 `datetime.utcnow()`（3.12 已弃用）与 naive/aware 混用。
- 主键：一律 UUIDv7 字符串（时间有序，用 `uuid_utils` 或自实现；TEXT 存储）。
- 空值：DB NULL ↔ Python None ↔ JSON null 一一对应；前端展示空串；禁止用 `""` 表示"无值"入库。
- 枚举：全小写（`confirmed`、`denied_by_guard`），前后端一致。

### 11.2 框架组合兼容性验证（开发第一天必做）

- PyGObject 在 Ubuntu 24.04 需用系统包 `python3-gi` + `gir1.2-gtk-4.0`，**不要 pip 装 PyGObject**（版本地狱）。
- FastAPI 0.115 + pydantic 2.10：`orm_mode` → `from_attributes`；validator → `field_validator`。
- pytest-asyncio 0.24：必须显式 `asyncio_mode = "auto"`（pyproject.toml），event loop scope 默认 function。
- openai SDK 1.x：流式用 `client.chat.completions.create(stream=True)` 迭代 chunk，`chunk.choices[0].delta`；工具调用增量在 `delta.tool_calls[i].function.arguments`（分片拼接，别按单片解析）。
- GNOME 46 扩展只支持 ESM（`import`），禁用旧式 `const X = imports.X` 写法。
- **第一天 smoke test**：跑通"pytest 异步用例 → 内存 SQLite 建表 → FastAPI TestClient 调 /healthz → mock LLM 流式返回"全链路。

### 11.3 外键依赖与数据操作顺序

拓扑序：`conversations → messages → tool_calls → audit_logs`。种子/测试数据正序插入，清理逆序删除（或依赖 CASCADE）。级联策略：messages/tool_calls 随会话 CASCADE；audit_logs.tool_call_id SET NULL（审计留痕不随会话删除而消失）——理由：审计的价值独立于会话生命周期。

### 11.4 全局副作用清单与测试隔离

| 副作用 | 测试隔离方案 |
|--------|--------------|
| SQLite 文件 | 每用例 `tmp_path` 独立库文件；autouse fixture 建库+迁移 |
| keyring | 测试用 `keyrings.alt` 内存后端或 monkeypatch KeyringService 接口 |
| 子进程（shell 工具） | Executor 抽象接口，测试注入 FakeExecutor；集成测试仅跑白名单安全命令（echo/ls tmp_path） |
| 环境变量/设置 | pydantic-settings 每用例重建；禁止改 os.environ 不恢复 |
| LLM 网络调用 | **单测永远 mock**（respx 拦截 httpx）；真实 API 测试打 `@pytest.mark.network` 默认不跑 |
| 端口绑定 | 测试用端口 0（系统分配） |

`conftest.py` 的 autouse fixture（db、keyring、fake-executor、env 恢复）**必须在写第一个测试文件之前完成**。

### 11.5 本地与生产环境差异对照

| 维度 | 开发机（可能是 macOS/Windows + Trae） | 生产（Ubuntu 24.04） | 踩坑 |
|------|--------------------------------------|----------------------|------|
| GTK4/PyGObject | macOS 上 brew 装或**根本跑不了 UI** | 系统包 | **UI 代码只能在 Ubuntu 24.04 容器/VM 中调试**；建议开发全程用 devcontainer（镜像 `ubuntu:24.04`） |
| systemd | 容器内无 systemd user session | 真实会话 | 守护进程需支持 `LINGOS_NO_SYSTEMD=1` 直跑模式 |
| keyring | 容器内无 gnome-keyring | 有 | KeyringService 接口化 + 文件后端 fallback（仅开发模式，打 WARN 日志） |
| 时区 | 开发机任意 | 用户任意 | 一律 UTC 存储，展示层转本地 |
| 路径 | — | — | 全部用 `pathlib` + XDG 目录规范，禁止硬编码 `/home/xxx` |

---

## 12. 测试策略

### 12.1 分层

| 层 | 范围 | 通过线 |
|----|------|--------|
| 单元测试（pytest） | guard 黑名单/敏感路径全覆盖（每条黑名单规则 ≥1 正例 1 反例）、上下文裁剪、熔断器状态机、迁移脚本、schema 校验 | 核心模块（executor/guard、llm、storage）覆盖率 ≥ 85% |
| API 集成测试 | FastAPI TestClient：18 个接口 × 正常/401/400/404/幂等重放/423（pending 冲突） | 全绿 |
| mock 流式端到端 | respx 模拟 DashScope SSE：纯文本流、单工具调用流、工具参数非法自纠流、上游 500 重试流、429 退避流 | 全绿 |
| 打包测试 | CI 中 `debci` 风格：干净 Ubuntu 24.04 容器装 deb → systemctl --user 启动 → curl /healthz → 卸载无残留 | 通过 |
| ISO 冒烟 | QEMU（UEFI+BIOS 各一次）：启动→安装→登录→Super+L 出面板→OOBE 完成 | 通过 |
| 安全测试 | gitleaks 全仓扫描；pip-audit；黑名单绕过尝试用例（`rm -rf / --no-preserve-root`、base64 变形命令等 ≥20 条攻击样本全部 DENY） | 0 泄露、0 绕过 |
| 手动 UI 验收 | 7.2 两条核心流程 + 全部 5.3 状态机界面逐个触发核对 | 通过 |

### 12.2 压力场景

本地 API：`hey -z 30s -c 20 -H "Authorization: Bearer t" http://127.0.0.1:PORT/api/v1/conversations`，通过线：无限流误杀、P95 ≤ 100ms、无 fd 泄漏。

---

## 13. CI/CD 与发布

### 13.1 仓库结构（Monorepo）

```
lingos/
├── TRAE.md                        # Trae 项目入口规则
├── docs/PRD.md                    # 本文档
├── daemon/                        # lingos-assistantd
│   ├── pyproject.toml
│   ├── lingos_assistantd/
│   │   ├── __init__.py            # 版本号唯一来源
│   │   ├── main.py                # 入口: uvicorn 启动
│   │   ├── config.py              # pydantic-settings
│   │   ├── api/                   # FastAPI routers (conversations/messages/tool_calls/settings/audit/ws)
│   │   ├── core/
│   │   │   ├── llm.py             # OpenAI 兼容客户端+熔断+重试+流式
│   │   │   ├── context.py         # 上下文组装与裁剪
│   │   │   └── prompts.py         # system prompt 模板
│   │   ├── tools/
│   │   │   ├── schemas.py         # 5 个工具的 function schema
│   │   │   ├── dispatcher.py      # 工具调用循环
│   │   │   └── system_info.py
│   │   ├── executor/
│   │   │   ├── guard.py           # 黑名单/敏感路径/决策
│   │   │   ├── runner.py          # systemd-run 子进程执行
│   │   │   └── trash.py           # FreeDesktop Trash
│   │   ├── storage/
│   │   │   ├── db.py              # 连接/WAL/迁移执行器
│   │   │   ├── migrations/001_init.sql
│   │   │   ├── conversations_repo.py / messages_repo.py / tool_calls_repo.py / audit_repo.py / settings_repo.py
│   │   ├── keyring_service.py
│   │   └── logging_setup.py       # 结构化日志+脱敏 filter
│   └── tests/                     # conftest.py + unit/ + api/ + e2e_mock/
├── ui/                            # GTK4 应用
│   ├── lingos_assistant_ui/
│   │   ├── app.py main_window.py quick_panel.py confirm_dialog.py settings_page.py audit_page.py oobe/
│   │   ├── client.py              # 守护进程 HTTP/WS 客户端
│   │   └── data/                  # .desktop / .gschema.xml / icons / css
│   └── tests/
├── extension/                     # GNOME Shell 扩展
│   ├── metadata.json extension.js shortcut.js tray.js
├── packaging/
│   ├── debian-assistant/          # deb: control/rules/postinst/…
│   ├── debian-extension/
│   ├── debian-settings/           # 品牌包: 壁纸/主题/dconf/plymouth
│   └── systemd/lingos-assistantd.service
├── iso/                           # live-build
│   ├── auto/ (config bootstrap chroot binary clean)
│   └── config/ (包列表/骨架文件)
├── repo/                          # apt 仓库生成脚本 (apt-ftparchive + GPG)
├── .github/workflows/
│   ├── ci.yml                     # lint+test+打包 (每次 push/PR)
│   └── release.yml                # tag 触发: deb 签名+apt 仓库更新+ISO 构建+QEMU 冒烟+GitHub Release
├── devcontainer/                  # Ubuntu 24.04 开发容器（GTK 调试用）
└── scripts/                       # 本地开发辅助
```

### 13.2 CI 流水线

- **ci.yml**（ubuntu-24.04）：ruff/black 检查 → pytest（单测+API+mock e2e）→ gitleaks → pip-audit → dpkg-buildpackage 三个 deb → 容器内安装冒烟。
- **release.yml**（tag `v*`）：上述全部 + GPG 签名 + apt 仓库索引重建并发布到 Pages + live-build 出 ISO（构建机需 ≥40GB 磁盘，超时 90min）+ QEMU 冒烟 + 上传 Release（iso/deb/SHA256SUMS）。
- 多环境：Dev（devcontainer 直跑，`LINGOS_NO_SYSTEMD=1` + 文件 keyring fallback）/ Staging（VM 装 deb，DashScope 测试 Key）/ Prod（ISO 安装，正式 Key）。差异仅 env 与 Key，代码零分叉。

### 13.3 本地开发命令（关键命令，同步于 TRAE.md）

```bash
# 守护进程（开发模式）
cd daemon && python -m venv .venv && .venv/bin/pip install -e ".[dev]"
LINGOS_NO_SYSTEMD=1 LINGOS_DEV_KEYRING=file .venv/bin/lingos-assistantd   # 前台启动
# 测试 / 质量
.venv/bin/pytest -m "not network" ; .venv/bin/ruff check . ; .venv/bin/black --check .
# UI（必须在 Ubuntu 24.04 环境）
cd ui && python -m lingos_assistant_ui.app
# 打 deb
cd packaging/debian-assistant && dpkg-buildpackage -us -uc
# ISO（需要 root/容器）
cd iso && sudo ./auto/build.sh
```

---

## 14. 架构韧性设计

### 14.1 单点故障识别

| 组件 | 是否单点 | 故障影响 | 应对 |
|------|----------|----------|------|
| DashScope 云端 | 是（外部） | AI 对话不可用 | 熔断+降级文案；V2 支持备用 provider 自动切换 |
| assistantd | 是（本机） | 助手全部功能不可用，**桌面其余部分不受影响** | systemd `Restart=on-failure` + `RestartSec=2`；连续 5 次崩溃进入 start-limit 后桌面通知 |
| gnome-keyring | 系统组件 | 无法取 Key | 守护进程降级为"未配 Key"状态并提示 |
| SQLite 文件 | 是 | 历史丢失 | WAL + integrity_check + 损坏自动备份重建（5.2） |

### 14.2 RTO/RPO

- assistantd 崩溃：RTO ≤ 5s（systemd 自动重启），RPO = 0（消息落库在流式完成前按条提交）。
- 用户数据（`~/.local/share/lingos`）：建议 OOBE 中提示纳入系统备份范围（déjà dup），V1 不做自动云备份。

### 14.3 优雅降级层级

| 级 | 状态 | 用户体验 |
|----|------|----------|
| L0 | 正常 | 全功能 |
| L1 | LLM 熔断 OPEN | 面板可用，发消息立即得到"AI 服务暂不可用"本地文案；历史/设置/审计仍可访问 |
| L2 | 无 Key/Key 失效 | 引导配置页；只读功能可用 |
| L3 | assistantd 反复崩溃 | 桌面通知 + 托盘红点 + "查看诊断日志"入口；系统其余功能完全正常 |
| L4 | GNOME 扩展加载失败 | Super+L 失效，但应用网格仍可手动打开助手窗口（扩展是增强不是依赖） |

### 14.4 超时分级

本地 API 5s / LLM 首 token 60s、整流 300s / shell 命令默认 30s 上限 120s / 连通性测试 10s。全部超时均有对应 UI 文案（5.3）。

---

## 15. 跨系统状态一致性

无支付/外部交易。唯一跨系统交互是 LLM 工具调用循环，一致性规则：`tool_calls.decision` 是唯一事实源；UI 断连重连后必须 `GET /tool-calls/pending` 对账；守护进程崩溃重启后，所有 `pending/confirmed 未执行` 的调用一律置为 `failed`（原因 `daemon_restart`）并通知用户"上次操作因服务重启未完成，请让 AI 重试"——**绝不自动续执行**（防止重启后重放危险命令）。

---

## 16. 第三方服务风险管理

| 服务 | 用途 | 配额/费用模型 | 风险 | 备选 |
|------|------|---------------|------|------|
| DashScope（阿里云百炼） | 默认 LLM | qwen-plus 按 token 计费；新用户有免费额度；有 RPM/TPM 限额 | 429 限流；Key 欠费停用 | 任何 OpenAI 兼容端点（改 base_url+model 即可）；V2 加 Ollama |
| GitHub Pages | apt 仓库托管 | 免费，1GB 空间/100GB 月流量 | 国内访问慢 | 对象存储（OSS）+CDN，切换成本：改一行 sources.list 说明文档 |
| GitHub Actions | CI/ISO 构建 | 免费额度 2000min/月；ISO 构建单次 ~40min | 额度耗尽 | 自建 runner |
| Ubuntu 官方源 | ISO 基础包 | 免费 | 镜像源波动 | live-build 配置可切清华/阿里镜像源 |

**费用预警**：助手设置页显示"本月估算 token 消耗"（本地按消息累计估算，非账单精确值）；DashScope 控制台侧由维护者设置预算告警（手动流程，写入运维手册）。
**冷启动**：新注册的 DashScope 账号先小额充值并跑通 100 次调用再分发内测，避免首月风控限额影响体验。

---

## 17. 事故响应流程（内测期）

| 级别 | 定义 | 响应 |
|------|------|------|
| P0 | 安全类：AI 绕过确认执行了未确认操作 / Key 泄露 | 立即停用工具能力（托盘"暂停工具"），24h 内出修复 deb，发内测群公告 |
| P1 | ISO 装不进系统 / 助手完全不可用 | 48h 修复 |
| P2 | 单功能缺陷（流式中断、diff 预览错误） | 下个补丁版本 |
| P3 | 体验问题 | 排期 |

升级路径：内测群反馈 → 维护者复现 → 定级 → issue。用户沟通：内测群 + Release Notes。事后复盘模板：时间线/根因/影响面/修复/预防项（写入 `docs/postmortems/`）。

---

## 18. 开发里程碑（按周，假设 1 人 + Trae 全职）

| 周 | 交付物 |
|----|--------|
| W1 | 仓库脚手架 + devcontainer + smoke test 全链路（11.2）+ SQLite 迁移器 + conftest 基座 |
| W2 | 守护进程核心：本地 API 18 接口 + WS + token 鉴权 + 会话/消息存储，单测+API 测试全绿 |
| W3 | LLM 客户端：流式/重试/熔断/上下文裁剪 + mock e2e 全绿；keyring 服务 |
| W4 | 工具系统：5 工具 schema + guard 黑名单（≥20 攻击样本全 DENY）+ executor + 确认流 |
| W5 | GTK4 UI：主窗口/快捷面板/确认框/设置页/审计页 + 全部状态机界面 |
| W6 | GNOME 扩展 + OOBE + 品牌设置包（壁纸/主题/dconf） |
| W7 | deb 打包 ×3 + CI 完整流水线 + 容器安装冒烟 + apt 仓库上线 |
| W8 | live-build ISO + QEMU 冒烟（UEFI/BIOS）+ 真机安装内测 + 修复 + v1.0.0 发布 |

**开发模式建议**：Trae 单 Agent 逐周迭代；每周结束跑全量测试再进下一模块；W4（安全）与 W8（ISO）人工重点审查，不全托管。

---

## 19. 环境变量与配置

`.env`（开发用；生产环境配置走 dconf/gsettings + keyring，**不用 .env**）：

```bash
# .env.example —— 提交到 Git 的模板；真实 .env 必须进 .gitignore
LINGOS_ENV=dev                      # dev|staging|prod
LINGOS_HOST=127.0.0.1               # 只允许 127.0.0.1，代码中硬校验
LINGOS_PORT=47831                   # 被占用自动 +1 至 47841
LINGOS_DB_PATH=                     # 默认 ~/.local/share/lingos/assistant.db
LINGOS_LOG_LEVEL=INFO
LINGOS_NO_SYSTEMD=1                 # 开发模式：不依赖 systemd user session
LINGOS_DEV_KEYRING=file             # 开发模式 keyring fallback（生产禁止，代码中 prod 环境强制 libsecret）
# 以下仅开发调试用，生产 Key 一律存 gnome-keyring —— 敏感，不入代码库
LINGOS_LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LINGOS_LLM_MODEL=qwen-plus
LINGOS_DEV_API_KEY=                 # ⚠️ 敏感，禁止提交
```

运行时可调（改后无需重启，经 `PUT /settings` 生效）：model、temperature、max_tokens、context_window、tools_enabled、theme。
特性开关（dconf `com.lingos.assistant`）：`enable-tools`（全局工具总开关）、`enable-oobe`、`enable-prewarmed-panel`（UI 预热）。

---

## 20. 第三方依赖清单（锁版本）

`daemon/pyproject.toml` 核心依赖：

```
fastapi==0.115.6
uvicorn==0.32.1
openai==1.58.1
pydantic==2.10.4
pydantic-settings==2.7.0
httpx==0.28.1
websockets==13.1
# dev: pytest==8.3.4  pytest-asyncio==0.24.0  respx==0.22.0  ruff==0.8.4  black==24.10.0  gitleaks(CI action)  pip-audit==2.7.3
```

系统包依赖（deb Depends）：`python3 (>=3.12), python3-gi, gir1.2-gtk-4.0, gir1.2-adw-1, python3-secretstorage, gnome-keyring, policykit-1, systemd (user session), xdg-utils`。
vendored（打入 `/usr/lib/lingos/venv`，离线可装）：fastapi/uvicorn/openai/pydantic 全家（版本同上）。
UI 无 npm 依赖（纯 GTK）。GNOME 扩展无构建依赖（原生 gjs）。
EOL 关注：Ubuntu 24.04 标准支持至 2029-04；Python 3.12 安全支持至 2028-10；GNOME 46 随 Ubuntu 维护周期。

---

## 21. 生产（用户侧）运维手册

### 21.1 日常命令

```bash
systemctl --user status lingos-assistantd     # 服务状态
journalctl --user -u lingos-assistantd -f     # 实时日志
systemctl --user restart lingos-assistantd    # 重启
cp ~/.local/share/lingos/assistant.db{,.bak}  # 手动备份历史
```

### 21.2 故障排查速查

| 症状 | 排查 |
|------|------|
| Super+L 无反应 | 应用网格手动开助手 → 能开则是扩展问题（`gnome-extensions info lingos@lingos.dev`）；不能开看 `systemctl --user status` |
| AI 一直"服务暂不可用" | 熔断中：查网络 → 设置页"测试连通性" → DashScope 控制台查 Key/欠费 |
| 安装后助手缺失 | `sudo apt install -f`；检查 apt 源 GPG（`sudo apt update` 看 NO_PUBKEY） |
| 历史丢失 | 查 `~/.local/share/lingos/*.corrupt-*` 备份文件 |

### 21.3 更新与回滚

- 更新：`sudo apt update && sudo apt upgrade`（LingOS 仓库随系统源更新）；ISO 大版本走重装或 `do-release-upgrade` 路径（V1 仅支持同版本内更新）。
- 回滚：apt pinning 降级 `sudo apt install lingos-assistant=0.9.x`；数据库迁移只向前——降级前提示用户导出会话 JSON。

---

## 22. 成本估算

| 项 | 一次性 | 月度（内测期 ~100 用户） |
|----|--------|--------------------------|
| 开发设备/VM | 0（本地+CI） | 0 |
| GitHub Actions | 0（免费额度内，ISO 构建 ~10 次/月 ×40min） | 超额时 ~$5/月 |
| DashScope API（开发+内测；用户自带 Key 为主，官方演示 Key 一份） | 充值 ¥100 | ¥50~200（qwen-plus，演示与测试用量） |
| apt 仓库托管（GitHub Pages） | 0 | 0（切 OSS+CDN 时 ~¥30/月） |
| 代码签名证书（可选，V1 用自管 GPG） | 0 | 0 |
| **合计** | **≈ ¥100** | **≈ ¥55~235/月** |

用户侧：每位用户自备 DashScope Key，个人轻度使用月成本约 ¥5~30（qwen-plus 定价，按实际用量）。

---

## 23. 发布检查清单（v1.0.0）

**技术**：全量测试绿；gitleaks/pip-audit 0 告警；三 deb 干净容器装卸冒烟通过；ISO UEFI+BIOS QEMU 冒烟通过；真机（≥1 台）安装走完 OOBE + 两条核心流程；黑名单攻击样本 ≥20 条全 DENY；断网/坏 Key/熔断三场景 UI 表现核对。
**发布物**：iso + 3×deb + SHA256SUMS + GPG 签名 + Release Notes（含安装指南、apt 源一行命令、已知问题）。
**应急**：内测群公告模板；托盘"暂停工具能力"作为 P0 快速止血手段；回滚版本号确认。

---

## 24. 附录

### 24.1 V2 规划（P2，V1 不开发）

本地 Ollama 接入与云-本地自动降级；文件语义搜索（本地向量索引 + 隐私开关）；软件商店 AI 推荐安装；语音输入/TTS；备用 LLM provider 自动切换；ARM64 ISO；AI 生成 GNOME 主题；自研 Wayland 合成器探索（预研性质）。

### 24.2 UI 默认方案

品牌色 #4C6EF5（靛蓝）；图标风格沿用 GNOME 符号化图标；深色模式跟随系统；字体跟随 GNOME 默认（Cantarell 11 / 中文 Noto Sans CJK）。

### 24.3 数据合规说明

- 对话内容会发送至用户配置的 LLM 提供商（默认 DashScope）——OOBE 与设置页必须明示，用户不配 Key 则无任何数据出网。
- 审计日志仅存本机；`file_read` 内容进入 LLM 上下文前经用户确认（确认框展示路径）。
- 项目本身不收集任何遥测（V1 无 telemetry；V2 若加必须 opt-in）。

### 24.4 交接要点

GPG 私钥保管（CI Secrets + 离线备份）、DashScope 账号归属、GitHub 组织权限、ISO 构建机磁盘配额、本文档与 TRAE.md 的更新责任。

### 24.5 变更记录

| 版本 | 日期 | 变更 |
|------|------|------|
| v1.0 | 2026-10-13 | 首版：确认基于 Ubuntu 24.04 LTS + GNOME 46 + DashScope 云端 API 形态 |
