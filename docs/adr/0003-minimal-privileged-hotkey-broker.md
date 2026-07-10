# ADR 0003: Isolate elevated hotkeys in a native broker

## Context

War Thunder and its anti-cheat may run at high integrity on Windows. A
medium-integrity Bomana process then loses game-foreground `RegisterHotKey`
delivery even though the same bindings work with ordinary foreground windows.
The first mitigation elevated the entire mutable Python App package. Security
review showed that this crossed the UAC boundary with user-writable code.

## Decision

Keep the launcher and Python App at ordinary integrity. Move only the five
allowlisted global-hotkey registrations into a small native broker installed in
an administrator-protected Program Files directory. The broker sends fixed
action IDs to the App through per-launch, local, ACL-restricted IPC and exits
with the App. No Python module, arbitrary command, file path, plugin, network
operation, game-process access, hook, polling path, service, or scheduled task
is allowed across the elevated boundary.

Broker release artifacts require Authenticode signing. Until a signed broker is
installed, Bomana retains the local `RegisterHotKey` path, clearly explains the
game-foreground limitation, and offers an explicit install/retry action.

## Consequences

- The mutable App package can no longer execute under an elevated token.
- UAC is limited to a fixed, protected, auditable executable.
- Ordinary-integrity games keep working through the existing local hotkey path.
- A release-grade broker now requires a code-signing identity and a protected
  installer flow; unsigned development binaries must not be published.
