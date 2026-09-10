import type { AircraftLandingProfile } from "./aircraft-parameters";

export interface LandingFlapReference {
  readonly limitIasKmh: number | null;
  /** Next documented curve point, not a claim about a selectable flap detent. */
  readonly next: { readonly percent: number; readonly limitIasKmh: number } | null;
  readonly risk: "unknown" | "reference" | "near-limit" | "over-limit";
}

/** Source IAS/fraction envelope only: never a target approach or stall speed. */
export function landingFlapReference(profile: AircraftLandingProfile | null | undefined,
  percent: number | null, ias: number | null, previous: string): LandingFlapReference {
  const points = profile?.flapsIasKmh;
  // No manual flap control does not mean no flaps (e.g. automatic JAS39 flaps).
  if (!points?.length || percent === null
    || !Number.isFinite(percent) || percent < 0 || percent > 100) return { limitIasKmh: null, next: null, risk: "unknown" };
  const fraction = percent / 100;
  const next = points.find(point => point[0] * 100 > percent + .5);
  let limitIasKmh: number | null = null;
  if (percent > 0) {
    const index = points.findIndex(point => point[0] >= fraction);
    if (index < 0) limitIasKmh = points[points.length - 1]![1];
    else {
      const upper = points[index]!;
      // The locked native table consumer uses linear interpolation and endpoint
      // clamping. This reproduces the curve, not its unresolved damage consumer.
      const lower = points[Math.max(0, index - 1)]!;
      limitIasKmh = index === 0 || upper[0] === fraction ? upper[1]
        : lower[1] + (upper[1] - lower[1]) * (fraction - lower[0]) / (upper[0] - lower[0]);
    }
  }
  let risk: LandingFlapReference["risk"] = "unknown";
  if (percent === 0) risk = "reference";
  else if (limitIasKmh !== null && ias !== null && Number.isFinite(ias) && ias >= 0) {
    const ratio = ias / limitIasKmh;
    risk = ratio >= 1 || previous === "over-limit" && ratio >= .98 ? "over-limit"
      : ratio >= .9 || previous === "near-limit" && ratio >= .88 ? "near-limit" : "reference";
  }
  return { limitIasKmh, next: next ? { percent: next[0] * 100, limitIasKmh: next[1] } : null, risk };
}
