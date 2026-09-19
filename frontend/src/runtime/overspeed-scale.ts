import { SPEED_WARNING_RATIOS } from "./speed-warning";

export interface OverspeedScaleProjection {
  readonly fillRatio: number;
  readonly markerRatios: readonly [number, number, number];
  readonly horizontalFocus: number;
  readonly visualScale: number;
}

export function overspeedDynamicProjection(
  value: number,
): OverspeedScaleProjection {
  const current = Math.max(0, finite(value));
  const focus = clamp((current - .5) / .5, 0, 1);
  return Object.freeze({
    fillRatio: speedStripProgress(current),
    markerRatios: Object.freeze(SPEED_WARNING_RATIOS.map(speedStripProgress)) as unknown as readonly [number, number, number],
    horizontalFocus: focus,
    visualScale: 1 + .8 * focus,
  });
}

export function speedStripProgress(value: number): number {
  const ratio = clamp(finite(value), 0, 1.1);
  // Preserve the smooth expansion near the model limit, and leave room for
  // exceeding it. 110% is the display extent, NOT a second damage threshold.
  // Markers share this mapping; the first two are advance warning margins.
  const compressedSlope = 2 / 17; // Normalizes total area: .85 * slope + .15 * 6 = 1.
  if (ratio <= .8) return compressedSlope * ratio / 1.6;
  if (ratio >= .9) return Math.min(1, (.4 + 6 * (ratio - .9)) / 1.6);
  const t = (ratio - .8) / .1;
  return (.8 * compressedSlope + .1 * (compressedSlope * t + (6 - compressedSlope) * (t ** 3 - .5 * t ** 4))) / 1.6;
}

function finite(value: number): number { return Number.isFinite(value) ? value : 0; }
function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, value));
}
