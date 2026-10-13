#!/usr/bin/env bash
# 开发模式一键启动（PRD 13.3）
set -e
cd "$(dirname "$0")/../daemon"
export LINGOS_NO_SYSTEMD=1
export LINGOS_DEV_KEYRING=file
exec .venv/bin/lingos-assistantd
