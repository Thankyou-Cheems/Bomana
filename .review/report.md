# Code Review Report

**Open findings:** 2 high, 2 medium
**Resolved:** 62  |  **Generated:** 2026-07-10T14:59:42+00:00

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

## F-fb781d8f [HIGH/confirmed] Mutable adjacent checksum authenticates the elevated broker
`bomana/utils/hotkey_broker.py:191-205`
```
def expected_broker_sha256(path: Path) -> str:
    checksum = broker_checksum_path(path)
    text = checksum.read_text(encoding="ascii").strip()
    fields = text.split()
    if len(fields) != 2 or fields[1] != BROKER_EXECUTABLE_NAME:
        raise ValueError("invalid bundled hotkey broker checksum")
    expected = fields[0].lower()
    if len(expected) != 64 or any(char not in "0123456789abcdef" for char in expected):
        raise ValueError("invalid bundled hotkey broker SHA-256")
    return expected


def verify_bundled_broker(path: Path) -> bool:
    try:
        return sha256_file(path) == expected_broker_sha256(path)
```
- **Impact:** A same-user writer to the supported portable App directory can replace BomanaHotkeyBroker.exe and its checksum; if the user then enables administrator hotkeys and approves UAC, the replacement executes as administrator.
- **Fix:** Do not offer runas from a user-writable App package. Require an OS-protected or Authenticode-verified broker boundary, or explicitly disable privileged hotkeys when no independent trust anchor is available.
- **Evidence:** [runtime] A temporary attacker-controlled BomanaHotkeyBroker.exe plus its matching adjacent sidecar made verify_bundled_broker() return True.; [read] hotkey_broker.py passes the accepted path to ShellExecuteExW with lpVerb=runas; build_portable.py packages the EXE and checksum together.; [read] launcher.pyw requires the install root to be writable and recommends a Desktop or Downloads Bomana directory; ADR 0003 acknowledges the user-writable package is weaker than Program Files plus Authenticode.; [tool] uv focused broker/elevation/build tests: 60 passed; existing tests pin matching-pair behavior but do not provide an independent trust anchor.

## F-61167c77 [MEDIUM/confirmed] Startup HUD initialization failure is not persisted
`bomana/ui/app.py:177-178`  ⚠ snippet exists but not at lines 177-178; first line now near line 193
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

## Focused Weapon-Physics Hardening Follow-up — PASS

No current high-severity blocker remains in the requested weapon fire-control scope. The four confirmed physics incidents were registered retrospectively and resolved against the current tree:

- **F-cfbcfd11** — glide records now use weapon-specific mass/caliber/`dragCx` only for a guided-ballistic reference; `within_ballistic_reference` and `beyond_ballistic_reference` remain yellow and never claim a full glide envelope.
- **F-be7d7ba5** — four schema-backed propulsion reason codes and source pointers cover exactly 26 generated records; all 26 fail closed as `insufficient_data/conditional_propulsion_unsupported` before integration.
- **F-43ae3a6c** — 176 AAM records retain guidance-table minima and provenance, while runtime emits neutral/yellow `within_2d_max_only` with an unknown minimum instead of using top-level `minDistance`.
- **F-9405771c** — launch TAS is isolated from ground closure; countdowns use only positive aligned `SOG * cos(relative)` and disappear off-axis/opening.

Verification on the current tree:

- Focused weapon/data/schema/UI/migration suite: **110 passed, 8 subtests passed**.
- Full suite: **459 passed, 12 subtests passed**.
- Ruff check and format check, `bash -n tools/scripts/build.sh`, and `git diff --check`: passed (line-ending warnings only from `git diff --check`).
- Clean Datamine regeneration from commit `96787940b7d0a48fcd6eb153081b4c852f9435e9` / `2.57.1.16`: 723 weapons, 1,257 aircraft, and byte-structural equality after excluding `generated_at_utc`.
- Previous weapon findings remain fixed: legacy command guidance, process-wide catalog fallback with tray lifecycle preserved, immediate hostile disappearance, and exact CCRP source-ID/physics mapping. Legacy CCRP config keys now migrate through `BombConfig.get_bomb_source_id`; Settings distinguishes `CCRP 默认炸弹` from main-card combat selection.

The two high and two medium open findings above predate this feature review and are unrelated to the requested weapon-physics scope.

## Spec Feedback (close the incident loop)
Findings below violate normative clauses. For each confirmed one, deliver the three-part unit from spec-anchored development §7: spec amendment (if the clause was falsified or gapped), PITFALLS.md entry citing the clause, and a behavioral regression pin in tests/contracts/.
- R8111-03: F-ae1f420a
