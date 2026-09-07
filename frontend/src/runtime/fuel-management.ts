import type { AircraftParameters } from "./aircraft-parameters";

/** Fuel observations belong to one aircraft and sortie; they are never restored from a checkpoint. */
export interface FuelEngine {
  readonly throttlePercent: number | null;
  readonly thrustKgf: number | null;
  readonly powerHp: number | null;
}

export interface AircraftFuelProfile {
  readonly engineType: string;
  readonly modelConfidence?: "reference-only" | "unsupported";
  readonly engines: readonly {
    readonly kind: string;
    readonly consumption: readonly [number, number, number, number] | null;
  }[];
}

export interface FuelObservation {
  readonly atMs: number;
  readonly aircraft: string;
  readonly fuelKg: number | null;
  readonly initialKg: number | null;
  readonly engines: readonly FuelEngine[];
  readonly altitudeM: number;
  readonly tasKmh: number | null;
  readonly iasKmh: number;
  readonly verticalSpeedMps: number;
  readonly onGround: boolean;
  readonly groundSpeedKmh: number | null;
}

export interface FuelSnapshot {
  readonly currentKg: number;
  readonly initialKg: number;
  readonly percent: number;
  readonly available: boolean;
  readonly rateKgMin: number;
  readonly stable: boolean;
  readonly remainingMinutes: number | null;
  readonly source: "measured" | "aircraft-estimate" | "learning" | "unavailable";
  readonly aircraftMatched: boolean;
  readonly engineType: string;
  readonly regime: string;
  readonly sampleSeconds: number;
  readonly returnNeededKg: number;
  readonly returnStatus: "safe" | "warning" | "danger" | "unknown";
  readonly returnTargetLabel: string;
  readonly returnDistanceKm: number | null;
  readonly returnMinutes: number | null;
  readonly tripKg: number | null;
  readonly reserveKg: number | null;
  readonly reserveMinutes: number;
  readonly marginKg: number | null;
  readonly reason: string;
  readonly economy: {
    readonly rateKgMin: number;
    readonly groundSpeedKmh: number;
    readonly throttlePercent: number;
    readonly savingPercent: number;
    readonly remainingMinutes: number;
    readonly returnNeededKg: number;
  } | null;
}

interface FuelSample { atMs: number; kg: number }
interface LearnedFuel {
  observation: FuelObservation;
  rate: number;
  modelRate: number | null;
}
export interface FuelReturnTarget { readonly label: string; readonly distanceKm: number }
const RESERVE_MINUTES = 5;
const ROUTE_ALLOWANCE = 1.2;

export class FuelManager {
  readonly #catalog: AircraftParameters | null;
  #aircraft = "";
  #currentKg = 0;
  #initialKg = 0;
  #last: FuelObservation | null = null;
  #segment: FuelObservation | null = null;
  #samples: FuelSample[] = [];
  #learned: LearnedFuel[] = [];
  #rate = 0;
  #stable = false;
  #event = "";
  #eventUntil = 0;
  #speed: number | null = null;
  #lastLearnedMs = 0;

  constructor(catalog: AircraftParameters | null = null) { this.#catalog = catalog; }

  reset(): void {
    this.#aircraft = "";
    this.#currentKg = this.#initialKg = this.#rate = this.#lastLearnedMs = 0;
    this.#last = this.#segment = null;
    this.#samples = [];
    this.#learned = [];
    this.#stable = false;
    this.#event = "";
    this.#eventUntil = 0;
    this.#speed = null;
  }

  observe(input: FuelObservation): void {
    if (input.aircraft && input.aircraft !== this.#aircraft) {
      this.reset();
      this.#aircraft = input.aircraft;
    }
    const previous = this.#last;
    if (previous && input.atMs <= previous.atMs) return;
    this.#last = input;
    if (input.fuelKg === null || !Number.isFinite(input.fuelKg) || input.fuelKg < 0) {
      this.#clearSegment();
      return;
    }
    this.#currentKg = input.fuelKg;
    if (this.#initialKg === 0 && input.initialKg !== null && input.initialKg > 0) this.#initialKg = input.initialKg;
    const dt = previous ? (input.atMs - previous.atMs) / 1000 : 0;
    const model = this.#modelRate(input);
    if (previous?.fuelKg !== null && previous?.fuelKg !== undefined && dt > 0 && dt <= 3) {
      const change = previous.fuelKg - input.fuelKg;
      const expected = Math.max(this.#rate, model ?? 0) * dt / 60;
      if (change < -.2 || change > Math.max(5, (this.#initialKg || this.#currentKg) * .02, expected * 6)) {
        this.#clearSegment();
        this.#learned = [];
        this.#event = change < 0 ? "refuel" : "fuel-jump";
        if (change < 0 && input.initialKg !== null && input.initialKg > 0) this.#initialKg = input.initialKg;
        this.#eventUntil = input.atMs + 10000;
      }
    }
    if (dt > 3 || !this.#segment || !sameCondition(this.#segment, input)) this.#clearSegment();
    if (!this.#segment) this.#segment = input;
    if (input.groundSpeedKmh !== null && input.groundSpeedKmh >= 50) {
      const alpha = 1 - Math.exp(-Math.max(0, dt) / 3);
      this.#speed = this.#speed === null ? input.groundSpeedKmh : this.#speed + alpha * (input.groundSpeedKmh - this.#speed);
    } else this.#speed = null;
    const latest = this.#samples.at(-1);
    if (latest && input.atMs - latest.atMs < 1000) return;
    this.#samples.push({ atMs: input.atMs, kg: input.fuelKg });
    this.#samples = this.#samples.filter((sample) => sample.atMs >= input.atMs - 45000);
    // A continuing leak or power change absent from /state must not take a full
    // 45-second history to displace the previous consumption rate.
    if (this.#stable && this.#samples.length >= 8) {
      const recent = this.#samples.filter((sample) => sample.atMs >= input.atMs - 6000);
      const fitted = fitConsumption(recent, this.#initialKg);
      if (fitted !== null && (fitted > this.#rate * 1.5 || fitted < this.#rate / 1.5)) this.#samples = recent;
    }
    const rate = fitConsumption(this.#samples, this.#initialKg);
    this.#stable = rate !== null;
    this.#rate = rate ?? 0;
    if (rate !== null && this.#spanSeconds() >= 12 && input.atMs - this.#lastLearnedMs >= 3000
      && !input.onGround && Math.abs(input.verticalSpeedMps) <= 5 && this.#speed !== null
      && input.engines.length > 0 && input.engines.every((engine) => engine.throttlePercent !== null && engine.throttlePercent > 5)) {
      const point = { observation: { ...input, groundSpeedKmh: this.#speed }, rate, modelRate: model };
      this.#learned = this.#learned.filter((item) => !sameCondition(item.observation, input));
      this.#learned.push(point);
      this.#learned = this.#learned.slice(-24);
      this.#lastLearnedMs = input.atMs;
    }
  }

  view(nowMs: number, live: boolean, target: FuelReturnTarget | null, trackValid: boolean): FuelSnapshot {
    const input = this.#last;
    const available = live && input !== null && input.fuelKg !== null && input.fuelKg >= 0 && nowMs - input.atMs <= 3000;
    const profile = this.#profile();
    const nominal = input ? this.#modelRate(input) : null;
    const calibration = input ? this.#learned.findLast((item) => sameCondition(item.observation, input) && item.modelRate !== null) : null;
    const modelRate = nominal !== null ? nominal * (calibration?.modelRate ? calibration.rate / calibration.modelRate : 1) : null;
    const stable = available && this.#stable;
    const rate = available ? stable ? this.#rate : modelRate ?? 0 : 0;
    const source = !available ? "unavailable" : stable ? "measured" : modelRate !== null ? "aircraft-estimate" : "learning";
    const regime = input ? fuelRegime(input) : "unknown";
    const currentSpeed = trackValid ? this.#speed : null;
    const cruise = input ? this.#learned.filter((item) =>
      input.atMs - item.observation.atMs <= 600000
      && Math.abs(input.altitudeM - item.observation.altitudeM) <= 1000
      && fuelRegime(item.observation) !== "boost"
      && item.observation.groundSpeedKmh !== null
      && item.observation.groundSpeedKmh >= 100)
      .sort((a, b) => a.rate / a.observation.groundSpeedKmh! - b.rate / b.observation.groundSpeedKmh!)[0] : null;
    let reason = !available ? "fuel-unavailable" : input?.onGround ? "on-ground"
      : !rate ? "learning" : !target ? "no-airfield" : currentSpeed === null ? "no-track"
      : input && (Math.abs(input.verticalSpeedMps) > 10 || regime === "idle") ? "maneuver" : "ready";
    if (available && this.#eventUntil > nowMs && !stable) reason = this.#event;
    let tripKg: number | null = null;
    let reserveKg: number | null = null;
    let returnMinutes: number | null = null;
    let marginKg: number | null = null;
    let returnNeededKg = 0;
    let returnStatus: FuelSnapshot["returnStatus"] = "unknown";
    if (reason === "ready" && target && currentSpeed !== null) {
      returnMinutes = target.distanceKm / currentSpeed * 60 * ROUTE_ALLOWANCE;
      tripKg = rate * returnMinutes;
      reserveKg = Math.max(rate, cruise?.rate ?? 0) * RESERVE_MINUTES;
      returnNeededKg = tripKg + reserveKg;
      marginKg = this.#currentKg - returnNeededKg;
      // Static engine coefficients are a starting estimate, never a positive
      // return verdict. The five-minute reserve is already inside this budget.
      if (stable) returnStatus = marginKg < 0 ? "danger" : marginKg < reserveKg * .5 ? "warning" : "safe";
    }
    if (available && this.#currentKg === 0) { reason = "empty"; returnStatus = "danger"; }
    const savings = cruise && currentSpeed && rate > 0 ? 100 * (1 - cruise.rate / cruise.observation.groundSpeedKmh! / (rate / currentSpeed)) : 0;
    const economy = available && stable && cruise && savings >= 10 && reason === "ready" ? {
      rateKgMin: cruise.rate, groundSpeedKmh: cruise.observation.groundSpeedKmh!,
      throttlePercent: averageThrottle(cruise.observation)!, savingPercent: savings,
      remainingMinutes: this.#currentKg / cruise.rate,
      returnNeededKg: cruise.rate * (target!.distanceKm / cruise.observation.groundSpeedKmh! * 60 * ROUTE_ALLOWANCE + RESERVE_MINUTES),
    } : null;
    return {
      currentKg: this.#currentKg, initialKg: this.#initialKg,
      percent: this.#initialKg > 0 ? Math.min(100, this.#currentKg / this.#initialKg * 100) : 0,
      available, rateKgMin: rate, stable,
      remainingMinutes: available && this.#currentKg === 0 ? 0 : rate > 0 ? this.#currentKg / rate : null,
      source, aircraftMatched: profile !== null, engineType: profile?.engineType ?? "unknown", regime,
      sampleSeconds: this.#spanSeconds(), returnNeededKg, returnStatus,
      returnTargetLabel: target?.label ?? "", returnDistanceKm: target?.distanceKm ?? null,
      returnMinutes, tripKg, reserveKg, reserveMinutes: RESERVE_MINUTES, marginKg, reason, economy,
    };
  }

  #clearSegment(): void {
    this.#samples = [];
    this.#segment = null;
    this.#rate = 0;
    this.#stable = false;
    this.#speed = null;
  }
  #spanSeconds(): number {
    return this.#samples.length > 1 ? (this.#samples.at(-1)!.atMs - this.#samples[0]!.atMs) / 1000 : 0;
  }
  #profile(): AircraftFuelProfile | null {
    return this.#catalog?.fuel(this.#aircraft) ?? null;
  }
  #modelRate(input: FuelObservation): number | null { return aircraftFuelRate(this.#profile(), input.engines); }
}

function fitConsumption(samples: readonly FuelSample[], capacityKg: number): number | null {
  if (samples.length < 5) return null;
  const first = samples[0]!;
  const last = samples.at(-1)!;
  const span = (last.atMs - first.atMs) / 1000;
  const used = first.kg - last.kg;
  if (span < 6 || used < Math.max(.2, capacityKg * .0001)) return null;
  const meanT = samples.reduce((sum, sample) => sum + (sample.atMs - first.atMs) / 1000, 0) / samples.length;
  const meanKg = samples.reduce((sum, sample) => sum + sample.kg, 0) / samples.length;
  let covariance = 0;
  let variance = 0;
  for (const sample of samples) {
    const dt = (sample.atMs - first.atMs) / 1000 - meanT;
    covariance += dt * (sample.kg - meanKg);
    variance += dt * dt;
  }
  if (variance <= 0) return null;
  const slope = covariance / variance;
  const residual = Math.sqrt(samples.reduce((sum, sample) => {
    const error = sample.kg - meanKg - slope * ((sample.atMs - first.atMs) / 1000 - meanT);
    return sum + error * error;
  }, 0) / samples.length);
  return slope < 0 && residual <= Math.max(.1, used * .15) ? -slope * 60 : null;
}

function averageThrottle(input: FuelObservation): number | null {
  if (!input.engines.length || input.engines.some((engine) => engine.throttlePercent === null)) return null;
  return input.engines.reduce((sum, engine) => sum + engine.throttlePercent!, 0) / input.engines.length;
}

export function fuelRegime(input: FuelObservation): string {
  if (input.onGround) return "ground";
  const throttle = averageThrottle(input);
  if (throttle === null) return "unknown";
  if (input.engines.some((engine) => engine.throttlePercent! > 100)) return "boost";
  if (throttle <= 5) return "idle";
  return throttle >= 95 ? "military" : "cruise";
}

function sameCondition(a: FuelObservation, b: FuelObservation): boolean {
  return fuelRegime(a) === fuelRegime(b)
    && a.engines.length === b.engines.length
    && a.engines.every((engine, index) => {
      const next = b.engines[index]!;
      return engine.throttlePercent === null ? next.throttlePercent === null
        : next.throttlePercent !== null && Math.abs(engine.throttlePercent - next.throttlePercent) <= 5;
    })
    && Math.abs(a.altitudeM - b.altitudeM) <= 500
    && Math.abs(a.iasKmh - b.iasKmh) <= Math.max(50, a.iasKmh * .15)
    && Math.sign(Math.trunc(a.verticalSpeedMps / 5)) === Math.sign(Math.trunc(b.verticalSpeedMps / 5));
}

export function aircraftFuelRate(profile: AircraftFuelProfile | null, engines: readonly FuelEngine[]): number | null {
  if (!profile || profile.modelConfidence === "unsupported" || !engines.length || profile.engines.length !== engines.length) return null;
  let total = 0;
  for (let index = 0; index < engines.length; index++) {
    const engine = engines[index]!;
    const specification = profile.engines[index]!;
    const curve = specification.consumption;
    if (engine.throttlePercent === null || !curve) return null;
    const throttle = Math.max(0, engine.throttlePercent);
    const coefficient = throttle > 100 ? curve[3] : throttle > 50
      ? curve[1] + (curve[2] - curve[1]) * (throttle - 50) / 50
      : curve[0] + (curve[1] - curve[0]) * throttle / 50;
    const output = specification.kind === "jet" ? engine.thrustKgf : specification.kind === "piston" ? engine.powerHp : null;
    if (output === null || output < 0 || coefficient <= 0) return null;
    total += output * coefficient / 60;
  }
  return total > 0 && Number.isFinite(total) ? total : null;
}

export function fuelEngines(state: Readonly<Record<string, unknown>>): FuelEngine[] {
  const engines: FuelEngine[] = [];
  for (let index = 1; index <= 16; index++) {
    const throttlePercent = fuelNumber(state, [`throttle ${index}, %`]);
    const thrustKgf = fuelNumber(state, [`thrust ${index}, kgs`]);
    const powerHp = fuelNumber(state, [`power ${index}, hp`]);
    if (throttlePercent === null && thrustKgf === null && powerHp === null) break;
    engines.push({ throttlePercent, thrustKgf, powerHp });
  }
  return engines;
}

export function fuelNumber(state: Readonly<Record<string, unknown>>, keys: readonly string[]): number | null {
  for (const key of keys) {
    const raw = state[key];
    if (typeof raw === "number" && Number.isFinite(raw)) return raw;
  }
  return null;
}
