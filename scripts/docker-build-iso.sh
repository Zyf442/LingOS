#!/usr/bin/env bash
# 本地构建 LingOS ISO（live-build，PRD 5.7/13.2）
# 前置：Docker Desktop 运行中；建议 ≥40GB 磁盘（E: 盘有足够空间）
# 用法：bash scripts/docker-build-iso.sh [输出目录]

set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT_DIR="${1:-$REPO_ROOT/dist}"
cd "$REPO_ROOT"

echo "==> 在 ubuntu:24.04 特权容器中构建 ISO（约 30-60 分钟）"
docker run --rm --privileged \
  -v "$(pwd)":/lingos \
  -w /lingos \
  -e VERSION="${VERSION:-1.0.0}" \
  ubuntu:24.04 bash -c '
    set -e
    export DEBIAN_FRONTEND=noninteractive
    sed -i "s|http://archive.ubuntu.com|https://mirrors.aliyun.com|g" /etc/apt/sources.list.d/ubuntu.sources
    apt-get update
    apt-get install -y --no-install-recommends \
      live-build debootstrap xorriso mtools squashfs-tools \
      isolinux syslinux-utils grub-pc-bin grub-efi-amd64-bin \
      dosfstools ca-certificates curl
    df -h /lingos | tail -1
    cd /lingos/iso
    ./auto/build.sh
    mkdir -p /lingos/dist
    cp -v *.iso /lingos/dist/lingos-${VERSION}-amd64.iso
    ls -lh /lingos/dist/
  '
echo "==> ISO 已生成，可直接在 VMware 中新建虚拟机并挂载 CD/DVD 使用"
