# Expose Web Surfaces While Keeping Their Behavior in the Application

Status: Accepted (2026-08-03)

The Launcher may expose explicit Web Surface Launch Control so users can start
or open an application-provided web surface, including a future web mode that
does not use an in-game overlay. The Launcher is responsible for discoverable
launch actions and the handoff to the application/browser, but it does not own
the Web Cockpit server, routes, ports, capabilities, or feature settings.

The selected application advertises which web surfaces it supports through its
verified installation metadata or launch contract. The Launcher renders only
those actions and does not show subscriber-only web controls for a channel that
does not provide them. The planned standalone no-overlay web mode remains
hidden until a released application capability declares it available.
