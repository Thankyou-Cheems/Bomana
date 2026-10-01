// Conservative handling groups, not a trajectory solver. Native drag references
// are grouped within 25% bands, keeping guidance and braking behavior separate.
// Powered weapons and missing profiles stay separate unless the weapon is identical.
export function deliveryGroup(id, weapon) {
  const profile = weapon?.deliveryProfile;
  if (weapon?.kind !== "bomb" || !profile || ![profile.drag_area_mass, profile.area_mass].every(value => Number.isFinite(value) && value > 0)) return `weapon:${id}`;
  const band = value => Math.floor(Math.log(value) / Math.log(1.25));
  const optionalBand = value => value == null ? "native-default" : band(value);
  return [weapon.satelliteGuidance ? "satellite" : profile.guidance, Boolean(weapon.highDrag), band(profile.drag_area_mass), band(profile.area_mass), optionalBand(profile.axial_coefficient), optionalBand(profile.lift_scale)].join(":");
}

export function loadoutSimplicity(items, weapons) {
  const ids = new Set(items.filter(([id, count]) => count > 0 && weapons.get(id)?.dmg > 0).map(([id]) => id));
  return {types: ids.size, profiles: new Set([...ids].map(id => deliveryGroup(id, weapons.get(id)))).size};
}
