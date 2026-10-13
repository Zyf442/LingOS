# LingOS（灵犀 OS）

基于 **Ubuntu 24.04 LTS + GNOME 46** 的 AI 原生 Linux 定制发行版。

- 系统级 AI 助手作为一等公民：守护进程 + `Super+L` 全局快捷键唤起的桌面 UI
- 云端大模型（默认 DashScope qwen-plus，OpenAI 兼容 API，可换任意端点）
- 能对话、能执行系统任务（shell / 文件 / gsettings），所有危险操作需用户确认，黑名单命令直接拒绝
- 提供自有 apt 仓库与可安装 ISO；也可只装 `lingos-assistant` deb 到任意 Ubuntu 24.04

> 完整产品需求见 `docs/PRD.md`；开发规则见 `TRAE.md`。

## 仓库结构

| 目录 | 说明 |
|------|------|
| `daemon/` | `lingos-assistantd` 守护进程（FastAPI + SQLite + LLM 客户端 + 工具执行器） |
| `ui/` | `lingos-assistant-ui` GTK4/libadwaita 桌面应用 |
| `extension/` | GNOME Shell 46 扩展（全局快捷键 / 托盘） |
| `packaging/` | 3 个 deb 包 + systemd user service |
| `iso/` | live-build ISO 构建配置 |
| `repo/` | apt 仓库生成脚本（apt-ftparchive + GPG） |
| `devcontainer/` | Ubuntu 24.04 开发容器 |
| `scripts/` | 本地开发辅助 |

## 快速开始（开发模式）

```bash
cd daemon
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
LINGOS_NO_SYSTEMD=1 LINGOS_DEV_KEYRING=file .venv/bin/lingos-assistantd
# token/port 写入 $XDG_RUNTIME_DIR/lingos/{assistant.token,port}
```

## 安装（用户侧）

```bash
# 方式一：LingOS ISO（见 Releases）
# 方式二：任意 Ubuntu 24.04 上安装 deb
curl -fsSL https://lingos.github.io/repo/pubkey.gpg | sudo tee /etc/apt/keyrings/lingos.asc
echo "deb [signed-by=/etc/apt/keyrings/lingos.asc] https://lingos.github.io/repo stable main" | sudo tee /etc/apt/sources.list.d/lingos.list
sudo apt update && sudo apt install lingos-assistant
```

## 许可证

AGPL-3.0（待定）
