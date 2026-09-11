import assert from "node:assert/strict";
import test from "node:test";
import {
  compareLoadouts,
  airportRepairVisit,
  airportPaletteBands,
  airportBarPositions,
  equivalentWeaponCount,
  explosiveConversion,
  durabilityBrBuckets,
  requiredCount,
  rewardUi,
  returnFuelPlan,
  sharedParameterSource,
  sortiePlan,
  usefulActionsReference,
  usefulActionsPlan,
  usefulActionsObservedFraction,
  usefulActionsCardRate,
  usefulActionsCurve,
} from "../../docs/calculator/model.mjs";

const airportNativeReference = { client_version: "2.57.1.135", pe_sha256: "0".repeat(64),
  hp_condition: "truncate_percent_to_integer", palette_selection: "first_key_greater_or_equal", server_recovery: "unknown" };

test("airport mission repair skips both dwelling boundaries and uses same HP for every module", () => {
  const input = { rule: { model: "integer_percent_dwelling/v1", hp_offset: 1, maximum_slowdown: 10,
    timing: "per_airfield_repair_visit", evidence: "client_mission_branch_not_server_prediction", native_reference: airportNativeReference },
    tier: { auxiliary_module_mission_hp: 160000, repair_base_hp: 4000 } };
  assert.equal(airportRepairVisit({ ...input, dwellingPercent: 100 }).gain, 0);
  assert.equal(airportRepairVisit({ ...input, dwellingPercent: 0 }).gain, 0);
  assert.equal(airportRepairVisit({ ...input, dwellingPercent: .9 }).gain, 0);
  assert.equal(airportRepairVisit({ ...input, dwellingPercent: .9 }).state, "below_threshold");
  assert.equal(airportRepairVisit({ ...input, dwellingPercent: 1 }).gain, 400);
  assert.equal(airportRepairVisit({ ...input, dwellingPercent: 50 }).gain, 2000.025);
  assert.ok(airportRepairVisit({ ...input, dwellingPercent: 99.999 }).gain > 3999);
  for (const dwellingPercent of [-1, 101, NaN, Infinity, null]) assert.equal(airportRepairVisit({ ...input, dwellingPercent }), null);
  assert.equal(airportRepairVisit({ ...input, rule: null, dwellingPercent: 50 }), null);
  assert.equal(airportRepairVisit({ ...input, rule: { ...input.rule, timing: "changed" }, dwellingPercent: 50 }), null);
  assert.equal(airportRepairVisit({ ...input, rule: { ...input.rule, native_reference: { ...airportNativeReference, client_version: null } }, dwellingPercent: 50 }), null);
});

test("airport bars follow directed endpoints and perpendicular sides, without a team flip", () => {
  const display = { orientation: "runway_endpoint_relative", native_reference: airportNativeReference, modules: [
    { module: "airfield", position: [.5,.5] }, { module: "storage", position: [.5,-.5] },
    { module: "parking", position: [-.5,-.5] }, { module: "dwelling", position: [-.5,.5] },
  ] };
  const rightward = airportBarPositions(display, 0);
  assert.deepEqual(rightward.map(row => [row.x, row.y]), [[1,.6],[1,-.6],[-1,-.6],[-1,.6]]);
  const reversed = airportBarPositions(display, 180);
  rightward.forEach((row, index) => {
    assert.ok(Math.abs(row.x + reversed[index].x) < 1e-12);
    assert.ok(Math.abs(row.y + reversed[index].y) < 1e-12);
  });
  display.modules[0].position[0] = -.5;
  assert.equal(airportBarPositions(display, 0)[0].x, -1, "consume updated HUD positions");
  assert.equal(airportBarPositions(null, 0), null);
});

test("airport color legend uses the generated palette instead of historical 30/70", () => {
  const display = { palette: [[0,0,0,0], [255,70,70,.25], [255,255,70,.75], [70,255,70,1]],
    native_reference: airportNativeReference };
  assert.deepEqual(airportPaletteBands(display).map(row => row.upper), [0,25,75,100]);
  display.palette[1][3] = .2;
  assert.equal(airportPaletteBands(display)[1].upper, 20);
  assert.equal(airportPaletteBands(null), null);
  display.palette[2][3] = .1;
  assert.equal(airportPaletteBands(display), null);
});

test("client card restores the premium visual split and adds account/booster effects", () => {
  const inputs = { rawRate: 3260, special: true, premiumAccount: false, boosterPercent: 0,
    premiumMultiplier: 1.5, premiumVisualPart: .5 };
  assert.equal(usefulActionsCardRate(inputs).rate, 3260);
  assert.equal(usefulActionsCardRate({ ...inputs, premiumAccount: true }).rate, 4890);
  assert.equal(usefulActionsCardRate({ ...inputs, premiumAccount: true, boosterPercent: 100 }).rate, 8150);
  assert.equal(usefulActionsCardRate({ ...inputs, special: false, rawRate: 1730, premiumAccount: true }).rate, 2595);
  for (const field of ["rawRate", "boosterPercent", "premiumMultiplier", "premiumVisualPart"]) {
    for (const value of [null, NaN, Infinity, -1, true]) assert.equal(usefulActionsCardRate({ ...inputs, [field]: value }), null);
  }
  assert.equal(usefulActionsCardRate({ ...inputs, premiumVisualPart: 1 }), null);
  assert.equal(usefulActionsCardRate({ ...inputs, rawRate: 1e308, boosterPercent: 1e308 }), null);
});

test("Useful Actions keeps historical score observations within their actual scope", () => {
  assert.deepEqual(usefulActionsReference({ mode: "air_sim", score: 600, minutes: 15 }), { fraction: .86, basis: "before_landing_split" });
  assert.ok(Math.abs(usefulActionsReference({ mode: "air_sim", score: 500, minutes: 15 }).fraction - .805) < 1e-12);
  for (const score of [0, 199, 1051, Infinity, NaN, null]) assert.equal(usefulActionsReference({ mode: "air_sim", score, minutes: 15 }), null);
  assert.equal(usefulActionsReference({ mode: "air_sim", score: 600, minutes: 7.5 }), null);
  assert.equal(usefulActionsReference({ mode: "heli_pve", score: 600, minutes: 10, vehicleId: "ka_50" }), null);
  assert.equal(usefulActionsReference({ mode: "heli_pve", score: 600, minutes: 15, vehicleId: "ka_52" }), null);
});

test("Air SB splits supplied SL and independent RP fractions without inventing RP/min", () => {
  const input = { periodMinutes: 15, minutes: 15, score: 600, slRate: 1730, fraction: .86, basis: "before_landing_split", immediateShare: .8 };
  const plan = usefulActionsPlan(input);
  assert.ok(Math.abs(plan.slImmediate - 17853.6) < 1e-9);
  assert.ok(Math.abs(plan.slDeferred - 4463.4) < 1e-9);
  assert.equal(plan.scorePerMinute, 40);
  assert.equal(plan.rpImmediate, null);
  assert.equal(usefulActionsPlan({ ...input, rpRate: 100 }).rpImmediate, null);
  assert.equal(usefulActionsPlan({ ...input, rpRate: 100, rpFraction: .5 }).rpImmediate, 600);
  assert.equal(usefulActionsPlan({ ...input, fraction: 0 }).slImmediate, 0);
  // An observed record does not create a constant exchange rate per point.
  assert.equal(usefulActionsPlan({ ...input, score: 1200 }).slImmediate, plan.slImmediate);
});

test("reward charts share payout arithmetic and leave unsupported scores or aircraft unknown", () => {
  const input = { mode: "air_sim", vehicleId: "f_15e", periodMinutes: 15, minutes: 15, slRate: 1730, immediateShare: .8, score: 500 };
  const curve = usefulActionsCurve(input);
  assert.deepEqual(curve.points.map(point => point.score), [200, 400, 600, 800, 1050]);
  assert.ok(Math.abs(curve.current.immediate - 1730 * 15 * .805 * .8) < 1e-9);
  assert.ok(Math.abs(curve.current.total - 1730 * 15 * .805) < 1e-9);
  assert.equal(curve.hasLanding, true);
  assert.equal(usefulActionsCurve({ ...input, score: 1500 }).current, null);
  assert.equal(usefulActionsCurve({ ...input, score: 0 }).current, null);
  assert.equal(usefulActionsCurve({ ...input, minutes: 7.5 }), null);
  assert.equal(usefulActionsCurve({ ...input, slRate: NaN }), null);
  assert.equal(usefulActionsCurve({ ...input, slRate: 1e308 }), null);
  const helicopter = { ...input, mode: "heli_pve", vehicleId: "ka_52", periodMinutes: 10, minutes: 10, slRate: 1660, score: 600 };
  assert.equal(usefulActionsCurve(helicopter).hasLanding, false);
  assert.equal(usefulActionsCurve(helicopter).current.total, usefulActionsCurve(helicopter).current.immediate);
  assert.ok(Math.abs(usefulActionsCurve(helicopter).current.immediate - 11586) < 1e-9);
  assert.equal(usefulActionsCurve({ ...helicopter, vehicleId: "ka_50" }), null);
});

test("Helicopter measurements already include the immediate share and never get Air SB's 20% deduction", () => {
  const reference = usefulActionsReference({ mode: "heli_pve", score: 600, minutes: 10, vehicleId: "ka_52" });
  const plan = usefulActionsPlan({ periodMinutes: 10, minutes: 10, score: 600, slRate: 1660, ...reference, immediateShare: null });
  assert.ok(Math.abs(plan.slImmediate - 11586) < 1e-9);
  assert.equal(plan.slDeferred, null);
  assert.equal(plan.rpImmediate, null);
});

test("Useful Actions missing or invalid inputs do not become a payable reward", () => {
  const input = { periodMinutes: 15, minutes: 15, score: 600, slRate: 1000, fraction: .8, basis: "before_landing_split", immediateShare: .8 };
  for (const field of ["periodMinutes", "minutes", "score", "slRate", "fraction", "immediateShare"]) {
    for (const value of [null, NaN, Infinity, -1, true]) assert.equal(usefulActionsPlan({ ...input, [field]: value }), null, `${field}=${value}`);
  }
  assert.equal(usefulActionsPlan({ ...input, minutes: 16 }), null);
  assert.equal(usefulActionsPlan({ ...input, fraction: 1.01 }), null);
  assert.equal(usefulActionsPlan({ ...input, slRate: 1e308 }), null);
  assert.equal(usefulActionsPlan({ ...input, rpRate: NaN }), null);
});

test("observed SL inverts the selected payment basis but does not clamp contradictory records", () => {
  assert.ok(Math.abs(usefulActionsObservedFraction({ slReceived: 9600, slRate: 1000, minutes: 15, immediateShare: .8 }) - .8) < 1e-12);
  assert.equal(usefulActionsObservedFraction({ slReceived: 7000, slRate: 1000, minutes: 10, immediateShare: 1 }), .7);
  assert.ok(usefulActionsObservedFraction({ slReceived: 20000, slRate: 1000, minutes: 15, immediateShare: .8 }) > 1);
  assert.equal(usefulActionsObservedFraction({ slReceived: 0, slRate: 1000, minutes: 15, immediateShare: .8 }), 0);
  assert.equal(usefulActionsObservedFraction({ slReceived: null, slRate: 1000, minutes: 15, immediateShare: .8 }), null);
});

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
});

test("whole counts preserve decimal products and real above-integer inputs", () => {
  for (const excess of [Number.EPSILON, 2 * Number.EPSILON, 3 * Number.EPSILON, 1e-10]) {
    const result = equivalentWeaponCount({ sourcePerItem: 1 + excess, targetPerItem: 1, sourceCount: 1 });
    assert.equal(result.wholeCount, 2);
    assert.equal(result.targetTotal, 2);
    assert.ok(result.surplus > .99);
  }
  const decimal = { sourceMassKg: .1, sourceFactor: 3, sourceCount: 1, targetMassKg: .3, targetFactor: 1 };
  assert.equal(explosiveConversion(decimal).wholeCount, 1);
  assert.equal(explosiveConversion({ ...decimal, sourceMassKg: .10000000000000002 }).wholeCount, 2);
  assert.equal(explosiveConversion({ ...decimal, sourceMassKg: 1e-20, targetMassKg: 3e-20 }).wholeCount, 1);
  assert.equal(equivalentWeaponCount({ sourcePerItem: Number.MIN_VALUE, targetPerItem: Number.MIN_VALUE, sourceCount: 1 }).wholeCount, 1);
  assert.equal(equivalentWeaponCount({ sourcePerItem: .1 + .2, targetPerItem: .3, sourceCount: 1 }).wholeCount, 2);
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
