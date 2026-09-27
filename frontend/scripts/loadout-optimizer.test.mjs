import test from "node:test";
import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import loadHighs from "highs";
import {optimizeLoadout} from "../../docs/calculator/loadout-optimizer.mjs";
import {validateLoadout} from "../../docs/calculator/custom-loadouts.mjs";
import {rewardUi} from "../../docs/calculator/model.mjs";

const highs = await loadHighs();
const catalog = JSON.parse(await readFile(new URL("../../docs/api/v1/calculator/index.json", import.meta.url)));
const weaponData = JSON.parse(await readFile(new URL("../../docs/api/v1/calculator/weapons.json", import.meta.url)));
const customData = JSON.parse(await readFile(new URL("../../docs/api/v1/calculator/custom-loadouts.json", import.meta.url)));
const weapons = new Map(weaponData.weapons.map(row => [row.id, row]));
const limits = {maxloadMass: -1, maxloadMassLeftConsoles: -1, maxloadMassRightConsoles: -1, maxDisbalance: -1};
const option = (tier, id, count = 1, extra = {}) => ({key: `${tier}:${id}`, slot: tier, tier, preset: id, weapons: [[id, count]], mass: count,
  cells: [{weapon: id, count, icon: "bombs_small", tier: tier + 1}], requires: [], bans: [], modifications: [], requiredWeapons: [], ...extra});
const run = (definition, weaponMap, mode = "reward", lockedKeys = [], threshold = 100) => optimizeLoadout({definition, presets: [], lockedKeys, weapons: weaponMap, threshold, mode, reward: catalog.reward}, highs);

test("single-zone optimum preserves selected stores and adds required pods under native constraints", () => {
  const a = option(0, "a", 1, {requires: [{slot: 1, preset: "pod"}], mass: 3});
  const pod = option(1, "pod", 0);
  const b = option(2, "b", 1, {mass: 3});
  const c = option(2, "c", 1, {mass: 4});
  const definition = {columns: 3, center: [1], limits: {maxloadMass: 8, maxloadMassLeftConsoles: 4, maxloadMassRightConsoles: 4, maxDisbalance: 1}, options: [a, pod, b, c]};
  const map = new Map([['a', {dmg: 60}], ['b', {dmg: 40}], ['c', {dmg: 65}], ['pod', {dmg: 1}]]);
  const result = run(definition, map, "reward", [a.key]);
  assert.equal(result.status, "optimal");
  assert.equal(result.damage, 100);
  assert.deepEqual(new Set(result.keys), new Set([a.key, pod.key, b.key]));
  assert.equal(validateLoadout(definition, result.keys).valid, true);
  const blocked = {...definition, options: [a, pod, {...b, bans: [{slot: 0, preset: "a"}]}, {...c, mass: 6}]};
  assert.equal(run(blocked, map, "reward", [a.key]).status, "infeasible");
});

test("most zones assigns indivisible bombs: three 80-HP bombs cover one 100-HP zone, not two", () => {
  const definition = {columns: 1, center: [0], limits, options: [option(0, "a", 3)]};
  const result = run(definition, new Map([['a', {dmg: 80}]]), "targets");
  assert.equal(result.status, "optimal");
  assert.equal(result.targets, 1);
  assert.deepEqual(result.plan, [[['a', 2]]]);
  const large = run({...definition, options: [option(0, "big")]}, new Map([['big', {dmg: 250}]]), "targets");
  assert.equal(large.targets, 1);
});

test("mixed per-zone allocation uses every weapon at most as many times as carried", () => {
  const definition = {columns: 2, center: [0, 1], limits, options: [option(0, "a", 3), option(1, "b", 3)]};
  const map = new Map([['a', {dmg: 60}], ['b', {dmg: 40}]]);
  const result = run(definition, map, "targets");
  assert.equal(result.targets, 3);
  for (const row of result.plan) assert.equal(row.reduce((sum, [id, count]) => sum + map.get(id).dmg * count, 0), 100);
});

test("unknown weapon damage is excluded and cannot satisfy a locked requirement", () => {
  const definition = {columns: 1, center: [0], limits, options: [option(0, "unknown")]};
  assert.equal(run(definition, new Map(), "reward", ['0:unknown']).status, "infeasible");
});

test("the real reward-curve upward discontinuity is compared, not incorrectly pruned", () => {
  const definition = {columns: 1, center: [0], limits, options: [option(0, "below"), option(0, "above")]};
  const map = new Map([['below', {dmg: 199000}], ['above', {dmg: 200000}]]);
  const result = run(definition, map, "reward", [], 190000);
  assert.equal(result.damage, 200000);
  assert.ok(result.reward > rewardUi(catalog.reward, 199000));
});

test("fixed-only aircraft choose complete native presets instead of mixing their rows", () => {
  const map = new Map([['a', {dmg: 80, kg: 2}], ['b', {dmg: 60, kg: 1}], ['c', {dmg: 40, kg: 1}]]);
  const presets = [{id: 'three-a', weapons: [['a', 3]], cells: []}, {id: 'two-zones', weapons: [['b', 2], ['c', 2]], cells: []}];
  const result = optimizeLoadout({definition: null, presets, weapons: map, lockedKeys: [], threshold: 100, mode: 'targets', reward: catalog.reward}, highs);
  assert.equal(result.status, 'optimal');
  assert.equal(result.kind, 'preset');
  assert.equal(result.presetId, 'two-zones');
  assert.equal(result.targets, 2);
});

function bruteTargets(items, threshold) {
  const sums = Array(1 << items.length).fill(0), best = Array(sums.length).fill(0);
  for (let mask = 1; mask < sums.length; mask++) {
    for (let bit = 0; bit < items.length; bit++) if (mask & (1 << bit)) sums[mask] += items[bit];
    for (let sub = mask; sub; sub = (sub - 1) & mask) if (sums[sub] >= threshold) best[mask] = Math.max(best[mask], 1 + best[mask ^ sub]);
  }
  return best.at(-1);
}

test("both optimization modes match exhaustive option and bomb-allocation enumeration", () => {
  for (let seed = 1; seed <= 8; seed++) {
    const map = new Map([['a', {dmg: 31 + seed * 3}], ['b', {dmg: 54 + seed * 4}]]);
    const options = Array.from({length: 3}, (_, tier) => [option(tier, "a", 1 + (tier + seed) % 2), option(tier, "b")]).flat();
    const definition = {columns: 3, center: [1], limits, options};
    for (const mode of ["reward", "targets"]) {
      let expected = null;
      for (let encoded = 0; encoded < 27; encoded++) {
        let code = encoded; const selected = [];
        for (let tier = 0; tier < 3; tier++) { const pick = code % 3; code = Math.floor(code / 3); if (pick) selected.push(options[tier * 2 + pick - 1]); }
        const items = selected.flatMap(row => row.weapons.flatMap(([id, count]) => Array(count).fill(map.get(id).dmg)));
        const damage = items.reduce((sum, item) => sum + item, 0);
        const targets = mode === "reward" ? Number(damage >= 100) : bruteTargets(items, 100);
        if (!targets) continue;
        if (!expected || targets > expected.targets || targets === expected.targets && damage < expected.damage) expected = {targets, damage};
      }
      const actual = run(definition, map, mode);
      assert.equal(actual.status, "optimal", `seed ${seed}, ${mode}`);
      assert.deepEqual({targets: actual.targets, damage: actual.damage}, expected, `seed ${seed}, ${mode}`);
    }
  }
});

test("real Typhoon locks survive both modes and every recommended configuration is valid", () => {
  const definition = customData.aircraft.ef_2000_typhoon_aesa;
  for (const mode of ["reward", "targets"]) {
    const result = run(definition, weapons, mode, ["11:mk18_slot11"], 23310);
    assert.ok(["optimal", "feasible"].includes(result.status), JSON.stringify(result));
    assert.ok(result.keys.includes("11:mk18_slot11"));
    assert.equal(validateLoadout(definition, result.keys).valid, true);
    assert.ok(result.plan.every(row => row.reduce((sum, [id, count]) => sum + weapons.get(id).dmg * count, 0) >= 23310 - 1e-8));
    console.log(`Typhoon ${mode}: ${result.status}, ${result.targets} zones, ${result.damage} HP`);
  }
});
