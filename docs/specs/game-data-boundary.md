# Official Game Data Boundary Contract

- `DATA-01`: Production App code MUST acquire live game state only through War
  Thunder's official loopback HTTP endpoints.
- `DATA-02`: Production App and Launcher code MUST NOT import process-memory,
  debugger, injection, or game-file mutation libraries.
- `DATA-03`: Missing or stale official data MUST produce an explicit unavailable
  state, never a hidden alternate acquisition path.
- `DATA-04`: Offline research tools, captures, and extracted working data MUST
  remain outside public and subscriber runtime packages.
- `DATA-05`: Tests MAY use deterministic fixtures but MUST NOT describe them as
  current live-game evidence.
