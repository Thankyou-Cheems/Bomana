# 202607 SDD Phase 5 Proposal

## Problem

`bomana/ui/dialogs.py` still combines Tk widget construction, settings value
collection, validation, persistence, runtime side effects, and several unrelated
modal dialogs. `bomana/ui/app.py` also retains coordination helpers that can be
owned by smaller services. Moving all UI code at once is high risk because Tk
layout, monkeypatch-heavy tests, and runtime side effects are tightly coupled.

## Scope

- Extract headless settings-dialog form logic first: value collection,
  validation, and save payload construction.
- Keep `bomana/ui/dialogs.py` class names and monkeypatch surfaces compatible
  while delegating non-widget logic to focused modules.
- Move one low-risk `App` coordination responsibility into an existing or new
  service helper where tests can stay headless.
- Record manual UI inspection items instead of trying to automate visual Tk
  checks in this phase.

## Out Of Scope

- Replacing Tk or changing production entrypoints.
- Restyling dialogs or changing geometry/layout behavior.
- Removing `dialogs.py` compatibility exports during this phase.
- Running real 8111 or manual GUI smoke inside the agent session.
- Pushing the branch to remote.

## Acceptance

- Extracted headless dialog helpers have focused tests.
- Existing dialog/app tests pass without weakening assertions.
- `SettingsDialog._save()` still performs validation before persistence and
  runtime side effects.
- Manual UI inspection checklist is recorded in review.
- Ruff and full pytest pass.
