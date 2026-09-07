import { describe, expect, it } from "vitest";
import { FuelManager, aircraftFuelRate, type AircraftFuelProfile, type FuelObservation } from "./fuel-management";
import { AircraftParameters } from "./aircraft-parameters";

const profiles: Record<string, AircraftFuelProfile> = {
  jet: { engineType: "jet", modelConfidence: "reference-only", engines: [{ kind: "jet", consumption: [1, 1, 1, 3] }] },
  prop: { engineType: "piston", modelConfidence: "reference-only", engines: [{ kind: "piston", consumption: [.2, .2, .2, .3] }] },
};
const catalog = new AircraftParameters({ schema_version: 1, unit_to_fm: { jet: "jet", prop: "prop" }, loadouts: {},
  flight_models: { jet: { speed: null, fuel: profiles.jet! }, prop: { speed: null, fuel: profiles.prop! } } });
function observation(atMs: number, fuelKg: number | null, patch: Partial<FuelObservation> = {}): FuelObservation {
  return { atMs, aircraft: "jet", fuelKg, initialKg: 1200,
    engines: [{ throttlePercent: 90, thrustKgf: 3600, powerHp: null }],
    altitudeM: 3000, tasKmh: 720, iasKmh: 700, verticalSpeedMps: 0,
    onGround: false, groundSpeedKmh: 720, ...patch };
}
const target = { label: "友方机场", distanceKm: 36 };
function learn(manager: FuelManager, start = 0, end = 30000, initial = 1000, ratePerSecond = 1, patch: Partial<FuelObservation> = {}) {
  for (let at = start; at <= end; at += 100) manager.observe(observation(at, initial - (at-start)/1000 * ratePerSecond, patch));
  return manager.view(end, true, target, true);
}

describe("aircraft fuel management", () => {
  it("learns actual consumption and budgets travel plus an explicit five-minute reserve", () => {
    const fuel = learn(new FuelManager(catalog));
    expect(fuel).toMatchObject({ source: "measured", rateKgMin: 60, returnStatus: "safe", reserveKg: 300 });
    expect(fuel.tripKg).toBeCloseTo(216);
    expect(fuel.returnNeededKg).toBeCloseTo(516);
    expect(fuel.marginKg).toBeCloseTo(454);
  });
  it("immediately withdraws cruise confidence on afterburner and learns the new rate", () => {
    const manager = new FuelManager(catalog);
    learn(manager);
    const boosted = { engines: [{ throttlePercent: 110, thrustKgf: 3600, powerHp: null }] };
    manager.observe(observation(30100, 969.7, boosted));
    expect(manager.view(30100, true, target, true)).toMatchObject({ stable: false, source: "aircraft-estimate", rateKgMin: 180, returnStatus: "unknown" });
    const fuel = learn(manager, 30200, 50200, 969.4, 3, boosted);
    expect(fuel.rateKgMin).toBeCloseTo(180);
    expect(fuel.returnStatus).toBe("danger");
    expect(fuel.economy?.savingPercent).toBeCloseTo(200/3);
    expect(fuel.economy?.throttlePercent).toBe(90);
  });
  it("uses the individual engine characteristic and requires every engine output", () => {
    expect(aircraftFuelRate(catalog.fuel("jet"), [{ throttlePercent: 100, thrustKgf: 6000, powerHp: 1500 }])).toBe(100);
    expect(aircraftFuelRate(catalog.fuel("prop"), [{ throttlePercent: 100, thrustKgf: 6000, powerHp: 1500 }])).toBe(5);
    expect(aircraftFuelRate(catalog.fuel("jet"), [])).toBeNull();
    expect(aircraftFuelRate({ engineType: "mixed", engines: [...profiles.jet!.engines, ...profiles.prop!.engines] },
      [{ throttlePercent: 100, thrustKgf: 6000, powerHp: null }])).toBeNull();
  });
  it("relearns after small-aircraft refuelling, tank drops, and changing aircraft", () => {
    const manager = new FuelManager();
    learn(manager);
    manager.observe(observation(30100, 980));
    expect(manager.view(30100, true, target, true)).toMatchObject({ stable: false, reason: "refuel" });
    learn(manager, 30200, 50000, 980);
    manager.observe(observation(50100, 700));
    expect(manager.view(50100, true, target, true)).toMatchObject({ currentKg: 700, stable: false, reason: "fuel-jump" });
    manager.observe(observation(50200, 100, { aircraft: "prop", initialKg: 150 }));
    expect(manager.view(50200, true, target, true)).toMatchObject({ currentKg: 100, initialKg: 150, stable: false, economy: null });
  });
  it("requires measurable consumption even for a known aircraft and ignores duplicate source timestamps", () => {
    const manager = new FuelManager(catalog);
    const fuel = learn(manager, 0, 30000, 1000, 0);
    expect(fuel).toMatchObject({ stable: false, returnStatus: "unknown", source: "aircraft-estimate" });
    manager.observe(observation(30000, 0));
    expect(manager.view(30000, true, target, true).currentKg).toBe(1000);
    expect(manager.view(33100, true, target, true)).toMatchObject({ available: false, source: "unavailable", returnStatus: "unknown" });
  });
  it("can resolve a low-consumption propeller aircraft without certifying quantization plateaus", () => {
    const manager = new FuelManager();
    const fuel = learn(manager, 0, 45000, 100, .01, { aircraft: "prop", initialKg: 150 });
    expect(fuel.stable).toBe(true);
    expect(fuel.rateKgMin).toBeCloseTo(.6);
  });
  it("does not use a dive, missing track or missing airfield as a cheap return route", () => {
    const manager = new FuelManager(catalog);
    learn(manager);
    expect(manager.view(30000, true, target, false)).toMatchObject({ reason: "no-track", returnStatus: "unknown", marginKg: null });
    expect(manager.view(30000, true, null, true)).toMatchObject({ reason: "no-airfield", marginKg: null });
    manager.observe(observation(30100, 969.9, { verticalSpeedMps: -30 }));
    expect(manager.view(30100, true, target, true)).toMatchObject({ reason: "maneuver", returnStatus: "unknown" });
  });
  it("withdraws estimates for missing fuel and reports actual empty fuel distinctly", () => {
    const manager = new FuelManager(catalog);
    learn(manager);
    manager.observe(observation(30100, null));
    expect(manager.view(30100, true, target, true)).toMatchObject({ currentKg: 970, available: false, returnStatus: "unknown" });
    manager.observe(observation(30200, 0));
    expect(manager.view(30200, true, target, true)).toMatchObject({ currentKg: 0, reason: "empty", returnStatus: "danger", remainingMinutes: 0 });
  });
});
