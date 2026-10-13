#!/bin/sh
# live-build 自动构建脚本（PRD 5.7 M8）
# 用法：cd iso && sudo ./auto/build.sh
# 需要：live-build、约 40GB 磁盘、可访问 Ubuntu 源（可切国内镜像，PRD 16）

set -e

lb config noauto \
    --architecture amd64 \
    --distribution noble \
    --archive-areas "main restricted universe multiverse" \
    --parent-mirror-bootstrap "http://archive.ubuntu.com/ubuntu" \
    --mirror-bootstrap "http://archive.ubuntu.com/ubuntu" \
    --parent-mirror-binary "http://archive.ubuntu.com/ubuntu" \
    --mirror-binary "http://archive.ubuntu.com/ubuntu" \
    --bootappend-live "boot=live components locales=zh_CN.UTF-8 keyboard-layouts=cn" \
    --bootloader grub \
    --debian-installer live \
    --iso-volume "LingOS 1.0" \
    --iso-application "LingOS (灵犀 OS)" \
    --iso-publisher "LingOS Maintainers <maintainers@lingos.dev>" \
    "${@}"

lb build
