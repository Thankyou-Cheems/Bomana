# Loadout tier icons

War Thunder's actual player-visible loadout icons, used for the user's explicit
2026-09-27 request to reproduce the real in-game icons faithfully. These are
**Gaijin artwork, not original Bomana designs**. The repository's MIT license
does not relicense the underlying artwork.

Reference: local client 2.59.0.28, `ui/atlases.vromfs.bin`, SHA-256
`d95ac53e00c5299a3e1a3adf30d1490903ccd95fc91e6f9f00bbf21268d9e6b0`.
Only icons referenced by the calculator are included. The extracted AVIF files
stay in the ignored local research directory. Every WebP preserves the complete
native canvas (389 at 100×100, two at 128×128) and alpha channel exactly. The compressor chooses the
smallest of the original lossless encoding, optimized lossless encoding with
irrelevant RGB under zero alpha cleared, and quality-92 WebP. The latter is
allowed only when mean RGB error on alpha > 127 pixels is at most 3/255;
complex icons that exceed that threshold remain lossless.

The complete fixed/custom set is 391 icons: 3,729,120 bytes as lossless WebP,
3,021,462 bytes after compression (19.0% smaller). Images are lazy loaded;
opening the calculator does not download all icons or custom-rule data.

Reproduce compression and verify alpha/dimensions from the local `gameuiskin` directory:

```text
uv run --with pillow==11.3.0 tools/research/prepare_loadout_icons.py <gameuiskin-directory>
```

Each image describes a whole tier, not one projectile. Do not multiply it by
ammunition count, recolor it, trim its transparent margins or stretch its aspect
ratio. Multiple weapons sharing a native tier retain the first tier image and
contribute to the combined tooltip, as in `getPredefinedTiers`.

A vector tracing experiment was rejected because it introduced gradient and
edge artifacts while greatly increasing the payload. See the source research
note for that comparison and the scope of this user-requested asset inclusion.
