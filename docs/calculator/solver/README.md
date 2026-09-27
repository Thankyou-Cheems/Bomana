# Calculator optimization runtime

Vendored from [`highs` 1.15.3](https://github.com/lovasoa/highs-js), including its
MIT license. Run `node frontend/scripts/copy-calculator-solver.mjs` to refresh
the files from the pinned frontend development dependency.

The calculator loads this runtime only in a background module worker when a
selected aircraft needs a recommendation. No solver service or external CDN is
used. The worker is cancelled when the aircraft, target, mode or fixed stores
change. A two-second pass can publish a feasible preview; the subsequent pass
has a bounded search time. Only a proven optimum is labelled optimal.

`loadout-optimizer.mjs` uses binary option selection, slot occupation,
dependency/conflict, wing mass and worst-case balance constraints. Integer
projectile allocations independently cover each target. Reward comparison
includes the actual curve's upward discontinuity at its first piecewise knot.
Returned stores and allocations are checked again against the original native
validator and unrounded damage data before being displayed.
