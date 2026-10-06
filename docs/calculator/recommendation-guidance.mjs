// Modes come from the same native parameter snapshot as damage and hardpoints.
export const guidanceFilterKeys = ["noLaser", "noOptical", "noSatellite"];
const filterForMode = {laser: "noLaser", infrared: "noOptical", tv: "noOptical", optical: "noOptical", satellite: "noSatellite"};
const modeBurden = {satellite: 0, infrared: 1, tv: 2, optical: 2, laser: 3};

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
  return {...filters, onlyGuided: Boolean(filters.onlyGuided), noGuided: !filters.onlyGuided && Boolean(filters.noGuided)};
}

export function availableGuidanceModes(weapon, filters = {}) {
  return (weapon?.guidanceModes ?? []).filter(mode => !filters[filterForMode[mode]]);
}

export function guidanceExcluded(weapon, filters = {}) {
  return Boolean(weapon?.guidanceModes?.length && !availableGuidanceModes(weapon, filters).length);
}

export function toggleRecommendationFilter(filters, key) {
  const next = {...filters, [key]: !filters[key]};
  if (key === "onlyGuided" && next.onlyGuided) next.noGuided = false;
  if (key === "noGuided" && next.noGuided) next.onlyGuided = false;
  const allExcluded = guidanceFilterKeys.every(key => next[key]);
  if (key === "onlyGuided" && next.onlyGuided && allExcluded) {
    for (const key of guidanceFilterKeys) next[key] = false;
  } else if (guidanceFilterKeys.includes(key) && allExcluded) next.onlyGuided = false;
  return next;
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
