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
    expect(manager.view(30100, true, target, true)).toMatchObject({ stable: false, source: "learning", rateKgMin: 0, remainingMinutes: null, returnStatus: "unknown" });
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
  it.each([
    [3000, 700, "fuel-jump"], [3000, 980, "refuel"],
    [5000, 700, "fuel-jump"], [5000, 980, "refuel"],
    [12000, 700, "fuel-jump"], [12000, 980, "refuel"],
  ] as const)("clears calibration after a %i ms gap and tank step to %i kg (%s)", (gap, kg, reason) => {
    const manager = new FuelManager(catalog);
    expect(learn(manager).stable).toBe(true);
    manager.observe(observation(30000 + gap, kg));
    expect(manager.view(30000 + gap, true, target, true)).toMatchObject({
      source: "learning", stable: false, rateKgMin: 0, remainingMinutes: null,
      returnStatus: "unknown", economy: null, reason,
    });
  });
  it.each([5000, 12000])("retains a same-condition calibration across an ordinary %i ms sampling gap", gap => {
    const manager = new FuelManager(catalog);
    expect(learn(manager).stable).toBe(true);
    manager.observe(observation(30000 + gap, 970 - gap / 1000));
    expect(manager.view(30000 + gap, true, target, true)).toMatchObject({
      source: "aircraft-estimate", stable: false, rateKgMin: 60, returnStatus: "unknown",
    });
  });
  it("clears calibration when a sampling outage exceeds twelve seconds", () => {
    const manager = new FuelManager(catalog);
    expect(learn(manager).stable).toBe(true);
    manager.observe(observation(42100, 957.9));
    expect(manager.view(42100, true, target, true)).toMatchObject({
      source: "learning", stable: false, rateKgMin: 0, remainingMinutes: null, returnStatus: "unknown",
    });
  });
  it.each([
    [null, 700], [null, 980], [NaN, 700], [NaN, 980], [-1, 700], [-1, 980],
  ])("clears calibration when invalid fuel %s precedes a tank step to %i kg", (invalid, kg) => {
    const manager = new FuelManager(catalog);
    expect(learn(manager).stable).toBe(true);
    manager.observe(observation(31000, invalid));
    expect(manager.view(31000, true, target, true)).toMatchObject({ available: false, remainingMinutes: null });
    manager.observe(observation(32000, kg));
    expect(manager.view(32000, true, target, true)).toMatchObject({
      source: "learning", stable: false, rateKgMin: 0, remainingMinutes: null,
      returnStatus: "unknown", economy: null,
    });
  });
  it("requires measurable consumption even for a known aircraft and ignores duplicate source timestamps", () => {
    const manager = new FuelManager(catalog);
    const fuel = learn(manager, 0, 30000, 1000, 0);
    expect(fuel).toMatchObject({ stable: false, returnStatus: "unknown", source: "learning", remainingMinutes: null });
    manager.observe(observation(30000, 0));
    manager.observe(observation(30000, 0, { aircraft: "prop" }));
    expect(manager.view(30000, true, target, true).currentKg).toBe(1000);
    expect(manager.view(33100, true, target, true)).toMatchObject({ available: false, source: "unavailable", returnStatus: "unknown" });
  });
  it("can resolve a low-consumption propeller aircraft without certifying quantization plateaus", () => {
    const manager = new FuelManager();
    const fuel = learn(manager, 0, 45000, 100, .01, { aircraft: "prop", initialKg: 150 });
    expect(fuel.stable).toBe(true);
    expect(fuel.rateKgMin).toBeCloseTo(.6);
  });
  it("resolves fine low loss without a capacity-based dead zone", () => {
    const fuel = learn(new FuelManager(), 0, 45000, 100, .001, { aircraft: "prop", initialKg: 150 });
    expect(fuel.source).toBe("measured");
    expect(fuel.rateKgMin).toBeCloseTo(.06);
    expect(fuel.remainingMinutes).toBeCloseTo(99.955 / .06);
  });
  it("converges across coarse low-burn steps without calling a plateau zero", () => {
    const manager = new FuelManager();
    for (let at = 0; at <= 120000; at += 1000) manager.observe(observation(at, Math.round((100 - at / 1000000) * 10) / 10));
    const provisional = manager.view(120000, true, target, true);
    expect(provisional.source).toBe("measured");
    expect(provisional.stable).toBe(false);
    expect(provisional.remainingMinutes).toBeGreaterThan(0);
    expect(provisional.returnStatus).toBe("unknown");
    const flat = learn(new FuelManager(), 0, 180000, 100, 0);
    expect(flat.remainingMinutes).toBeNull();
    expect(flat.flowState).toBe("unresolved");
  });
  it("keeps formatted decimal integer steps provisional until several losses are resolved", () => {
    const manager = new FuelManager();
    for (let at = 0; at <= 120000; at += 1000) {
      const kg = JSON.parse((Math.round(1000 - at / 100000) + .000001).toFixed(6));
      manager.observe(observation(at, kg));
    }
    expect(manager.view(120000, true, target, true)).toMatchObject({ source: "measured", stable: false, returnStatus: "unknown" });
    for (let at = 121000; at <= 180000; at += 1000) manager.observe(observation(at, Math.round(1000 - at / 100000) + .000001));
    expect(manager.view(180000, true, target, true).stable).toBe(false);
  });
  it.each([200, 1000])("uses actual elapsed time at %i ms cadence with duplicates, jitter and short gaps", (cadence) => {
    const manager = new FuelManager();
    for (let at = 0; at <= 40000; at += cadence) {
      if (at > 10000 && at < 12000) continue;
      const time = at + (at % 3) * 17;
      manager.observe(observation(time, 1000 - time / 1000));
      manager.observe(observation(time, 0));
    }
    const fuel = manager.view(40050, true, target, true);
    expect(fuel.rateKgMin).toBeCloseTo(60);
    expect(fuel.stable).toBe(true);
    expect(fuel.currentKg).toBeGreaterThan(959);
  });
  it("tracks unreported increases and decreases in loss promptly without changing throttle", () => {
    const manager = new FuelManager();
    learn(manager);
    const high = learn(manager, 30100, 41100, 969.7, 3);
    expect(high.rateKgMin).toBeCloseTo(180);
    const low = learn(manager, 41200, 53200, high.currentKg - .03, .3);
    expect(low.rateKgMin).toBeCloseTo(18);
  });
  it("withdraws a multi-engine fit when one engine stops and never infers infinite endurance", () => {
    const manager = new FuelManager();
    const twin = { engines: [{ throttlePercent: 90, thrustKgf: 3600, powerHp: null }, { throttlePercent: 90, thrustKgf: 3600, powerHp: null }] };
    learn(manager, 0, 30000, 1000, 2, twin);
    const one = { engines: [twin.engines[0]!, { throttlePercent: 90, thrustKgf: 0, powerHp: null }] };
    manager.observe(observation(30100, 939.9, one));
    expect(manager.view(30100, true, target, true)).toMatchObject({ stable: false, remainingMinutes: null });
    expect(learn(manager, 30200, 40200, 939.8, 1, one).rateKgMin).toBeCloseTo(60);
    const off = { engines: one.engines.map(() => ({ throttlePercent: 0, thrustKgf: 0, powerHp: null })) };
    expect(learn(manager, 40300, 80300, 929.8, 0, off)).toMatchObject({ flowState: "output-zero", remainingMinutes: null, returnStatus: "unknown" });
    const idle = { engines: [{ throttlePercent: 0, thrustKgf: 30, powerHp: null }] };
    expect(learn(manager, 80400, 110400, 929.8, .01, idle)).toMatchObject({ stable: true, flowState: "consuming", reason: "maneuver", returnStatus: "unknown" });
  });
  it("excludes a tank-drop step but measures continuous large losses such as dumping", () => {
    const manager = new FuelManager();
    learn(manager, 0, 30000, 5000, 1, { initialKg: 6000 });
    for (let at = 31000; at <= 41000; at += 1000) manager.observe(observation(at, 4970 - (at - 30000) / 1000 * 200, { initialKg: 6000 }));
    const dumping = manager.view(41000, true, target, true);
    expect(dumping.rateKgMin).toBeCloseTo(12000);
    expect(dumping.remainingMinutes).toBeLessThan(1);
    expect(dumping.returnStatus).toBe("danger");
    manager.observe(observation(42000, 1500, { initialKg: 6000 }));
    expect(manager.view(42000, true, target, true)).toMatchObject({ stable: false, reason: "fuel-jump" });
    expect(learn(manager, 42100, 52100, 1499.9, 1, { initialKg: 6000 }).rateKgMin).toBeCloseTo(60);
  });
  it("clears bad and stale data, resets after suspension, and conserves kg/min and seconds", () => {
    const manager = new FuelManager(catalog);
    const fuel = learn(manager, 0, 30000, 150, 1);
    expect(fuel.currentKg).toBe(120);
    expect(fuel.remainingMinutes! * 60).toBeCloseTo(120);
    manager.observe(observation(30100, NaN));
    expect(manager.view(30100, true, target, true)).toMatchObject({ available: false, remainingMinutes: null, flowState: "unavailable" });
    manager.observe(observation(60000, 119));
    expect(manager.view(60000, true, target, true)).toMatchObject({ stable: false, remainingMinutes: null });
    expect(manager.view(64000, true, target, true)).toMatchObject({ source: "unavailable" });
    const empty = learn(new FuelManager(), 0, 6000, 6, 1);
    expect(empty.remainingMinutes).toBe(0);
    expect(empty.returnStatus).toBe("danger");
  });
  it("restarts after a small refuel on a low-capacity aircraft", () => {
    const manager = new FuelManager();
    const prior = learn(manager, 0, 30000, .5, .001, { initialKg: 1 });
    expect(prior.stable).toBe(true);
    manager.observe(observation(30100, .57, { initialKg: 1 }));
    expect(manager.view(30100, true, target, true)).toMatchObject({ stable: false, reason: "refuel", remainingMinutes: null });
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
