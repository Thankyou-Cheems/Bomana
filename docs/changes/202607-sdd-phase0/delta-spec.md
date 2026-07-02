# 202607 SDD Phase 0 Delta Spec

## Added

- `docs/specs/runtime-8111-boundary.md`
- `docs/specs/release-signing.md`
- `docs/specs/threading-ui-contract.md`
- `docs/specs/config-variants.md`
- `docs/specs/testing-quality-gates.md`
- `docs/specs/schemas/app-manifest.schema.json`
- `docs/specs/schemas/launcher-manifest.schema.json`
- `tests/contracts/test_manifest_schemas.py`
- `tests/contracts/test_runtime_8111_boundary.py`
- `tests/contracts/test_tk_thread_contract.py`

## Changed

- Entrypoint documentation now routes durable rules to `docs/specs/`.
- `README.md` no longer names the retired GitHub-to-Tencent deployment fallback.
- Test documentation includes the `tests/contracts/` layer.

## Behavior

No production runtime behavior changes are intended in Phase 0.
