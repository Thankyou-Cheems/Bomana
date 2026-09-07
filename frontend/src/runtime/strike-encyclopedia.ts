import type { StrikeRuntimeResources } from "./runtime-resources";

export type StrikeTargetKind = "bombing_point" | "airport_module";
export type AirportModule = "airfield" | "storage" | "parking" | "dwelling";

export interface StrikeWeaponSummary {
  readonly weaponId: string;
  readonly kind: string;
  readonly displayName: string;
  readonly displayNameZh: string;
}

export interface StrikeAircraftSummary {
  readonly id: string;
  readonly displayName: string;
}

export interface StrikeCalculation {
  readonly roomMaxBr: number;
  readonly balanceLevel: number;
  readonly targetKind: StrikeTargetKind;
  readonly airportModule: AirportModule | null;
  readonly targetMissionHp: number;
  readonly damagePerHitMissionHp: number | null;
  readonly fullDestroyCount: number | null;
  readonly fireTriggerCount: number | null;
  readonly practicalCount: number | null;
  readonly respawnSeconds: number | null;
  readonly repairBaseHp: number | null;
  readonly evidenceKind: string;
  readonly message: string;
}

interface WeaponRecord extends StrikeWeaponSummary {
  readonly raw_explosive_mass_kg: number;
  readonly strength_equivalent: number;
  readonly mission_damage_model: string;
  readonly splash_damage: number | null;
  readonly splash_penetration: number | null;
  readonly fire_damage: number | null;
  readonly fire_life_time: number | null;
  readonly nuclear_yield_kt: number | null;
}

export class StrikeEncyclopedia {
  readonly #encyclopedia: Readonly<Record<string, unknown>>;
  readonly #splash: Readonly<Record<string, unknown>>;
  readonly #weapons: readonly WeaponRecord[];
  readonly #weaponsById: ReadonlyMap<string, WeaponRecord>;
  readonly #aircraftWeapons: ReadonlyMap<string, readonly string[]>;
  readonly #aircraft: readonly StrikeAircraftSummary[];

  constructor(resources: StrikeRuntimeResources) {
    this.#encyclopedia = resources.encyclopedia;
    this.#splash = resources.splash;
    const rawWeapons = resources.weapons.weapons;
    if (!Array.isArray(rawWeapons)) throw new Error("strike weapon catalog is invalid");
    this.#weapons = Object.freeze(rawWeapons.map(parseWeapon));
    this.#weaponsById = new Map(this.#weapons.map((weapon) => [weapon.weaponId, weapon]));
    const rawAircraft = resources.aircraftWeapons.aircraft;
    if (!Array.isArray(rawAircraft)) throw new Error("strike aircraft catalog is invalid");
    const aircraft: StrikeAircraftSummary[] = [];
    this.#aircraftWeapons = new Map(rawAircraft.flatMap((raw) => {
      if (!raw || typeof raw !== "object" || Array.isArray(raw)) return [];
      const record = raw as Record<string, unknown>;
      const id = String(record.id ?? "");
      const weapons = Array.isArray(record.weapons)
        ? record.weapons.map(String)
        : [];
      if (weapons.some(weaponId => !this.#weaponsById.has(weaponId))) throw new Error(`机型挂载引用了缺失的武器：${id}`);
      if (id) aircraft.push(Object.freeze({
        id,
        displayName: String(record.name_zh ?? record.name ?? id),
      }));
      return id ? [[id, Object.freeze(weapons)] as const] : [];
    }));
    this.#aircraft = Object.freeze(aircraft.sort((left, right) => left.id.localeCompare(right.id)));
  }

  aircraft(): readonly StrikeAircraftSummary[] { return this.#aircraft; }

  weapons(aircraftId?: string): readonly StrikeWeaponSummary[] {
    const allowed = aircraftId ? this.#aircraftWeapons.get(aircraftId) : null;
    const records = allowed
      ? allowed.map((weaponId) => this.#weaponsById.get(weaponId)).filter((weapon): weapon is WeaponRecord => Boolean(weapon))
      : this.#weapons;
    return Object.freeze(records.map((weapon) => Object.freeze({
      weaponId: weapon.weaponId,
      kind: weapon.kind,
      displayName: weapon.displayName,
      displayNameZh: weapon.displayNameZh,
    })));
  }

  calculate(input: {
    readonly roomMaxBr: number;
    readonly targetKind: StrikeTargetKind;
    readonly weaponId: string;
    readonly missionMode?: "planes" | "heli";
    readonly airportModule?: AirportModule;
  }): StrikeCalculation {
    const balanceLevel = balanceLevelFromBr(input.roomMaxBr);
    const weapon = this.#weaponsById.get(input.weaponId);
    if (!weapon) throw new Error("unknown_weapon");
    const damage = this.#weaponDamage(weapon);
    if (input.targetKind === "bombing_point") {
      const tier = tierFor(this.#encyclopedia.bombing_point_tiers, balanceLevel);
      const missionMode = input.missionMode ?? "planes";
      const targetHp = number(tier[missionMode === "planes" ? "planes_mission_hp" : "heli_mission_hp"]);
      const behavior = object(this.#encyclopedia.bombing_point_behavior);
      const directToFire = targetHp * (1 - number(behavior.hp_fire_mult));
      const fullCount = damage ? requiredCount(targetHp, damage.damage) : null;
      const fireCount = damage ? requiredCount(directToFire, damage.damage) : null;
      return Object.freeze({
        roomMaxBr: input.roomMaxBr,
        balanceLevel,
        targetKind: input.targetKind,
        airportModule: null,
        targetMissionHp: targetHp,
        damagePerHitMissionHp: damage?.damage ?? null,
        fullDestroyCount: fullCount,
        fireTriggerCount: fireCount,
        practicalCount: fullCount === null ? null : Math.min(fullCount, fireCount ?? fullCount),
        respawnSeconds: number(behavior.respawn_seconds),
        repairBaseHp: null,
        evidenceKind: damage?.evidenceKind ?? "native_unknown",
        message: damage
          ? "战区达到 90% 直接伤害后进入静态参数支持的燃烧自毁线；同时保留满血摧毁枚数。"
          : "该武器缺少静态溅射公式输入，不能给出可靠枚数。",
      });
    }
    const module = input.airportModule ?? "airfield";
    const tier = tierFor(this.#encyclopedia.airport_tiers, balanceLevel);
    const targetHp = number(tier[module === "airfield" ? "runway_mission_hp" : "auxiliary_module_mission_hp"]);
    const count = damage ? requiredCount(targetHp, damage.damage) : null;
    return Object.freeze({
      roomMaxBr: input.roomMaxBr,
      balanceLevel,
      targetKind: input.targetKind,
      airportModule: module,
      targetMissionHp: targetHp,
      damagePerHitMissionHp: damage?.damage ?? null,
      fullDestroyCount: count,
      fireTriggerCount: null,
      practicalCount: count,
      respawnSeconds: null,
      repairBaseHp: number(tier.repair_base_hp),
      evidenceKind: damage?.evidenceKind ?? "native_unknown",
      message: damage
        ? "机场模块没有已证实的战区燃烧尾段；结果按模块 HP 与同一溅射伤害估算，并单列生活区维修参数。"
        : "该武器缺少静态溅射公式输入，不能给出可靠枚数。",
    });
  }

  #weaponDamage(weapon: WeaponRecord): { damage: number; evidenceKind: string } | null {
    const armor = object(this.#splash.armor);
    const armorMm = number(armor.armor_thickness_mm);
    const restrain = number(armor.restrain_explosion_damage);
    if (weapon.mission_damage_model === "nuclear_yield") {
      if (!weapon.nuclear_yield_kt) return null;
      const point = curve(this.#splash.nuclear_yield_to_damage)
        .find(([yieldKt]) => Math.abs(yieldKt - weapon.nuclear_yield_kt!) <= 1e-9);
      return point ? { damage: point[1], evidenceKind: "exact_static_nuclear_yield" } : null;
    }
    if (weapon.mission_damage_model === "napalm_splash_fire") {
      if (
        weapon.splash_damage === null || weapon.splash_penetration === null
        || weapon.fire_damage === null || weapon.fire_life_time === null
      ) return null;
      const instant = weapon.splash_penetration >= armorMm
        ? weapon.splash_damage
        : weapon.splash_damage * (weapon.splash_penetration / armorMm) * restrain;
      return {
        damage: instant + weapon.fire_damage * weapon.fire_life_time * number(armor.napalm_damage_mult),
        evidenceKind: "exact_static_napalm_splash_fire",
      };
    }
    if (weapon.mission_damage_model !== "splash_tnte_curve") return null;
    const tnte = weapon.raw_explosive_mass_kg * weapon.strength_equivalent;
    if (tnte <= 0) return null;
    const base = interpolate(curve(this.#splash.explosive_mass_to_damage), tnte);
    const penetration = interpolate(curve(this.#splash.explosive_mass_to_penetration), tnte);
    return {
      damage: penetration >= armorMm ? base : base * (penetration / armorMm) * restrain,
      evidenceKind: "exact_static_splash_curve",
    };
  }
}

export function roomMaxBattleRatings(): readonly number[] {
  return Object.freeze(Array.from({ length: 42 }, (_, rank) => Math.round((rank / 3 + 1) * 10) / 10));
}

function balanceLevelFromBr(br: number): number {
  if (!Number.isFinite(br)) throw new Error("invalid_room_max_br");
  const index = roomMaxBattleRatings().findIndex((value) => Math.abs(value - br) <= 1e-6);
  if (index < 0) throw new Error("invalid_room_max_br");
  return index;
}

function tierFor(raw: unknown, rank: number): Readonly<Record<string, unknown>> {
  if (!Array.isArray(raw)) throw new Error("invalid_durability_tiers");
  for (const entry of raw) {
    const tier = object(entry);
    const range = tier.balance_level;
    if (Array.isArray(range) && number(range[0]) <= rank && rank <= number(range[1])) return tier;
  }
  throw new Error("missing_balance_level_tier");
}

function requiredCount(hp: number, damage: number): number {
  if (hp <= 0 || damage <= 0) throw new Error("invalid_weapon_count_inputs");
  return Math.max(1, Math.ceil(hp / damage - 1e-9));
}

function parseWeapon(raw: unknown): WeaponRecord {
  const record = object(raw);
  const weaponId = String(record.weapon_id ?? "");
  if (!weaponId) throw new Error("invalid strike weapon id");
  return {
    weaponId,
    kind: String(record.kind ?? ""),
    displayName: String(record.display_name ?? weaponId),
    displayNameZh: String(record.display_name_zh ?? ""),
    raw_explosive_mass_kg: number(record.raw_explosive_mass_kg),
    strength_equivalent: number(record.strength_equivalent),
    mission_damage_model: String(record.mission_damage_model ?? "native_unknown"),
    splash_damage: nullableNumber(record.splash_damage),
    splash_penetration: nullableNumber(record.splash_penetration),
    fire_damage: nullableNumber(record.fire_damage),
    fire_life_time: nullableNumber(record.fire_life_time),
    nuclear_yield_kt: nullableNumber(record.nuclear_yield_kt),
  };
}

function interpolate(points: readonly (readonly [number, number])[], value: number): number {
  if (value <= points[0]![0]) return points[0]![1];
  if (value >= points.at(-1)![0]) return points.at(-1)![1];
  for (let index = 0; index < points.length - 1; index += 1) {
    const [x0, y0] = points[index]!;
    const [x1, y1] = points[index + 1]!;
    if (x0 <= value && value <= x1) return x1 === x0 ? y1 : y0 + (value - x0) * (y1 - y0) / (x1 - x0);
  }
  return points.at(-1)![1];
}

function curve(raw: unknown): readonly (readonly [number, number])[] {
  if (!Array.isArray(raw) || raw.length < 2) throw new Error("invalid splash curve");
  return raw.map((point) => {
    if (!Array.isArray(point) || point.length !== 2) throw new Error("invalid splash point");
    return Object.freeze([number(point[0]), number(point[1])] as const);
  }).sort((left, right) => left[0] - right[0]);
}

function object(raw: unknown): Readonly<Record<string, unknown>> {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) throw new Error("invalid strike data object");
  return raw as Readonly<Record<string, unknown>>;
}

function number(raw: unknown): number {
  if (typeof raw !== "number" || !Number.isFinite(raw)) throw new Error("invalid strike data number");
  return raw;
}

function nullableNumber(raw: unknown): number | null {
  return raw === null || raw === undefined ? null : number(raw);
}
