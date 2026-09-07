export function requiredCount(hp, damage) {
  if (!Number.isFinite(hp) || !Number.isFinite(damage) || !(hp > 0) || !(damage > 0)) return null;
  return Math.max(1, Math.ceil(hp / damage - 1e-9));
}

export function equivalentWeaponCount({ sourcePerItem, targetPerItem, sourceCount }) {
  if (![sourcePerItem, targetPerItem].every(value => Number.isFinite(value) && value > 0) ||
      !Number.isSafeInteger(sourceCount) || sourceCount < 0) return null;
  const sourceTotal = sourcePerItem * sourceCount;
  const exactCount = sourceTotal / targetPerItem;
  if (![sourceTotal, exactCount].every(Number.isFinite) || (sourceCount > 0 && !(exactCount > 0))) return null;
  // Correct only floating-point arithmetic noise, never round displayed values
  // before choosing the minimum whole number of weapons.
  const nearest = Math.round(exactCount);
  const wholeCount = Math.abs(exactCount - nearest) <= Number.EPSILON * Math.max(1, exactCount) * 2
    ? nearest : Math.ceil(exactCount);
  const targetTotal = wholeCount * targetPerItem;
  if (!Number.isSafeInteger(wholeCount) || (sourceCount > 0 && wholeCount === 0) || !Number.isFinite(targetTotal)) return null;
  return { sourceTotal, exactCount, wholeCount, targetTotal, surplus: Math.max(0, targetTotal - sourceTotal) };
}

export function explosiveConversion({ sourceMassKg, sourceFactor, sourceCount, targetMassKg, targetFactor }) {
  if (![sourceMassKg, sourceFactor, targetMassKg, targetFactor].every(value => Number.isFinite(value) && value > 0)) return null;
  const sourceTntKg = sourceMassKg * sourceFactor, targetTntKg = targetMassKg * targetFactor;
  const equivalent = equivalentWeaponCount({ sourcePerItem: sourceTntKg, targetPerItem: targetTntKg, sourceCount });
  return equivalent ? { sourceTntKg, targetTntKg, ...equivalent } : null;
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
