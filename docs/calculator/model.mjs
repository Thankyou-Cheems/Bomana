// Reviewed 2.59.0.13 EC rank 07 example: fr_crotale_ng + uk_rooikat_za_35.
// This is only the mass gate of their configured projectile priority windows.
export function airfieldDefenseMassAssessment({ massKg, sourceVersion }) {
  if (sourceVersion !== "2.59.0.13") return "version_mismatch";
  if (!Number.isFinite(massKg) || massKg <= 0) return "unknown_mass";
  if (massKg < 80 || massKg > 3500) return "outside_mass_windows";
  return "within_mass_windows";
}

function airportNativeReferenceSupported(reference) {
  return typeof reference?.client_version === "string" && reference.client_version.trim().length > 0 &&
    typeof reference.pe_sha256 === "string" && /^[0-9a-fA-F]{64}$/.test(reference.pe_sha256) &&
    reference.hp_condition === "truncate_percent_to_integer" &&
    reference.palette_selection === "first_key_greater_or_equal" && reference.server_recovery === "unknown";
}

export function airportBarPositions(display, angleDegrees) {
  const modules = display?.modules;
  if (!airportNativeReferenceSupported(display?.native_reference) ||
      display?.orientation !== "runway_endpoint_relative" || !Number.isFinite(angleDegrees) ||
      !Array.isArray(modules) || modules.length !== 4 ||
      new Set(modules.map(row => row?.module)).size !== 4 ||
      modules.some(row => !["airfield", "storage", "parking", "dwelling"].includes(row?.module) ||
        !Array.isArray(row.position) || row.position.length !== 2 || !row.position.every(Number.isFinite))) return null;
  const angle = angleDegrees * Math.PI / 180, dx = Math.cos(angle), dy = Math.sin(angle);
  return modules.map(row => {
    const end = row.position[0] >= 0 ? 1 : -1, side = row.position[1] > 0 ? 1 : -1;
    return { module: row.module, x: end * dx - side * dy * .6, y: end * dy + side * dx * .6 };
  });
}

export function airportPaletteBands(display) {
  const rows = display?.palette;
  if (!airportNativeReferenceSupported(display?.native_reference) ||
      !Array.isArray(rows) || rows.length !== 4 ||
      rows.some((row, index) => !Array.isArray(row) || row.length !== 4 ||
        !row.every(Number.isFinite) || row.slice(0, 3).some(value => value < 0 || value > 255) ||
        row[3] < 0 || row[3] > 1 || (index > 0 && row[3] <= rows[index - 1][3])) ||
      rows[0][3] !== 0 || rows[3][3] !== 1) return null;
  return rows.map((row, index) => ({ color: `rgb(${row.slice(0, 3).join(",")})`,
    lower: index === 0 ? 0 : rows[index - 1][3] * 100, upper: row[3] * 100 }));
}

export function airportRepairVisit({ rule, tier, dwellingPercent }) {
  if (rule?.model !== "integer_percent_dwelling/v1" ||
      !airportNativeReferenceSupported(rule.native_reference) ||
      rule.timing !== "per_airfield_repair_visit" || rule.evidence !== "client_mission_branch_not_server_prediction" ||
      rule.hp_offset !== 1 || rule.maximum_slowdown !== 10 ||
      ![tier?.auxiliary_module_mission_hp, tier?.repair_base_hp].every(value => Number.isFinite(value) && value > 0) ||
      !Number.isFinite(dwellingPercent) || dwellingPercent < 0 || dwellingPercent > 100) return null;
  const maximum = tier.auxiliary_module_mission_hp, base = tier.repair_base_hp;
  const dwellingHp = maximum * dwellingPercent / 100;
  const state = dwellingPercent === 0 ? "destroyed" : dwellingPercent < 1 ? "below_threshold" : dwellingPercent === 100 ? "intact" : "damaged";
  const gain = state === "damaged" ? base / Math.min(maximum / (dwellingHp + rule.hp_offset), rule.maximum_slowdown) : 0;
  if (!Number.isFinite(gain)) return null;
  return { state, dwellingHp, maximum, base, gain };
}

export function requiredCount(hp, damage) {
  if (!Number.isFinite(hp) || !Number.isFinite(damage) || !(hp > 0) || !(damage > 0)) return null;
  return Math.max(1, Math.ceil(hp / damage - 1e-9));
}

export function equivalentWeaponCount({ sourcePerItem, targetPerItem, sourceCount }) {
  if (![sourcePerItem, targetPerItem].every(value => Number.isFinite(value) && value > 0) ||
      !Number.isSafeInteger(sourceCount) || sourceCount < 0) return null;
  return convertFactors([sourcePerItem, sourceCount], [targetPerItem]);
}

export function explosiveConversion({ sourceMassKg, sourceFactor, sourceCount, targetMassKg, targetFactor }) {
  if (![sourceMassKg, sourceFactor, targetMassKg, targetFactor].every(value => Number.isFinite(value) && value > 0) ||
      !Number.isSafeInteger(sourceCount) || sourceCount < 0) return null;
  const sourceTntKg = sourceMassKg * sourceFactor, targetTntKg = targetMassKg * targetFactor;
  if (![sourceTntKg, targetTntKg].every(value => Number.isFinite(value) && value > 0)) return null;
  const equivalent = convertFactors([sourceMassKg, sourceFactor, sourceCount], [targetMassKg, targetFactor]);
  return equivalent ? { sourceTntKg, targetTntKg, ...equivalent } : null;
}

function decimalProduct(factors) {
  return factors.reduce(([coefficient, exponent], factor) => {
    const [significand, power = "0"] = factor.toString().split("e");
    const [integer, fraction = ""] = significand.split(".");
    return [coefficient * BigInt(integer + fraction), exponent + Number(power) - fraction.length];
  }, [1n, 0]);
}

function convertFactors(sourceFactors, targetFactors) {
  const product = factors => factors.reduce((total, factor) => total * factor, 1);
  const sourceTotal = product(sourceFactors), targetPerItem = product(targetFactors);
  const exactCount = sourceTotal / targetPerItem;
  if (![sourceTotal, exactCount].every(Number.isFinite) || (sourceTotal > 0 && !(exactCount > 0))) return null;
  // Count complete weapons using the input decimals, before binary floating-
  // point multiplication. A tolerance would erase real above-integer inputs.
  let [numerator, sourceExponent] = decimalProduct(sourceFactors);
  let [denominator, targetExponent] = decimalProduct(targetFactors);
  const exponent = sourceExponent - targetExponent;
  if (exponent > 0) numerator *= 10n ** BigInt(exponent);
  else denominator *= 10n ** BigInt(-exponent);
  const wholeCount = Number((numerator + denominator - 1n) / denominator);
  const targetTotal = wholeCount * targetPerItem;
  if (!Number.isSafeInteger(wholeCount) || !Number.isFinite(targetTotal)) return null;
  return { sourceTotal, exactCount, wholeCount, targetTotal, surplus: Math.max(0, targetTotal - sourceTotal) };
}

// Each row is a separate maximum same-type loadout, never a combined preset.
export function compareLoadouts({ aircraft, weapons, hp }) {
  if (!aircraft || !(hp > 0)) return [];
  const byId = new Map(weapons.map((weapon) => [weapon.id, weapon]));
  return aircraft.w.flatMap((id, index) => {
    const weapon = byId.get(id);
    const required = requiredCount(hp, weapon?.dmg);
    const capacity = aircraft.n[index];
    if (required === null || !Number.isInteger(capacity) || capacity <= 0) return [];
    return [{
      weapon, required, capacity,
      sorties: Math.ceil(required / capacity),
      targetsPerLoad: Math.floor(capacity / required),
      remaining: capacity % required,
      massKg: Number.isFinite(weapon.kg) && weapon.kg > 0 ? required * weapon.kg : null,
    }];
  }).sort((a, b) => a.sorties - b.sorties || b.targetsPerLoad - a.targetsPerLoad ||
    a.required - b.required || a.weapon.id.localeCompare(b.weapon.id));
}

export function returnFuelPlan({ fuelKg, burnKgMin, groundSpeedKmh, distanceKm, routePercent, reserveMin }) {
  const values = [burnKgMin, groundSpeedKmh, distanceKm, routePercent, reserveMin];
  if (!values.every(Number.isFinite) || burnKgMin <= 0 || groundSpeedKmh <= 0 ||
      distanceKm < 0 || routePercent < 0 || reserveMin < 0 ||
      (fuelKg !== null && (!Number.isFinite(fuelKg) || fuelKg < 0))) return null;
  const tripMin = (distanceKm * (1 + routePercent / 100) / groundSpeedKmh) * 60;
  const tripKg = tripMin * burnKgMin;
  const reserveKg = reserveMin * burnKgMin;
  const requiredKg = tripKg + reserveKg;
  if (![tripMin, tripKg, reserveKg, requiredKg].every(Number.isFinite)) return null;
  return { tripMin, tripKg, reserveKg, requiredKg, marginKg: fuelKg === null ? null : fuelKg - requiredKg };
}

export function sharedParameterSource(payloads) {
  const source = payloads[0]?.source;
  if (!source?.version || !["local-client", "datamine"].includes(source.kind)) return null;
  const canonical = (value) => JSON.stringify(value, (_key, item) =>
    item && typeof item === "object" && !Array.isArray(item)
      ? Object.fromEntries(Object.keys(item).sort().map((key) => [key, item[key]])) : item);
  const identity = canonical(source);
  return payloads.every((payload) => canonical(payload?.source) === identity) ? source : null;
}

export function durabilityBrBuckets(brValues, tiers) {
  if (!Array.isArray(brValues) || !brValues.length || !Array.isArray(tiers)) return [];
  const lastIndex = brValues.length - 1;
  return tiers.flatMap((tier) => {
    const range = tier?.balance_level;
    if (!Array.isArray(range) || range.length !== 2) return [];
    const [rawStart, rawEnd] = range;
    if (!Number.isInteger(rawStart) || !Number.isInteger(rawEnd)) return [];
    const startIndex = Math.max(0, rawStart);
    const endIndex = Math.min(lastIndex, rawEnd);
    if (startIndex > endIndex || startIndex > lastIndex) return [];
    return [Object.freeze({
      startIndex,
      endIndex,
      minBr: String(brValues[startIndex]),
      maxBr: String(brValues[endIndex]),
      value: String(brValues[endIndex]),
      tier,
    })];
  });
}

function interpolate(points, value) {
  if (!Array.isArray(points) || points.length < 2) return null;
  if (value <= points[0][0]) return points[0][1];
  if (value >= points.at(-1)[0]) return points.at(-1)[1];
  for (let index = 0; index < points.length - 1; index += 1) {
    const [x0, y0] = points[index];
    const [x1, y1] = points[index + 1];
    if (x0 <= value && value <= x1) {
      return x1 === x0 ? y1 : y0 + ((value - x0) * (y1 - y0)) / (x1 - x0);
    }
  }
  return points.at(-1)[1];
}

export function rewardUi(reward, totalDamage) {
  if (reward && totalDamage === 0) return reward.ui_decoration;
  if (!reward || !(totalDamage > 0)) return null;
  const floor = reward.piecewise_linear?.[0]?.[0];
  if (!(floor > 0)) return null;
  let multiplier;
  if (totalDamage >= floor) {
    multiplier = interpolate(reward.piecewise_linear, totalDamage);
  } else {
    const span = reward.preset_dmg_max - reward.preset_dmg_min;
    if (!(span > 0)) return null;
    const scale =
      1 + ((reward.bombing_reward_modifier - 1) * (totalDamage - reward.preset_dmg_min)) / span;
    multiplier = Math.min((scale * reward.preset_dmg_min) / totalDamage, 1);
  }
  return multiplier === null ? null : multiplier * reward.ui_decoration;
}

export function sortiePlan({ required, capacity, damage, rewardDamage = damage, reward }) {
  if (!Number.isInteger(required) || required <= 0 || !Number.isInteger(capacity) || capacity <= 0 || !(damage > 0)) {
    return null;
  }
  const sorties = Math.ceil(required / capacity);
  const lastSortieCount = required - capacity * (sorties - 1);
  return Object.freeze({
    capacity,
    sorties,
    lastSortieCount,
    fullLoadDamage: capacity * damage,
    fullLoadReward: rewardUi(reward, capacity * rewardDamage),
  });
}

// Historical measurements, not a recovered server function or hard score cap.
// Heli observations already include its unknown immediate-payment fraction.
export const usefulActionsReferences = Object.freeze({
  air_sim: {
    minutes: 15, basis: "before_landing_split", vehicleId: null,
    points: [[200, .54], [400, .75], [600, .86], [800, .90], [1050, .92]],
    url: "https://www.reddit.com/r/WarthunderSim/comments/1e7s9gu/",
    label: "2024 玩家实测 · 15 分钟完整周期",
  },
  heli_pve: {
    minutes: 10, basis: "immediate", vehicleId: "ka_52",
    points: [[200, 8800 / 16600], [400, 10957 / 16600], [600, 11586 / 16600], [800, 11714 / 16600]],
    url: "https://wiki.warthunder.ru/economy/735-ekonomika-v-vertoletnom-pve-rezhime",
    label: "2024 Wiki 作者 Ka-52 实测 · 10 分钟即时 SL",
  },
});

/** Client card display only: GUI unit.nut / airinfo.nut, reviewed at 2.57.1.132. */
export function usefulActionsCardRate({ rawRate, special, premiumAccount, boosterPercent,
  premiumMultiplier, premiumVisualPart }) {
  if (![rawRate, boosterPercent, premiumMultiplier, premiumVisualPart].every(Number.isFinite) ||
      rawRate <= 0 || boosterPercent < 0 || premiumMultiplier < 1 ||
      premiumVisualPart < 0 || premiumVisualPart >= 1 ||
      typeof special !== "boolean" || typeof premiumAccount !== "boolean") return null;
  const visualShare = 1 - (special ? premiumVisualPart : 0);
  const visualMultiplier = Math.round(10 / visualShare) / 10;
  const visualBase = rawRate * visualShare;
  const accountBonus = premiumAccount ? premiumMultiplier - 1 : 0;
  const boosterBonus = boosterPercent / 100;
  const rate = visualBase * visualMultiplier * (1 + accountBonus + boosterBonus);
  return Number.isFinite(rate) && rate > 0
    ? { rate, visualBase, visualMultiplier, accountBonus, boosterBonus } : null;
}

export function usefulActionsReference({ mode, score, minutes, vehicleId }) {
  const sample = usefulActionsReferences[mode];
  if (!sample || !Number.isFinite(score) || minutes !== sample.minutes ||
      (sample.vehicleId && sample.vehicleId !== vehicleId) ||
      score < sample.points[0][0] || score > sample.points.at(-1)[0]) return null;
  // Interpolation is only a planning reference inside the observed range.
  return { fraction: interpolate(sample.points, score), basis: sample.basis };
}

/** Arithmetic on an explicitly supplied effective fraction, never score->server activity. */
export function usefulActionsPlan({ periodMinutes, minutes, score, slRate, rpRate = null, rpFraction = null,
  fraction, basis, immediateShare }) {
  if (![periodMinutes, minutes, score, slRate, fraction].every(Number.isFinite) ||
      periodMinutes <= 0 || minutes <= 0 || minutes > periodMinutes || score < 0 ||
      slRate <= 0 || fraction < 0 || fraction > 1 ||
      (rpRate !== null && (!Number.isFinite(rpRate) || rpRate <= 0)) ||
      (rpFraction !== null && (!Number.isFinite(rpFraction) || rpFraction < 0 || rpFraction > 1)) ||
      !["before_landing_split", "immediate"].includes(basis) ||
      (basis === "before_landing_split" && (!Number.isFinite(immediateShare) || immediateShare < 0 || immediateShare > 1))) return null;
  const slNominal = slRate * minutes;
  const rpNominal = rpRate === null || rpFraction === null ? null : rpRate * minutes;
  const split = basis === "before_landing_split";
  const sl = slNominal * fraction, rp = rpNominal === null ? null : rpNominal * rpFraction;
  if (![slNominal, sl, score / minutes, ...[rpNominal, rp].filter(v => v !== null)].every(Number.isFinite)) return null;
  return {
    scorePerMinute: score / minutes, slNominal,
    slImmediate: sl * (split ? immediateShare : 1),
    slDeferred: split ? sl * (1 - immediateShare) : null,
    rpImmediate: rp === null ? null : rp * (split ? immediateShare : 1),
    rpDeferred: !split || rp === null ? null : rp * (1 - immediateShare),
  };
}

export function usefulActionsObservedFraction({ slReceived, slRate, minutes, immediateShare }) {
  if (![slReceived, slRate, minutes, immediateShare].every(Number.isFinite) || slReceived < 0 ||
      slRate <= 0 || minutes <= 0 || immediateShare <= 0 || immediateShare > 1) return null;
  const value = slReceived / slRate / minutes / immediateShare;
  return Number.isFinite(value) ? value : null;
}

/** Plot the same bounded estimates as the result, with no invented endpoints. */
export function usefulActionsCurve({ mode, vehicleId, minutes, periodMinutes, slRate, immediateShare, score }) {
  const sample = usefulActionsReferences[mode];
  if (!sample || minutes !== sample.minutes || (sample.vehicleId && sample.vehicleId !== vehicleId)) return null;
  const point = value => {
    const reference = usefulActionsReference({ mode, vehicleId, minutes, score: value });
    if (!reference) return null;
    const plan = usefulActionsPlan({ periodMinutes, minutes, score: value, slRate, immediateShare, ...reference });
    return plan ? { score: value, immediate: plan.slImmediate, total: plan.slImmediate + (plan.slDeferred ?? 0) } : null;
  };
  const points = sample.points.map(([value]) => point(value));
  if (points.some(value => !value)) return null;
  return { points, current: point(score), hasLanding: sample.basis === "before_landing_split", minutes };
}


// One user observation calibrates this empirical model. These are exact API
// identities, not a claim that other aircraft or incendiaries are equivalent.
const calibrationReward = Object.freeze({
  preset_dmg_min: 18000,
  preset_dmg_max: 97500,
  bombing_reward_modifier: 2,
  ui_decoration: 10,
  piecewise_linear: Object.freeze([[200000, .3], [1200000, .17], [50000000, .017]].map(Object.freeze)),
});
const calibrationDamage = 8 * 10860;
const calibrationMultiplier = rewardUi(calibrationReward, calibrationDamage) / calibrationReward.ui_decoration;

export const simScoreCalibrations = Object.freeze([Object.freeze({
  id: "q_5l_250_2_dwelling_br10_7_8_full_burn/v1",
  aircraftId: "q_5l",
  weaponId: "cn_gp_250_2_incendiary",
  targetId: "airport_dwelling",
  roomMaxBr: 10.7,
  carriedCount: 8,
  deliveredCount: 8,
  damagePerItem: 10860,
  rewardDamagePerItem: 10860,
  acceptedDamage: calibrationDamage,
  reward: calibrationReward,
  multiplier: calibrationMultiplier,
  tabBefore: 3230,
  tabAfter: 4038,
  score: 808,
  scale: 808 / (calibrationDamage * calibrationMultiplier),
  source: Object.freeze({
    kind: "user_battle_record",
    label: "用户实战记录 · 强-5L / 8 枚 250-2 / 生活区 / 房间最高 BR 10.7 · Tab 3230→4038（+808）",
    url: null,
  }),
})]);

export const simScoreAssumptions = Object.freeze({
  fullHit: true,
  burnComplete: true,
  damageBasis: "catalog_modeled_direct_plus_burn_damage",
  multiplierBasis: "whole_carried_loadout_reward_damage",
  acceptedDamageBasis: "minimum_of_delivered_modeled_damage_and_remaining_target_hp",
  empirical: true,
  observationCount: 1,
  uncalibrated: Object.freeze(["bonus", "SL", "RP"]),
  warning: "经验估算假设投放武器全部命中、燃烧完成；计入伤害不超过目标剩余 HP，倍率始终按整套携带挂载计算。仅有一条 +808 分实测校准，同条件其他数量属于模型估算，跨机型、弹种、目标或房间 BR 属于未实测外推。额外奖励、SL 和 RP 未校准，此模型不是服务器计分公式或命中保证。",
});

const coverageLabels = Object.freeze({
  calibrated_observation: Object.freeze({ coverageLabel: "实测条件校准", confidence: "single_observation", confidenceLabel: "单条实测校准，精度未验证" }),
  within_condition_estimate: Object.freeze({ coverageLabel: "同条件模型估算", confidence: "model_estimate", confidenceLabel: "同条件估算，非独立实测" }),
  extrapolated: Object.freeze({ coverageLabel: "未实测跨条件外推", confidence: "uncalibrated_extrapolation", confidenceLabel: "跨条件未校准，精度未知" }),
});

/** Validate all reward parameters even when an explicit rewardDmg of zero gives M=1. */
export function simScoreRewardParametersSupported(reward) {
  if (!reward || ![reward.preset_dmg_min, reward.preset_dmg_max,
    reward.bombing_reward_modifier, reward.ui_decoration].every(Number.isFinite) ||
    reward.preset_dmg_min <= 0 || reward.preset_dmg_max <= reward.preset_dmg_min ||
    reward.bombing_reward_modifier < 0 || reward.ui_decoration <= 0) return false;
  const points = reward.piecewise_linear;
  return Array.isArray(points) && points.length >= 2 && Array.from(points).every((point, index) =>
    Array.isArray(point) && point.length === 2 && point.every(Number.isFinite) &&
    point[0] > 0 && point[1] > 0 && (index === 0 || point[0] > points[index - 1][0]));
}

function loadoutCounts(items, allowZero) {
  if (!Array.isArray(items)) return null;
  const counts = new Map();
  for (const row of items) {
    if (!Array.isArray(row) || row.length !== 2) return null;
    const [id, count] = row;
    if (typeof id !== "string" || !id.trim() || !Number.isSafeInteger(count) ||
      count < (allowZero ? 0 : 1)) return null;
    const total = (counts.get(id) ?? 0) + count;
    if (!Number.isSafeInteger(total)) return null;
    counts.set(id, total);
  }
  return counts;
}

function sameRewardCurve(reward, reference) {
  return ["preset_dmg_min", "preset_dmg_max", "bombing_reward_modifier"].every(field => reward[field] === reference[field]) &&
    reward.piecewise_linear.length === reference.piecewise_linear.length &&
    reward.piecewise_linear.every((point, index) => point.every((value, coordinate) => value === reference.piecewise_linear[index][coordinate]));
}

/**
 * Empirical Air Simulator target-damage score, S = k * acceptedDamage * M.
 * carried/delivered are [[weaponId, wholeCount]], weapons is the catalog Map.
 * dmg already includes modeled direct + complete burn damage; never apply a
 * fire multiplier again. Unknown damage/reward data excludes the whole loadout.
 * remainingHp must be explicitly supplied by the caller, including zero.
 */
export function empiricalSimScore(input = {}) {
  if (!input) return null;
  const { aircraftId, roomMaxBr, targetId, carried, delivered = carried,
    weapons, reward, remainingHp } = input;
  if (typeof aircraftId !== "string" || !aircraftId.trim() ||
    typeof targetId !== "string" || !targetId.trim() ||
    !Number.isFinite(roomMaxBr) || roomMaxBr <= 0 ||
    !Number.isFinite(remainingHp) || remainingHp < 0 ||
    !(weapons instanceof Map) || !simScoreRewardParametersSupported(reward)) return null;
  const carriedCounts = loadoutCounts(carried, false);
  const deliveredCounts = loadoutCounts(delivered, true);
  if (!carriedCounts?.size || !deliveredCounts) return null;
  for (const [id, count] of deliveredCounts) {
    if (!carriedCounts.has(id) || count > carriedCounts.get(id)) return null;
  }
  let carriedDamage = 0, carriedRewardDamage = 0, deliveredDamage = 0;
  for (const [id, count] of carriedCounts) {
    const weapon = weapons.get(id);
    if (!Number.isFinite(weapon?.dmg) || weapon.dmg <= 0 ||
      !Number.isFinite(weapon?.rewardDmg) || weapon.rewardDmg < 0 ||
      ["aam", "arm", "ashm"].includes(weapon.role)) return null;
    carriedDamage += weapon.dmg * count;
    carriedRewardDamage += weapon.rewardDmg * count;
    deliveredDamage += weapon.dmg * (deliveredCounts.get(id) ?? 0);
  }
  if (![carriedDamage, carriedRewardDamage, deliveredDamage].every(Number.isFinite)) return null;
  const multiplier = rewardUi(reward, carriedRewardDamage) / reward.ui_decoration;
  if (!Number.isFinite(multiplier) || multiplier <= 0) return null;
  const acceptedDamage = Math.min(deliveredDamage, remainingHp);

  // Add future exact-identity observations as separate rows. An unmatched
  // request uses the first observation only as explicitly labelled extrapolation.
  const condition = simScoreCalibrations.find(reference =>
    reference.aircraftId === aircraftId && reference.targetId === targetId &&
    reference.roomMaxBr === roomMaxBr && carriedCounts.size === 1 &&
    carriedCounts.has(reference.weaponId) &&
    weapons.get(reference.weaponId).dmg === reference.damagePerItem &&
    weapons.get(reference.weaponId).rewardDmg === reference.rewardDamagePerItem &&
    sameRewardCurve(reward, reference.reward));
  const calibration = condition ?? simScoreCalibrations[0];
  // This is k * acceptedDamage * M, evaluated relative to the calibration
  // so its exact 808-point anchor is not lost to binary multiplication order.
  const score = calibration.score * (acceptedDamage / calibration.acceptedDamage) *
    (multiplier / calibration.multiplier);
  if (!Number.isFinite(score)) return null;
  const reproducesObservation = condition &&
    carriedCounts.get(condition.weaponId) === condition.carriedCount &&
    deliveredCounts.get(condition.weaponId) === condition.deliveredCount &&
    acceptedDamage === condition.acceptedDamage;
  const coverage = reproducesObservation ? "calibrated_observation" :
    condition ? "within_condition_estimate" : "extrapolated";
  return Object.freeze({
    score, carriedDamage, carriedRewardDamage, multiplier, deliveredDamage, acceptedDamage,
    calibrationId: calibration.id, coverage, ...coverageLabels[coverage],
    source: calibration.source, sourceLabel: calibration.source.label,
    assumptions: simScoreAssumptions,
  });
}
