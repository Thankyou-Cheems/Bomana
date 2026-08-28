# Repository Agent Instructions

Use PowerShell 7 (`pwsh`) on Windows. The current tree is browser/Go only; do not reintroduce Python App or desktop Launcher code.

Before changing Edition behavior, read `CONTEXT.md` and `docs/specs/public-editions.md`.

Public-boundary rules:

- Lite is timer-only.
- Standard is limited to official zone/airfield Basic Navigation.
- Enhanced App implementation, models, terrain data, tactical coordinates, chat recognition, countdowns, Y66, airport modules, and weapon solving remain outside this repository.
- Public integration protocols may include mobile pairing transport and signed Local Data Store object transport; they must not embed Enhanced App code, terrain objects, or solvers.
- Bridge is read-only and owns no Edition or solver.
- Existing Git history, tags, and Releases are historical records; do not rewrite or delete them.
