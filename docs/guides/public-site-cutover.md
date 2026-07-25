# Bomana 介绍站域名迁移指南

本文只处理公开介绍站从 `https://ruikang.wang/bomana/` 迁移到
`https://bomana.ruikang.wang/`。它不迁移 App、Launcher 或地形包更新服务。

## 不变的更新契约

| 用途 | 稳定入口 | 是否随介绍站迁移 |
|------|----------|------------------|
| App / Launcher 版本清单 | `https://bomanaupdate.ruikang.wang/api/v1/...` | 否 |
| App / Launcher / 地形下载 | `https://bomanaupdate.ruikang.wang/downloads/...` | 否 |
| GitHub 备用下载 | GitHub Releases | 否 |
| 介绍、截图与下载入口 | `https://bomana.ruikang.wang/` | 是 |

当前 Launcher 源码以及已审计的 `v1.5.5-launcher` 及以后标签都把更新源
设为独立的 `bomanaupdate.ruikang.wang`，不会请求主站 `/bomana` 路径。
更早的 `v1.1.1-launcher` / `v1.2.0-launcher` 使用另一条旧更新域名并保留
GitHub 回退；它们同样不依赖主站路径。迁移介绍站本身不会改变任何一组
Launcher 的更新行为。

介绍站的版本卡片优先读取随站点部署的同源
`download-catalog.json`。部署工具在维护者电脑上从更新 API 刷新该文件，
浏览器不需要跨域读取更新 API；下载按钮直接指向稳定更新域名。

## 推荐的切换顺序

1. 让 `bomana.ruikang.wang` 指向现有 EdgeOne 站点，并把源站根目录映射到
   `/opt/Website/bomana`。
2. 确认新域名直接返回 `200`，不能把 HTTPS 请求重定向回完全相同的 URL。
3. 使用 `tools/deploy_pages_mirror.py` 发布并验证新域名。
4. 在 `ruikang.wang` 上把 `/bomana` 和 `/bomana/*` 逐路径 `308` 到新域名。
5. 保持 `bomanaupdate.ruikang.wang` 的 DNS、证书、API 和下载路径不变。
6. 清理 EdgeOne 缓存后，验证新入口、旧入口和更新 API，再更新搜索引擎或
   外部书签。

若 EdgeOne 以 HTTP 回源，而 Caddy 对同一主机强制跳转 HTTPS，外部 HTTPS
请求可能表现为“重定向到自己”的循环。本项目采用与 SiguaArmor 发布站相同
的职责划分：EdgeOne 负责访客侧 HTTPS 强制跳转并以 HTTPS 回源，Caddy
同时提供显式 HTTP/HTTPS 主机块，HTTPS 源站使用内部证书。EdgeOne 不校验
该源站证书，但回源链路保持加密。

可部署配置已经固化在：

- `deploy/bomana-pages/Caddyfile.snippet`：新域名静态站与源站缓存头；
- `deploy/bomana-pages/legacy-redirect.caddy`：插入现有
  `http://ruikang.wang` 主站块的路径保留跳转；
- `deploy/bomana-pages/edgeone-domain.template.json`：独立 HTTPS 回源
  加速域；
- `deploy/bomana-pages/edgeone-rule.template.json`：仅匹配
  `bomana.ruikang.wang` 的 HTTPS 与缓存规则。

这些规则不得挂载到 `*.ruikang.wang` 通配加速域，否则会连带改变
`bomanaupdate.ruikang.wang`。页面、脚本和同源版本清单缓存 60 秒；截图等
稳定文件名资源只缓存一小时，而不是使用永久 immutable 缓存。

## 切换前验收

在 Windows 维护机上执行：

```powershell
curl.exe -sS -I --max-redirs 0 https://bomana.ruikang.wang/
curl.exe -sS -I --max-redirs 0 https://ruikang.wang/bomana/
curl.exe -sS -I --max-redirs 0 https://ruikang.wang/bomana/assets/bomana-app.png
curl.exe -sS -D - -o NUL "https://bomanaupdate.ruikang.wang/api/v1/version?channel=Enhanced"
```

必须同时满足：

- 新域名首页返回 `200`；
- 旧首页返回 `308`，`Location` 为 `https://bomana.ruikang.wang/`；
- 旧资源路径返回 `308`，并保留 `/assets/bomana-app.png`；
- 更新 API 返回 `200`，且域名仍是 `bomanaupdate.ruikang.wang`；
- 新站的 Launcher/App 按钮最终都指向更新域名或 GitHub 备用下载；
- 浏览器桌面与窄屏视图均能加载 `download-catalog.json`、航向带和 CCRP
  截图。

完成上述检查前，不要删除旧 `/bomana` 路由，也不要把更新域名改成介绍站
域名。
