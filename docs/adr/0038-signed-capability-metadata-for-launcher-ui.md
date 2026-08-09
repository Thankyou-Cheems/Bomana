# Drive Launcher Optional UI from Signed Capability Metadata

Status: Accepted (2026-08-03)

Application artifacts carry Signed Capability Metadata for optional launch
surfaces and prerequisites, including web overlay, standalone web, and the
non-blocking terrain recommendation/feature list. The Launcher renders only capabilities
declared by the verified artifact; it does not infer features from Lite,
Standard, or Enhanced channel names.

Unknown or unsupported capability values fail closed: the related action is
hidden or the application starts in the appropriate degraded state. A new
capability can therefore ship with an application manifest without requiring a
Launcher release, while unreleased roadmap features remain invisible.
