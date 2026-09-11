import type { AircraftFuelProfile } from "./fuel-management";

type LimitValue = number | readonly (readonly [number, number])[] | null;
export interface AircraftSpeedLimits { readonly ias: LimitValue; readonly mach: LimitValue }
export interface AircraftLandingProfile {
  readonly gearIasKmh: number | null;
  readonly gearControl: boolean | null;
  readonly arrestorHook: boolean | null;
  readonly flapsIasKmh?: readonly (readonly [number, number])[] | null;
  readonly flapsControl?: boolean | null;
  readonly airbrakeControl?: boolean | null;
  readonly wheelBrakeControl?: boolean | null;
  readonly brakeChute?: boolean | null;
}
export interface AircraftParameterData {
  readonly schema_version: 1;
  readonly source?: { readonly kind: string; readonly version: string };
  readonly unit_to_fm: Readonly<Record<string, string>>;
  readonly flight_models: Readonly<Record<string, {
    readonly speed: AircraftSpeedLimits | null;
    readonly fuel: AircraftFuelProfile | null;
    readonly landing?: Omit<AircraftLandingProfile, "arrestorHook"> | null;
  }>>;
  readonly arrestor_hooks?: Readonly<Record<string, boolean | null>>;
  readonly weapon_release_limits?: Readonly<Record<string, Readonly<Record<string, readonly (number | null)[]>>>>;
  readonly loadouts: Readonly<Record<string, {
    readonly name: string;
    readonly name_zh?: string;
    readonly name_long?: string;
    readonly name_long_zh?: string;
    readonly weapon_max_counts: Readonly<Record<string, number>>;
    readonly max_load_mass_kg?: number;
  }>>;
}

/** Owns aircraft identity and capability lookup; weapon physics stay in their catalogs. */
export class AircraftParameters {
  readonly #data: AircraftParameterData;

  constructor(data: AircraftParameterData) {
    if (data.schema_version !== 1 || !data.unit_to_fm || !data.flight_models || !data.loadouts) {
      throw new Error("机型参数目录无效");
    }
    for (const [unit, fm] of Object.entries(data.unit_to_fm)) {
      if (!unit || typeof fm !== "string" || !Object.hasOwn(data.flight_models, fm)) throw new Error(`机型参数关联缺失：${unit}`);
    }
    for (const [fm, profile] of Object.entries(data.flight_models)) {
      if (!profile || typeof profile !== "object") throw new Error(`飞行模型参数无效：${fm}`);
      if (profile.speed && Object.values(profile.speed).some(value => !validLimit(value))) throw new Error(`速度参数无效：${fm}`);
      if (profile.fuel && (!Array.isArray(profile.fuel.engines) || !["reference-only", "unsupported"].includes(profile.fuel.modelConfidence ?? ""))) throw new Error(`燃油参数无效：${fm}`);
      if (profile.landing && (!(profile.landing.gearIasKmh === null || typeof profile.landing.gearIasKmh === "number" && Number.isFinite(profile.landing.gearIasKmh) && profile.landing.gearIasKmh > 0)
        || !(profile.landing.gearControl === null || typeof profile.landing.gearControl === "boolean"))) throw new Error(`起落架参数无效：${fm}`);
      const landing = profile.landing;
      if (landing?.flapsIasKmh != null && (!Array.isArray(landing.flapsIasKmh) || !validLimit(landing.flapsIasKmh)
        || landing.flapsIasKmh.some(point => point[0] < 0 || point[0] > 1))) throw new Error(`襟翼参数无效：${fm}`);
      if (landing && [landing.flapsControl, landing.airbrakeControl, landing.wheelBrakeControl, landing.brakeChute]
        .some(value => value != null && typeof value !== "boolean")) throw new Error(`降落构型参数无效：${fm}`);
    }
    for (const [unit, hook] of Object.entries(data.arrestor_hooks ?? {})) {
      if (!Object.hasOwn(data.unit_to_fm,unit) || !(hook === null || typeof hook === "boolean")) throw new Error(`着舰钩参数无效：${unit}`);
    }
    for (const [unit, loadout] of Object.entries(data.loadouts)) {
      if (!Object.hasOwn(data.unit_to_fm, unit) || !loadout.weapon_max_counts || Object.values(loadout.weapon_max_counts).some(count => !Number.isInteger(count) || count <= 0)) throw new Error(`挂载参数无效：${unit}`);
    }
    for (const [unit, weapons] of Object.entries(data.weapon_release_limits ?? {})) {
      if (!Object.hasOwn(data.unit_to_fm, unit) || !weapons || typeof weapons !== "object"
        || Object.values(weapons).some(values => !Array.isArray(values) || !values.length
          || values.some(v => v !== null && (typeof v !== "number" || !Number.isFinite(v) || v <= 0)))) {
        throw new Error(`武器投放限速无效：${unit}`);
      }
    }
    this.#data = data;
  }

  static parse(value: unknown): AircraftParameters {
    if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("机型参数目录无效");
    return new AircraftParameters(value as AircraftParameterData);
  }

  #profile(aircraft: string): AircraftParameterData["flight_models"][string] | null {
    const id = aircraft.trim().toLowerCase();
    const fm = this.#data.unit_to_fm[id] ?? id;
    return Object.hasOwn(this.#data.flight_models, fm) ? this.#data.flight_models[fm]! : null;
  }

  speed(aircraft: string, sweep: number | null = null): { ias: number | null; mach: number | null; estimated: boolean } | null {
    const limits = this.#profile(aircraft)?.speed;
    if (!limits) return null;
    if (sweep !== null && !Number.isFinite(sweep)) sweep = null;
    return { ias: resolveLimit(limits.ias, sweep), mach: resolveLimit(limits.mach, sweep),
      estimated: sweep === null && (Array.isArray(limits.ias) || Array.isArray(limits.mach)) };
  }
  fuel(aircraft: string): AircraftFuelProfile | null { return this.#profile(aircraft)?.fuel ?? null; }
  releaseMach(aircraft: string, weapon: string): readonly (number | null)[] | null {
    return this.#data.weapon_release_limits?.[aircraft.trim().toLowerCase()]?.[weapon] ?? null;
  }
  landing(aircraft: string): AircraftLandingProfile | null {
    const profile = this.#profile(aircraft)?.landing;
    if (!profile) return null;
    return { ...profile, arrestorHook: this.#data.arrestor_hooks?.[aircraft.trim().toLowerCase()] ?? null };
  }

  /** Loadouts retain unit IDs: two variants sharing an FM can carry different weapons. */
  strikeCatalog(): Readonly<Record<string, unknown>> {
    return { schema: "bomana_strike_aircraft_weapons/v2", aircraft: Object.entries(this.#data.loadouts).map(([id, row]) => ({
      id, ...row, weapons: Object.keys(row.weapon_max_counts),
    })) };
  }
}

function validLimit(value: LimitValue): boolean {
  if (value === null) return true;
  if (typeof value === "number") return Number.isFinite(value) && value > 0;
  return Array.isArray(value) && value.length > 0 && value.every((point, index) => Array.isArray(point) && point.length === 2 &&
    point.every(Number.isFinite) && point[1] > 0 && (index === 0 || point[0] > value[index - 1]![0]));
}

function resolveLimit(value: LimitValue, sweep: number | null): number | null {
  if (value === null || typeof value === "number") return value;
  if (sweep === null || !Number.isFinite(sweep)) return Math.min(...value.map(point => point[1]));
  if (sweep <= value[0]![0]) return value[0]![1];
  for (let index = 1; index < value.length; index++) {
    const left = value[index - 1]!, right = value[index]!;
    if (sweep <= right[0]) return left[1] + (right[1] - left[1]) * (sweep - left[0]) / (right[0] - left[0]);
  }
  return value.at(-1)![1];
}
