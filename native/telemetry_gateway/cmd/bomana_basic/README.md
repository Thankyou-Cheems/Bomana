# Bomana 精简桌面版 | Basic Desktop

只保留周期计时与官方战区、机场的距离和航向导航。Windows x64 单个
`BomanaBasic.exe`，直接双击，无需安装、登录、Bridge、浏览器或本地计算模块。
程序由 Go 和 Windows 原生控件编写，不需要 Java/JVM；本机 HTTP 读取使用系统 WinHTTP。

- 默认 15 分钟，进入有效飞机状态后开始计时；右键可重新计时。
  周期可设为 1–180 分钟。它是本地周期参考，不读取服务器结算时刻。
- 默认选择前方目标；右键可以固定某个战区或机场。橙色菱形表示战区，
  跑道形状表示机场，青色表示友方机场；带下划线的是当前目标。
  目标转出航向带后，选中目标和友方机场保留边缘箭头。
- 拖动窗口移动，始终置顶；游戏使用窗口化或无边框窗口模式。
  独占全屏中的覆盖显示不保证可用。
- 右键 → 设置：背景、文字、航向带图标透明度分别为 0–100%，背景可完全透明，
  默认无边框；可选显示边框、鼠标穿透和窗口宽度。
- 完全透明或鼠标穿透后，左键系统托盘图标或再次运行 EXE 打开设置，
  点击“恢复默认外观”即可恢复。若快捷键注册成功，设置会显示该快捷键
  （优先 `Ctrl+Alt+M`，占用时尝试 `Ctrl+Alt+Shift+M`）。
- 外观、计时周期和位置保存在 `%LOCALAPPDATA%\Bomana\BasicDesktop\settings.json`。
  点击“完成”保存设置；鼠标穿透每次启动关闭，退出程序后计时重新开始。
- 数据暂断时短暂保留计时；旧导航最多保留 3 秒。退出飞机或持续断开后重新计时。
  本版不包含投弹计算、POI / Y66 模块推断、燃油、降落辅助、地图图片、手机、音效或更新器。

Build manually from clean committed source with Go 1.25+ and PowerShell 7:

```powershell
pwsh -NoProfile -File tools/build_basic_desktop.ps1 -Version 0.1.2
```

The builder strips symbols, rejects unexpected linked packages, checks the GUI
subsystem and application icon, and launches the actual EXE alone in a temporary
directory. It does not bundle a browser, fonts, a kernel, catalogs or another executable. No UPX or
other executable packer is used. Send only `dist/basic-desktop/0.1.2/BomanaBasic.exe`;
`build-info.json` is maintainer evidence and is not required by users.

The EXE, native windows and tray reuse `bomana/assets/web/favicon.svg`. The
committed `app.ico` and `rsrc_windows_amd64.syso` contain compressed 16/32/48/256 px
frames. After changing the SVG, run `pwsh -NoProfile -File tools/generate_basic_icon.ps1`
with the frontend's frozen dependencies, Edge, Node and Go installed. These are
maintenance tools only; regular Go builds use the committed resource and the
product needs no SVG renderer or external icon file.

Automated tests cover source/clock/navigation behavior and real native window,
settings and alpha composition. Real War Thunder acceptance is separate from
these tests. See `docs/specs/basic-desktop.md` for the supported boundary.

WinHTTP requests use asynchronous completions with a 600 ms total deadline.
Cancellation closes the request, and its read buffer stays pinned until the last
handle callback completes; see
[Microsoft's concurrency contract](https://learn.microsoft.com/en-us/windows/win32/winhttp/concurrency-in-winhttp).
