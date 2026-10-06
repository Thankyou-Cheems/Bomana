// Modes come from the same native parameter snapshot as damage and hardpoints.
export const guidanceFilterKeys = ["noLaser", "noOptical", "noSatellite", "noManual"];
const filterForMode = {laser: "noLaser", infrared: "noOptical", tv: "noOptical", optical: "noOptical", satellite: "noSatellite", manual: "noManual"};
const modeBurden = {satellite: 0, infrared: 1, tv: 2, optical: 2, laser: 3, manual: 4};

export function weaponGuidanceKind(weapon) {
  if (weapon && (weapon.kind === "missile" || weapon.guidanceModes?.length || weapon.deliveryProfile?.guidance && weapon.deliveryProfile.guidance !== "none")) return "guided";
  return weapon?.deliveryProfile?.guidance === "none" ? "unguided" : "unknown";
}

export function guidanceSelectionExcluded(weapon, filters = {}) {
  const kind = weaponGuidanceKind(weapon);
  return Boolean(filters.onlyGuided && kind !== "guided" || filters.noGuided && kind !== "unguided");
}

export function recommendationWeaponExcluded(weapon, filters = {}) {
  return Boolean(guidanceSelectionExcluded(weapon, filters) || filters.noHighDrag && weapon?.highDrag ||
    filters.noRockets && weapon?.kind === "rocket" || filters.noMissiles && weapon?.kind === "missile" || guidanceExcluded(weapon, filters));
}

export function normalizeGuidanceSelection(filters = {}) {
  const next = {...filters, onlyGuided: Boolean(filters.onlyGuided), noGuided: !filters.onlyGuided && Boolean(filters.noGuided)};
  for (const key of [...guidanceFilterKeys, "noHighDrag", "noRockets", "noMissiles"]) next[key] = Boolean(next[key]);
  if (next.noGuided) {
    for (const key of guidanceFilterKeys) next[key] = true;
    next.noMissiles = true;
  }
  if (guidanceFilterKeys.every(key => next[key])) {
    next.onlyGuided = false; next.noGuided = true; next.noMissiles = true;
  }
  if (next.onlyGuided) next.noHighDrag = next.noRockets = true;
  return next;
}

export function selectRecommendationGuidance(filters, selection) {
  const next = {...filters, onlyGuided: selection === "guided", noGuided: selection === "unguided",
    noHighDrag: selection === "guided", noRockets: selection === "guided", noMissiles: selection === "unguided"};
  for (const key of guidanceFilterKeys) next[key] = selection === "unguided";
  return next;
}

export function availableGuidanceModes(weapon, filters = {}) {
  return (weapon?.guidanceModes ?? []).filter(mode => Object.hasOwn(filterForMode, mode) && !filters[filterForMode[mode]]);
}

export function guidanceExcluded(weapon, filters = {}) {
  return Boolean(weapon?.guidanceModes?.length ? !availableGuidanceModes(weapon, filters).length :
    weaponGuidanceKind(weapon) === "guided" && guidanceFilterKeys.some(key => filters[key]));
}

export function toggleRecommendationFilter(filters, key) {
  if (key === "onlyGuided" || key === "noGuided") return selectRecommendationGuidance(filters,
    filters[key] ? "any" : key === "onlyGuided" ? "guided" : "unguided");
  const current = normalizeGuidanceSelection(filters), next = {...current, [key]: !current[key]};
  if (guidanceFilterKeys.includes(key) && !next[key]) next.noGuided = false;
  if ((key === "noHighDrag" || key === "noRockets") && !next[key]) next.onlyGuided = false;
  if (key === "noMissiles" && !next.noMissiles) {
    next.noGuided = false;
    if (guidanceFilterKeys.every(key => next[key])) for (const key of guidanceFilterKeys) next[key] = false;
  }
  return normalizeGuidanceSelection(next);
}

// An ordinal delivery preference, not flight time or a hit-probability model.
// Coordinate navigation avoids seeker pre-lock; EO and illumination add work.
export function guidanceBurden(weapon, filters = {}) {
  const modes = availableGuidanceModes(weapon, filters);
  return modes.length ? Math.min(...modes.map(mode => modeBurden[mode])) : 2;
}

export function preferredGuidanceMode(weapon, filters = {}) {
  return availableGuidanceModes(weapon, filters).reduce((best, mode) => best === null || modeBurden[mode] < modeBurden[best] ? mode : best, null);
}

export function deliveryWorkload(plan, weapons, filters = {}) {
  let designation = 0, shots = 0;
  for (const row of plan) for (const [id, count] of row) {
    designation += guidanceBurden(weapons.get(id), filters) * count;
    shots += count;
  }
  return {designation, shots};
}
