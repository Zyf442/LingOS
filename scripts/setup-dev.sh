#!/usr/bin/env bash
# 开发环境初始化（devcontainer postCreateCommand，PRD 13.3）
set -e

cd daemon
python3 -m venv .venv
.venv/bin/pip install -i https://mirrors.aliyun.com/pypi/simple/ \
    fastapi==0.115.6 uvicorn==0.32.1 openai==1.58.1 \
    pydantic==2.10.4 pydantic-settings==2.7.0 httpx==0.28.1 websockets==13.1 \
    pytest==8.3.4 pytest-asyncio==0.24.0 respx==0.22.0 ruff==0.8.4 black==24.10.0

.venv/bin/pytest -m "not network"
echo ""
echo "开发环境就绪："
echo "  cd daemon && LINGOS_NO_SYSTEMD=1 LINGOS_DEV_KEYRING=file .venv/bin/lingos-assistantd"
echo "  xvfb-run -a python3 ui/lingos_assistant_ui/app.py   # UI 调试（虚拟显示）"
