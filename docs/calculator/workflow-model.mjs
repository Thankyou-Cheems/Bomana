// UI helpers only. Existing game damage, reward and encounter models are unchanged.
export function measuredFuelBurn({ startKg, endKg, seconds }) {
  if ([startKg, endKg, seconds].some(value => value === null)) return { error: "empty" };
  if (![startKg, endKg, seconds].every(Number.isFinite) || startKg < 0 || endKg < 0 || seconds <= 0) return { error: "invalid" };
  if (endKg >= startKg) return { error: "increase" };
  const burnKgMin = (startKg - endKg) * 60 / seconds;
  return Number.isFinite(burnKgMin) && burnKgMin > 0 ? { burnKgMin } : { error: "invalid" };
}

export const fuelFields = Object.freeze([
  ["fuelKg", "currentFuel", false, false],
  ["fuelBurn", "burnRate", true, true],
  ["fuelSpeed", "groundSpeed", true, true],
  ["fuelDistance", "distance", true, false],
  ["fuelRoute", "route", true, false],
  ["fuelReserve", "reserve", true, false],
]);

export function fuelInputIssues(values) {
  return fuelFields.flatMap(([id, label, required, positive]) => {
    const value = values[id];
    const reason = value === null ? (required ? "fuelMissing" : null)
      : !Number.isFinite(value) ? "fuelInvalid"
      : positive && value <= 0 ? "fuelPositive"
      : value < 0 ? "fuelNonnegative" : null;
    return reason ? [{ id, label, reason }] : [];
  });
}

export const workflowIds = Object.freeze(["returnFuel", "usefulActions", "airportStatus", "loadoutCompare", "explosiveConversion", "airCombat", "airfieldDefense", "fieldGuide"]);
export const workflowFromHash = hash => workflowIds.includes(hash.replace(/^#/, "")) ? hash.replace(/^#/, "") : null;
