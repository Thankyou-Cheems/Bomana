import { rewardUi, requiredCount } from "./model.mjs";
import { validateLoadout, previewCustomPreset } from "./custom-loadouts.mjs";
import { presetTotals } from "./loadouts.mjs";

// All decisions are whole options / whole projectiles. Damage is never rounded
// to integer HP or converted through TNT. The original validator checks the
// returned option set independently of the optimization model.
const expression = terms => terms.filter(([, value]) => value !== 0).map(([name, value]) => `${value < 0 ? "-" : "+"} ${Math.abs(value)} ${name}`).join(" ") || "0 zero";
const damageOf = (items, weapons) => items.reduce((sum, [id, count]) => weapons.get(id)?.dmg > 0 ? sum + weapons.get(id).dmg * count : NaN, 0);

function supportedReward(reward) {
  const {preset_dmg_min: min, preset_dmg_max: max, bombing_reward_modifier: modifier, piecewise_linear: points} = reward;
  // Below the first knot the formula is a + b / damage. Above it the
  // supplied piecewise curve must also decrease. Its first-knot jump is
  // handled separately below when comparing the two decreasing regions.
  const b = min * (1 - (modifier - 1) * min / (max - min));
  return max > min && b >= 0 && points.every((point, i) => i === 0 || point[0] > points[i - 1][0] && point[1] <= points[i - 1][1]);
}

function prepare({definition, presets, lockedKeys, weapons, threshold}) {
  const custom = Boolean(definition);
  const source = custom ? definition.options : presets.filter(preset => !preset.customName);
  const options = source.map((option, i) => ({...option, variable: `x${i}`, damage: damageOf(option.weapons, weapons)}));
  const constraints = [], bounds = ["zero = 0"], binaries = options.map(option => option.variable);
  const add = (terms, relation, value) => constraints.push(`${expression(terms)} ${relation} ${value}`);
  let unknown = false;
  for (const option of options) if (!Number.isFinite(option.damage)) { bounds.push(`${option.variable} = 0`); unknown = true; option.damage = 0; }
  const damage = options.map(option => [option.variable, option.damage]);
  let mass;
  if (custom) {
    const byKey = new Map(options.map(option => [option.key, option]));
    const hasLimits = Object.values(definition.limits).some(limit => limit >= 0);
    for (const field of ["tier", "slot"]) for (const value of new Set(options.map(option => option[field]))) {
      add(options.filter(option => option[field] === value).map(option => [option.variable, 1]), "<=", 1);
    }
    for (const option of options) {
      for (const dependency of option.requires) {
        const required = options.find(other => other.slot === dependency.slot && other.preset === dependency.preset);
        if (required) add([[option.variable, 1], [required.variable, -1]], "<=", 0);
      }
      for (const conflict of option.bans) {
        const banned = options.find(other => other.slot === conflict.slot && other.preset === conflict.preset);
        if (banned) add([[option.variable, 1], [banned.variable, 1]], "<=", 1);
      }
    }
    for (const key of lockedKeys) {
      if (!byKey.has(key)) return {error: "locked_unknown"};
      bounds.push(`${byKey.get(key).variable} = 1`);
    }
    const side = option => definition.center.includes(option.tier) ? 0 : option.tier < Math.floor(definition.columns / 2) ? -1 : 1;
    mass = options.map(option => [option.variable, option.mass]);
    if (hasLimits) {
      add(mass, "<=", definition.limits.maxloadMass);
      for (const [direction, field] of [[-1, "maxloadMassLeftConsoles"], [1, "maxloadMassRightConsoles"]]) {
        add(options.filter(option => side(option) === direction).map(option => [option.variable, option.mass]), "<=", definition.limits[field]);
        add(options.filter(option => side(option)).map(option => [option.variable, side(option) === direction ? option.mass : -(option.massRange?.[0] ?? option.mass)]), "<=", definition.limits.maxDisbalance);
      }
    }
  } else {
    add(options.map(option => [option.variable, 1]), "=", 1);
    mass = options.map(option => [option.variable, presetTotals(option, weapons).mass || 0]);
  }
  const supplies = new Map();
  for (const option of options) for (const [id, count] of option.weapons) if (weapons.get(id)?.dmg > 0) {
    if (!supplies.has(id)) supplies.set(id, []);
    supplies.get(id).push([option.variable, count]);
  }
  // Clip each projectile at one target's HP: a single oversized bomb cannot
  // be credited as destroying several geographically separate targets.
  const effective = options.map(option => [option.variable, option.weapons.reduce((sum, [id, count]) => sum + Math.min(weapons.get(id)?.dmg || 0, threshold) * count / threshold, 0)]);
  return {options, constraints, bounds, binaries, damage, mass, supplies, effective, unknown, custom, add};
}

export function optimizeLoadout(input, highs, {timeLimit = 20} = {}) {
  const {definition, weapons, threshold, mode, reward} = input;
  if (!(threshold > 0) || !supportedReward(reward)) return {status: "unsupported"};
  const model = prepare(input);
  if (model.error) return {status: "infeasible", reason: model.error};
  const deadline = performance.now() + timeLimit * 1000;
  let complete = true;
  function solve(objective, direction, targets = 0, extra = []) {
    const constraints = [...model.constraints, ...extra], bounds = [...model.bounds], integers = [];
    const allocation = [];
    if (targets === 1) constraints.push(`${expression(model.damage)} >= ${threshold}`);
    if (targets > 1) {
      for (let t = 0; t < targets; t++) {
        const row = [];
        for (const [w, [id]] of [...model.supplies].entries()) {
          const variable = `a${t}_${w}`;
          integers.push(variable); row.push([variable, weapons.get(id).dmg / threshold]);
          allocation.push({variable, target: t, id});
        }
        constraints.push(`${expression(row)} >= 1`);
        if (t > 0) constraints.push(`${expression([...row, ...row.map(([name, value]) => [name.replace(`a${t}_`, `a${t - 1}_`), -value])])} <= 0`);
      }
      for (const [id, supply] of model.supplies) constraints.push(`${expression([...allocation.filter(row => row.id === id).map(row => [row.variable, 1]), ...supply.map(([name, count]) => [name, -count])])} <= 0`);
    }
    const lp = `${direction}\n obj: ${expression(objective)}\nSubject To\n${constraints.map((row, i) => ` c${i}: ${row}`).join("\n")}\nBounds\n${bounds.join("\n")}\nBinaries\n${model.binaries.join(" ")}\n${integers.length ? `Generals\n${integers.join(" ")}\n` : ""}End`;
    const result = highs.solve(lp, {output_flag: false, time_limit: Math.max(.01, (deadline - performance.now()) / 1000), mip_rel_gap: 0, mip_abs_gap: 0, mip_feasibility_tolerance: 1e-9});
    if (result.Status !== "Optimal" && result.Status !== "Infeasible") complete = false;
    if (!result.Columns) return {status: result.Status};
    const value = name => result.Columns[name]?.Primal || 0;
    const chosen = model.options.filter(option => value(option.variable) > .5);
    const keys = chosen.map(option => option.key);
    if (!chosen.length || input.lockedKeys.some(key => !keys.includes(key))) return {status: result.Status};
    const validation = definition ? validateLoadout(definition, keys) : null;
    if (validation && !validation.valid) { complete = false; return {status: "Invalid solution"}; }
    const items = new Map();
    for (const option of chosen) for (const [id, count] of option.weapons) items.set(id, (items.get(id) || 0) + count);
    const damage = damageOf([...items], weapons);
    if (!(damage > 0)) return {status: result.Status};
    const plan = Array.from({length: targets}, () => []);
    const used = new Map();
    for (const row of allocation) {
      const count = Math.round(value(row.variable));
      if (count < 0 || Math.abs(count - value(row.variable)) > 1e-6) { complete = false; return {status: "Invalid solution"}; }
      if (count) { plan[row.target].push([row.id, count]); used.set(row.id, (used.get(row.id) || 0) + count); }
    }
    if (targets === 1) {
      let remaining = threshold;
      for (const [id, count] of [...items].sort(([a], [b]) => weapons.get(b).dmg - weapons.get(a).dmg)) {
        if (remaining <= 0) break;
        const amount = Math.min(count, requiredCount(remaining, weapons.get(id).dmg));
        plan[0].push([id, amount]); remaining -= amount * weapons.get(id).dmg;
      }
    }
    if ([...used].some(([id, count]) => count > (items.get(id) || 0)) || plan.some(row => requiredCount(threshold, damageOf(row, weapons)) !== 1)) { complete = false; return {status: "Invalid solution"}; }
    return {status: result.Status, chosen, keys, damage, plan, mass: validation?.mass ?? chosen.reduce((sum, option) => sum + (presetTotals(option, weapons).mass || 0), 0), effective: model.effective.reduce((sum, [name, coefficient]) => sum + coefficient * value(name), 0), warnings: validation?.warnings || []};
  }
  if (!model.supplies.size || !model.options.length) return {status: "infeasible", unknown: model.unknown};
  let best, targets = 1, targetUpper = 1;
  if (mode === "targets") {
    const upper = solve(model.effective, "Maximize");
    if (!upper.chosen) return {status: complete ? "infeasible" : "unknown", unknown: model.unknown};
    // A time-limited maximum is not a valid upper bound. Only proven maxima
    // can establish the global maximum number of independently covered zones.
    if (upper.status !== "Optimal") return {status: "unknown", unknown: model.unknown};
    let low = 0, high = Math.floor(upper.effective + 1e-8);
    while (low < high && performance.now() < deadline) {
      const middle = Math.ceil((low + high) / 2);
      const candidate = solve([], "Minimize", middle);
      if (candidate.chosen) { low = middle; best = candidate; }
      else if (candidate.status === "Infeasible") high = middle - 1;
      else break;
    }
    targets = low;
    targetUpper = high;
    complete &&= low === high;
    if (!targets) return {status: complete ? "infeasible" : "unknown", unknown: model.unknown};
  }
  const refined = solve(model.damage, "Minimize", targets);
  if (refined.chosen) best = refined;
  if (!best) return {status: complete ? "infeasible" : "unknown", unknown: model.unknown};
  // The actual game curve jumps slightly upwards at its first knot. Compare
  // both decreasing regions rather than assuming that less damage always wins.
  const knot = reward.piecewise_linear[0][0];
  if (best.damage < knot && rewardUi(reward, knot) > rewardUi(reward, best.damage)) {
    const above = solve(model.damage, "Minimize", targets, [`${expression(model.damage)} >= ${knot}`]);
    if (above.chosen && rewardUi(reward, above.damage) > rewardUi(reward, best.damage)) best = above;
  }
  // Deterministic second priority after reward/damage: lower carried mass.
  if (refined.status === "Optimal" && performance.now() < deadline) {
    const lighter = solve(model.mass, "Minimize", targets, [`${expression(model.damage)} = ${best.damage}`]);
    if (lighter.chosen && Math.abs(lighter.damage - best.damage) <= 1e-7) best = lighter;
  }
  const preset = definition ? previewCustomPreset(definition, {id: "recommendation", name: "推荐挂载", keys: best.keys}).preset : best.chosen[0];
  const fixedDamage = model.options.filter(option => input.lockedKeys.includes(option.key)).reduce((sum, option) => sum + option.damage, 0);
  const minimumDamage = Math.max(threshold * targets, fixedDamage);
  const rewardUpper = Math.max(rewardUi(reward, minimumDamage), minimumDamage <= knot ? rewardUi(reward, knot) : 0);
  return {status: complete ? "optimal" : "feasible", kind: definition ? "custom" : "preset", presetId: definition ? null : preset.id,
    keys: best.keys, preset, targets, damage: best.damage, mass: best.mass, reward: rewardUi(reward, best.damage), plan: best.plan,
    rewardUpper, targetUpper, unknown: model.unknown, warnings: best.warnings};
}
