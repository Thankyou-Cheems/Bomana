# Local terrain-height pack

Run every command below from the Bomana project root. Terrain utilities live in
the project-local `tools` directory and are launched through `uv run`, so callers
do not need to know or invoke the virtual-environment path directly.

Bomana can fill the target-height field missing from 8111 with a local,
terrain-only elevation pack. The extractor prefers the installed client's
native Dagor `\0HM2` physics heightmap and otherwise reads the `lmap/LTdump`
collision terrain. It deliberately ignores buildings, vegetation, scene
objects, generated instances, vehicles, and dynamic objects.

Level terrain uses Dagor world Y, while 8111 `H, m` uses the level's vertical
datum. The installed client's `aces.vromfs.bin` level config supplies that
origin as `levels/<map>.blk:water_level`; the pack stores it per map. When that
field is explicit, the target collision surface is
`max(terrain_world_y, water_level)` so underwater seabed is clamped to the
actual water surface, then the solver receives
`collision_surface_world_y - water_level`. A missing `water_level` uses the
engine's zero datum without inventing a water surface. For example,
`air_israel` declares `60.0`, which
matches the approximately 60 m world-Y/8111 offset measured in the same game
process.
The same datum is added to aircraft `H, m` before the Dagor atmosphere curve is
evaluated; it therefore controls both target height and aerodynamic density.

Developer-generated `.bth` files remain under
`%USERPROFILE%\.bomana\terrain-v1`. Release builds use the separately
versioned, integrity-pinned `terrain-v1`. Launcher 3.3+ stores it outside the
rotating App directory and hands the selected validated pack to `Enhanced`
through `BOMANA_TERRAIN_DIR`; Standard and Lite never resolve or install it.
The runtime still accepts an explicit developer override, then a legacy bundled
pack for migration compatibility, then the developer directory. It uses
`/map.img` only to identify the active grid and normal 8111 target coordinates
to query it.

## Build a compressed offline pack

Bomana can convert a complete validated `BTH1` directory into the drop-in
`BTH2` offline format. `BTH2` keeps the same grid geometry and interpolation,
then selects the smallest per-map integer depth that satisfies both a 0.5 m
maximum added-error budget and the existing 3 m P95 quality ceiling. Maps with
too little remaining quality margin automatically stay lossless. A reversible
two-dimensional predictor, byte shuffle, and standard-library Zstandard frame
compress the resulting samples.

```powershell
uv run tools\build_terrain_offline_pack.py `
  --input "$env:USERPROFILE\.bomana\terrain-v1" `
  --output "build\terrain-offline-balanced\terrain-v1" `
  --archive "dist\Bomana-terrain-offline-balanced-v1.zip"
```

The command refuses a non-empty output directory, loads every generated grid
through the production validator, writes `manifest.json`, and places the ZIP's
SHA-256 in the adjacent `.sha256` file. The archive is stored rather than
deflated again because every BTH2 payload is already compressed.

For a developer override, close Bomana, back up an existing terrain directory,
and extract the archive's `terrain-v1` folder under
`%USERPROFILE%\.bomana`. BTH2 requires a Bomana build containing BTH2 runtime
support; older builds continue to read the original BTH1 pack. Verify an
extracted pack independently with:

```powershell
uv run tools\build_terrain_offline_pack.py `
  --output "$env:USERPROFILE\.bomana\terrain-v1" `
  --verify-only
```

The offline package remains derived from locally installed game data. Confirm
that redistribution is permitted before publishing it outside the environment
where it was generated.

## Independent release lifecycle

Terrain changes much less frequently than the App. The monolithic source
archive remains pinned by name, exact byte size, SHA-256, map count, archive
root, and fallback URLs in `tools/release_assets/terrain-v1.json`, but it is
only a maintainer input. End users do not receive that archive inside each App
release.

Prepare the validated source pack from an existing pinned archive when needed:

```powershell
uv run python tools/prepare_builtin_terrain.py

uv run python tools/prepare_builtin_terrain.py `
  --archive "dist\Bomana-terrain-offline-balanced-v1.zip"
```

Then build the independent signed release:

```powershell
uv run python tools\build_terrain_release.py
```

This writes `dist/terrain-release/terrain_manifest.json`,
`checksums_terrain.txt`, and `objects/`. The Ed25519-signed manifest covers the
logical pack id, content-derived revision, map count, total bytes, and every
runtime filename/object filename/SHA-256/size tuple. Object filenames contain
their SHA-256, so identical files keep the same URL across terrain revisions.
The manually triggered `build-terrain.yml` workflow publishes these assets to
the independent `terrain-v1` GitHub Release; normal App/Launcher tags never run
that workflow.

Deploy a changed terrain revision to Tencent/EdgeOne from the maintainer
workstation:

```powershell
uv run python tools/deploy_update_assets.py --target terrain
```

`--target all` intentionally excludes terrain, so ordinary App and Launcher
publishes do not include or re-upload the roughly 118 MB resource. The terrain
target refuses to overwrite an existing content-hash object with different
bytes, atomically updates the signed current manifest, and verifies every
public object. Keep `terrain-v1` for compatible data refreshes: changing one
map produces a new revision but only that map plus changed small metadata
objects are new. Use a new logical id such as `terrain-v2` only for an
incompatible pack/runtime contract.

On the client, Launcher keeps a content-addressed `terrain/objects` cache,
immutable revision directories under `terrain/packs`, and a small atomic
`terrain/current.json` selector inside the launcher data root. If the signed
revision and all runtime files are already valid, no object request is made.
On an update, unchanged hashes are hard-linked or copied from the cache; an
upgrade from the old embedded layout also imports matching files locally.
Failed, cancelled, truncated, or hash-mismatched downloads never replace the
current pack.

## View a pseudocolor heightmap

Launch the desktop viewer without arguments. It opens the compressed build pack
when present and otherwise uses the installed `%USERPROFILE%\.bomana\terrain-v1`
directory:

```powershell
uv run tools\terrain_heightmap_viewer.py
```

The viewer can switch between the effective 8111 target altitude and raw Dagor
world height, offers terrain, viridis, turbo, and grayscale palettes, and saves
the current view as PNG. It renders world max-Z at the top so the preview has
the same vertical orientation as the 8111 tactical map.

For scripted export, first list map ids and then render one map:

```powershell
uv run tools\terrain_heightmap_viewer.py --list

uv run tools\terrain_heightmap_viewer.py `
  --map air_pyrenees `
  --palette terrain `
  --max-size 1600 `
  --output "dist\terrain-previews\air_pyrenees-terrain.png" `
  --open
```

The PNG includes the source grid identity, elevation range, palette, and terrain
SHA-256 as metadata. Rendering always loads the selected BTH1/BTH2 file through
the same integrity validator used by the App.

## Build the pack

Use the repository virtual environment and provide:

- the War Thunder installation root;
- JSON-form level configs extracted from `aces.vromfs.bin`;
- an external compatible `ooz` executable for `LTdump` terrain streams;
- when the open decoder cannot read a newer map-texture or `HM2` stream, a
  local licensed `oo2core_9_win64.dll` that you already have permission to use.

Extract only the small level-config folder with a locally built `wt_ext_cli`:

```powershell
& 'C:\path\to\wt_ext_cli.exe' unpack_vromf `
  -i 'D:\SteamLibrary\steamapps\common\War Thunder\aces.vromfs.bin' `
  -o "$env:TEMP\bomana-aces-levels" `
  --format Json `
  --blk_extension blkx `
  --folder levels
```

```powershell
uv run tools\terrain_heightmap_extractor.py `
  --build-pack `
  --game-root 'D:\SteamLibrary\steamapps\common\War Thunder' `
  --level-config-dir "$env:TEMP\bomana-aces-levels" `
  --ooz 'C:\path\to\ooz.exe' `
  --oodle-dll 'C:\path\to\oo2core_9_win64.dll' `
  --spacing 64 `
  --min-spacing 8 `
  --max-p95-error 3 `
  --validation-samples 5000 `
  --workers 4
```

The command discovers dedicated `air_*`, `arcade_*`, and legacy air-battle
levels represented by `locations_maps.dxp.bin`, writes one integrity-checked
grid per map, and records P50/P95/P99/max interpolation error in `index.json`.
The level config's `mapCoord0/mapCoord1` are stored separately from the terrain
grid bounds. This matters for older island maps whose 8111 tactical-map extent
is much larger than their collision terrain: the map can still be identified,
while a target outside the actual grid safely returns no terrain height.
Native `HM2` samples retain their original cell spacing, full unsigned 16-bit
range, and the game's four-triangle diamond interpolation. `LTdump` maps start
at 64 m and automatically refine to 32, 16, or 8 m while P95 exact-triangle
error exceeds 3 m and the bounded grid-size limit permits it. Any failed map is
listed under `failures`; a non-empty failure list
makes the command exit non-zero.

If terrain samples were already generated, add the altitude metadata without
resampling the maps:

```powershell
uv run tools\terrain_heightmap_extractor.py `
  --apply-altitude-datums `
  --level-config-dir "$env:TEMP\bomana-aces-levels"
```

Load every file through the production integrity validator and summarize source
types, spacings, quality exceptions, and ambiguous fingerprints:

```powershell
uv run tools\terrain_heightmap_extractor.py --audit-pack
```

Set `BOMANA_TERRAIN_DIR` only when testing a pack outside the default location.
Restart Bomana after generating or replacing the pack. On a recognized map the
CCRP work item reports `target_altitude_source=terrain`; if no validated
terrain is available, prediction fails closed with `terrain_unavailable`.

## Focused verification

```powershell
.\.venv\Scripts\pytest.exe `
  tests\test_terrain_elevation.py `
  tests\test_terrain_heightmap_extractor.py `
  tests\test_bombing_prediction_constraints.py `
  tests\test_runtime_threading.py
```

For a live smoke, start the source app after the pack finishes, enter a match,
and keep 8111 available. The log event `terrain_map_identified` must name the
active map, and the cached bombing result must use `terrain` rather than the
fallback source before treating target elevation as active.
