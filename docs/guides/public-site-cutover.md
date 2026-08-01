# Public Site and Download Cutover

Use this runbook when changing `bomana.ruikang.wang` or the public download
catalog. The operation must be reversible and must not make subscriber bytes
public.

Public update artifacts remain on `https://bomanaupdate.ruikang.wang`.

## Preconditions

- Lite, Standard, and Launcher were built from clean checkouts.
- Their manifests, hashes, sizes, channels, and compatibility ranges were
  verified from the actual artifacts.
- The site catalog lists only Lite, Standard, and Launcher public artifacts.
- Super Bomb calls to action enter CheemsPay authorization; they do not expose a
  direct Enhanced object URL.
- The prior site/configuration and its content hashes are retained for rollback.

## Deploy

```powershell
uv run python tools/deploy_pages_mirror.py
```

Deploy update artifacts independently:

```powershell
uv run python tools/deploy_update_assets.py --target app --version X.Y.Z
uv run python tools/deploy_update_assets.py --target launcher
```

The public deploy tool must reject terrain and Enhanced App targets.

## Verify

From a clean browser session and a separate HTTP client, verify:

- the canonical page and static assets return expected MIME types and hashes;
- desktop and narrow layouts render without console errors;
- Standard and Lite catalog entries resolve only their signed public artifacts;
- Launcher metadata resolves the expected signed package;
- the Super Bomb action reaches authorization and reveals no artifact URL;
- an unauthenticated request to private manifest/artifact endpoints is denied;
- cache-busted and ordinary requests converge on the same release revision.

A `200` status alone is insufficient: compare raw byte length and SHA-256 for
critical JavaScript, catalog, and downloadable assets.

## Roll back

Restore the retained site objects/configuration, invalidate only affected cache
keys, and repeat the same byte-level checks. Do not weaken manifest validation
or temporarily publish subscriber artifacts to recover availability.
