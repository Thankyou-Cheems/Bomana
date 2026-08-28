# Legacy Python retirement

The browser cutover removes these active source closures from the current tree:

- `Bomana.pyw`, `launcher.pyw`, `bomana/`, and `launcher/`;
- tkinter UI, Python App runtime, PyInstaller packaging, and Python dependency locks;
- the desktop Launcher update/install pipeline;
- the native hotkey broker and packaged-desktop tests;
- old App/Launcher build and Release workflows.

They remain available in the repository's existing commit history, tags, and GitHub Releases. The cutover uses a normal descendant commit on `main`; it does not force-push, rewrite refs, delete tags, or delete Release assets.

The replacement public source closures are:

- `frontend/`: Online Launcher plus Lite and Standard;
- `native/telemetry_gateway/`: Bomana Bridge;
- `docs/`: public site and current browser-first documentation.

Enhanced App source, models, terrain data, tactical intelligence, and release artifacts remain outside the public repository. Public Bridge protocol code for mobile pairing and signed Local Data Store transport remains because it contains no App implementation or private artifact bytes.
