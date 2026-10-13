# TRAE.md — LingOS 项目入口规则（Trae / AI 编程工具必读）

> 本文件与 `docs/PRD.md` 是唯一真相源。任何未在 PRD 中定义的依赖、接口、行为，开发前必须先补充到 PRD 再实现。

## 项目概述

LingOS（灵犀 OS）：基于 Ubuntu 24.04 LTS + GNOME 46 的 AI 原生 Linux 定制发行版。
核心组件：`lingos-assistantd`（Python 守护进程）+ `lingos-assistant-ui`（GTK4）+ GNOME Shell 扩展 + deb/ISO/apt 仓库。

## 仓库结构

```
daemon/     Python 守护进程（FastAPI, 127.0.0.1:47831, token 鉴权）
ui/         GTK4 + libadwaita 桌面应用（PyGObject，禁止 pip 装 PyGObject）
extension/  GNOME 46 Shell 扩展（gjs ESM，禁用旧式 imports 语法）
packaging/  3 个 deb 包（assistant / extension / default-settings）+ systemd unit
iso/        live-build 配置
repo/       apt 仓库生成（apt-ftparchive + GPG）
devcontainer/  Ubuntu 24.04 开发容器（GTK 调试必须在此环境）
scripts/    本地开发辅助脚本
```

## 关键命令

```bash
# 守护进程（开发模式）
cd daemon && python -m venv .venv && .venv/bin/pip install -e ".[dev]"
LINGOS_NO_SYSTEMD=1 LINGOS_DEV_KEYRING=file .venv/bin/lingos-assistantd   # 前台启动

# 测试 / 质量
cd daemon && .venv/bin/pytest -m "not network"
.venv/bin/ruff check . && .venv/bin/black --check .

# UI（必须在 Ubuntu 24.04 环境 / devcontainer 内）
cd ui && python -m lingos_assistant_ui.app

# 打 deb（Ubuntu 24.04）
cd packaging/debian-assistant && dpkg-buildpackage -us -uc

# ISO（需要 root/容器）
cd iso && sudo ./auto/build.sh
```

## 开发规约（违反即返工）

1. **时间**：一律 ISO8601 UTC 字符串（`...Z` 结尾）；Python 用 `datetime.now(timezone.utc)`，禁止 `datetime.utcnow()`。
2. **主键**：UUIDv7 字符串（`lingos_assistantd.ids.uuid7()`），TEXT 存储。
3. **空值**：DB NULL ↔ None ↔ JSON null 一一对应；禁止 `""` 表示"无值"入库。
4. **枚举**：全小写字符串，前后端一致。
5. **安全**：guard 黑名单命中 = DENY 不可确认；默认拒绝未知工具；API Key 永不出现在日志/响应/LLM 请求回显中。
6. **测试**：单测永远 mock LLM（`@pytest.mark.network` 的真实 API 测试默认不跑）；SQLite 用 tmp_path；端口用 0。
7. **路径**：全部 pathlib + XDG 规范，禁止硬编码 `/home/xxx`。
8. **守护进程绝不以 root 运行**；所有写/执行类工具必须经用户确认（system_info 除外）。
9. GNOME 46 扩展只支持 ESM；PyGObject 用系统包（python3-gi），不要 pip 安装。

## 禁止事项

- ❌ 引入 PRD 之外的新依赖（先改 PRD）
- ❌ AI 助手任何形式的 sudo/polkit 提权路径（V1 明确不开放）
- ❌ 把 API Key / token 写入明文配置、日志或错误信息
- ❌ 在守护进程绑定 127.0.0.1 以外的地址、添加 CORS
- ❌ 未经确认执行任何 shell 命令或文件写删（system_info 只读除外）
