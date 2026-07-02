# 202607 SDD Post-Adaptation Evidence

Task tracking remains in `bd`; this file records adaptation evidence only.

| ID | Status | Evidence |
| --- | --- | --- |
| A-1 | done | Claimed `Bomana-e7q.9` after Phase 5 commit `8b5a61e`. |
| A-2 | done | Reopened/adapted HUD bug work: `Bomana-c0k`, `Bomana-6r8`, and `Bomana-6ui` now target `hud_overlay.py`, `AppRuntimeServices`, `ConfigManager`, and related HUD tests under the refactored boundaries. |
| A-3 | done | Reopened/adapted tactical-link research and follow-ups: `Bomana-2oa`, `Bomana-co8`, `Bomana-ffh`, and `Bomana-v94` now reference `runtime-8111-boundary.md`, telemetry, navigation presenters, and official 8111 endpoints only. |
| A-4 | done | Reopened/adapted CCRP calibration work: `Bomana-482` now targets `ballistics.py`, `ccrp_scheduler.py`, CCRP data, and manual evidence requirements. |
| A-5 | done | Left `Bomana-hh2` deferred because it belongs to the external TencentCloudPublic/HomeLab update-service pipeline, not this repo refactor. |
| A-6 | done | Left `Bomana-s13` deferred because stronger battle fingerprinting may require a future delta-spec or user approval beyond the current official-8111 boundary. |
| A-7 | done | Reopened `Bomana-sbr` as the cleanup epic for temporary compatibility facades and linked Phase 4/5 follow-ups including `Bomana-07o`, `Bomana-1fa`, and `Bomana-a9g8`. |
| A-8 | not_applicable | Ruff and pytest are not applicable to bd-only adaptation plus evidence docs; Phase 5 already passed full quality gates before this pass. |
