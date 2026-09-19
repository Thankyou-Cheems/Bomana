import type { AngularRange } from "./extension-types";

/** Split a short unwrapped heading interval at the signed-angle boundary. */
export function canonicalAngularRanges(range: AngularRange): readonly AngularRange[] {
  const [low, high] = range;
  if (![low, high].every(Number.isFinite) || high < low) return [];
  const width = high - low;
  if (width >= 360 - 1e-7) return [[-180, 180]];
  const start = ((low + 180) % 360 + 360) % 360 - 180;
  const end = start + width;
  if (end <= 180 + 1e-7) return [[start, Math.min(180, end)]];
  return [[start, 180], [-180, end - 360]];
}
