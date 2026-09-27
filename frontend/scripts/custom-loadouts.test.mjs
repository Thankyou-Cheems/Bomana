import assert from "node:assert/strict";
import test from "node:test";
import { combinationTotals, validateLoadout, customPreset } from "../../docs/calculator/custom-loadouts.mjs";
import { readFileSync } from "node:fs";

const weapons = new Map([
  ["a", {kg: 250, dmg: 3000, charge: {mass_kg: 100, strength_equivalent: 1.2}}],
  ["b", {kg: 500, dmg: 5000, charge: {mass_kg: 200, strength_equivalent: 1.5}}],
  ["unknown", {kg: 100, dmg: null, charge: {mass_kg: null, strength_equivalent: null}}],
]);

test("mixed bomb quantities sum TNT and mission HP independently, then count complete sorties", () => {
  assert.deepEqual(combinationTotals([["a", 2], ["b", 3]], weapons, 25900), {
    count: 5, mass: 2000, tnt: 1140, damage: 21000, rounds: 2,
  });
  assert.equal(combinationTotals([["a", 2], ["b", 3]], weapons, 21000).rounds, 1);
});

const option = (key, tier, mass, overrides = {}) => ({key, tier, mass, slot: tier, preset: key,
  requires: [], bans: [], weapons: [["a", 1]], cells: [], ...overrides});
const definition = {columns: 13, center: [6], limits: {maxloadMass: 1600,
  maxloadMassLeftConsoles: 600, maxloadMassRightConsoles: 600, maxDisbalance: 100},
  options: [option("left", 5, 600), option("right", 7, 600), option("center", 6, 400),
    option("over", 7, 601), option("pod", 9, 50),
    option("guided", 5, 50, {requires: [{slot: 9, preset: "pod"}]}),
    option("ban", 5, 50, {bans: [{slot: 9, preset: "pod"}]})]};

test("native wing limits include racks, exclude center from balance, and accept exact boundaries", () => {
  assert.equal(validateLoadout(definition, ["left", "right", "center"]).valid, true);
  const invalid = validateLoadout(definition, ["left", "over", "center"]);
  assert.deepEqual(invalid.errors.map(row => row.code), ["maxloadMass", "maxloadMassRightConsoles"]);
  assert.equal(validateLoadout(definition, ["left"]).errors[0].code, "maxDisbalance");
  const odd = {...definition, center: [], options: [option("middle", 6, 1)]};
  assert.equal(validateLoadout(odd, ["middle"]).right, 1); // Squirrel integer division: 13 / 2 = 6.
});

test("exact slot/preset dependencies, directional bans and tier occupation block invalid saves", () => {
  assert.equal(validateLoadout(definition, ["guided"]).errors[0].required, "pod");
  assert.equal(validateLoadout(definition, ["guided", "pod"]).valid, true);
  assert.equal(validateLoadout(definition, ["pod", "ban"]).errors[0].code, "conflict");
  assert.equal(validateLoadout(definition, ["left", "guided"]).errors[0].code, "occupied");
  assert.equal(customPreset(definition, {id: "user:old", name: "Old", keys: ["removed"]}), null);
  assert.equal(customPreset(definition, {id: "user:1", name: "Mixed", keys: ["left", "right"]}).weapons[0][1], 2);
});

test("order-dependent mixed-store mass cannot falsely pass a native boundary", () => {
  const ranged = {...definition, options: [option("mixed", 5, 150, {massRange: [50, 150]})]};
  const result = validateLoadout(ranged, ["mixed"]);
  assert.equal(result.valid, false);
  assert.match(result.errors[0].message, /跨过.*需在游戏中核对/);
  assert.deepEqual(result.ranges.imbalance, [50, 150]);
  const safe = {...ranged, limits: {...ranged.limits, maxDisbalance: 200}};
  assert.equal(validateLoadout(safe, ["mixed"]).valid, true);
});

test("unresolvable native references stay visible and follow the client's skip behavior", () => {
  const sourceGap = {...definition, options: [option("a", 6, 10, {requires: [{slot: 99, preset: "absent"}]})]};
  const result = validateLoadout(sourceGap, ["a"]);
  assert.equal(result.valid, true);
  assert.match(result.warnings[0], /源数据依赖.*不存在/);
});

test("current native A-10C and MiG-23 require their targeting/data-link pods; Pe-8 cannot customize", () => {
  const data = JSON.parse(readFileSync(new URL("../../docs/api/v1/calculator/custom-loadouts.json", import.meta.url)));
  assert.equal(data.aircraft["pe-8_m82"], undefined);
  for (const [id, pod] of [["a_10c", "sniper_pod"], ["mig_23mld", "delta_ng"]]) {
    const aircraft = data.aircraft[id]; assert.ok(aircraft, id);
    const guided = aircraft.options.find(row => row.requires.some(item => item.preset === pod));
    assert.ok(guided, `${id}: ${pod}`);
    assert.ok(validateLoadout(aircraft, [guided.key]).errors.some(row => row.code === "dependency"));
    const paired = [...new Set([guided.key, ...guided.requires.map(req => aircraft.options.find(row => row.slot === req.slot && row.preset === req.preset).key)])];
    assert.ok(!validateLoadout(aircraft, paired).errors.some(row => row.code === "dependency"));
  }
});

test("zero rows are ignored; unknown inputs never silently become zero damage", () => {
  assert.equal(combinationTotals([["a", 1], ["unknown", 1]], weapons, 1000).damage, null);
  assert.equal(combinationTotals([["a", 1], ["unknown", 1]], weapons, 1000).tnt, null);
  assert.equal(combinationTotals([["a", 1], ["unknown", 0]], weapons, 1000).rounds, 1);
  assert.equal(combinationTotals([["a", 0]], weapons, 1000).rounds, null);
  for (const count of [-1, 1.5, NaN, Infinity, Number.MAX_SAFE_INTEGER + 1]) {
    assert.equal(combinationTotals([["a", count]], weapons, 1000), null);
  }
  assert.equal(combinationTotals([["absent", 1]], weapons, 1000), null);
});
