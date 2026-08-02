# Release Signing and Delivery Contract

This contract covers public Lite/Standard artifacts, the universal Launcher,
and the minimum trust boundary used when the Launcher hands off to private
subscriber delivery.

- `SIGN-01`: Every release manifest MUST conform to its repository-owned JSON
  schema and reject additional or malformed security-critical fields.
- `SIGN-02`: Every manifest MUST carry a non-empty Ed25519 signature and an
  explicit signing-key identifier.
- `SIGN-03`: The Launcher package MUST contain the runtime resources required to
  verify, install, recover, and roll back without importing the App package.
- `SIGN-04`: Signature verification MUST cover the canonical serialized payload,
  not a reinterpreted subset.
- `SIGN-05`: Artifact download MUST be bounded in size and time and MUST reject
  redirects or schemes outside the configured trust policy.
- `SIGN-06`: The downloaded artifact SHA-256 and byte length MUST match the
  signed manifest before extraction.
- `SIGN-07`: Archive extraction MUST reject absolute paths, parent traversal,
  duplicate destinations, links, and unsupported entry types.
- `SIGN-08`: Installation MUST use staging and an atomic activation step while
  retaining one last known-good version.
- `SIGN-09`: App and Launcher build roots MUST be separate, complete closures;
  neither may depend on ambient source files after packaging.
- `SIGN-10`: App manifests MUST bind canonical channel, version, file name,
  digest, size, and minimum compatible Launcher version.
- `SIGN-11`: Launcher manifests MUST bind canonical version, file name, digest,
  size, and minimum compatible App version.
- `SIGN-12`: Downgrades below the active compatibility or security floor MUST be
  rejected unless an explicit signed recovery policy permits them.
- `SIGN-13`: Private signing keys MUST enter only through protected deployment
  configuration and MUST never be printed or committed.
- `SIGN-14`: Public CI MUST build App artifacts only for Lite and Standard.
- `SIGN-15`: The JSON schemas under `docs/specs/schemas/` are the authoritative
  manifest shape definitions used by tests and release tooling.
- `SIGN-16`: Enhanced manifest and artifact endpoints MUST require a short-lived
  CheemsPay-derived grant in addition to the Launcher's valid local receipt.
- `SIGN-17`: The Launcher release build MUST compare the CheemsPay receipt key
  id and public key supplied by CI with the repository-owned subscription key
  contract and MUST fail before packaging on any mismatch.

GitHub build provenance, when present, is additional evidence; it does not
replace manifest signatures or create a Windows Authenticode publisher identity.
Public Tencent/EdgeOne publication is performed from a maintainer workstation by
`tools/deploy_update_assets.py`; GitHub-hosted Actions must not SSH, rsync, or scp
artifacts to that host.
