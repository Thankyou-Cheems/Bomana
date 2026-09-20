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
  // Spend 95% of the bar BEFORE the source limit: 80/90/95/100% speed maps
  // to 15/40/65/95% width. Each join preserves position and movement rate.
  if (ratio <= .8) return .1875 * ratio;
  if (ratio < .9) {
    const t = (ratio - .8) / .1;
    return .15 + .1 * (.1875 * t + 3.125 * t ** 2 - .8125 * t ** 3);
  }
  if (ratio < .95) {
    const approach = ratio - .9;
    return .4 + 4 * approach + 20 * approach ** 2;
  }
  if (ratio < 1) return .65 + 6 * (ratio - .95);
  // The short red tail means ALREADY over limit, not spare operating room.
  // Exponent 12 joins the preceding slope of 6, then flattens at the 110%
  // drawing cap. Numeric percentage and warning state remain uncapped.
  const overflow = (ratio - 1) / .1;
  return 1 - .05 * (1 - overflow) ** 12;
}

function finite(value: number): number { return Number.isFinite(value) ? value : 0; }
function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, value));
}
