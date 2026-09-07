import assert from "node:assert/strict";
import test from "node:test";
import {
  compareLoadouts,
  equivalentWeaponCount,
  explosiveConversion,
  durabilityBrBuckets,
  requiredCount,
  rewardUi,
  returnFuelPlan,
  sharedParameterSource,
  sortiePlan,
} from "../../docs/calculator/model.mjs";

test("converts actual filler and TNT strength without confusing weapon mass or mission damage", () => {
  const inputs = { sourceMassKg: 100, sourceFactor: 1.5, sourceCount: 2, targetMassKg: 50, targetFactor: 1 };
  assert.deepEqual(explosiveConversion(inputs), { sourceTntKg: 150, targetTntKg: 50, sourceTotal: 300, exactCount: 6, wholeCount: 6, targetTotal: 300, surplus: 0 });
  const partial = explosiveConversion({ ...inputs, targetMassKg: 80 });
  assert.equal(partial.exactCount, 3.75);
  assert.equal(partial.wholeCount, 4);
  assert.equal(partial.surplus, 20);
  assert.equal(equivalentWeaponCount({ sourcePerItem: 200, targetPerItem: 80, sourceCount: 2 }).wholeCount, 5);
  assert.equal(explosiveConversion({ ...inputs, sourceCount: 0 }).wholeCount, 0);
});

test("conversion rejects missing, negative, non-finite and unsafe input without masking it", () => {
  const inputs = { sourceMassKg: 100, sourceFactor: 1.5, sourceCount: 2, targetMassKg: 50, targetFactor: 1 };
  for (const field of Object.keys(inputs)) {
    for (const value of [null, undefined, NaN, Infinity, -1, true]) assert.equal(explosiveConversion({ ...inputs, [field]: value }), null, `${field}: ${value}`);
  }
  for (const field of ["sourceMassKg", "sourceFactor", "targetMassKg", "targetFactor"]) assert.equal(explosiveConversion({ ...inputs, [field]: 0 }), null);
  assert.equal(explosiveConversion({ ...inputs, sourceCount: .5 }), null);
  assert.equal(explosiveConversion({ ...inputs, sourceFactor: 1e308 }), null);
  assert.equal(explosiveConversion({ ...inputs, targetMassKg: 1e-300 }), null);
  assert.equal(equivalentWeaponCount({ sourcePerItem: .1 + .2, targetPerItem: .3, sourceCount: 1 }).wholeCount, 1);
  assert.equal(equivalentWeaponCount({ sourcePerItem: 1 + 1e-10, targetPerItem: 1, sourceCount: 1 }).wholeCount, 2);
});

const reward = Object.freeze({
  preset_dmg_min: 18_000,
  preset_dmg_max: 97_500,
  bombing_reward_modifier: 2,
  ui_decoration: 10,
  piecewise_linear: [[200_000, .3], [1_200_000, .17], [50_000_000, .017]],
});

test("compares independent loadouts without inventing unknown damage or partial targets", () => {
  const rows = compareLoadouts({
    aircraft: { w: ["small", "large", "unknown"], n: [10, 2, 100] }, hp: 100,
    weapons: [{ id: "small", dmg: 30, kg: 20 }, { id: "large", dmg: 60, kg: 50 }, { id: "unknown", dmg: null }],
  });
  assert.deepEqual(rows.map(({ weapon, required, capacity, targetsPerLoad, remaining, massKg }) =>
    [weapon.id, required, capacity, targetsPerLoad, remaining, massKg]),
  [["small", 4, 10, 2, 2, 80], ["large", 2, 2, 1, 0, 100]]);
  assert.equal(compareLoadouts({ aircraft: null, weapons: [], hp: 100 }).length, 0);
  assert.equal(requiredCount(100, Infinity), null);
});

test("return plan separates route allowance, reserve and measured fuel margin", () => {
  const inputs = { fuelKg: 1000, burnKgMin: 60, groundSpeedKmh: 720, distanceKm: 36, routePercent: 20, reserveMin: 5 };
  const plan = returnFuelPlan(inputs);
  assert.ok(Math.abs(plan.tripMin - 3.6) < 1e-12);
  assert.ok(Math.abs(plan.requiredKg - 516) < 1e-9);
  assert.ok(Math.abs(plan.marginKg - 484) < 1e-9);
  assert.equal(returnFuelPlan({ ...inputs, fuelKg: null }).marginKg, null);
  assert.ok(returnFuelPlan({ ...inputs, fuelKg: 100 }).marginKg < 0);
  assert.equal(returnFuelPlan({ ...inputs, distanceKm: 0 }).requiredKg, 300);
  for (const key of ["burnKgMin", "groundSpeedKmh", "distanceKm", "routePercent", "reserveMin"]) {
    assert.equal(returnFuelPlan({ ...inputs, [key]: null }), null, key);
    assert.equal(returnFuelPlan({ ...inputs, [key]: -1 }), null, key);
  }
  assert.equal(returnFuelPlan({ ...inputs, groundSpeedKmh: 0 }), null);
  assert.equal(returnFuelPlan({ ...inputs, fuelKg: NaN }), null);
});

test("calculator rejects independently updated API sources before displaying results", () => {
  const source = { kind: "local-client", version: "2.57.1.132", archives: [{ name: "aces", sha256: "aaa" }] };
  assert.equal(sharedParameterSource([{ source }, { source: { ...source, version: "2.57.1.133" } }]), null);
  assert.equal(sharedParameterSource([{ source }, {}]), null);
  assert.equal(sharedParameterSource([{ source }, { source: { ...source, archives: [{ name: "aces", sha256: "bbb" }] } }]), null);
  assert.deepEqual(sharedParameterSource([{ source }, { source: { archives: source.archives, version: source.version, kind: source.kind } }]), source);
});

test("plans sorties from the selected aircraft weapon limit", () => {
  const plan = sortiePlan({ required: 26, capacity: 7, damage: 10_982.625, reward });
  assert.deepEqual(plan && {
    capacity: plan.capacity,
    sorties: plan.sorties,
    lastSortieCount: plan.lastSortieCount,
  }, { capacity: 7, sorties: 4, lastSortieCount: 5 });
  assert.equal(plan?.fullLoadDamage, 76_878.375);
  assert.equal(plan?.fullLoadReward, rewardUi(reward, 76_878.375));
});

test("keeps target quantity separate from full-load reward", () => {
  const required = requiredCount(25_900, 10_982.625);
  assert.equal(required, 3);
  const plan = sortiePlan({ required, capacity: 7, damage: 10_982.625, reward });
  assert.equal(plan?.sorties, 1);
  assert.equal(plan?.fullLoadDamage, 7 * 10_982.625);
});

test("rejects an unknown aircraft limit instead of inventing sorties", () => {
  assert.equal(sortiePlan({ required: 6, capacity: 0, damage: 4_720.376, reward }), null);
});

test("collapses BR choices into durability ranges and clips the final open tier", () => {
  const brValues = ["1.0", "1.3", "1.7", "2.0", "2.3", "2.7", "3.0", "3.3", "3.7", "4.0"];
  const tiers = [
    { balance_level: [0, 3], hp: 4_000 },
    { balance_level: [4, 7], hp: 6_000 },
    { balance_level: [8, 50], hp: 10_000 },
  ];
  const buckets = durabilityBrBuckets(brValues, tiers);
  assert.deepEqual(
    buckets.map(({ minBr, maxBr, value }) => ({ minBr, maxBr, value })),
    [
      { minBr: "1.0", maxBr: "2.0", value: "2.0" },
      { minBr: "2.3", maxBr: "3.3", value: "3.3" },
      { minBr: "3.7", maxBr: "4.0", value: "4.0" },
    ],
  );
});
