#!/usr/bin/env python3
"""
Bomana app entrypoint for the War Thunder SB timer and navigation UI.

This file intentionally stays thin. It wires startup diagnostics, runtime
compatibility checks, single-instance protection, Windows DPI setup, and the
top-level `App` object. Feature logic belongs under `bomana/`.

Compliance boundary:
- Use only the official localhost:8111 API.
- Do not read game memory, inject code, or modify game files.
- Do not surface enemy-only or otherwise player-invisible information.

Runtime inputs:
- `/indicators`
- `/state`
- `/map_obj.json`
- `/map_info.json`

Maintenance notes:
- Respect `ENABLE_*` feature flags and shared variant behavior in
  `bomana/config.py`.
- Bump `__version__` in `bomana/config.py` for user-visible releases.
- Project-wide workflow and documentation rules live in `AGENTS.md` and
  `docs/`.
"""
import sys
import tkinter as tk
from tkinter import messagebox

from bomana.config import FileConfig, __version__
from bomana.ui.app import App
from bomana.utils.diagnostics import app_context, configure_diagnostics, log_event, shutdown_diagnostics
from bomana.utils.system import SingleInstanceManager, Win32

# ============================================================================
# 程序入口
# ============================================================================

def main():
    """主函数"""
    log_path = configure_diagnostics(FileConfig.CONFIG_FILE.with_name(".wttimer_diagnostics.log"))
    log_event("app_start", version=__version__, log_path=str(log_path or ""), **app_context())

    if sys.version_info < (3, 14):
        try:
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror(
                "Bomana",
                (
                    f"当前运行时过旧，Bomana {__version__} 需要 Python 3.14+。\n"
                    "如果你是通过绿色版启动器启动，请先更新启动器到 1.5.0 或更高版本。"
                ),
                parent=root,
            )
            root.destroy()
        except Exception:
            pass
        raise SystemExit(f"Bomana {__version__} requires Python 3.14+.")

    # 确保单实例运行
    SingleInstanceManager.ensure_single_instance_or_exit()
    
    # 启用DPI感知
    Win32.enable_dpi()
    
    # 隐藏控制台窗口
    Win32.hide_console()
    
    # 创建主窗口和应用
    root = tk.Tk()
    App(root)
    try:
        root.mainloop()
    finally:
        log_event("app_exit", version=__version__)
        shutdown_diagnostics()


if __name__ == "__main__":
    main()

