# Bomana 隐私说明

**最后更新：2026-08-31**

Bomana App 通过 Web 运行；本机 Bridge 只转发官方 War Thunder ExtUI 并管理签名地形缓存。Bridge 不保存 Enhanced、账号授权、计算逻辑或统计身份，也不上报日活。

## 匿名日活

当 Lite、Standard 或已授权 Enhanced 成功初始化后，Web 会以尽力而为方式向
`https://bomanaupdate.ruikang.wang/api/v1/telemetry/dau`
发送一次匿名日活。一次请求严格只有：

```json
{
  "schema_version": 1,
  "install_day_token": "64 位小写十六进制 HMAC",
  "channel": "Lite"
}
```

- Web 在当前浏览器中生成随机 32 字节安装秘密；秘密永不上传。
- `install_day_token` 是安装秘密对当前 UTC 日期的 HMAC-SHA-256，因此每天变化，无法跨日关联。
- 三个 Edition 共用同一秘密和每日令牌；同一浏览器安装每天总体只计一次，服务端保留当天首次接受的 Edition 供聚合拆分。
- 上报不包含 CheemsPay 账号、权益、IP 字段、硬件标识、版本、8111、地图、飞机、武器、投弹结果、文件路径或 Bridge 数据。
- HTTPS/CDN 基础设施仍会看到普通连接元数据；匿名 DAU 数据表不会保存请求 IP 或 User-Agent。
- 网络或存储失败会静默处理，不阻塞 App，也不会转投旧版事件接口。

Launcher 在“技术详情 → 匿名日活”中以普通说明展示该默认策略，不要求用户理解或管理低层统计开关。

匿名日活的原始每日去重令牌滚动保留 30 个 UTC 日；每日、每 Edition 的聚合数量长期保留。聚合数据公开于：

- `https://bomanaupdate.ruikang.wang/api/v1/stats/daily`
- `https://bomanaupdate.ruikang.wang/api/v1/stats/daily/list`

## 游戏与本机数据

Web 只通过 Bridge 读取本机 War Thunder ExtUI 数据。Bridge 仅检查固定回环端口 `8111`、`9222`、`10333`，不会连接用户指定或任意上游。Bomana 不读取游戏进程内存，不注入代码，不修改游戏文件，不控制游戏，也不把 ExtUI 数据或计算结果发送到日活服务或 CheemsPay。

地形大文件由 Bridge 按签名地形目录缓存。求解器、WASM、武器目录与 Enhanced 实现由 Web 在线加载并在浏览器会话中运行，不进入 Bridge 持久缓存。

同一台电脑的桌面 Web、手机 Web 与置顶窗可通过 Bridge 同步当前武器目录 ID。Bridge 仅在内存中保存最长 128 字符的受限 ID 和单调修订号，重启即清除；它不保存挂载、弹道、解算结果、Edition、账号或游戏状态，也不会把该 ID 上传到服务器。

为恢复误关的桌面 Web，Standard/Enhanced 会在当前浏览器站点数据中保存最多 15 分钟的同地图 Sortie Resume Checkpoint，包括计时起点、目标/手动 POI 选择和清单勾选。该记录不包含原始 8111 frame、油耗历史、地面航迹、敌机历史或 Solver 结果；地图签名不匹配、超时或清除站点数据都会使其失效。J3/坠机或超时重置另保留最多 30 秒的同类耐久状态用于用户撤销，同样不保存或恢复实时遥测与解算结果。

用户从 Web 或 Bridge 托盘开启“手机配对”后，Bridge 会临时监听当前电脑的私有 IPv4 局域网接口。用户可选择公开 Standard 或 Enhanced：Standard 不请求 CheemsPay，也没有手机 Lease；Enhanced Web 入口使用电脑端已经授权的会话代为取得手机 Lease，因此手机无需登录。托盘 Enhanced 入口不接触电脑账号，手机若没有现成授权则在手机浏览器中登录 CheemsPay，再把签名手机 Lease 经 URL fragment 带回本地 Bridge。Enhanced 手机页面与 Bridge 都会独立校验 Lease 签名、用途、配对 ID 和有效期；Bridge 永不接收手机或电脑的 CheemsPay access token。

用户可选择候选网络并生成二维码；局域网地址、随机配对 ID、临时 Bridge 令牌、Enhanced 托盘入口的签名手机 Lease，以及可选的提示音总开关、倒计时/战区摧毁开关和内置音频方案编号，只存在于二维码/跳转 URL fragment、Bridge 临时内存和手机本地浏览器中，不会作为公共页面请求发送到 Bomana。为允许误关标签页后重开，手机的精确私有 Bridge origin 会把 Bridge 令牌和可选的 Enhanced 手机 Lease 保存在该 origin 的本地站点数据中，并按页面活动滚动刷新最长 15 分钟的重开期限；它绝不超过更早的 Bridge/Lease 到期时间。CheemsPay 仅接收随机配对 ID，不接收局域网地址、Bridge 令牌或 8111。fragment 不包含自定义音频文件、账号或游戏数据。手机直接连接 Bridge，8111、地图、目标、武器与解算数据不经过服务器，Enhanced 解算继续在手机浏览器的 Worker/WASM 中完成。配对最长 8 小时，重新生成会使旧 Bridge 令牌失效。

## CheemsPay

Lite 与 Standard 不需要 CheemsPay。Enhanced 使用 CheemsPay 设备授权和最长 14 天的签名访问租约。手机配对另使用一次性、最长 5 分钟的票据换取最长 8 小时且绑定本次 Bridge 配对的手机租约；CheemsPay 只接收不含局域网地址的随机配对 ID。Bomana 不接收 CheemsPay 密码或支付资料；日活令牌也不使用账号或权益生成。

## 用户控制

- 清除当前浏览器的 Bomana 站点数据会同时移除本地偏好、匿名安装秘密和授权缓存。
- 手机配对令牌保存在二维码所选的私有 Bridge origin；若要立即移除它，还需清除该局域网地址对应的站点数据，或在电脑上重新生成/撤销配对会话。
- CheemsPay 账号、订单与权益需在 CheemsPay 账户页面管理。

如有疑问，请通过项目 GitHub Issues 或 Bomana/CheemsPay 支持页面联系维护者。
