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

export function sortiePlan({ required, capacity, damage, reward }) {
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
    fullLoadReward: rewardUi(reward, capacity * damage),
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
