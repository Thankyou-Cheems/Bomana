import type { EditionSnapshot, NavigationItem } from "./runtime-types";
import type { GroundTrackEstimate } from "./ground-track";
import type { AircraftLandingProfile } from "./aircraft-parameters";

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
  readonly stage: "intercept" | "final" | "runway" | "past-runway";
  readonly heightM: number | null;
  readonly glideDeviationM: number | null;
  readonly referenceDescentMps: number | null;
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
  const aligned = along < -30 && Math.abs(crossTrackM) <= Math.max(80, -along * .1)
    && trackErrorDeg !== null && Math.abs(trackErrorDeg) <= 30;
  const stage = along >= lengthM ? "past-runway" : along >= 0 ? "runway" : aligned ? "final" : "intercept";
  const heightM = input.altitudeM !== null && input.elevationM !== null ? input.altitudeM - input.elevationM : null;
  const slope = Math.tan(input.glideAngleDeg * Math.PI / 180);
  // 15 m threshold crossing height is an editable-angle planning reference,
  // not an observed touchdown point or a game's native ILS signal.
  const glideDeviationM = aligned && heightM !== null ? heightM - (15 - along * slope) : null;
  const referenceDescentMps = aligned && heightM !== null && velocity
    ? -(velocity[0] * ux + velocity[1] * uy) * slope : null;
  return { courseDeg, lengthM, thresholdDistanceM: -along, crossTrackM, trackErrorDeg, stage,
    heightM, glideDeviationM, referenceDescentMps };
}

/** A sustained inbound approach or a manual lock; an acquired runway never chases targets. */
export class LandingAssist {
  #settings = DEFAULT_LANDING_SETTINGS;
  #context = "";
  #runwayKey = "";
  #gearRisk: NonNullable<LandingSnapshot["gearRisk"]> = "unknown";
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
      flapsPercent: input.fresh ? input.flapsPercent : null, geometry, aircraft: input.aircraft ?? null, gearRisk: this.#gearRisk };
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
      const leaving = Math.hypot(g.thresholdDistanceM, g.crossTrackM) > 20_000
        || g.thresholdDistanceM < -g.lengthM - 1000 || Math.abs(g.trackErrorDeg ?? 0) > 90
        || (input.verticalSpeedMps !== null && input.verticalSpeedMps > 3 && g.thresholdDistanceM < 2000 && input.gearPercent !== null && input.gearPercent < 5);
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
    for (const runway of runways) for (const reverse of [false, true]) {
      const g = geometry(runway, reverse), ias = input.iasKmh, vy = input.verticalSpeedMps;
      const error = (g.trackErrorDeg ?? 180) * Math.PI / 180;
      const towards = (g.thresholdDistanceM * Math.cos(error) - g.crossTrackM * Math.sin(error))
        / Math.hypot(g.thresholdDistanceM, g.crossTrackM);
      const inbound = ias !== null && ias >= 70 && ias <= 700 && vy !== null && vy <= 1
        && track.groundSpeedMps >= 20 && g.thresholdDistanceM >= 600 && g.thresholdDistanceM <= 15_000
        && g.trackErrorDeg !== null && Math.abs(g.trackErrorDeg) <= 45
        && towards >= .82
        && Math.abs(g.crossTrackM) <= Math.max(750, g.thresholdDistanceM * .5);
      if (!inbound) continue;
      const score = g.thresholdDistanceM + 4 * Math.abs(g.crossTrackM) + 100 * Math.abs(g.trackErrorDeg!);
      if (!best || score < best.score) best = { runway, reverse, score };
    }
    const key = best ? `${best.runway.id}|${best.reverse}|${JSON.stringify([best.runway.runwayStart, best.runway.runwayEnd])}` : "";
    if (!key || key !== this.#candidateKey) { this.#candidateKey = key; this.#candidateSince = at; return; }
    if (best && at - this.#candidateSince >= 3000) {
      this.#settings = { ...this.#settings, enabled: true, runwayId: best.runway.id, reverse: best.reverse, runwayElevationM: null };
      this.#runwayKey = JSON.stringify([best.runway.runwayStart, best.runway.runwayEnd]);
      this.#candidateKey = ""; this.#exitSince = 0;
    }
  }
}
