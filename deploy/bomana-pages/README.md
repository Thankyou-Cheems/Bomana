# Bomana public-site deployment

This directory contains the versioned origin and EdgeOne configuration for
`https://bomana.ruikang.wang/`.

- `Caddyfile.snippet` is appended to the shared origin Caddyfile.
- `legacy-redirect.caddy` is inserted into the existing
  `http://ruikang.wang` site block.
- `edgeone-domain.template.json` creates an explicit HTTPS-pull acceleration
  domain after replacing its two placeholders.
- `edgeone-rule.template.json` is passed as the `Rules` payload to EdgeOne's
  `CreateRule` API.

The app, launcher, terrain-pack APIs and binary downloads remain at
`https://bomanaupdate.ruikang.wang`. Do not apply these site rules to the
wildcard acceleration domain.

Validate the candidate Caddyfile before replacing `/opt/Caddyfile`, keep a
timestamped server-side backup, then reload the existing Caddy container.
Deploy the static files only after the new host returns without a redirect
loop:

```powershell
uv run python tools/deploy_pages_mirror.py --skip-catalog-refresh
```

`--skip-catalog-refresh` is intentional during a website-only pre-release:
the deployed catalog continues to advertise the currently published
Launcher/App versions.
