# Ubuntu 24.04 开发容器（PRD 11.5：GTK 调试必须在 Ubuntu 24.04 环境）
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
# 国内镜像加速（可在构建参数覆盖）
RUN sed -i 's|http://archive.ubuntu.com|https://mirrors.aliyun.com|g' /etc/apt/sources.list.d/*.sources 2>/dev/null || true

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv python3-gi \
    gir1.2-gtk-4.0 gir1.2-adw-1 \
    python3-secretstorage gnome-keyring \
    systemd policykit-1 xdg-utils \
    build-essential devscripts debhelper dh-python \
    live-build \
    libgtk-4-dev libadwaita-1-dev \
    xvfb x11-utils \
    curl git jq \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspaces/lingos
