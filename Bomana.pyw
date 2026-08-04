#!/usr/bin/env python3
# ruff: noqa: E402
"""
Bomana app entrypoint for the War Thunder SB timer and navigation UI.

This file intentionally stays thin. It wires startup diagnostics, runtime
compatibility checks, single-instance protection, Windows DPI setup, and the
top-level `App` object. Feature logic belongs under `bomana/`.

Runtime inputs:
- `/indicators`
- `/state`
- `/map_obj.json`
- `/map_info.json`

Maintenance notes:
- Respect `ENABLE_*` feature flags and shared variant behavior in
  `bomana/config/`.
- Bump `__version__` in `bomana/metadata.py` for user-visible releases.
- Project documentation and maintained contracts live in `docs/`.
"""

from bomana_version import validate_app_launcher_identity

validate_app_launcher_identity()

import os
import tkinter as tk

from bomana.anonymous_dau import start_daily_active_report
from bomana.config.settings import FileConfig
from bomana.metadata import __version__
from bomana.ui.app import App
from bomana.utils.diagnostics import (
    app_context,
    configure_diagnostics,
    log_event,
    shutdown_diagnostics,
)
from bomana.utils.system import SingleInstanceManager, Win32

# ============================================================================
# 程序入口
# ============================================================================


def main():
    """主函数"""
    log_path = configure_diagnostics(FileConfig.CONFIG_FILE.with_name(".wttimer_diagnostics.log"))
    log_event("app_start", version=__version__, log_path=str(log_path or ""), **app_context())

    # 确保单实例运行
    SingleInstanceManager.ensure_single_instance_or_exit()

    # Green Lite bypasses the Launcher, so it schedules the shared anonymous
    # daily-active contract after local startup is ready.  The daemon reporter
    # swallows every storage, serialization, and transport failure.
    if os.environ.get("BOMANA_DISTRIBUTION_MODE", "").strip().lower() == "green":
        start_daily_active_report(channel="Lite", installation_scope="green")

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
