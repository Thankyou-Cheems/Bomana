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
  // Fixed scale: 0–50% occupies 15%; 80–100% occupies 46% at a constant
  // rate. Integrating smoothstep between them joins both slope and curvature,
  // so acceleration through the transition cannot make the bar suddenly jump.
  if (ratio <= .5) return .3 * ratio;
  if (ratio >= .8) return .54 + 2.3 * (ratio - .8);
  const t = (ratio - .5) / .3;
  return .15 + .3 * (.3 * t + 2 * (t ** 3 - .5 * t ** 4));
}

function finite(value: number): number { return Number.isFinite(value) ? value : 0; }
function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, value));
}
