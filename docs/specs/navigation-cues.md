# Public Navigation Cue Contract

- `NAVCUE-01`: Navigation coordinates MUST use the normalized official 8111 map
  frame and reject missing or degenerate map metadata.
- `NAVCUE-02`: Zone, airfield, and point-of-interest selection MUST preserve a
  stable semantic identity across refreshes when the source object remains.
- `NAVCUE-03`: Bearing and distance MUST become unavailable when ownship or
  target coordinates are stale, non-finite, or outside the active map frame.
- `NAVCUE-04`: Heading displays MUST use one shared wrap/shortest-turn rule so
  integrated and detached public views cannot disagree at north crossing.
- `NAVCUE-05`: User-selectable public navigation actions MUST have persistent,
  keyboard-reachable controls and a visible selected state.
- `NAVCUE-06`: Disabling public navigation in Lite MUST prevent its worker state,
  controls, and detached window from being created.
- `NAVCUE-07`: Navigation output is advisory and MUST NOT send input to the game.

Subscriber targeting and prediction semantics are owned by the private module
and are deliberately outside this public specification.
