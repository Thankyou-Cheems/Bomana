# 实机截图说明

页面「实机界面」会探测下列文件；存在则替换空位展示。

| 文件名 | 内容 | 状态 |
|--------|------|------|
| `web-cockpit-desktop.png` | 桌面浏览器网页驾驶舱 | 已收录 |
| `web-cockpit.png` | 手机网页驾驶舱（已裁系统/浏览器栏） | 已收录 |
| `desktop-main.png` | 桌面 Tk 主窗口 | 已收录 |
| `nav-hud.png` | 独立导航航向带 | 已收录 |
| `nav-precision.png` | 航向带内非线性精确对准区 | 已收录 |
| `ccrp-compact.png` | 紧凑 CCRP 标题、选弹与释放提示 | 已收录 |
| `launcher.png` | 启动器（本机路径已脱敏） | 已收录 |

## 处理约定

- 长边约 1600–2200px，PNG。
- 手机图裁掉状态栏、地址栏（尤其内网 IP）和底部系统导航。
- 启动器图勿暴露用户名/完整安装路径。
- Tk 航向带与 CCRP 三图由当前组件直接生成：

```powershell
uv run python tools/capture_pages_tk_shots.py
```

- Web 双图可用：

```bash
uv run python tools/prepare_pages_shots.py <desktop-web.png> <mobile-web.png>
```
