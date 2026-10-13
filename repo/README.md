# apt 仓库（GitHub Pages 托管，PRD 16）

本目录脚本由 CI（release.yml）在打 tag 时执行：

1. `build-repo.sh dist/ repo-out/` —— apt-ftparchive 生成 `Packages.gz` 与签名 `Release`
2. 产物发布到 GitHub Pages（`stable` 分支 / Pages 站点）

用户端一行命令添加源：

```bash
curl -fsSL https://lingos.github.io/repo/lingos.asc | sudo tee /etc/apt/keyrings/lingos.asc
echo "deb [signed-by=/etc/apt/keyrings/lingos.asc] https://lingos.github.io/repo stable main" | sudo tee /etc/apt/sources.list.d/lingos.list
sudo apt update && sudo apt install lingos-assistant
```

> 国内访问慢时切 OSS+CDN（改 sources.list 即可，见 PRD 第 16 章）。
