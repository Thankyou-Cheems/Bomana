# Public Browser Architecture

Bomana's public closure contains three independently reviewable parts:

1. `frontend/` builds the Online Launcher, Lite, and Standard.
2. `native/telemetry_gateway/` builds Bomana Bridge.
3. `docs/` is the public site served at `bomana.ruikang.wang`.

## Runtime flow

```text
War Thunder localhost:8111
          |
          v
Bomana Bridge (fixed read-only routes, loopback-first)
          |
          v
Online Launcher -> Lite or Standard Web
```

Lite reads the public frame only to maintain the respawn-cycle timer. Standard additionally derives bearing and distance to official `bombing_point` and `airfield` objects. The public runtime does not request gamechat, terrain, mobile pairing, or any Enhanced endpoint.

Enhanced is a stable integration identity in the public Launcher. Its implementation, models, data, tests, and release definition are not part of this repository. Bridge may expose public mobile-pairing and signed-object transport protocols because those protocols carry opaque authorization/artifacts and contain no Enhanced App implementation, terrain object, or solver.

## Retired code

The Python App, desktop Launcher, PyInstaller packaging, tkinter UI, and native hotkey broker are removed from the current tree. Their commits, tags, and Releases remain unchanged for historical recovery.

## Release boundary

- Public CI builds and tests Lite, Standard, Launcher, and Bridge only as reproducibility evidence.
- Public CI must not publish, deploy, or hold credentials for production.
- Public CI must not build or upload Enhanced or terrain artifacts.
- Production composition, Sigstore publication, Caddy/SSH activation, rollback, and the private Enhanced/mobile subtrees remain owned by the private release pipeline.
- The public promotional-site source is mirrored into the private release closure before production deployment.
