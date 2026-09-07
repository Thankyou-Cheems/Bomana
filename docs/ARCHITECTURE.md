# Public architecture

The online Launcher opens an independently versioned App Web and distributes Bridge. Bridge forwards official 8111 observations and stores signed resource objects. Lite / Standard use the same `PublicRuntime` and `public-main.ts` as the maintained production build. Parameter assets come from the same validated parameter set as the flight toolbox.

The runtime owns lifecycle, recovery, timer, fuel learning and official zone / airfield navigation. Presentation consumes snapshots and commands. The heading renderer is shared with the private extension through a guidance presentation callback; only navigation guidance is included here. Advanced release calculation remains private.

Public source updates are generated, tested in a clean directory and appended to public `main`. CI in this repository repeats the public checks. It does not sign official releases, store deployment credentials or deploy to Tencent Cloud. Existing tags / Releases are historical, not a second publication pipeline.
