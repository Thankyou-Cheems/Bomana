# Code Review Report

**Open findings:** 5 high, 24 medium, 4 low
**Resolved:** 11  |  **Generated:** 2026-06-18T01:46:33+00:00

## F-1fa20106 [HIGH/confirmed] Schema-empty /state frames are marked healthy
`bomana/core/telemetry.py:280-287`
```
        # 请求 /state (飞机状态)
        state_result = self.http.get_json(f"{NetworkConfig.API_BASE}/state", budget)
        data.state_resp_ok = state_result.ok
        data.state_error_kind = state_result.error_kind
        data.state_elapsed_ms = state_result.elapsed_ms
        j = state_result.payload
        if state_result.ok and isinstance(j, dict):
            data.ias_kmh, _ = self._read_scaled_float(
```
- **Impact:** An HTTP 200 /state payload such as {} leaves state_resp_ok true while all state fields remain defaults, so ALIVE fallback and landing/fuel guards treat zero/default telemetry as fresh data.
- **Fix:** Validate the /state payload shape before setting state_resp_ok, or add a payload/schema flag used by fallback, fuel, landing, gear, and diagnostics.
- **Evidence:** [tool] Probe with /state payload {} returned state_resp_ok=True, ias_kmh=0.0, gear_pct=0.0.; [read] GameLogic fallback only triggers when not tel.state_resp_ok at bomana/core/logic.py:189-193.

## F-97143313 [HIGH/confirmed] 82mm mortar bomb is stored with a 0.82m caliber
`bomana/data/ccrp_bomb_params.json:133-147`
```
    "bomb_ussr_82mm_o_832": {
      "mass": 3.31,
      "caliber": 0.82,
      "dragCx": 0.07,
      "distFromCmToStab": 0.77,
      "brakeTime": [
        0.0,
        0.0
      ],
      "brakeCxK": 0.0,
      "brakeArm": 0.0,
      "stab_enabled": false,
      "source_file": "bomb_ussr_82mm_o_832.blkx",
      "mesh": "bomb_82mm_mortar"
    },
```
- **Impact:** Selecting bomb_ussr_82mm_o_832 feeds caliber 0.82 into drag area, making the 3.31 kg 82mm mortar behave like a 0.82 m projectile and producing a much shorter CCRP range.
- **Fix:** Correct this entry to 0.082 m and add a data validation check for IDs/source/mesh names containing Nmm.
- **Evidence:** [tool] calculate_bomb_trajectory(1000,100) range was 583.249m with caliber 0.82 and 1408.789m with only caliber changed to 0.082.; [read] id/source_file/mesh all identify this as 82mm; ballistics.py computes area from caliber in meters.

## F-4cfa222a [HIGH/confirmed] HUD can fall back to a non-click-through topmost window
`bomana/ui/hud_overlay.py:419-432`
```
        if self._transparency_support.win32_layered:
            if Win32.setup_window(
                self.hwnd,
                click_through=bool(click_through),
                alpha=target_alpha,
                color_key=self._transparent_color_ref,
            ):
                return
            if not self._transparency_support.tk_color_key:
                raise HUDOverlayUnavailable("HUD overlay Win32 layered style failed")

        if self._transparency_support.tk_color_key:
            with contextlib.suppress(tk.TclError):
                self.window.attributes("-alpha", target_alpha / 255.0)
```
- **Impact:** If Win32 layered setup fails while Tk color-key support exists, click_through=True falls back to only setting Tk alpha, leaving a topmost HUD that can intercept game clicks.
- **Fix:** When click_through is requested and Win32.setup_window fails, raise HUDOverlayUnavailable or hide/destroy HUD; reserve Tk-only fallback for non-click-through contexts.
- **Evidence:** [read] Fallback path applies only window.attributes("-alpha") and has no click-through equivalent.; [read] tests/test_hud_overlay.py raises only when tk_color_key=False; it does not cover the tk_color_key=True click-through failure path.

## F-612d9b37 [HIGH/confirmed] Non-dict panels value crashes config migration
`bomana/utils/file_utils.py:221-226`
```
        if version < 2:
            panels = config.get("panels", {})
            if "show_bombing" not in panels:
                panels["show_bombing"] = True
                changed = True
            config["panels"] = panels
```
- **Impact:** A valid JSON config such as {"config_version":1,"panels":null} crashes ConfigManager.load during migration instead of falling back, so startup or settings load can fail until the user manually edits or deletes the config.
- **Fix:** Normalize nested sections before migration, e.g. treat non-dict panels as {}, and catch TypeError from migration in the tolerant load path.
- **Evidence:** [tool] Probe ConfigManager._migrate_config({"config_version":1,"panels":None}) raised TypeError; list panels raised TypeError list indices must be integers or slices.; [read] ConfigManager.load catches json.JSONDecodeError, ValueError, and OSError, but not TypeError from _migrate_config.

## F-691747c0 [HIGH/confirmed] Win32 window style setup reports success on API failure
`bomana/utils/system.py:304-329`
```
        try:
            # 获取当前样式
            style = cls.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)

            # 添加必要样式
            style |= WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_TOOLWINDOW

            # 根据锁定状态切换点击穿透
            # 关键：同时设置 WS_EX_TRANSPARENT 和 WS_EX_NOACTIVATE
            # - WS_EX_TRANSPARENT: 让点击穿透到下层窗口
            # - WS_EX_NOACTIVATE: 防止窗口被激活，确保持续穿透
            if click_through:
                style |= WS_EX_TRANSPARENT | WS_EX_NOACTIVATE
            else:
                style &= ~(WS_EX_TRANSPARENT | WS_EX_NOACTIVATE)

            # 应用样式和透明度/颜色键
            cls.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
            target_alpha = max(0, min(255, int(alpha)))
            flags = LWA_ALPHA
            key = 0
            if color_key is not None:
                flags |= LWA_COLORKEY
                key = int(color_key) & 0x00FFFFFF
            cls.user32.SetLayeredWindowAttributes(hwnd, key, target_alpha, flags)
            return True
```
- **Impact:** On Windows, failed SetWindowLongW or SetLayeredWindowAttributes calls can leave the main/HUD window non-transparent or non-click-through while callers proceed as if lock/click-through succeeded.
- **Fix:** Declare ctypes argtypes/restype with wintypes, check BOOL/last-error return values, and return False when any required style or layered attribute call fails.
- **Evidence:** [read] ctypes Win32 BOOL failures do not raise OSError by default; this code ignores both SetWindowLongW and SetLayeredWindowAttributes return values and returns True.; [read] tests/test_system_portability.py only covers non-Windows user32 absence, not Windows API failure returns.

## F-2eb5a564 [MEDIUM/confirmed] Tiny positive budgets still start over-budget requests
`bomana/core/telemetry.py:73-82`
```
        rem = budget.remaining()
        if rem <= 0.0:
            return FetchResult(endpoint=endpoint, ok=False, error_kind="budget_exhausted")

        # 计算超时时间
        connect_t = min(NetworkConfig.API_CONNECT_TIMEOUT, max(0.01, rem))
        read_t = min(NetworkConfig.API_READ_TIMEOUT, max(0.01, rem))

        try:
            r = self.session.get(url, timeout=(connect_t, read_t))
```
- **Impact:** When remaining budget is below 10 ms, HttpJson still sends a request with 10 ms connect and 10 ms read timeouts, allowing a tick to exceed the remaining deadline before the next endpoint check.
- **Fix:** Treat remaining time below the minimum usable timeout as budget_exhausted, or allocate one total per-request timeout from the remaining budget.
- **Evidence:** [tool] Probe with Budget(0.001) still called session.get with timeout=(0.01, 0.01).; [read] Budget is only checked before session.get, so it cannot interrupt the in-flight request.

## F-57957fbb [MEDIUM/confirmed] Telemetry numeric parsing accepts NaN and Infinity
`bomana/core/telemetry.py:143-160`
```
        try:
            return float(raw)
        except _NUMERIC_PARSE_ERRORS:
            return float(default)

    @staticmethod
    def _to_optional_float(raw: Any) -> float | None:
        """将8111字段值转换为可空float。"""
        if raw is None:
            return None
        if isinstance(raw, dict):
            raw = raw.get("value")
        elif isinstance(raw, (list, tuple)):
            raw = raw[0] if raw else None
        try:
            return float(raw)
        except _NUMERIC_PARSE_ERRORS:
            return None
```
- **Impact:** 8111 values like "nan" or NaN are converted into non-finite floats and can poison gear, fuel, attitude, speed, or snapshot fields instead of falling back safely.
- **Fix:** Require math.isfinite after float conversion and return the default or None for non-finite values; clamp bounded fields where appropriate.
- **Evidence:** [tool] Probe with {"IAS, km/h":"nan", "gear, %":"nan"} returned state_resp_ok=True, ias_kmh=nan, gear_pct=nan.; [read] MapObjectsFetcher._float_or_none already rejects non-finite values, but TelemetryFetcher scalar parsers do not.

## F-8fb5648b [MEDIUM/confirmed] Malformed map object payloads are reported as healthy empty maps
`bomana/core/telemetry.py:582-595`
```
        out = MapObjData()
        result = self.http.get_json(f"{NetworkConfig.API_BASE}/map_obj.json", budget)
        self.last_result = result
        out.error_kind = result.error_kind
        out.elapsed_ms = result.elapsed_ms
        j = result.payload
        if not result.ok:
            return out

        out.ok = True

        # 提取对象列表
        objs = self._extract_objects(j)
        out.obj_count = len(objs)
```
- **Impact:** HTTP 200 /map_obj.json payloads with non-list or unrecognized dict shapes set MapObjData.ok=True and obj_count=0, hiding schema failures from API-down diagnostics and stale-map fallback logic.
- **Fix:** Validate the payload shape before setting out.ok; keep legitimate empty object lists valid but mark unsupported JSON shapes as schema errors.
- **Evidence:** [tool] Probe with payload "bad-shape" and {"unexpected": []} returned ok=True, obj_count=0, error_kind="".; [read] GameLogic records map endpoint health from raw_map.ok at bomana/core/logic.py:596-600.

## F-5aefffd3 [MEDIUM/confirmed] Version comparison treats prerelease digits as newer stable versions
`bomana/launcher_core.py:68-81`
```
def extract_version_tuple(version: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", version or "")
    if not nums:
        return (0,)
    return tuple(int(x) for x in nums)


def version_is_newer(remote: str, local: str) -> bool:
    a = extract_version_tuple(remote)
    b = extract_version_tuple(local)
    n = max(len(a), len(b))
    aa = a + (0,) * (n - len(a))
    bb = b + (0,) * (n - len(b))
    return aa > bb
```
- **Impact:** A remote version like 2.0.0-rc.1 compares greater than local 2.0.0, and min_launcher_version 2.0.0-rc.1 can make stable 2.0.0 appear too old.
- **Fix:** Use a SemVer or PEP 440 parser and explicitly reject or handle prerelease/build metadata; skip draft/prerelease GitHub releases unless opted in.
- **Evidence:** [tool] extract_version_tuple("2.0.0-rc.1") yields (2,0,0,1), which compares newer than (2,0,0).; [grep] tests/test_launcher_core.py only covers numeric versions.

## F-00164968 [MEDIUM/confirmed] Runtime hotkey changes leave Tk-local bindings stale
`bomana/ui/app.py:547-550`
```
        self.root.bind(f"<{HotkeyConfig.KEY_LOCK}>", lambda e: self._toggle_lock())
        self.root.bind(f"<{HotkeyConfig.KEY_CORNER}>", lambda e: self._next_corner())
        self.root.bind(f"<{HotkeyConfig.KEY_BEEP}>", lambda e: self._toggle_beep())
        self.root.bind(f"<{HotkeyConfig.KEY_ZONES}>", lambda e: self._toggle_zone_sound())
```
- **Impact:** After Settings changes hotkey bindings, global hotkeys and hints can use the new keys while the Tk window remains bound to startup keys; with global hotkeys off, new local shortcuts do not work.
- **Fix:** Track and unbind current Tk sequences, then refresh local bindings after HotkeyConfig.set_bindings.
- **Evidence:** [read] _init_bindings is called once during App construction at app.py:170.; [read] SettingsRuntimeMixin mutates HotkeyConfig at settings_runtime.py:78-79; dialogs.py only restarts global hotkeys and refreshes hints.

## Deferred (23 lower-priority findings)
- F-eb62a69c [medium] Navigation width is applied but not saved by Settings (`bomana/ui/dialogs.py:1646`)
- F-f4261c90 [medium] Settings save drops the bombing panel preference (`bomana/ui/dialogs.py:1683`)
- F-fdfd306f [medium] Showing primary reticle re-shows stale secondary markers (`bomana/ui/hud_overlay.py:736`)
- F-9660e3a1 [medium] Enemy airfield tape markers ignore core target selection (`bomana/ui/navigation_presenter.py:107`)
- F-ed9ba16e [medium] Hidden ancestors prevent panel removal from taking effect (`bomana/ui/panel_renderer.py:80`)
- F-d8a0e46f [medium] Zone hotkey is registered when zones are compiled out (`bomana/ui/runtime_services.py:60`)
- F-d563b2d3 [medium] Malformed timer state can crash restore (`bomana/utils/file_utils.py:340`)
- F-dff0276c [medium] normalize_angle can hang on infinite input (`bomana/utils/math_utils.py:113`)
- F-f5cbb6e5 [medium] Deploy script trusts manifest asset paths outside staging directory (`tools/deploy_update_assets.py:163`)
- F-d88c090c [medium] Python repr is used as remote shell quoting (`tools/deploy_update_assets.py:202`)
- F-6fcde172 [medium] Final zone disappearance is never reported as destroyed (`bomana/core/logic.py:843`)
- F-b6ca75c1 [medium] Rollback can fail after changing app state and deleting preserved current version (`bomana/launcher_install.py:300`)
- F-7858d3a3 [medium] Destroyed-marker rendering bypasses the snapshot (`bomana/ui/nav_window.py:565`)
- F-67345260 [medium] Standalone navigation stops updating when zones are hidden (`bomana/ui/panel_renderer.py:355`)
- F-eeba46b2 [medium] Dispatcher can leak RuntimeError during Tk shutdown (`bomana/ui/runtime.py:23`)
- F-6df88130 [medium] Custom non-WAV playback cannot be cancelled during shutdown (`bomana/utils/sound.py:183`)
- F-85c0464b [medium] GlobalHotkeys.stop can miss startup race (`bomana/utils/system.py:573`)
- F-e05f92e3 [medium] Launcher self-update does not rehash staged EXE at apply time (`launcher.pyw:1798`)
- F-bef29479 [medium] Auto-update artifacts are hash-checked but not publisher-signed (`tools/build_portable.py:299`)
- F-d03b8edc [low] Reset defaults restores the old UI scale (`bomana/ui/dialogs.py:1571`)
- F-122bb5c5 [low] Legacy build ignores version-info generation failure (`tools/scripts/build.bat:122`)
- F-5061272d [low] NavigationWindow Win32 handle lookup can crash before fallback (`bomana/ui/nav_window.py:75`)
- F-1efbc5c5 [low] Standalone toggle during history mode can lose restore intent (`bomana/ui/navigation_runtime.py:62`)
