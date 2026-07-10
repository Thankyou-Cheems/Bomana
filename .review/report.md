# Code Review Report

**Open findings:** 1 high, 2 medium
**Resolved:** 51  |  **Generated:** 2026-07-10T05:32:31+00:00

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

## F-61167c77 [MEDIUM/confirmed] Startup HUD initialization failure is not persisted
`bomana/ui/app.py:177-178`  ⚠ snippet exists but not at lines 177-178; first line now near line 185
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
