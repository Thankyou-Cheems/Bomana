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

export function rewardUi(reward, totalDamage, aircraft = null) {
  if (reward && totalDamage === 0) return reward.ui_decoration;
  if (!reward || !(totalDamage > 0)) return null;
  const floor = reward.piecewise_linear?.[0]?.[0];
  if (!(floor > 0)) return null;
  let multiplier;
  if (totalDamage >= floor) {
    multiplier = interpolate(reward.piecewise_linear, totalDamage);
  } else {
    // Public aircraft flags: fighter=1, premium=2, ordinary=0, unknown=null.
    if (aircraft && !Number.isInteger(aircraft.reward)) return null;
    const span = reward.preset_dmg_max - reward.preset_dmg_min;
    if (!(span > 0)) return null;
    const scale =
      1 + ((reward.bombing_reward_modifier - 1) * (totalDamage - reward.preset_dmg_min)) / span;
    multiplier = (scale * reward.preset_dmg_min) / totalDamage;
    if (aircraft?.reward & 2) multiplier *= reward.prem_bombing_reward_mul;
    multiplier = Math.min(multiplier, 1);
    if (aircraft?.reward & 1) multiplier *= reward.fighter_bombing_reward_mul;
  }
  if (multiplier === null) return null;
  const result = multiplier * reward.ui_decoration;
  return Number.isFinite(result) ? result : null;
}

// The premium factor moves the end of the constant-coefficient region.
// Fighter penalties change its height, after the native clamp.
export function rewardPlateauDamage(reward, aircraft = null) {
  const span = reward.preset_dmg_max - reward.preset_dmg_min;
  const a = reward.preset_dmg_min * (reward.bombing_reward_modifier - 1) / span;
  const b = reward.preset_dmg_min * (1 - (reward.bombing_reward_modifier - 1) * reward.preset_dmg_min / span);
  const premium = aircraft?.reward & 2 ? reward.prem_bombing_reward_mul : 1;
  return Math.min(reward.piecewise_linear[0][0], b * premium / (1 - a * premium));
}

export function sortiePlan({ required, capacity, damage, rewardDamage = damage,
  fullLoadRewardDamage = capacity * rewardDamage, reward, aircraft = null }) {
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
    fullLoadReward: rewardUi(reward, fullLoadRewardDamage, aircraft),
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


// Empirical coefficients supported by the recorded conventional/napalm samples.
// Neither coefficient nor napalm attribution is a recovered server function.
export const simScoreDamageScale = .018;
const simScoreDestructionScale = .009;
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
  scoreDamagePerItem: 14500,
  rewardDamagePerItem: 10860,
  acceptedDamage: calibrationDamage,
  reward: calibrationReward,
  multiplier: calibrationMultiplier,
  tabBefore: 3230,
  tabAfter: 4038,
  score: 808,
  damageScore: 808, destructionScore: 0, observedTotal: 808,
  reportedDamageScoreRange: Object.freeze([807, 808]),
  repeatedObservation: Object.freeze({source: "user_report", exactTrialCount: null,
    clientVersion: null, roundingMechanism: null, usedForCoefficientCalibration: false}),
  battleMode: "simulator", targetDestroyed: false,
  scale: simScoreDamageScale,
  source: Object.freeze({
    kind: "user_battle_record",
    label: "用户实战记录 / 强-5L / 8 枚 250-2 / 生活区未摧毁 / 房间最高 BR 10.7 / 轰炸分 3230→4038（+808），摧毁分 0",
    confirmation: "user_confirmed_bombing_only_no_destruction",
    clientVersion: null,
    url: null,
  }),
})]);

// Separate damage and destruction events from a confirmed solo, full-health
// Air Simulator base kill. Equal RB/SB HP does not make their scores equal.
const baseDamage = 12 * 2071;
const baseMultiplier = rewardUi(calibrationReward, baseDamage) / calibrationReward.ui_decoration;
export const simBaseScoreCalibrations = Object.freeze([Object.freeze({
  id: "jh_7_250_3_12_solo_high_br_base/v1",
  aircraftId: "jh_7", weaponId: "cn_gp_250_3_default", targetId: "bombing_point_planes",
  minimumRoomBr: 8, targetFullHp: 25900, destructionThreshold: 23310,
  roomMaxBr: null, roomRangeEvidence: "user_reported_shared_hp_not_shared_score",
  carriedCount: 12, deliveredCount: 12, damagePerItem: 2071, rewardDamagePerItem: 2071,
  scoreDamagePerItem: 2071,
  acceptedDamage: baseDamage, reward: calibrationReward, multiplier: baseMultiplier,
  score: 367, destructionScore: 183, observedTotal: 550, independentDestruction: true,
  scale: simScoreDamageScale,
  source: Object.freeze({kind: "user_battle_record", url: null, clientVersion: null,
    label: "用户实战记录 · 全真 JH-7 / 12 枚 250-3 / 独立摧毁满血高 BR 战区 · 轰炸 367 + 摧毁 183 = 550"}),
})]);

// Cumulative damage-score counter, not a 719-point sortie. Unknown hit count
// makes this comparison evidence unsuitable for fitting full-hit damage scale.
export const simScoreComparisonObservations = Object.freeze([Object.freeze({
  id: "jh_7_250_3_12_dwelling_unknown_hits/v1", aircraftId: "jh_7",
  weaponId: "cn_gp_250_3_default", targetId: "airport_dwelling", carriedCount: 12,
  deliveredCount: null, initialTargetHealth: "full", counterBefore: 367, counterAfter: 719,
  score: 352, usableForFullHitCalibration: false,
  source: Object.freeze({kind: "user_battle_record", url: null,
    label: "用户实战记录 · JH-7 / 12 枚 250-3 / 满血生活区 · 轰炸累计 367→719（+352），命中数未知、期间无其它轰炸分"}),
}), Object.freeze({
  id: "jh_7_250_3_12_repeated_base_counter/v1", aircraftId: "jh_7",
  weaponId: "cn_gp_250_3_default", targetId: "bombing_point_planes", carriedCount: 12,
  deliveredCount: null, initialTargetHealth: null, teammateDamage: null,
  counterBefore: 719, counterAfter: 1086, score: 367,
  destructionCounterBefore: 183, destructionCounterAfter: 366, destructionScore: 183,
  totalScore: 550, usableForFullHitCalibration: false,
  source: Object.freeze({kind: "user_battle_record", url: null,
    label: "用户同局后续记录 · 挂载未变 / 再炸战区 · 轰炸累计 719→1086（+367），摧毁累计 183→366（+183）；初始满血及队友参与未确认"}),
}), Object.freeze({
  id: "jh_7_250_3_single_dwelling_counter/v1", aircraftId: "jh_7",
  weaponId: "cn_gp_250_3_default", targetId: "airport_dwelling", battleMode: "simulator",
  deliveredCount: 1, confirmedHits: 1, initialTargetHealth: "full",
  counterBefore: 2550, counterAfter: 2579, score: 29,
  followupDeliveredCount: 11, followupConfirmedHits: null,
  followupCounterAfter: 2902, followupScore: 323, totalDeliveredCount: 12, totalScore: 352,
  followupOtherScoreEventsExcluded: null,
  picturedPresetId: "jh_7_bomb250_gp_default", picturedCarriedCount: 12,
  roomMaxBr: null, usedForCoefficientCalibration: false,
  source: Object.freeze({kind: "user_battle_record", url: null, clientVersion: null,
    libraryFileId: "libfile_c1356b404cec8191845185c0c8517628",
    imageReview: "actual_pixels_reviewed_in_parent_thread_not_this_executor",
    label: "用户连续记录 / 歼轰-7 02 批次飞豹 / 精确命中满血生活区一枚250-3 / 2550→2579（+29），随后投11枚→2902（+323），合计352；后11枚命中及其它同期得分未单独确认"}),
}), Object.freeze({
  id: "jh_7a_gb1000_gb250_two_solo_bases/v1", aircraftId: "jh_7a",
  targetId: "bombing_point_planes", battleMode: "simulator",
  carried: Object.freeze([Object.freeze(["cn_ls_1000j", 2]), Object.freeze(["cn_ts_250", 2])]),
  rounds: 2, destroyedTargets: 2, initialTargetHealth: "full", teammateDamage: false,
  roomMaxBr: null, damageScore: 728, destructionScore: 364, totalScore: 1092,
  usedForCoefficientCalibration: false, roundingMechanism: null,
  source: Object.freeze({kind: "user_battle_record", url: null, clientVersion: null,
    label: "用户实战截图 · JH-7A / 每轮 2 枚 GB1000 + 2 枚 GB250 / 两轮独立摧毁两个满血战区 · 轰炸 728 + 摧毁 364 = 1092"}),
})]);

export const simScoreAssumptions = Object.freeze({
  fullHit: true,
  burnComplete: true,
  model: "empirical_sim_score/v3",
  damageBasis: "nominal_hp_damage_separate_from_empirical_score_damage",
  multiplierBasis: "whole_carried_loadout_reward_damage",
  acceptedDamageBasis: "separate_hp_and_score_caps_full_health_solo_base_full_hp_credit",
  empirical: true,
  observationCount: 6,
  calibrationCount: 2,
  destructionRewardScope: "full_health_solo_base_kill_estimate",
  uncalibrated: Object.freeze(["bonus", "SL", "RP"]),
  warning: "经验估算假设投放武器全部命中，倍率始终按整套携带挂载计算。普通弹得分使用 .018；燃烧弹以原始溅射估计得分伤害，HP 求解仍用原名义伤害并假设燃烧完成，强-5L 的 807–808 分支持此口径但未证实服务器归属。独立摧毁满血战区时计满 HP，轰炸和摧毁分项使用 .018 和 .009；已受损战区的摧毁归属、额外奖励、SL 和 RP 未校准。跨条件未实测，不能保证服务器分数或命中。",
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
 * Empirical Air Simulator score keeps HP solving and score damage separate.
 * Full-health solo base kills estimate damage and destruction events using
 * the recorded coefficients. Damaged bases retain unknown reward attribution.
 * carried/delivered are [[weaponId, wholeCount]], weapons is the catalog Map.
 * Napalm scoreDmg is a raw-splash hypothesis, not actual HP damage. Explicitly
 * unknown score damage excludes the loadout; older ordinary rows use dmg.
 * remainingHp must be explicitly supplied by the caller, including zero.
 */
export function empiricalSimScore(input = {}) {
  if (!input) return null;
  const { aircraftId, roomMaxBr, targetId, carried, delivered = carried, battleMode = "simulator",
    weapons, reward, remainingHp } = input;
  if (typeof aircraftId !== "string" || !aircraftId.trim() ||
    typeof targetId !== "string" || !targetId.trim() ||
    !Number.isFinite(roomMaxBr) || roomMaxBr <= 0 ||
    !Number.isFinite(remainingHp) || remainingHp < 0 ||
    !(weapons instanceof Map) || !simScoreRewardParametersSupported(reward) || battleMode !== "simulator") return null;
  const isBase = targetId === "bombing_point_planes";
  if (!isBase && !targetId.startsWith("airport_")) return null;
  const carriedCounts = loadoutCounts(carried, false);
  const deliveredCounts = loadoutCounts(delivered, true);
  if (!carriedCounts?.size || !deliveredCounts) return null;
  for (const [id, count] of deliveredCounts) {
    if (!carriedCounts.has(id) || count > carriedCounts.get(id)) return null;
  }
  let carriedDamage = 0, carriedRewardDamage = 0, deliveredDamage = 0, deliveredScoreDamage = 0;
  for (const [id, count] of carriedCounts) {
    const weapon = weapons.get(id);
    if (!Number.isFinite(weapon?.dmg) || weapon.dmg <= 0 ||
      !Number.isFinite(weapon?.rewardDmg) || weapon.rewardDmg < 0 ||
      ["aam", "arm", "ashm"].includes(weapon.role)) return null;
    const scoreDamage = simScoreDamageOf(weapon);
    if (!Number.isFinite(scoreDamage) || scoreDamage <= 0) return null;
    carriedDamage += weapon.dmg * count;
    carriedRewardDamage += weapon.rewardDmg * count;
    deliveredDamage += weapon.dmg * (deliveredCounts.get(id) ?? 0);
    deliveredScoreDamage += scoreDamage * (deliveredCounts.get(id) ?? 0);
  }
  if (![carriedDamage, carriedRewardDamage, deliveredDamage, deliveredScoreDamage].every(Number.isFinite)) return null;
  const multiplier = rewardUi(reward, carriedRewardDamage) / reward.ui_decoration;
  if (!Number.isFinite(multiplier) || multiplier <= 0) return null;
  const acceptedDamage = Math.min(deliveredDamage, remainingHp);

  // Add future exact-identity observations as separate rows. An unmatched
  // request uses the first observation only as explicitly labelled extrapolation.
  const references = isBase ? simBaseScoreCalibrations : simScoreCalibrations;
  const condition = references.find(reference =>
    reference.aircraftId === aircraftId && reference.targetId === targetId &&
    (isBase ? roomMaxBr >= reference.minimumRoomBr && input.targetFullHp === reference.targetFullHp &&
      input.destructionThreshold === reference.destructionThreshold : reference.roomMaxBr === roomMaxBr) && carriedCounts.size === 1 &&
    carriedCounts.has(reference.weaponId) &&
    weapons.get(reference.weaponId).dmg === reference.damagePerItem &&
    weapons.get(reference.weaponId).rewardDmg === reference.rewardDamagePerItem &&
    simScoreDamageOf(weapons.get(reference.weaponId)) === reference.scoreDamagePerItem &&
    sameRewardCurve(reward, reference.reward));
  const calibration = condition ?? references[0];
  const {targetFullHp, destructionThreshold} = input;
  const knownTarget = Number.isFinite(targetFullHp) && Number.isFinite(destructionThreshold) &&
    targetFullHp > 0 && destructionThreshold > 0 && destructionThreshold <= targetFullHp && remainingHp <= targetFullHp;
  const mayDestroy = knownTarget && deliveredDamage >= Math.max(0, remainingHp - (targetFullHp - destructionThreshold));
  // The solo/full-health planning scenario credits the burn tail up to full
  // HP on reaching the native destruction threshold. Other loadouts are
  // empirical extrapolations; HP damage and the number solver stay unchanged.
  const soloBaseKill = isBase && knownTarget && remainingHp === targetFullHp && mayDestroy;
  const acceptedScoreDamage = soloBaseKill ? targetFullHp : Math.min(deliveredScoreDamage, remainingHp);
  const damageScore = simScoreDamageScale * acceptedScoreDamage * multiplier;
  if (!Number.isFinite(damageScore)) return null;
  // A damaged base can include teammate damage: its destruction attribution
  // stays unknown. Full-health estimates assume this delivery destroys it solo.
  const destructionScore = !isBase ? 0 : soloBaseKill ? simScoreDestructionScale * targetFullHp * multiplier :
    deliveredDamage === 0 || remainingHp === 0 || knownTarget && !mayDestroy ? 0 : null;
  const totalScore = destructionScore === null ? null : damageScore + destructionScore;
  const score = totalScore ?? damageScore;
  // The base sample's exact room BR/client version was not measured. Matching
  // the shared HP range reproduces its anchor, not independent score trials.
  const jhAirportObservation = !isBase && aircraftId === "jh_7" && targetId === "airport_dwelling" &&
    carriedCounts.size === 1 && carriedCounts.get("cn_gp_250_3_default") === 12 &&
    weapons.get("cn_gp_250_3_default")?.dmg === 2071 &&
    weapons.get("cn_gp_250_3_default")?.rewardDmg === 2071 &&
    simScoreDamageOf(weapons.get("cn_gp_250_3_default")) === 2071 && sameRewardCurve(reward, calibrationReward)
    ? simScoreComparisonObservations[2] : null;
  const coverage = condition || jhAirportObservation ? "within_condition_estimate" : "extrapolated";
  const reference = jhAirportObservation ?? calibration;
  return Object.freeze({
    score, damageScore, destructionScore, totalScore, scoreKind: totalScore === null ? "damage_only" : "total",
    carriedDamage, carriedRewardDamage, multiplier, deliveredDamage, acceptedDamage,
    deliveredScoreDamage, acceptedScoreDamage, damageScale: simScoreDamageScale,
    calibrationId: reference.id, coverage, ...coverageLabels[coverage],
    source: reference.source, sourceLabel: reference.source.label,
    assumptions: simScoreAssumptions,
  });
}

export function simScoreDamageOf(weapon) {
  if (weapon && Object.hasOwn(weapon, "scoreDmg")) return weapon.scoreDmg;
  return weapon?.damage_model === "napalm_splash_fire" ? null : weapon?.dmg;
}
