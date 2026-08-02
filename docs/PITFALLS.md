# Public Development Pitfalls

## Treating an edition name as an access boundary

`Enhanced` in a file name or UI control does not protect subscriber bytes.
Access requires all three layers: a valid signed receipt, an authorized private
manifest request, and an authorized artifact download.

## Hiding private code behind feature flags

A disabled import or ZIP exclusion still leaves implementation in public Git
history. Public modules must depend on a narrow optional interface, while the
subscriber implementation lives only in the private repository.

## Scattering channel checks

String comparisons across UI, build scripts, and deployment tools drift over
time. Use `bomana.editions` for identity and access decisions and
`bomana.release_closure` for source-path decisions.

## Letting Launcher policy become payment logic

CheemsPay owns accounts, payments, subscription state, and receipt issuance.
Bomana verifies a bounded receipt and installs authorized artifacts; it should
not reproduce billing state locally.

## Trusting client-only enforcement

Desktop clients are inspectable. A valid local gate does not make a public
object URL private. The manifest and every byte-serving endpoint need a
short-lived server-side grant.

## Weakening update verification to recover from an outage

Never bypass Ed25519 signatures, SHA-256, canonical channel/file names, or
compatibility checks. Preserve the last known-good installation and repair the
release metadata instead.

## Running Tk work from a worker thread

Polling, network, and update workers may publish immutable state, but Tk widget
creation and mutation stay on the UI owner thread. Shutdown stops workers before
destroying the root window.

## Assuming the hangar represents a live session

War Thunder's official 8111 endpoints may be absent or incomplete outside a
battle. Model this as unavailable data, not as zero, and do not add an alternate
memory-reading path.

## Treating Datamine `fmFile` paths as canonical names

Datamine contains both `fm/name.blk` and `/fm/name.blk` references. Normalize
the path prefix and extension before joining `unit_to_fm` to the extracted
flight-model table; otherwise variants such as the French Tornado killstreak
can silently report an unknown speed limit.

## Coupling tests to source layout

Source-text assertions make refactoring expensive without protecting users.
Prefer public behavior tests, interface tests with in-memory adapters, and
inspection of the final signed archive.

## Calling a local split a completed migration

The split is complete only after clean-checkout builds, private remote/CI,
CheemsPay server enforcement, reversible release routing, and live artifact
verification. Keep local, remote, and production status distinct.

## Assuming rewritten history revokes an earlier license

History rewriting can remove private implementation from the official public
repository going forward. It cannot revoke rights already granted under MIT or
delete clones, forks, cached archives, or previously published releases.
