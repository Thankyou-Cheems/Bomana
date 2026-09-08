export interface OverspeedScaleProjection {
  readonly fillRatio: number;
  readonly markerRatios: readonly [number, number, number];
  readonly horizontalFocus: number;
  readonly visualScale: number;
}

export function overspeedDynamicProjection(
  value: number,
  thresholds: readonly [number, number, number] = [0.94, 0.97, 0.992],
): OverspeedScaleProjection {
  const current = Math.max(0, finite(value));
  const [caution, warning, critical] = thresholds;
  const focus = clamp((current - .5) / .5, 0, 1);
  const markers = [caution, warning, critical].map(speedStripProgress);
  return Object.freeze({
    fillRatio: speedStripProgress(current),
    markerRatios: Object.freeze(markers) as unknown as readonly [number, number, number],
    horizontalFocus: focus,
    visualScale: 1 + .8 * focus,
  });
}

export function speedStripProgress(value: number): number {
  const ratio = clamp(finite(value), 0, 1);
  if (ratio >= 1) return 1;
  // Fixed scale: 0–80% uses less than 10% of the strip; 90–100% uses 60%
  // at a constant rate. Integrating smoothstep over 80–90% joins both slope
  // and curvature, keeping movement smooth before the expanded warning bands.
  const compressedSlope = 2 / 17; // Normalizes total area: .85 * slope + .15 * 6 = 1.
  if (ratio <= .8) return compressedSlope * ratio;
  if (ratio >= .9) return .4 + 6 * (ratio - .9);
  const t = (ratio - .8) / .1;
  return .8 * compressedSlope + .1 * (compressedSlope * t + (6 - compressedSlope) * (t ** 3 - .5 * t ** 4));
}

function finite(value: number): number { return Number.isFinite(value) ? value : 0; }
function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, value));
}
