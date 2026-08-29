# Bridge Contract

- `BRIDGE-01`: Bridge listens on explicit loopback by default.
- `BRIDGE-02`: Bridge exposes only enumerated official 8111, Local Data Store, and temporary mobile-pairing transport routes.
- `BRIDGE-03`: Bridge never reads game process memory, injects code, modifies game files, or sends game commands.
- `BRIDGE-04`: LAN listening exists only for an explicit temporary mobile pairing session.
- `BRIDGE-05`: Bridge owns no Edition, App UI, solver, terrain model, or CheemsPay credential.
- `BRIDGE-06`: Bridge release bytes are bound to a versioned SHA-256 document and Sigstore bundle.
- `BRIDGE-07`: Mobile pairing and signed-object transport are public integration protocols; they MUST NOT embed Enhanced App code, terrain objects, or a solver.
- `BRIDGE-08`: Tray pairing MUST keep Bridge account-blind. Phone Web obtains a pairing-bound signed mobile lease, and Bridge independently verifies its signature, phone-only purpose, pairing id, and expiry without receiving an account access token.
- `BRIDGE-09`: `BomanaBridgeDiagnostics.exe` MUST remain a bounded single-file connectivity reporter and MUST NOT record account authorization, pairing secrets, game field values, maps, chats, or raw 8111 response bodies.
