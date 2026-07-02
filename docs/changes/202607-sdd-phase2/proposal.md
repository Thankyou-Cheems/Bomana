# 202607 SDD Phase 2 Proposal

## Problem

`UISnapshot` and several Tk renderer methods still mix domain facts with UI
strings, colors, target selection, and status formatting. A full `DomainSnapshot`
rewrite would touch too many call sites at once, so this phase starts with
headless presenter models while preserving the legacy `UISnapshot` shape.

## Scope

- Add pure presenter modules for panel, HUD, dialog, and snapshot status models.
- Update selected Tk consumers to apply presenter models instead of rebuilding
  strings and colors inline.
- Keep widget creation, layout, sound side effects, tray state, and overlay
  lifecycle in existing Tk/runtime modules.
- Add headless tests and boundary contract tests.

## Out Of Scope

- Removing legacy `UISnapshot` fields.
- Rewriting `GameLogic.snapshot()` into a new domain snapshot API.
- Changing Tk layout, geometry, style, or sound timing behavior.
- Changing navigation lock semantics or 8111 parsing.
- Pushing the branch to remote.

## Acceptance

- Presenter modules have headless tests.
- `bomana/core` does not import `bomana.ui`.
- Presenter modules do not import Tk or mutate widgets.
- Runtime behavior remains compatibility-first through existing `UISnapshot`.
- Ruff and pytest pass.
