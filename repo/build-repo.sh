#!/bin/bash
# apt 仓库构建（PRD 5.7 M9）：apt-ftparchive 生成索引 + GPG 签名，静态托管（GitHub Pages）。
# 用法：repo/build-repo.sh <debs目录> <输出目录>
# 依赖：apt-utils（apt-ftparchive）、gpg（私钥在 CI Secrets 注入）

set -euo pipefail

DEBS_DIR="${1:-../dist}"
OUT_DIR="${2:-./repo-out}"
GPG_KEY="${LINGOS_GPG_KEY:-}"

mkdir -p "$OUT_DIR/pool/main" "$OUT_DIR/dists/stable/main/binary-amd64"
cp -v "$DEBS_DIR"/*.deb "$OUT_DIR/pool/main/"

cat > "$OUT_DIR/dists/stable/main/binary-amd64/Release" <<EOF
Archive: stable
Component: main
Origin: LingOS
Label: LingOS apt repository
Architecture: amd64
EOF

# Packages 索引
cd "$OUT_DIR"
apt-ftparchive packages pool/main > dists/stable/main/binary-amd64/Packages
gzip -kf dists/stable/main/binary-amd64/Packages

# 顶层 Release（含校验和）+ 签名
apt-ftparchive -o APT::FTPArchive::Release::Origin="LingOS" \
    -o APT::FTPArchive::Release::Suite="stable" \
    -o APT::FTPArchive::Release::Codename="stable" \
    -o APT::FTPArchive::Release::Architectures="amd64" \
    -o APT::FTPArchive::Release::Components="main" \
    release dists/stable > dists/stable/Release

if [ -n "$GPG_KEY" ]; then
    gpg --batch --yes --default-key "$GPG_KEY" \
        --armor --detach-sign --output dists/stable/Release.gpg dists/stable/Release
    gpg --batch --yes --default-key "$GPG_KEY" \
        --armor --export > lingos.asc
    echo "已签名（公钥：$OUT_DIR/lingos.asc）"
else
    echo "警告：未提供 GPG_KEY，索引未签名（内测可用，正式发布必须签名）" >&2
fi

echo "仓库构建完成：$OUT_DIR"
echo "用户安装："
echo "  curl -fsSL <repo-url>/lingos.asc | sudo tee /etc/apt/keyrings/lingos.asc"
echo "  echo \"deb [signed-by=/etc/apt/keyrings/lingos.asc] <repo-url> stable main\" | sudo tee /etc/apt/sources.list.d/lingos.list"
