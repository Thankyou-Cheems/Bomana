# Public Edition contract

- **PUB-01 — Lite:** sortie timer and its settings / recovery. No navigation or solver.
- **PUB-02 — Standard:** official zone / airfield Basic Navigation, aircraft speed limits, measured / estimated fuel, checklist, timer, mission alerts and PiP. No manual POI, enemy tracking, airport module resolution, Y66 calibration, terrain, chat interpretation or weapon solving.
- **PUB-03 — Shared source:** production public editions and this repository use the same Public Runtime, Web entry and parameter projection. Enhanced extends the runtime privately; its algorithms and assets are excluded by the source allowlist and import checks.
- **PUB-04 — Mobile Pairing:** Standard pairs directly with the local Bridge without CheemsPay login. Public protocol and signed resource verification code may also describe Enhanced transport; they do not implement its solver or entitlement authority.
- **PUB-05 — Distribution:** public CI performs independent builds without production signing or server credentials. Official signed artifacts belong to the maintained release process. A public source update does not activate production.
- **PUB-06 — History:** preserve public history, tags and Releases. Export commits use only the preceding public commit as their parent. Never mirror the private Git history.
