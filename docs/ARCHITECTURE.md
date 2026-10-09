# Public architecture

Both Web entrypoints send existing telemetry to a bounded local recorder before
frame coalescing. `flight-recorder.worker.ts` owns filtering, delta/gzip encoding
and IndexedDB persistence under one writer Web Lock per origin. Shared Settings
offers export, disable and clear. Exports support offline replay only; no recorded
data feeds live flight or timer restoration. See [the recording contract](specs/local-flight-recording.md).

Basic Desktop (`native/telemetry_gateway/cmd/bomana_basic/`) is an independent
native Windows timer/navigation window. It reuses the ExtUI resolver directly,
without starting Bridge, and draws system fonts and vector symbols on a
per-pixel-alpha canvas. Its manually built EXE needs no Web assets, account or
calculation module. See [its usage and build guide](../native/telemetry_gateway/cmd/bomana_basic/README.md).

The online Launcher opens an independently versioned App Web and distributes Bridge. Bridge forwards official 8111 observations and stores signed resource objects. Lite / Standard use the same `PublicRuntime` and `public-main.ts` as the maintained production build. Parameter assets come from the same validated parameter set as the flight toolbox.

The runtime owns lifecycle, recovery, timer, fuel learning and official zone / airfield navigation. Presentation consumes snapshots and commands. The heading renderer is shared with the private extension through a guidance presentation callback; only navigation guidance is included here. Standard composes the shared Air Realistic renderer directly, without an Enhanced instrument shell. Official aircraft observations are independent of navigation selection; bounded motion estimates provide short trails, closure and uncertain grouping. The default-on horizontal ground-track vector and its remembered toggle are shared by the main map and compact PiP. Advanced release calculation, terrain, airport modules, Y66 and chat interpretation remain private.

Commands update their snapshot without ingesting the previous telemetry sample
again. Standard's page and Picture-in-Picture window share one flight-status
presentation, so reopening the window preserves gear movement direction. Each
phone page has its own runtime while consuming the paired Bridge's observations.

Public source updates are generated, tested in a clean directory and appended to public `main`. CI in this repository repeats the public checks. It does not sign official releases, store deployment credentials or deploy to Tencent Cloud. Existing tags / Releases are historical, not a second publication pipeline.
