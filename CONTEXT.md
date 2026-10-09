# Bomana public context

**Local Flight Recording** is default-on browser-local diagnostic storage for recent official telemetry, bounded to one detected match and a three-hour / 32 MiB rolling window. Settings supports export, disable and clear; it never uploads automatically or restores live flight/timer state. See [the recording contract](docs/specs/local-flight-recording.md).

**Basic Desktop** is the separate minimal native Windows surface: only a cycle
timer and official bombing-zone/airfield Basic Navigation. It does not include
the complete Standard Edition, Web assets or an Enhanced calculation module.

**App Web** is the browser application distributed by the online **Launcher**. **Bridge** is the local Go process that relays official 8111 observations and provides local resource storage and mobile pairing transport. **Public Runtime** owns sortie lifecycle, timer, Basic Navigation, speed and fuel estimates. **Basic Navigation** includes official zones and airfields only. **Air Realistic** is the shared Standard / Enhanced map and flight presentation with official aircraft observations and horizontal motion estimates, independent of navigation target selection. Its velocity vector is horizontal ground track, not three-dimensional air velocity or angle of attack. **Mobile Pairing** grants short-lived access to one local Bridge; Standard pairing requires no account. **Enhanced** is a separately authorized private extension.

**Shared Cycle Timer** is a volatile, bounded presentation held by Bridge for paired Web views. App supplies active state, elapsed seconds, period and life ordinal; Bridge sequences full snapshots with a monotonic uptime anchor and revision. Both views use browser monotonic time, and explicit reset/period commands synchronize in either direction. It requires the matching new Bridge binary. Bridge does not infer sortie lifecycle or game rules.

The public tree is a generated source distribution, not a separate development trunk. The same Public Runtime and Web entry are used in maintained production Lite / Standard builds. A public source sync is not a production release. Formal Web / Bridge version metadata in the online Launcher identifies production downloads; old GitHub release records remain historical.
