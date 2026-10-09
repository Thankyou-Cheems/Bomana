# Local Web flight recording

All three Web Editions record recent official telemetry by default, locally in
IndexedDB. Settings contains enable, export and clear controls; the heading tape
and main flight layout gain no row. There is no upload or additional Bridge poll.
Native Enhanced Desktop remains paused.

Retain the latest detected match, with a rolling maximum of three hours and
32 MiB of compressed chunks. The three-hour window is measured back from the
newest recorded frame, not the current wall clock: stopped recordings remain
exportable later until replaced by a new match, resumed retention or manual clear.
Map bounds/generation changes and ten seconds of
explicit invalid state with unavailable map objects delimit matches. Aircraft
death/respawn with map observations, brief disconnections, timer resets and Y66
resets do not. Official 8111 has no reliable universal battle ID: an indistinguishable
same-map change remains in the time-bounded recording. A reload within five minutes
on the same map/Edition resumes the retained recording unless hangar was confirmed.
Initial frames wait for map identity before replacing a retained session; missing
map info during an existing session does not create a new one. Ownship detection
uses the flight runtime's supported payload envelopes and player markers.
After one minute without a player, pause appending so idle/disconnected data cannot
evict the useful flight; resume when telemetry returns.

Frames are captured before latest-frame coalescing. The main thread sends at most
one outstanding frame; overload drops are counted in the next accepted frame.
The worker filters payloads, emits top-level deltas, gzip-compresses independent
keyframe chunks every ten seconds or 1 MiB, and prunes old chunks. A Web Lock gives
one writer per origin across Edition tabs. Export and clear use the same settings
component in Lite, Standard and Enhanced. Storage failures stop recording and show
a settings status without stopping flight functions. Crash/forced-close may lose
the final unflushed chunk; page-hide flush is best effort.

Record state, indicators, map objects/info, route availability/holdover, receipt
times and selected app context. Do not record chat, authentication, names, URLs,
headers or account data. Enhanced context includes previous processed Y66 status
and counts. All Editions include prior processed snapshot timing, timer, selected
target/weapon and available CCRP context; it is not a serialized private catalog
or terrain pack. Raw inputs
reproduce algorithms; it is not a pixel/video recorder or an exact complete UI
command history. A maximum of 2000 map objects is retained, prioritizing the
selected ownship and marking truncation explicitly. Context and telemetry fields
are bounded.

Export `.json` schema `bomana-flight-recording/v1`, containing version/Edition
metadata and individually compressed base64 chunks. To expand into full replay
frames (the output must not exist):

```text
node frontend/scripts/flight-recording-read.mjs recording.json replay.jsonl
```

The reader bounds file and decompressed chunk sizes and does not execute input.
Retained chunks each begin with a complete frame, so eviction preserves replay.
The flight log is independent of the sortie timer's fifteen-minute checkpoint
lifetime and never restores a timer or navigation command.
