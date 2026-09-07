export interface MapHeadingRay {
  readonly start: readonly [number, number];
  readonly end: readonly [number, number];
}

export function headingRayToMapEdge(x: number, y: number, headingDeg: number): MapHeadingRay | null {
  if (![x, y, headingDeg].every(Number.isFinite) || x < 0 || x > 1 || y < 0 || y > 1) return null;
  const radians = headingDeg * Math.PI / 180;
  const dx = Math.sin(radians);
  const dy = -Math.cos(radians);
  const candidates = [
    dx > 1e-12 ? (1 - x) / dx : dx < -1e-12 ? -x / dx : Number.POSITIVE_INFINITY,
    dy > 1e-12 ? (1 - y) / dy : dy < -1e-12 ? -y / dy : Number.POSITIVE_INFINITY,
  ].filter((value) => value >= 0 && Number.isFinite(value));
  const distance = Math.min(...candidates);
  if (!Number.isFinite(distance)) return null;
  return Object.freeze({
    start: Object.freeze([x, y] as const),
    end: Object.freeze([
      clampBoundary(x + dx * distance),
      clampBoundary(y + dy * distance),
    ] as const),
  });
}

function clampBoundary(value: number): number {
  if (Math.abs(value) < 1e-12) return 0;
  if (Math.abs(value - 1) < 1e-12) return 1;
  return Math.min(1, Math.max(0, value));
}
