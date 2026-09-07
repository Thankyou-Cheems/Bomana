export interface OfficialMapInfoBounds {
  readonly minimum: readonly [number, number];
  readonly maximum: readonly [number, number];
}

export function normalizeOfficialMapInfo(
  raw: Readonly<Record<string, unknown>> | null,
): OfficialMapInfoBounds | null {
  if (
    !raw
    || raw.valid === false
    || !Array.isArray(raw.map_min)
    || !Array.isArray(raw.map_max)
  ) return null;
  const minimum = tuple(raw.map_min);
  const maximum = tuple(raw.map_max);
  if (!minimum || !maximum || maximum[0] <= minimum[0] || maximum[1] <= minimum[1]) return null;
  return Object.freeze({ minimum, maximum });
}

function tuple(raw: readonly unknown[]): readonly [number, number] | null {
  const x = finite(raw[0]);
  const y = finite(raw[1]);
  return x === null || y === null ? null : Object.freeze([x, y]);
}

function finite(raw: unknown): number | null {
  return typeof raw === "number" && Number.isFinite(raw) ? raw : null;
}
