# Code Review Report

**Open findings:** 5 high, 6 medium
**Resolved:** 0  |  **Generated:** 2026-06-17T13:44:54+00:00

## F-dda5869e [HIGH/confirmed] Manual release workflow falls back to dev because it greps config.py for version
`.github/workflows/build.yml:58-74`
```
          if [ -n "${{ github.event.inputs.version }}" ]; then
            VERSION="${{ github.event.inputs.version }}"
            echo "版本来源: 手动输入"
          elif [[ "$TAG_REF" =~ ^v(.+)-app$ ]]; then
            VERSION="${BASH_REMATCH[1]}"
            AUTO_TARGET="app"
            echo "版本来源: Git Tag (app only)"
          elif [[ "$TAG_REF" =~ ^v(.+)-launcher$ ]]; then
            VERSION="${BASH_REMATCH[1]}"
            AUTO_TARGET="launcher"
            echo "版本来源: Git Tag (launcher only)"
          elif [[ "${GITHUB_REF}" == refs/tags/* ]]; then
            VERSION="${GITHUB_REF#refs/tags/v}"
            echo "版本来源: Git Tag"
          else
            VERSION=$(grep -oP '__version__\s*=\s*["\x27]\K[^"\x27]+' bomana/config.py || echo "dev")
            echo "版本来源: 源代码 __version__"
```
- **Impact:** A workflow_dispatch release with an empty version input now reads no literal version from bomana/config.py and emits dev, producing vdev and dev-labeled artifacts.
- **Fix:** Read __version__ from bomana/metadata.py in the workflow fallback, and fail release preparation if the resolved version is empty or dev.
- **Evidence:** [runtime] Running the same grep against bomana/config.py in this checkout returns no match and falls back to dev.; [read] bomana/config.py re-exports __version__ from metadata, while bomana/metadata.py contains the literal __version__ value.

## F-598db3d6 [HIGH/confirmed] Telemetry fetcher skips /state whenever /indicators fails
`bomana/core/telemetry.py:280-284`
```
        if not data.ind_ok:
            return data

        # 请求 /state (飞机状态)
        state_result = self.http.get_json(f"{NetworkConfig.API_BASE}/state", budget)
```
- **Impact:** When /indicators times out or returns bad JSON but /state is still healthy, the main tick never samples /state, reports state_resp_ok as false with an empty error, and loses /state as an independent API-up signal.
- **Fix:** Continue fetching /state while budget remains even when /indicators fails, or explicitly mark /state as not_fetched if the skip is intentional.
- **Evidence:** [runtime] A FakeHttp probe with /indicators failing and /state succeeding recorded only the /indicators URL; state_resp_ok stayed False and ias_kmh stayed 0.; [read] tools/sample_8111_attitude.py requests /indicators and /state independently, so the endpoints are not inherently coupled.

## F-765d37d7 [HIGH/confirmed] Hotkey settings restart stops a non-existent manager
`bomana/ui/dialogs.py:1748-1757`
```
        # 重启热键服务（如果需要）
        need_restart_hotkeys = (
            previous["hotkeys_enabled"] != HotkeyConfig.GLOBAL_HOTKEYS
            or hotkey_bindings != previous["hotkey_bindings"]
        )
        if need_restart_hotkeys:
            if hasattr(self.app, "_ghk") and self.app._ghk:
                self.app._ghk.stop()
            if HotkeyConfig.GLOBAL_HOTKEYS:
                self.app._init_global_hotkeys()
```
- **Impact:** On Windows, changing or disabling global hotkeys from settings leaves the old AppRuntimeServices.global_hotkeys listener running, so old shortcuts can keep firing or keep RegisterHotKey IDs occupied.
- **Fix:** Restart hotkeys through AppRuntimeServices.stop_global_hotkeys() before reinitializing, and make init_global_hotkeys stop any existing manager before replacing the reference.
- **Evidence:** [grep] rg '_ghk|global_hotkeys' shows dialogs.py is the only _ghk reference; the real manager is runtime_services.global_hotkeys.; [read] AppRuntimeServices.init_global_hotkeys assigns self.global_hotkeys = None before creating a new manager and does not stop the old manager first.

## F-46da3c19 [HIGH/confirmed] Config migration resets hidden panel preferences after first save
`bomana/utils/file_utils.py:225-260`
```
        # 检查编译开关是否变化（精简版 <-> 完整版切换）
        saved_switches = config.get("compile_switches", {})
        current_switches = {
            "ENABLE_CCRP": ENABLE_CCRP,
            "ENABLE_ZONES": ENABLE_ZONES,
            "ENABLE_AIRFIELDS": ENABLE_AIRFIELDS,
            "ENABLE_FUEL": ENABLE_FUEL,
            "ENABLE_CHECKLIST": ENABLE_CHECKLIST,
        }

        # 如果某个功能从禁用变为启用，重置该面板为默认显示
        panels = config.get("panels", {})
        switches_changed = False

        for switch_name, current_enabled in current_switches.items():
            was_enabled = saved_switches.get(switch_name, False)
            if current_enabled and not was_enabled:
                # 功能从禁用变为启用，重置对应面板为显示
                panel_key = {
                    "ENABLE_CCRP": "show_bombing",
                    "ENABLE_ZONES": "show_zones",
                    "ENABLE_AIRFIELDS": "show_airfields",
                    "ENABLE_FUEL": "show_fuel",
                    "ENABLE_CHECKLIST": "show_checklist",
                }.get(switch_name)
                if panel_key:
                    panels[panel_key] = True
                    switches_changed = True
                    changed = True

        if switches_changed:
            config["panels"] = panels

        # 更新保存的编译开关状态
        if saved_switches != current_switches:
            config["compile_switches"] = current_switches
```
- **Impact:** A saved config without compile_switches treats every current feature as newly enabled on the next load, overwriting user hidden panel choices such as show_zones=false back to true.
- **Fix:** Persist current compile_switches in ConfigManager.save, and only reset panels when a previous compile_switches block explicitly shows a feature changed from disabled to enabled.
- **Evidence:** [runtime] A temporary ConfigManager.save({'panels': {'show_zones': False, 'show_fuel': False}}) followed by load returned both fields as True and added compile_switches.; [read] ConfigManager.save only writes config_version before atomic_write_json and does not add compile_switches.

## F-17e5ea82 [HIGH/confirmed] App --version build labels the package without updating packaged metadata
`tools/build_portable.py:363-371`
```
        app_version = args.version.strip() or read_version(metadata_text)
        min_launcher_version = read_min_launcher_version(metadata_text)

        if args.target in ("all", "app"):
            patched = replace_switches(original, VARIANT_SWITCHES[args.variant])
            if patched != original:
                config_path.write_text(patched, encoding="utf-8")
                config_patched = True
            app_zip = build_app_zip(root, args.variant, app_version, out_dir)
```
- **Impact:** Building an app package with --version can produce a manifest and zip filename for one version while the installed app still reports the source metadata version, causing repeated update prompts and untrustworthy release metadata.
- **Fix:** Reject --version values that differ from bomana/metadata.py for app builds, or patch the packaged metadata file inside the build output consistently.
- **Evidence:** [runtime] Built --target app --version 9.9.9; manifest app_version was 9.9.9, zip bomana/metadata.py still had __version__ = 6.14.4, and read_local_app_version returned 6.14.4.

## F-ed18df31 [MEDIUM/confirmed] LogicPoller swallows GameLogic.tick exceptions without diagnostics
`bomana/ui/runtime.py:41-45`
```
            try:
                self.game.tick()
            except Exception:
                time.sleep(NetworkConfig.BACKOFF_MAX)
                continue
```
- **Impact:** If the background 8111 polling loop hits a regression, users see stale or delayed data while diagnostics contain no exception event explaining the failure.
- **Fix:** Log tick exceptions with diagnostics, preferably with throttling, then keep the existing backoff behavior.
- **Evidence:** [read] No log_exception call exists in bomana/ui/runtime.py and existing runtime threading tests only cover the successful tick path.; [grep] rg 'logic_poller|tick_failed|BACKOFF_MAX' shows only the silent sleep/continue path for LogicPoller errors.

## F-cb582860 [MEDIUM/confirmed] Default pytest capture breaks the smoke gate in WSL Windows-temp environments
`pyproject.toml:30-30`
```
addopts = "-q"
```
- **Impact:** When tempfile uses /mnt/c/Users/.../Temp, pytest fd capture fails before running tests, making uv run --extra dev pytest report no tests ran even though the suite passes.
- **Fix:** Set a stable capture mode such as --capture=sys for local smoke commands, or document/export TMPDIR=/tmp for WSL runs.
- **Evidence:** [runtime] uv run --extra dev pytest failed with FileNotFoundError in _pytest/capture.py and no tests ran; env TMPDIR=/tmp uv run --extra dev pytest passed with 94 tests.; [runtime] A direct tempfile.TemporaryFile(...).truncate() probe fails under /mnt/c/Users/cheb2/AppData/Local/Temp and passes under TMPDIR=/tmp.

## F-e2f05678 [MEDIUM/confirmed] build_portable --target all emits checksum names deploy_update_assets rejects
`tools/build_portable.py:330-335`
```
    if target == "launcher":
        path = out_dir / "checksums_launcher.txt"
    elif target == "app":
        path = out_dir / f"checksums_app_{variant}.txt"
    else:
        path = out_dir / f"checksums_portable_{variant}.txt"
```
- **Impact:** The documented local all build can succeed but deploy_update_assets --target all then fails because it requires checksums_app_<channel>.txt and checksums_launcher.txt, not checksums_portable_<variant>.txt.
- **Fix:** Make all builds write the same checksum files deploy_update_assets requires, or teach deploy_update_assets to accept the portable checksum file for all builds.
- **Evidence:** [runtime] write_checksum_info(..., target='all') produced checksums_portable_Enhanced.txt; required_assets(..., target='all') immediately reported missing checksums_app_Enhanced.txt and checksums_launcher.txt.; [read] tools/deploy_update_assets.py required_assets requires checksums_app_* for app/all and checksums_launcher.txt for launcher/all.

## F-b5b819eb [MEDIUM/confirmed] Launcher build ignores the wrapper's version argument
`tools/build_portable.py:360-364`
```
    launcher_version = read_launcher_version(launcher_text)

    try:
        app_version = args.version.strip() or read_version(metadata_text)
        min_launcher_version = read_min_launcher_version(metadata_text)
```
- **Impact:** tools/scripts/build_launcher.bat 2.1.0 passes --version but build_portable still reads LAUNCHER_VERSION from launcher.pyw, so maintainers can publish a launcher with a different version than requested.
- **Fix:** For launcher targets, either reject a --version mismatch against LAUNCHER_VERSION or implement a temporary launcher.pyw version patch with restoration.
- **Evidence:** [grep] args.version is only assigned to app_version; build_launcher is called with launcher_version from launcher.pyw.; [read] tools/scripts/build_launcher.bat forwards its optional VERSION argument as --version to tools/build_portable.py.

## F-7129cc8e [MEDIUM/confirmed] generate_ui_assets.py depends on undeclared fontTools
`tools/generate_ui_assets.py:88-90`
```
    from fontTools import subset
    from fontTools.ttLib import TTFont
    from fontTools.varLib import instancer
```
- **Impact:** The documented asset generator cannot run in the standard uv dev or build environments, so font and icon asset refreshes are not reproducible from the repository metadata.
- **Fix:** Add fonttools to the appropriate project extra and update the lockfile; also make the script runnable from uv by inserting the repository root before importing bomana.
- **Evidence:** [runtime] uv run --extra dev python tools/generate_ui_assets.py failed with ModuleNotFoundError: No module named 'bomana'; PYTHONPATH=. then failed with ModuleNotFoundError: No module named 'fontTools'.; [grep] pyproject.toml declares pillow as a runtime dependency but no extra contains fonttools.

## F-493fddd1 [MEDIUM/likely] Dialog mousewheel handling relies on global bind_all cleanup
`bomana/ui/dialogs.py:374-382`
```
        self._content_canvas.bind(
            "<Enter>",
            lambda _e: self._content_canvas.bind_all("<MouseWheel>", self._on_content_mousewheel),
            add="+",
        )
        self._content_canvas.bind(
            "<Leave>",
            lambda _e: self._content_canvas.unbind_all("<MouseWheel>"),
            add="+",
```
- **Impact:** If a scrollable dialog is destroyed without a Leave event, the Tk all-bind can keep pointing at dialog callbacks and later wheel events can fail or clear other global wheel bindings.
- **Fix:** Bind wheel handling to dialog-local bindtags or add a single cleanup path for WM_DELETE_WINDOW and Destroy that only removes this dialog's binding.
- **Evidence:** [grep] rg 'WM_DELETE_WINDOW|protocol\(' bomana/ui/dialogs.py found no dialog close protocol binding.; [read] AboutDialog has a manual _close cleanup, but SettingsDialog relies on Leave and both use bind_all/unbind_all on <MouseWheel>.
