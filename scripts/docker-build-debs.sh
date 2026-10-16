#!/usr/bin/env bash
# 本地构建 3 个 deb（在 ubuntu:24.04 容器内跑，PRD 5.7/13.2）
# 前置：Docker Desktop 运行中（需 WSL2 后端）
# 用法：bash scripts/docker-build-debs.sh

set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

echo "==> 启动 ubuntu:24.04 构建容器"
docker run --rm \
  -v "$(pwd)":/lingos \
  -w /lingos \
  ubuntu:24.04 bash -c '
    set -e
    export DEBIAN_FRONTEND=noninteractive
    # 国内镜像加速（PRD 16）
    sed -i "s|http://archive.ubuntu.com|https://mirrors.aliyun.com|g" /etc/apt/sources.list.d/ubuntu.sources
    apt-get update
    apt-get install -y --no-install-recommends \
      devscripts debhelper python3 ca-certificates \
      libglib2.0-bin curl
    mkdir -p /lingos/dist
    for pkg in debian-assistant debian-extension debian-settings; do
      echo "==> 构建 $pkg"
      cd /lingos/packaging/$pkg
      dpkg-buildpackage -us -uc -b
      cp ../*.deb /lingos/dist/
      rm -f ../*.deb ../*.changes ../*.buildinfo ../*.build
    done
    echo "==> 产物："
    ls -lh /lingos/dist/
  '
