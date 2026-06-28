# Code Review Report

**Open findings:** 3 high, 3 medium
**Resolved:** 43  |  **Generated:** 2026-06-28T04:23:10+00:00

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
`bomana/data/ccrp_bomb_params.json:133-147`  ⚠ snippet exists but not at lines 133-147; first line now near line 238
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

## F-61167c77 [MEDIUM/confirmed] Startup HUD initialization failure is not persisted
`bomana/ui/app.py:177-178`
```
        if HUDConfig.enabled and not self._show_hud_overlay():
            HUDConfig.enabled = False
```
- **Impact:** On a machine where the HUD overlay cannot be created or shown, a saved hud_enabled=true config is only disabled in memory during startup, so the next launch reads true again and repeats the failing HUD initialization and diagnostics instead of converging to a repaired config.
- **Fix:** When startup _show_hud_overlay() fails, reuse the runtime disable path or call _save_config() after setting HUDConfig.enabled = False.
- **Evidence:** [read] runtime_services.update_hud_overlay() persists the later failure path at runtime_services.py:315-319, but App.__init__ disables HUD at app.py:177-178 before the first frame and does not save.

## F-fdfd306f [MEDIUM/confirmed] Showing primary reticle re-shows stale secondary markers
`bomana/ui/hud_overlay.py:736-750`
```
    def _set_reticle_visible(self, visible: bool) -> None:
        state = "normal" if visible else "hidden"
        for item_id in (
            self._reticle_ring_id,
            self._reticle_hline_id,
            self._reticle_vline_id,
            self._reticle_mode_id,
            self._reticle_dist_id,
        ):
            if item_id is not None:
                self.canvas.itemconfig(item_id, state=state)
        for item_id in self._secondary_marker_ids:
            self.canvas.itemconfig(item_id, state=state)
        for item_id in self._secondary_label_ids:
            self.canvas.itemconfig(item_id, state=state)
```
- **Impact:** When secondary targets drop from a previous frame, _render_secondary_targets hides unused IDs, then _set_reticle_visible(True) marks every secondary item normal again, potentially showing stale or empty secondary markers.
- **Fix:** Let _render_secondary_targets own secondary visibility; _set_reticle_visible should hide secondary IDs only when visible is false or split primary and secondary visibility.
- **Evidence:** [read] _render_reticle calls _render_secondary_targets at hud_overlay.py:999-1007 and then _set_reticle_visible(True) at line 1012.; [read] _render_secondary_targets hides unused/empty secondary IDs at hud_overlay.py:878-884.
