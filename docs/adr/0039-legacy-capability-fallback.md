# Keep Legacy Applications Startable Without New Capability Metadata

Status: Accepted (2026-08-03)

An installed application that predates Signed Capability Metadata remains
startable when its channel identity, package integrity, and Compatibility Floor
are valid. The Launcher hides new optional Web actions and treats unknown
terrain prerequisites as Terrain-Degraded Startup. It requires a managed
redownload or reinstall only when identity, integrity, or compatibility
evidence is missing or invalid.

This preserves local continuity for historical releases while ensuring that
new optional behavior is never guessed or silently enabled.
