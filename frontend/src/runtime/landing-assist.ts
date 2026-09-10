import type { EditionSnapshot, NavigationItem } from "./runtime-types";
import type { GroundTrackEstimate } from "./ground-track";
import type { AircraftLandingProfile } from "./aircraft-parameters";
import { landingFlapReference, type LandingFlapReference } from "./landing-configuration";

export interface LandingSettings {
  readonly enabled: boolean;
  readonly automatic?: boolean;
  readonly runwayId: string | null;
  readonly reverse: boolean;
  readonly glideAngleDeg: number;
  readonly targetIasKmh: number | null;
  readonly runwayElevationM: number | null;
}
export const DEFAULT_LANDING_SETTINGS: LandingSettings = Object.freeze({
  enabled: false, automatic: true, runwayId: null, reverse: false, glideAngleDeg: 3,
  targetIasKmh: null, runwayElevationM: null,
});
export interface LandingGeometry {
  readonly courseDeg: number;
  readonly lengthM: number;
  /** Positive before the selected threshold, negative after it. */
  readonly thresholdDistanceM: number;
  /** Positive on the right of the inbound runway course. */
  readonly crossTrackM: number;
  readonly trackErrorDeg: number | null;
  readonly airportDistanceM: number;
  readonly airportBearingDeg: number | null;
  readonly airportTrackErrorDeg: number | null;
  readonly stage: "return" | "intercept" | "final" | "runway" | "past-runway";
  readonly heightM: number | null;
  readonly glideDeviationM: number | null;
  readonly referenceDescentMps: number | null;
  /** Product ground-track interception reference; never a commanded aircraft heading. */
  readonly guidanceCourseDeg?: number | null;
  readonly guidanceErrorDeg?: number | null;
  readonly thresholdTimeS?: number | null;
  readonly predictedThresholdCrossM?: number | null;
}
export interface LandingSnapshot {
  readonly settings: LandingSettings;
  readonly runways: readonly { readonly id: string; readonly label: string; readonly distanceKm: number }[];
  readonly runwayLabel: string;
  readonly status: "disabled" | "unavailable" | "guidance";
  readonly reason: string;
  readonly elevationM: number | null;
  readonly elevationSource: "manual" | "terrain" | null;
  readonly iasKmh: number | null;
  readonly verticalSpeedMps: number | null;
  readonly gearPercent: number | null;
  readonly airbrakePercent: number | null;
  readonly flapsPercent: number | null;
  readonly geometry: LandingGeometry | null;
  readonly aircraft?: AircraftLandingProfile | null;
  readonly gearRisk?: "unknown" | "reference" | "near-limit" | "over-limit" | "extension-too-fast";
  readonly flapReference?: LandingFlapReference;
}
export interface LandingInput {
  readonly context: string;
  readonly sampledAtMs?: number;
  readonly fresh: boolean;
  readonly navigation: EditionSnapshot["navigation"];
  readonly track: GroundTrackEstimate | null;
  readonly altitudeM: number | null;
  readonly iasKmh: number | null;
  readonly verticalSpeedMps: number | null;
  readonly gearPercent: number | null;
  readonly airbrakePercent: number | null;
  readonly flapsPercent: number | null;
  readonly aircraft?: AircraftLandingProfile | null;
}

export function validateLandingSettings(value: LandingSettings): void {
  if (typeof value.enabled !== "boolean" || typeof value.reverse !== "boolean"
    || value.automatic !== undefined && typeof value.automatic !== "boolean"
    || !(value.runwayId === null || typeof value.runwayId === "string")
    || !Number.isFinite(value.glideAngleDeg) || value.glideAngleDeg < 1 || value.glideAngleDeg > 8
    || !(value.targetIasKmh === null || Number.isFinite(value.targetIasKmh) && value.targetIasKmh >= 60 && value.targetIasKmh <= 600)
    || !(value.runwayElevationM === null || Number.isFinite(value.runwayElevationM) && value.runwayElevationM >= -1000 && value.runwayElevationM <= 10000)) {
    throw new Error("降落参数无效：参考角 1–8°，IAS 60–600 km/h，高程 −1000–10000 m");
  }
}

export function landingRunways(navigation: EditionSnapshot["navigation"]): readonly NavigationItem[] {
  const scale = navigation?.mapScaleM;
  if (!scale || !scale.every(v => Number.isFinite(v) && v > 0)) return [];
  return navigation.items.filter(item => {
    if (item.kind !== "airfield" || !item.friendly || item.hostile || !item.runwayStart || !item.runwayEnd) return false;
    if (![...item.runwayStart, ...item.runwayEnd].every(v => Number.isFinite(v) && v >= 0 && v <= 1)) return false;
    const length = Math.hypot((item.runwayEnd[0] - item.runwayStart[0]) * scale[0], (item.runwayEnd[1] - item.runwayStart[1]) * scale[1]);
    return length >= 150;
  }).sort((a, b) => a.distanceKm - b.distanceKm || a.id.localeCompare(b.id));
}

export function landingGeometry(input: {
  readonly player: { readonly x: number; readonly y: number };
  readonly scale: readonly [number, number];
  readonly start: readonly [number, number];
  readonly end: readonly [number, number];
  readonly altitudeM: number | null;
  readonly elevationM: number | null;
  readonly glideAngleDeg: number;
  readonly velocity: readonly [number, number] | null; // map x / map y, m/s
}): LandingGeometry {
  const dx = (input.end[0] - input.start[0]) * input.scale[0];
  const dy = (input.end[1] - input.start[1]) * input.scale[1];
  const lengthM = Math.hypot(dx, dy), ux = dx / lengthM, uy = dy / lengthM;
  const px = (input.player.x - input.start[0]) * input.scale[0];
  const py = (input.player.y - input.start[1]) * input.scale[1];
  const along = px * ux + py * uy, crossTrackM = -px * uy + py * ux;
  const courseDeg = (Math.atan2(ux, -uy) * 180 / Math.PI + 360) % 360;
  const velocity = input.velocity;
  const trackErrorDeg = velocity && Math.hypot(...velocity) >= 10
    ? ((Math.atan2(velocity[0], -velocity[1]) * 180 / Math.PI - courseDeg + 540) % 360) - 180 : null;
  const toAirportX = dx * .5 - px, toAirportY = dy * .5 - py;
  const airportDistanceM = Math.hypot(toAirportX, toAirportY);
  const airportBearingDeg = airportDistanceM >= 1 ? (Math.atan2(toAirportX, -toAirportY) * 180 / Math.PI + 360) % 360 : null;
  const airportTrackErrorDeg = trackErrorDeg !== null && airportBearingDeg !== null
    ? ((courseDeg + trackErrorDeg - airportBearingDeg + 540) % 360) - 180 : null;
  const nearApproach = along >= -15_000 && along <= lengthM + 1000
    && Math.abs(crossTrackM) <= Math.max(750, -along * .5);
  const aligned = nearApproach && along < -30 && Math.abs(crossTrackM) <= Math.max(80, -along * .1)
    && trackErrorDeg !== null && Math.abs(trackErrorDeg) <= 30;
  const stage = !nearApproach ? "return" : along >= lengthM ? "past-runway" : along >= 0 ? "runway" : aligned ? "final" : "intercept";
  const heightM = input.altitudeM !== null && input.elevationM !== null ? input.altitudeM - input.elevationM : null;
  const slope = Math.tan(input.glideAngleDeg * Math.PI / 180);
  // 15 m threshold crossing height is an editable-angle planning reference,
  // not an observed touchdown point or a game's native ILS signal.
  const glideDeviationM = aligned && heightM !== null ? heightM - (15 - along * slope) : null;
  const referenceDescentMps = aligned && heightM !== null && velocity
    ? -(velocity[0] * ux + velocity[1] * uy) * slope : null;
  let guidanceCourseDeg: number | null = null, guidanceErrorDeg: number | null = null;
  let thresholdTimeS: number | null = null, predictedThresholdCrossM: number | null = null;
  if (velocity && trackErrorDeg !== null) {
    // A bounded 12-second lookahead avoids steering solely from position: an
    // aircraft on the centerline can already be drifting out of the approach.
    const lookaheadM = Math.max(300, Math.min(3000, Math.hypot(...velocity) * 12));
    const interceptDeg = Math.max(-35, Math.min(35, Math.atan2(crossTrackM, lookaheadM) * 180 / Math.PI));
    guidanceCourseDeg = stage === "return" ? airportBearingDeg : (courseDeg - interceptDeg + 360) % 360;
    if (guidanceCourseDeg !== null) guidanceErrorDeg = ((courseDeg + trackErrorDeg - guidanceCourseDeg + 540) % 360) - 180;
    const closingMps = velocity[0] * ux + velocity[1] * uy;
    if (along < 0 && closingMps >= 10 && -along / closingMps <= 120) {
      thresholdTimeS = -along / closingMps;
      predictedThresholdCrossM = crossTrackM + (-velocity[0] * uy + velocity[1] * ux) * thresholdTimeS;
    }
  }
  return { courseDeg, lengthM, thresholdDistanceM: -along, crossTrackM, trackErrorDeg,
    airportDistanceM, airportBearingDeg, airportTrackErrorDeg, stage,
    heightM, glideDeviationM, referenceDescentMps, guidanceCourseDeg, guidanceErrorDeg,
    thresholdTimeS, predictedThresholdCrossM };
}

/** Acquire an airport-bound return, then retain the same runway through its approach. */
export class LandingAssist {
  #settings = DEFAULT_LANDING_SETTINGS;
  #context = "";
  #runwayKey = "";
  #gearRisk: NonNullable<LandingSnapshot["gearRisk"]> = "unknown";
  #flapRisk = "unknown";
  #candidateKey = "";
  #candidateSince = 0;
  #exitSince = 0;
  #lastAutoAt = 0;
  #cooldownUntil = 0;
  settings(): LandingSettings { return this.#settings; }
  configure(settings: LandingSettings, navigation: EditionSnapshot["navigation"]): void {
    validateLandingSettings(settings);
    const runways = landingRunways(navigation);
    const runway = settings.runwayId ? runways.find(item => item.id === settings.runwayId) : runways[0];
    if (settings.enabled && !runway) throw new Error("暂无带有效端点的友方跑道");
    const key = runway ? JSON.stringify([runway.runwayStart, runway.runwayEnd]) : "";
    const changed = (runway?.id ?? null) !== this.#settings.runwayId || key !== this.#runwayKey;
    let reverse = settings.reverse;
    if (changed && runway && navigation?.player && navigation.mapScaleM) {
      const distance = (p: readonly [number, number]) => Math.hypot((p[0] - navigation.player!.x) * navigation.mapScaleM![0], (p[1] - navigation.player!.y) * navigation.mapScaleM![1]);
      reverse = distance(runway.runwayEnd!) < distance(runway.runwayStart!);
    }
    const directionChanged = changed || reverse !== this.#settings.reverse;
    this.#settings = { ...settings, automatic: settings.automatic ?? false, runwayId: runway?.id ?? null, reverse,
      runwayElevationM: directionChanged ? null : settings.runwayElevationM };
    this.#runwayKey = key;
    this.#candidateKey = ""; this.#exitSince = 0;
  }
  update(input: LandingInput, terrainElevation: (point: readonly [number, number]) => number | null = () => null): LandingSnapshot {
    if (this.#context && input.context !== this.#context) {
      this.#settings = { ...DEFAULT_LANDING_SETTINGS, automatic: this.#settings.automatic }; this.#runwayKey = "";
      this.#gearRisk = "unknown";
      this.#flapRisk = "unknown";
      this.#candidateKey = ""; this.#exitSince = this.#lastAutoAt = this.#cooldownUntil = 0;
    }
    this.#context = input.context;
    this.#updateAutomatic(input);
    const limit = input.aircraft?.gearIasKmh;
    if (!input.fresh || input.iasKmh === null || input.gearPercent === null || !limit) this.#gearRisk = "unknown";
    else {
      const ratio = input.iasKmh / limit;
      if (input.gearPercent <= 0) this.#gearRisk = ratio >= 1 && input.aircraft?.gearControl !== false ? "extension-too-fast" : "reference";
      else if (ratio >= 1 || this.#gearRisk === "over-limit" && ratio >= .98) this.#gearRisk = "over-limit";
      else if (ratio >= .9 || this.#gearRisk === "near-limit" && ratio >= .88) this.#gearRisk = "near-limit";
      else this.#gearRisk = "reference";
    }
    const settings = this.#settings, runways = landingRunways(input.navigation);
    const flapReference = landingFlapReference(input.aircraft, input.fresh ? input.flapsPercent : null,
      input.fresh ? input.iasKmh : null, this.#flapRisk);
    this.#flapRisk = flapReference.risk;
    const runway = runways.find(item => item.id === settings.runwayId);
    const unavailable = !settings.enabled ? "disabled" : !input.fresh || !input.navigation?.player ? "telemetry"
      : !runway ? "runway-missing" : JSON.stringify([runway.runwayStart, runway.runwayEnd]) !== this.#runwayKey ? "runway-changed" : "";
    const start = runway && (settings.reverse ? runway.runwayEnd! : runway.runwayStart!);
    const end = runway && (settings.reverse ? runway.runwayStart! : runway.runwayEnd!);
    const terrainM = !unavailable && start && settings.runwayElevationM === null ? terrainElevation(start) : null;
    const elevationM = settings.runwayElevationM ?? terrainM;
    const geometry = !unavailable && start && end && input.navigation?.player && input.navigation.mapScaleM ? landingGeometry({
      player: input.navigation.player, scale: input.navigation.mapScaleM, start, end,
      altitudeM: input.altitudeM, elevationM, glideAngleDeg: settings.glideAngleDeg,
      velocity: input.track?.valid ? [input.track.velocityX, -input.track.velocityZ] : null,
    }) : null;
    return { settings, runways: runways.map(({ id, label, distanceKm }) => ({ id, label, distanceKm })),
      runwayLabel: runway?.label ?? "", status: !settings.enabled ? "disabled" : geometry ? "guidance" : "unavailable",
      reason: unavailable, elevationM: geometry ? elevationM : null,
      elevationSource: geometry && elevationM !== null ? settings.runwayElevationM !== null ? "manual" : "terrain" : null,
      iasKmh: input.fresh ? input.iasKmh : null, verticalSpeedMps: input.fresh ? input.verticalSpeedMps : null,
      gearPercent: input.fresh ? input.gearPercent : null, airbrakePercent: input.fresh ? input.airbrakePercent : null,
      flapsPercent: input.fresh ? input.flapsPercent : null, geometry, aircraft: input.aircraft ?? null, gearRisk: this.#gearRisk, flapReference };
  }

  #updateAutomatic(input: LandingInput): void {
    const at = input.sampledAtMs, n = input.navigation, track = input.track;
    if (!this.#settings.automatic || !input.fresh || at == null || !Number.isFinite(at)
      || !n?.player || !n.mapScaleM || !track?.valid) {
      this.#candidateKey = ""; this.#exitSince = 0; return;
    }
    if (at <= this.#lastAutoAt) return;
    if (at - this.#lastAutoAt > 1500) { this.#candidateKey = ""; this.#exitSince = 0; }
    this.#lastAutoAt = at;
    const runways = landingRunways(n);
    const geometry = (r: NavigationItem, reverse: boolean) => landingGeometry({ player: n.player!, scale: n.mapScaleM!,
      start: reverse ? r.runwayEnd! : r.runwayStart!, end: reverse ? r.runwayStart! : r.runwayEnd!,
      altitudeM: null, elevationM: null, glideAngleDeg: this.#settings.glideAngleDeg,
      velocity: [track.velocityX, -track.velocityZ] });
    if (this.#settings.enabled) {
      const runway = runways.find(r => r.id === this.#settings.runwayId);
      // A missing or moved runway withdraws live guidance; it cannot select a replacement.
      if (!runway || JSON.stringify([runway.runwayStart, runway.runwayEnd]) !== this.#runwayKey) {
        this.#exitSince = 0; return;
      }
      const g = geometry(runway, this.#settings.reverse);
      // A runway-relative course is irrelevant while returning from its side.
      const leaving = g.airportDistanceM > g.lengthM * .5 + 1000 && Math.abs(g.airportTrackErrorDeg ?? 0) > 75
        || (g.airportDistanceM < g.lengthM * .5 + 2000 && input.verticalSpeedMps !== null && input.verticalSpeedMps > 3
          && input.gearPercent !== null && input.gearPercent < 5);
      if (!leaving) { this.#exitSince = 0; return; }
      if (!this.#exitSince) this.#exitSince = at;
      if (at - this.#exitSince >= 8000) {
        this.#settings = { ...this.#settings, enabled: false, runwayId: null, runwayElevationM: null };
        this.#runwayKey = ""; this.#candidateKey = ""; this.#exitSince = 0; this.#cooldownUntil = at + 15_000;
      }
      return;
    }
    if (at < this.#cooldownUntil) return;
    let best: { runway: NavigationItem; reverse: boolean; score: number } | null = null;
    for (const runway of runways) {
      const g = geometry(runway, false);
      const departing = g.airportDistanceM < g.lengthM * .5 + 2000 && input.verticalSpeedMps !== null && input.verticalSpeedMps > 3
        && input.gearPercent !== null && input.gearPercent < 5;
      const inbound = Math.hypot(track.velocityX, track.velocityZ) >= 20 && !departing
        && g.airportDistanceM >= g.lengthM * .5 + 600
        && g.airportTrackErrorDeg !== null && Math.abs(g.airportTrackErrorDeg) <= 25;
      if (!inbound) continue;
      // Airport choice follows the actual return track; runway direction is a separate nearest-end choice.
      const reverse = Math.hypot(g.thresholdDistanceM + g.lengthM, g.crossTrackM) < Math.hypot(g.thresholdDistanceM, g.crossTrackM);
      const score = g.airportDistanceM * (1 + Math.abs(g.airportTrackErrorDeg!) / 25);
      if (!best || score < best.score) best = { runway, reverse, score };
    }
    // Small position changes can swap the nearer end without changing the airport-bound return.
    const key = best ? `${best.runway.id}|${JSON.stringify([best.runway.runwayStart, best.runway.runwayEnd])}` : "";
    if (!key || key !== this.#candidateKey) { this.#candidateKey = key; this.#candidateSince = at; return; }
    if (best && at - this.#candidateSince >= 3000) {
      this.#settings = { ...this.#settings, enabled: true, runwayId: best.runway.id, reverse: best.reverse, runwayElevationM: null };
      this.#runwayKey = JSON.stringify([best.runway.runwayStart, best.runway.runwayEnd]);
      this.#candidateKey = ""; this.#exitSince = 0;
    }
  }
}
