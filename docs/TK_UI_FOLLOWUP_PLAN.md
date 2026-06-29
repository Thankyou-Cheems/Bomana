# Tk UI Follow-up Plan

Date: 2026-05-17

This plan records the remaining `Bomana-21x` work after the completed Tk UI repair pass.
Production UI work stays on Tk.

## Completed Baseline

Do not repeat these areas:

- Dialog high-DPI reflow and screen fitting: `88ae8de`, bd `Bomana-6qh`.
- Heading tape size from Tk font metrics: `5e6b6e6`, bd `Bomana-c71`.
- Integrated and standalone navigation status row elastic layout: `f47ce0f`, bd `Bomana-2p6`.
- Navigation list column sizing from font metrics: `23bc27c`.
- Shared Tk text wrap, elide, and measure helpers: `b0ebc46`, bd `Bomana-v72`.
- HUD overlay graceful-disable regression coverage: `2c81753`, bd `Bomana-5e2`.
- Bundled UI fonts and icon assets: `670f9a4`, bd `Bomana-ql9`.
- Basic bundled icon scaling for navigation panels: `bfa244e`, bd `Bomana-de5`.
- Shared Tk UI and monospace font fallback resolution: `df8613e`, bd `Bomana-7qt`.

## Remaining Order

1. `Bomana-who` - HUD overlay logical/physical pixel split.
   - Keep this strictly in `bomana/ui/hud_overlay.py` and existing Win32/Tk integration.
   - Focus on DPI, monitor geometry, transparent color support, and graceful degradation.
   - Do not duplicate runtime-service failure tests already covered by `2c81753`.

2. `Bomana-v13` - larger icon assets and selection strategy.
   - Focus on 40/48/64 px availability or a documented alternative.
   - Update `IconManager` selection so text scale 1.5+ does not make icons undersized.
   - Do not redo the existing 12-32 px PNG bundling or nav-panel scaling fix.

3. `Bomana-4om` - shared visual tokens/control factories between launcher and main app.
   - Treat this as consolidation of duplicated Tk styling patterns.
   - Do not restyle the launcher from scratch; `c9511df` already did that.

4. Close or update `Bomana-21x` once the above Tk-only follow-ups are done or explicitly
   deferred.

## Acceptance Matrix

For every code-changing UI task:

- Run `uv run --extra dev ruff check .`.
- Run `uv run --extra dev ruff format --check .`.
- Run focused tests for touched surfaces.
- Prefer adding or updating targeted tests when behavior is pure Python or Tk geometry can run
  under the existing CI display assumptions.

Task-specific checks:

- HUD overlay:
  - `uv run --extra dev pytest tests/test_runtime_services.py`
  - Add a focused HUD sizing/style test if the refactor creates pure helpers.
  - Manual Windows smoke: enable HUD, lock/unlock click-through, change text scale/HUD scale,
    move the main window across monitors if available, and verify no blank or stuck overlay.

- Icon scaling:
  - `uv run --extra dev pytest tests/test_panel_renderer.py tests/test_ui_geometry.py`
  - Verify `tools/generate_ui_assets.py` output paths if assets change.
  - Manual smoke: text scale 1.0, 1.5, 2.0; check nav/fuel/bombing/checklist icon alignment.

- Launcher/main visual token consolidation:
  - Run any focused launcher tests touched by the change.
  - Manual smoke: open launcher source mode, details/support dialog, and main app settings.

## Guardrails

- Official 8111 API only; no game memory reads, injection, or game file edits.
- Respect `ENABLE_*` feature flags and keep build variants sharing one config file.
- Preserve the existing Tk production entrypoints: `launcher.pyw` and `Bomana.pyw`.
