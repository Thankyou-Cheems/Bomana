import { rewardUi, rewardPlateauDamage, requiredCount, empiricalSimScore, simScoreDamageScale, simScoreDamageOf, simScoreRewardParametersSupported } from "./model.mjs";
import { validateLoadout, previewCustomPreset } from "./custom-loadouts.mjs";
import { presetTotals } from "./loadouts.mjs";
import { deliveryGroup, loadoutSimplicity } from "./loadout-simplicity.mjs";
import { availableGuidanceModes, guidanceBurden, deliveryWorkload, recommendationWeaponExcluded } from "./recommendation-guidance.mjs";

// All decisions are whole options / whole projectiles. Damage is never rounded
// to integer HP or converted through TNT. The original validator checks the
// returned option set independently of the optimization model.
const expression = terms => terms.filter(([, value]) => value !== 0).map(([name, value]) => `${value < 0 ? "-" : "+"} ${Math.abs(value)} ${name}`).join(" ") || "0 zero";
const damageOf = (items, weapons) => items.reduce((sum, [id, count]) => weapons.get(id)?.dmg > 0 ? sum + weapons.get(id).dmg * count : NaN, 0);
const scoreDamageOf = (items, weapons) => items.reduce((sum, [id, count]) => {
  const weapon = weapons.get(id), damage = simScoreDamageOf(weapon);
  return weapon?.dmg > 0 && Number.isFinite(damage) && damage > 0 ? sum + damage * count : NaN;
}, 0);
const rewardDamageOf = (items, weapons) => items.reduce((sum, [id, count]) => sum + (weapons.get(id)?.rewardDmg ?? weapons.get(id)?.dmg ?? 0) * count, 0);
const forbidden = (option, weapons) => option.cells?.some(cell => ["aam", "arm", "ashm"].includes(cell.role)) || option.weapons.some(([id]) => ["aam", "arm", "ashm"].includes(weapons.get(id)?.role));

export function preferRecommendation(candidate, current, filters = {}) {
  if (!candidate.preset) return false;
  if (!current.preset) return true;
  if (["sim_score", "global_sim_score"].includes(candidate.objective) || ["sim_score", "global_sim_score"].includes(current.objective)) {
    if (!Number.isFinite(candidate.score)) return false;
    if (!Number.isFinite(current.score)) return true;
    if (Math.abs(candidate.score - current.score) > 1e-8) return candidate.score > current.score;
    if (candidate.objective === "global_sim_score" && candidate.plan.length !== current.plan.length) return candidate.plan.length < current.plan.length;
    for (const field of ["profiles", "types"]) if (candidate.simplicity?.[field] !== current.simplicity?.[field]) return candidate.simplicity[field] < current.simplicity[field];
    if (candidate.damage !== current.damage) return candidate.damage < current.damage;
    if (candidate.mass !== current.mass) return candidate.mass < current.mass;
    return candidate.keys.join(",") < current.keys.join(",");
  }
  if (candidate.targets !== current.targets) return candidate.targets > current.targets;
  if (candidate.objective === "custom_targets" && Math.abs(candidate.reward - current.reward) < 1e-8 &&
      (!filters.simpleLoadout || candidate.simplicity?.profiles === current.simplicity?.profiles && candidate.simplicity?.types === current.simplicity?.types)) {
    if (candidate.damage !== current.damage) return candidate.damage < current.damage;
    if (candidate.mass !== current.mass) return candidate.mass < current.mass;
  }
  const closeToCap = !filters.strictReward && Math.min(candidate.reward, current.reward) >= (candidate.rewardCap ?? 10) - (filters.rewardTolerance ?? .2) - 1e-8;
  if (!filters.simpleLoadout && (closeToCap || Math.abs(candidate.reward - current.reward) < 1e-8) && candidate.workload && current.workload) {
    for (const field of ["designation", "shots"]) if (candidate.workload[field] !== current.workload[field]) return candidate.workload[field] < current.workload[field];
  }
  if (filters.simpleLoadout || closeToCap || Math.abs(candidate.reward - current.reward) < 1e-8) for (const field of ["profiles", "types"]) {
    if (candidate.simplicity?.[field] !== current.simplicity?.[field]) return candidate.simplicity[field] < current.simplicity[field];
  }
  return candidate.reward > current.reward + 1e-8 || Math.abs(candidate.reward - current.reward) < 1e-8 &&
    (candidate.damage < current.damage || candidate.damage === current.damage && candidate.mass < current.mass);
}

function supportedReward(reward) {
  const {preset_dmg_min: min, preset_dmg_max: max, bombing_reward_modifier: modifier, piecewise_linear: points} = reward;
  // Below the first knot the formula is a + b / damage. Above it the
  // supplied piecewise curve must also decrease. Its first-knot jump is
  // handled separately below when comparing the two decreasing regions.
  const b = min * (1 - (modifier - 1) * min / (max - min));
  return max > min && b >= 0 && points.every((point, i) => i === 0 || point[0] > points[i - 1][0] && point[1] <= points[i - 1][1]);
}

function prepare({definition, presets, lockedKeys, weapons, threshold, filters = {}}) {
  const custom = Boolean(definition);
  const source = custom ? definition.options : presets.filter(preset => !preset.customName);
  const options = source.map((option, i) => ({...option, variable: `x${i}`,
    damage: (filters.requireSimScore ? scoreDamageOf : damageOf)(option.weapons, weapons),
    nativeDamage: damageOf(option.weapons, weapons),
    rewardDamage: filters.requireSimScore || !Object.hasOwn(option, "rewardDamage")
      ? rewardDamageOf(option.weapons, weapons) : option.rewardDamage}));
  const constraints = [], bounds = ["zero = 0"], binaries = options.map(option => option.variable);
  const add = (terms, relation, value) => constraints.push(`${expression(terms)} ${relation} ${value}`);
  let unknown = false;
  for (const option of options) {
    option.excluded = !lockedKeys.includes(option.key) && (forbidden(option, weapons) || option.weapons.some(([id]) => {
      const weapon = weapons.get(id);
      return recommendationWeaponExcluded(weapon, filters);
    }));
    if (option.excluded) bounds.push(`${option.variable} = 0`);
  }
  for (const option of options) if (!Number.isFinite(option.damage) || !Number.isFinite(option.rewardDamage) || filters.requireSimScore && option.weapons.some(([id, count]) => count > 0 && (!Number.isFinite(weapons.get(id)?.rewardDmg) || weapons.get(id).rewardDmg < 0))) { bounds.push(`${option.variable} = 0`); unknown = true; option.damage = 0; option.rewardDamage = 0; }
  const damage = options.map(option => [option.variable, option.damage]);
  const nativeDamage = options.map(option => [option.variable, Number.isFinite(option.nativeDamage) ? option.nativeDamage : 0]);
  const rewardDamage = options.map(option => [option.variable, option.rewardDamage]);
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
    // Support equipment is added only for a selected dependency or user lock.
    for (const option of options.filter(row => !row.weapons.some(([, count]) => count > 0) && !lockedKeys.includes(row.key))) {
      const dependents = options.filter(other => other.requires.some(dep => dep.slot === option.slot && dep.preset === option.preset));
      add([[option.variable, 1], ...dependents.map(other => [other.variable, -1])], "<=", 0);
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
  const types = [], profiles = [], groups = new Map();
  for (const [index, [id]] of [...supplies].entries()) {
    const variable = `w${index}`;
    binaries.push(variable); types.push([variable, 1]);
    const users = options.filter(option => option.weapons.some(([weapon, count]) => weapon === id && count > 0));
    for (const option of users) add([[option.variable, 1], [variable, -1]], "<=", 0);
    add([[variable, 1], ...users.map(option => [option.variable, -1])], "<=", 0);
    const group = deliveryGroup(id, weapons.get(id));
    if (!groups.has(group)) groups.set(group, []);
    groups.get(group).push(variable);
  }
  for (const [index, variables] of [...groups.values()].entries()) {
    const variable = `g${index}`;
    binaries.push(variable); profiles.push([variable, 1]);
    for (const weapon of variables) add([[weapon, 1], [variable, -1]], "<=", 0);
    add([[variable, 1], ...variables.map(weapon => [weapon, -1])], "<=", 0);
  }
  return {options, constraints, bounds, binaries, damage, nativeDamage, rewardDamage, mass, supplies, effective, types, profiles, unknown, custom, add};
}

export function optimizeLoadout(input, highs, {timeLimit = 20, preparedModel} = {}) {
  const {definition, weapons, threshold, mode, reward, aircraft = null} = input;
  if (mode === "global_sim_score") return optimizeGlobalSimScore(input, highs, timeLimit);
  if (mode === "sim_score") return optimizeSimScore(input, highs, {timeLimit});
  if (mode === "custom_targets" && (!Number.isSafeInteger(input.targetCount) || input.targetCount < 1)) return {status: "invalid", reason: "invalid_target_count"};
  if (!(threshold > 0) || !supportedReward(reward)) return {status: "unsupported"};
  const coefficient = damage => rewardUi(reward, damage, aircraft);
  if (!Number.isFinite(coefficient(1))) return {status: "unsupported"};
  const plateau = rewardPlateauDamage(reward, aircraft);
  const rewardCap = coefficient(1);
  const zeroRewardIsHigher = coefficient(0) > rewardCap;
  const template = preparedModel || prepare(input);
  const model = {...template, constraints: [...(template.constraints || [])]};
  if (model.error) return {status: "infeasible", reason: model.error};
  const compareGuidance = model.options.some(option => !option.excluded && option.damage > 0 && option.weapons.some(([id]) => availableGuidanceModes(weapons.get(id), input.filters).length));
  const overallDeadline = performance.now() + timeLimit * 1000;
  const deadline = overallDeadline - (mode === "targets" ? timeLimit * 250 : 0);
  let complete = true;
  function solve(objective, direction, targets = 0, extra = []) {
    const constraints = [...model.constraints, ...extra], bounds = [...model.bounds], integers = [];
    const allocation = [];
    if (targets >= 1) {
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
    const terms = typeof objective === "function" ? objective(allocation) : objective;
    const lp = `${direction}\n obj: ${expression(terms)}\nSubject To\n${constraints.map((row, i) => ` c${i}: ${row}`).join("\n")}\nBounds\n${bounds.join("\n")}\nBinaries\n${model.binaries.join(" ")}\n${integers.length ? `Generals\n${integers.join(" ")}\n` : ""}End`;
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
    if ([...used].some(([id, count]) => count > (items.get(id) || 0)) || plan.some(row => requiredCount(threshold, damageOf(row, weapons)) !== 1)) { complete = false; return {status: "Invalid solution"}; }
    return {status: result.Status, chosen, keys, damage, rewardDamage: chosen.reduce((sum, option) => sum + option.rewardDamage, 0), plan, workload: deliveryWorkload(plan, weapons, input.filters), simplicity: loadoutSimplicity([...items], weapons), mass: validation?.mass ?? chosen.reduce((sum, option) => sum + (presetTotals(option, weapons).mass || 0), 0), effective: model.effective.reduce((sum, [name, coefficient]) => sum + coefficient * value(name), 0), warnings: validation?.warnings || []};
  }
  if (!model.supplies.size || !model.options.length) return {status: "infeasible", unknown: model.unknown};
  let best, targets = 1, targetUpper = 1;
  if (mode === "targets" || mode === "custom_targets") {
    const upper = solve(model.effective, "Maximize");
    if (!upper.chosen) return {status: complete ? "infeasible" : "unknown", unknown: model.unknown};
    // A time-limited maximum is not a valid upper bound. Only proven maxima
    // can establish the global maximum number of independently covered zones.
    if (upper.status !== "Optimal") return {status: "unknown", unknown: model.unknown};
    let low = 0, high = Math.min(mode === "custom_targets" ? input.targetCount : Infinity, Math.floor(upper.effective + 1e-8));
    if (mode === "custom_targets" && high === input.targetCount) {
      const requested = solve([], "Minimize", high);
      if (requested.chosen) { low = high; best = requested; }
      else if (requested.status === "Infeasible") high--;
      else return {status: "unknown", requestedTargets: input.targetCount, targetUpper: high, unknown: model.unknown};
    }
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
    if (!targets) return {status: complete ? "infeasible" : "unknown", requestedTargets: mode === "custom_targets" ? input.targetCount : undefined, targets: 0, targetUpper, unknown: model.unknown};
  }
  if (input.filters?.simpleLoadout) {
    for (const [objective, field] of [[model.profiles, "profiles"], [model.types, "types"]]) {
      const simpler = solve(objective, "Minimize", targets);
      if (simpler.chosen) best = simpler;
      if (!best) return {status: complete ? "infeasible" : "unknown", unknown: model.unknown};
      model.constraints.push(`${expression(objective)} <= ${best.simplicity[field]}`);
    }
  }
  const refined = solve(model.rewardDamage, "Minimize", targets);
  if (refined.chosen) best = refined;
  if (!best) return {status: complete ? "infeasible" : "unknown", unknown: model.unknown};
  // The actual game curve jumps slightly upwards at its first knot. Compare
  // both decreasing regions rather than assuming that less damage always wins.
  const knot = reward.piecewise_linear[0][0];
  if (best.rewardDamage < knot && coefficient(knot) > coefficient(best.rewardDamage)) {
    const above = solve(model.rewardDamage, "Minimize", targets, [`${expression(model.rewardDamage)} >= ${knot}`]);
    if (above.chosen && coefficient(above.rewardDamage) > coefficient(best.rewardDamage)) best = above;
  }
  const maximumReward = coefficient(best.rewardDamage);
  // Keep the exact best coefficient except in the near-cap band the user accepts.
  // This inversion stays below the first knot, so its upward jump is not bridged.
  const nearCapFloor = rewardCap - (input.filters?.rewardTolerance ?? .2);
  let allowedDamage = best.rewardDamage === 0 && zeroRewardIsHigher ? 0 : best.rewardDamage <= plateau ? plateau : best.rewardDamage;
  if (!input.filters?.simpleLoadout && !input.filters?.strictReward && maximumReward >= nearCapFloor && (best.rewardDamage > 0 || !zeroRewardIsHigher) && best.rewardDamage < knot) {
    let low = plateau, high = knot;
    for (let i = 0; i < 50; i++) {
      const middle = (low + high) / 2;
      if (coefficient(middle) >= nearCapFloor) low = middle;
      else high = middle;
    }
    allowedDamage = Math.max(allowedDamage, low);
  }
  let sameRewardScope;
  if (!input.filters?.simpleLoadout) {
    // An upper bound alone would admit the lower-reward region just before the
    // knot. Preserve the winning value when the best result is above that jump.
    model.constraints.push(`${expression(model.rewardDamage)} ${best.rewardDamage >= knot ? "=" : "<="} ${allowedDamage}`);
    sameRewardScope = [...model.constraints];
    // Compare actual delivery plans within the accepted reward band. Prefer
    // coordinate guidance, then fewer seeker/illumination actions and releases;
    // a small optical supplement can beat an otherwise insufficient GNSS load.
    for (const [field, coefficient] of compareGuidance ? [["designation", id => guidanceBurden(weapons.get(id), input.filters)], ["shots", () => 1]] : []) {
      const terms = rows => rows.map(row => [row.variable, coefficient(row.id)]);
      const easier = solve(terms, "Minimize", targets);
      if (easier.chosen) best = easier;
      const allocation = [...model.supplies.keys()].flatMap((id, w) => Array.from({length: targets}, (_, target) => [`a${target}_${w}`, coefficient(id)]));
      model.constraints.push(`${expression(allocation)} <= ${best.workload[field]}`);
    }
    for (const [objective, field] of [[model.profiles, "profiles"], [model.types, "types"]]) {
      const simpler = solve(objective, "Minimize", targets);
      if (simpler.chosen) best = simpler;
      model.constraints.push(`${expression(objective)} <= ${best.simplicity[field]}`);
    }
    const higherReward = solve(model.rewardDamage, "Minimize", targets);
    if (higherReward.chosen) best = higherReward;
  }
  // Equal coefficient: first remove excess impact damage, then carried mass.
  // Custom counts retain the user's reward band / explicit uniform preference,
  // but equal-coefficient candidates compare surplus before delivery convenience.
  if (mode === "custom_targets" && sameRewardScope) model.constraints = sameRewardScope;
  // Below the reward cap all damage values have the same coefficient.
  const cap = best.rewardDamage === 0 && zeroRewardIsHigher ? 0 : plateau;
  const rewardConstraint = best.rewardDamage <= cap
    ? `${expression(model.rewardDamage)} <= ${cap}`
    : `${expression(model.rewardDamage)} = ${best.rewardDamage}`;
  const lessDamage = solve(model.damage, "Minimize", targets, [rewardConstraint]);
  if (lessDamage.chosen) best = lessDamage;
  // Deterministic final priority: lower carried mass.
  if (refined.status === "Optimal" && performance.now() < deadline) {
    const lighter = solve(model.mass, "Minimize", targets, [rewardConstraint, `${expression(model.damage)} = ${best.damage}`]);
    if (lighter.chosen && Math.abs(lighter.damage - best.damage) <= 1e-7) best = lighter;
  }
  // Once the carried loadout is fixed, choose exact integer shot counts. A
  // feasibility witness may otherwise spend an arbitrary number of spare rockets.
  const fixedLoadout = model.options.map(option => `${option.variable} = ${best.keys.includes(option.key) ? 1 : 0}`);
  const fewerShots = solve(rows => rows.map(row => [row.variable, 1]), "Minimize", targets, fixedLoadout);
  if (fewerShots.chosen) best = fewerShots;
  const preset = definition ? previewCustomPreset(definition, {id: "recommendation", name: "推荐挂载", keys: best.keys}).preset : best.chosen[0];
  const minimumDamage = model.options.filter(option => input.lockedKeys.includes(option.key)).reduce((sum, option) => sum + option.rewardDamage, 0);
  const rewardUpper = Math.max(coefficient(minimumDamage), minimumDamage <= knot ? coefficient(knot) : 0);
  const output = {status: complete ? "optimal" : "feasible", kind: definition ? "custom" : "preset", presetId: definition ? null : preset.id,
    keys: best.keys, preset, targets, damage: best.damage, rewardDamage: best.rewardDamage, mass: best.mass, reward: coefficient(best.rewardDamage), plan: best.plan,
    rewardUpper, targetUpper, unknown: model.unknown, warnings: best.warnings};
  output.totalReward = output.targets * output.reward;
  output.simplicity = best.simplicity;
  output.workload = compareGuidance ? best.workload : null;
  output.rewardCap = best.rewardDamage === 0 ? reward.ui_decoration : rewardCap;
  output.maximumReward = maximumReward;
  if (mode === "custom_targets") {
    output.objective = mode;
    output.requestedTargets = input.targetCount;
    output.targetReached = targets === input.targetCount;
    output.coverageProven = targets === targetUpper;
    // Repeating this legal plan gives an estimate, not a game sortie guarantee.
    output.estimatedSorties = Math.ceil(input.targetCount / targets);
  }
  const used = new Map();
  for (const row of best.plan) for (const [id, count] of row) used.set(id, (used.get(id) || 0) + count);
  output.remaining = preset.weapons.map(([id, count]) => [id, count - (used.get(id) || 0)]).filter(([, count]) => count > 0);
  if (mode === "targets") {
    const single = optimizeLoadout({...input, mode: "reward"}, highs, {timeLimit: Math.max(.1, (overallDeadline - performance.now()) / 1000)});
    if (single.status !== "optimal") output.status = "feasible";
    if (single.preset) {
      output.singleZone = single;
      output.moreLoadoutUseful = targets > 1 && output.totalReward > single.totalReward + 1e-8;
    }
  }
  return output;
}

function optimizeGlobalSimScore(input, highs, timeLimit) {
  const scenarios = input.scenarios || [], comparisons = [];
  const deadline = performance.now() + timeLimit * 1000;
  let best;
  for (const scenario of scenarios) {
    const airport = scenario.targetId.startsWith("airport_");
    // This action searches the whole aircraft; current manual selections are
    // not locks. Airport strike stores must be explicitly unguided, including
    // multi-mode weapons. Other ammunition exclusions still apply.
    const filters = {...input.filters, ...(airport ? {noGuided: true} : {})};
    const budget = Math.max(.05, (deadline - performance.now()) / 1000 / (scenarios.length - comparisons.length));
    const request = {...input, lockedKeys: [], filters, scenario};
    const previous = airport && comparisons.find(row => row.targetId.startsWith("airport_") && row.scenario.remainingHp === scenario.remainingHp);
    const next = previous ? {...previous, estimate: previous.preset && empiricalSimScore({...scenario,carried:previous.preset.weapons,weapons:input.weapons,reward:input.reward})}
      : airport ? optimizeSimScore(request, highs, {timeLimit:budget}) : optimizeBaseSortieScore(request, highs, budget);
    const candidate = {...next, objective:"global_sim_score", targetId:scenario.targetId, scenario};
    comparisons.push(candidate);
    if (preferRecommendation(candidate, best || {})) best = candidate;
  }
  const complete = comparisons.length > 0 && comparisons.every(row => ["optimal","infeasible"].includes(row.status) || best && Number.isFinite(row.scoreUpper) && row.scoreUpper <= best.score + 1e-6);
  if (!best) return {status:complete ? "infeasible" : "unknown", objective:"global_sim_score", comparisons};
  const upper = comparisons.every(row => row.status === "infeasible" || Number.isFinite(row.scoreUpper))
    ? Math.max(...comparisons.map(row => row.scoreUpper || 0)) : null;
  return {...best, status:complete ? "optimal" : "feasible", scoreUpper:upper, comparisons};
}

// One full-health base per sortie. Score credit is capped separately from
// native HP; only native damage can trigger a kill.
function optimizeBaseSortieScore(input, highs, timeLimit) {
  const {definition, weapons, reward, scenario} = input;
  const hp = scenario.targetFullHp, threshold = scenario.destructionThreshold;
  if (scenario.targetId !== "bombing_point_planes" || !(hp > 0) || !(threshold > 0) || threshold > hp ||
      scenario.remainingHp !== hp || !simScoreRewardParametersSupported(reward) || !supportedReward(reward)) return {status:"unsupported"};
  const model = prepare({...input, threshold, filters:{...input.filters,requireSimScore:true}});
  if (model.error || !model.supplies.size) return {status:"infeasible"};
  const eligible = model.options.filter(row => !row.excluded && row.damage > 0);
  if (!eligible.length) return {status:"infeasible",unknown:model.unknown};
  const suppliedIds = new Set(eligible.flatMap(row => row.weapons.map(([id]) => id)));
  for (const id of model.supplies.keys()) if (!suppliedIds.has(id)) model.supplies.delete(id);
  const targetCount = 1;
  const globalMultiplierUpper = Math.max(...[0,reward.preset_dmg_min,...reward.piecewise_linear.map(([x])=>x)].map(value=>rewardUi(reward,value)/reward.ui_decoration));
  const universalUpper = simScoreDamageScale * hp * 1.5 * targetCount * globalMultiplierUpper;
  const allocation = [], credit = [], integers = [], binaries = [...model.binaries], bounds = [...model.bounds];
  const constraints = [...model.constraints];
  constraints.push(`${expression(model.damage)} >= ${Math.min(...eligible.map(row=>row.damage))}`);
  for (let target=0; target<targetCount; target++) {
    const native = [], score = [], kill = `k${target}`, damage = `d${target}`;
    binaries.push(kill); bounds.push(`0 <= ${damage} <= 1`); credit.push([damage,1],[kill,.5]);
    for (const [index,[id]] of [...model.supplies].entries()) {
      const variable=`a${target}_${index}`;
      integers.push(variable); allocation.push({variable,target,id});
      native.push([variable,Math.min(weapons.get(id).dmg/threshold,1)]);
      score.push([variable,Math.min(simScoreDamageOf(weapons.get(id))/hp,1)]);
    }
    constraints.push(`${expression([...native,[kill,-1]])} >= 0`);
    constraints.push(`${expression([[damage,1],[kill,-1],...score.map(([name,value])=>[name,-value])])} <= 0`);
    if (target) constraints.push(`${expression([[`d${target-1}`,1],[`k${target-1}`,.5],[damage,-1],[kill,-.5]])} >= 0`);
  }
  for (const [id,supply] of model.supplies) constraints.push(`${expression([...allocation.filter(row=>row.id===id).map(row=>[row.variable,1]),...supply.map(([name,n])=>[name,-n])])} = 0`);
  const deadline=performance.now()+timeLimit*1000;
  let best, complete=true;
  function solve(terms,direction,extra=[]) {
    const lp=`${direction}\n obj: ${expression(terms)}\nSubject To\n${[...constraints,...extra].map((row,index)=>` c${index}: ${row}`).join("\n")}\nBounds\n${bounds.join("\n")}\nBinaries\n${binaries.join(" ")}\nGenerals\n${integers.join(" ")}\nEnd`;
    const solved=highs.solve(lp,{output_flag:false,time_limit:Math.max(.01,(deadline-performance.now())/1000),mip_rel_gap:0,mip_abs_gap:0,mip_feasibility_tolerance:1e-9});
    if (!["Optimal","Infeasible"].includes(solved.Status)) complete=false;
    if (!solved.Columns) return {solverStatus:solved.Status};
    const value=name=>solved.Columns[name]?.Primal || 0;
    const chosen=model.options.filter(row=>value(row.variable)>.5), keys=chosen.map(row=>row.key ?? row.id);
    const validation=definition ? validateLoadout(definition,keys) : null;
    if (!chosen.length || validation && !validation.valid) {complete=false;return {solverStatus:"Invalid solution"};}
    const preset=definition ? previewCustomPreset(definition,{id:"recommendation",name:"推荐挂载",keys}).preset : chosen[0];
    const rows=Array.from({length:targetCount},()=>[]), used=new Map();
    for (const row of allocation) {
      const n=Math.round(value(row.variable));
      if (n<0 || Math.abs(n-value(row.variable))>1e-6) {complete=false;return {solverStatus:"Invalid solution"};}
      if (n) {rows[row.target].push([row.id,n]);used.set(row.id,(used.get(row.id)||0)+n);}
    }
    const carried=new Map();
    for (const [id,n] of preset.weapons) carried.set(id,(carried.get(id)||0)+n);
    if ([...used].some(([id,n])=>n!==carried.get(id))) {complete=false;return {solverStatus:"Invalid solution"};}
    const plan=rows.filter(row=>row.length), estimates=plan.map(delivered=>empiricalSimScore({...scenario,carried:preset.weapons,delivered,weapons,reward}));
    if (estimates.some(row=>!row || row.totalScore===null)) {complete=false;return {solverStatus:"Invalid solution"};}
    const score=estimates.reduce((sum,row)=>sum+row.totalScore,0), totals=presetTotals(preset,weapons);
    const candidate={objective:"global_sim_score",status:"feasible",kind:definition?"custom":"preset",presetId:definition?null:preset.id,preset,keys,plan,remaining:[],
      score,estimate:estimates[0],estimates,targets:plan.length,destroyedTargets:estimates.filter(row=>row.destructionScore>0).length,
      damage:damageOf(preset.weapons,weapons),rewardDamage:rewardDamageOf(preset.weapons,weapons),mass:validation?.mass ?? totals.mass ?? Infinity,
      simplicity:loadoutSimplicity(preset.weapons,weapons),warnings:validation?.warnings || [],unknown:model.unknown};
    if (preferRecommendation(candidate,best || {})) best=candidate;
    return {...candidate,solverStatus:solved.Status,credit:credit.reduce((sum,[name,n])=>sum+n*value(name),0)};
  }
  const lower=solve(model.rewardDamage,"Minimize"), upper=solve(model.rewardDamage,"Maximize");
  if (!best) return {status:complete?"infeasible":"unknown",unknown:model.unknown,scoreUpper:universalUpper};
  if (lower.solverStatus!=="Optimal" || upper.solverStatus!=="Optimal") return {...best,scoreUpper:universalUpper};
  const multiplier=value=>rewardUi(reward,value)/reward.ui_decoration;
  const knots=[reward.preset_dmg_min,...reward.piecewise_linear.map(([x])=>x)];
  const queue=[{lo:lower.rewardDamage,hi:upper.rewardDamage,bound:universalUpper}];
  let unresolved=0;
  while(queue.length && performance.now()<deadline) {
    queue.sort((a,b)=>b.bound-a.bound);
    const interval=queue.shift();
    if (interval.bound<=best.score+1e-6) continue;
    const candidate=solve(credit,"Maximize",[`${expression(model.rewardDamage)} >= ${interval.lo}`,`${expression(model.rewardDamage)} <= ${interval.hi}`]);
    if (!candidate.preset) {if(candidate.solverStatus!=="Infeasible") unresolved=Math.max(unresolved,interval.bound);continue;}
    if (candidate.solverStatus!=="Optimal") {unresolved=Math.max(unresolved,interval.bound);break;}
    const maxMultiplier=Math.max(...[interval.lo,interval.hi,...knots.filter(x=>x>=interval.lo && x<=interval.hi)].map(multiplier));
    const bound=simScoreDamageScale*hp*candidate.credit*maxMultiplier;
    if (bound<=best.score+1e-6) continue;
    const middle=interval.lo+(interval.hi-interval.lo)/2;
    if (!(middle>interval.lo && middle<interval.hi)) {unresolved=Math.max(unresolved,bound);break;}
    queue.push({lo:interval.lo,hi:middle,bound},{lo:middle,hi:interval.hi,bound});
  }
  const scoreUpper=Math.max(best.score,unresolved,...queue.map(row=>row.bound));
  complete &&= scoreUpper<=best.score+1e-6;
  return {...best,status:complete?"optimal":"feasible",scoreUpper:Number.isFinite(scoreUpper)?scoreUpper:null};
}

// A worker session retains the static hardpoint model while only N changes.
// Each solve gets its own constraints; reward refinements cannot contaminate it.
export function createOptimizerSession(input, highs) {
  const template = input.threshold > 0 ? prepare(input) : null;
  const results = new Map();
  return (request, options = {}) => {
    if (request.mode === "custom_targets" && (!Number.isSafeInteger(request.targetCount) || request.targetCount < 1)) return {status: "invalid", reason: "invalid_target_count"};
    const key = `${request.mode}|${request.targetCount ?? ""}`;
    if (results.has(key)) return results.get(key);
    const result = optimizeLoadout({...input, mode: request.mode, targetCount: request.targetCount}, highs, {...options, preparedModel: template});
    if (["optimal", "infeasible"].includes(result.status)) {
      if (results.size >= 32) results.delete(results.keys().next().value);
      results.set(key, result);
    }
    return result;
  };
}

// Maximize the empirical score itself. The existing whole-option feasibility
// model is shared, but neither reward coefficient nor zone count is the objective.
function optimizeSimScore(input, highs, {timeLimit}) {
  const {definition, weapons, reward, scenario} = input;
  // Fixed-HP bases retain reward/count objectives. Unknown destruction rewards
  // cannot support a proof of highest total-score optimality across loadouts.
  if (scenario?.targetId === "bombing_point_planes") return {status: "unsupported", objective: "sim_score"};
  if (!scenario || !simScoreRewardParametersSupported(reward) || !supportedReward(reward) ||
      !Number.isFinite(scenario.remainingHp) || scenario.remainingHp < 0) return {status: "unsupported", objective: "sim_score"};
  const model = prepare({...input, threshold: Math.max(1, scenario.remainingHp), filters: {...input.filters, requireSimScore: true}});
  if (model.error) return {status: "infeasible", reason: model.error, objective: "sim_score"};
  const positive = model.options.filter(option => option.damage > 0);
  if (!positive.length) return {status: "infeasible", objective: "sim_score", unknown: model.unknown};
  model.constraints.push(`${expression(model.damage)} >= ${Math.min(...positive.map(option => option.damage))}`);
  const deadline = performance.now() + timeLimit * 1000;
  let complete = true, best = null;
  function solve(terms, direction, extra = []) {
    const constraints = [...model.constraints, ...extra];
    const lp = `${direction}\n obj: ${expression(terms)}\nSubject To\n${constraints.map((row, index) => ` c${index}: ${row}`).join("\n")}\nBounds\n${model.bounds.join("\n")}\nBinaries\n${model.binaries.join(" ")}\nEnd`;
    const result = highs.solve(lp, {output_flag: false, time_limit: Math.max(.01, (deadline - performance.now()) / 1000), mip_rel_gap: 0, mip_abs_gap: 0, mip_feasibility_tolerance: 1e-9});
    if (!["Optimal", "Infeasible"].includes(result.Status)) complete = false;
    if (!result.Columns) return {status: result.Status};
    const chosen = model.options.filter(option => result.Columns[option.variable]?.Primal > .5);
    return evaluate(chosen, result.Status);
  }
  function evaluate(chosen, solverStatus) {
    const keys = chosen.map(option => option.key ?? option.id);
    if (!chosen.length || input.lockedKeys.some(key => !keys.includes(key))) return {status: solverStatus};
    const validation = definition ? validateLoadout(definition, keys) : null;
    if (validation && !validation.valid) { complete = false; return {status: "Invalid solution"}; }
    const preset = definition ? previewCustomPreset(definition, {id: "recommendation", name: "推荐挂载", keys}).preset : chosen[0];
    const estimate = empiricalSimScore({...scenario, carried: preset.weapons, weapons, reward});
    if (!estimate) return {status: solverStatus};
    const totals = presetTotals(preset, weapons);
    const candidate = {status: solverStatus, objective: "sim_score", kind: definition ? "custom" : "preset", presetId: definition ? null : preset.id,
      preset, keys, score: estimate.score, estimate, damage: estimate.carriedDamage, rewardDamage: estimate.carriedRewardDamage,
      scoreDamage: estimate.deliveredScoreDamage,
      mass: validation?.mass ?? totals.mass ?? Infinity, simplicity: loadoutSimplicity(preset.weapons, weapons),
      plan: [preset.weapons.map(row => [...row])], remaining: [], targets: 1, warnings: validation?.warnings || [], unknown: model.unknown};
    if (preferRecommendation(candidate, best || {})) best = candidate;
    return {...candidate, solverStatus};
  }
  if (!model.options.length || !model.supplies.size) return {status: "infeasible", objective: "sim_score", unknown: model.unknown};
  if (!definition) {
    // Native presets are a finite list: compare every eligible complete row,
    // including equal-score rows with different carried reward damage.
    for (const option of model.options) if (!option.excluded && option.damage > 0) evaluate([option], "Optimal");
    return best ? {...best, status: "optimal", scoreUpper: best.score, scoreTolerance: 0}
      : {status: "infeasible", objective: "sim_score", unknown: model.unknown};
  }
  const lower = solve(model.rewardDamage, "Minimize"), upper = solve(model.rewardDamage, "Maximize");
  if (!best) return {status: complete ? "infeasible" : "unknown", objective: "sim_score", unknown: model.unknown};
  if (lower.solverStatus !== "Optimal" || upper.solverStatus !== "Optimal") return {...best, status: "feasible", scoreUpper: null};
  const scale = simScoreDamageScale, hp = scenario.remainingHp;
  // A proportional damage/reward basis has a tight one-dimensional bound.
  // This is verified from the eligible options, never assumed for all weapons.
  const eligible = model.options.filter(option => option.damage > 0 && !option.excluded);
  const ratio = eligible.find(option => option.rewardDamage > 0)?.damage / eligible.find(option => option.rewardDamage > 0)?.rewardDamage;
  const proportional = Number.isFinite(ratio) && eligible.every(option => Math.abs(option.damage - ratio * option.rewardDamage) <= 1e-7);
  const knots = [reward.preset_dmg_min, ...reward.piecewise_linear.map(([x]) => x)];
  const multiplier = value => rewardUi(reward, value) / reward.ui_decoration;
  function bound(lo, hi, damageMaximum) {
    if (proportional) {
      const values = [lo, hi, hp / ratio, damageMaximum / ratio];
      for (const knot of knots) values.push(knot, knot - Number.EPSILON * Math.max(1, knot));
      for (let index = 0; index < reward.piecewise_linear.length - 1; index++) {
        const [x0, y0] = reward.piecewise_linear[index], [x1, y1] = reward.piecewise_linear[index + 1];
        const slope = (y1 - y0) / (x1 - x0), intercept = y0 - slope * x0;
        if (slope < 0) {
          const vertex = -intercept / (2 * slope);
          if (vertex >= x0 && vertex <= x1) values.push(vertex);
        }
      }
      return Math.max(...values.filter(value => value >= lo && value <= hi).map(value => scale * Math.min(ratio * value, hp, damageMaximum) * multiplier(value)));
    }
    const maxMultiplier = Math.max(...[lo, hi, ...knots.filter(value => value >= lo && value <= hi)].map(multiplier));
    return scale * Math.min(damageMaximum, hp) * maxMultiplier;
  }
  const queue = [{lo: lower.rewardDamage, hi: upper.rewardDamage, bound: Infinity}];
  let unresolvedUpper = 0;
  // Bounds are conservative; time-limited results remain visibly feasible.
  // The 1e-6 point tolerance is far below the two-decimal score presentation.
  const tolerance = 1e-6;
  while (queue.length && performance.now() < deadline) {
    queue.sort((a, b) => b.bound - a.bound);
    const interval = queue.shift();
    if (interval.bound <= best.score + tolerance) continue;
    const extra = [`${expression(model.rewardDamage)} >= ${interval.lo}`, `${expression(model.rewardDamage)} <= ${interval.hi}`];
    const candidate = solve(model.damage, "Maximize", extra);
    if (!candidate.preset) { if (candidate.status !== "Infeasible") unresolvedUpper = Math.max(unresolvedUpper, interval.bound); continue; }
    if (candidate.solverStatus !== "Optimal") { unresolvedUpper = Math.max(unresolvedUpper, interval.bound); break; }
    const scoreUpper = bound(interval.lo, interval.hi, candidate.scoreDamage);
    if (scoreUpper <= best.score + tolerance) continue;
    const middle = interval.lo + (interval.hi - interval.lo) / 2;
    if (!(middle > interval.lo && middle < interval.hi)) { unresolvedUpper = Math.max(unresolvedUpper, scoreUpper); break; }
    queue.push({lo: interval.lo, hi: middle, bound: scoreUpper}, {lo: middle, hi: interval.hi, bound: scoreUpper});
  }
  const scoreUpper = Math.max(best.score, unresolvedUpper, ...queue.map(interval => interval.bound));
  complete &&= scoreUpper <= best.score + tolerance;
  if (complete && performance.now() < deadline) {
    // Refine an equal-score witness and its constant-M region: fewer delivery profiles and
    // types, then less excess modeled damage and lower mass. Reward preferences
    // never lower the predicted score in this mode.
    let tieLow = best.rewardDamage, tieHigh = best.rewardDamage;
    if (best.rewardDamage <= reward.preset_dmg_min && best.estimate.multiplier === 1) {
      tieLow = 0; tieHigh = reward.preset_dmg_min;
    }
    const points = reward.piecewise_linear;
    if (best.rewardDamage >= points.at(-1)[0]) { tieLow = points.at(-1)[0]; tieHigh = upper.rewardDamage; }
    for (let index = 0; index < points.length - 1; index++) if (points[index][1] === points[index + 1][1] &&
      best.rewardDamage >= points[index][0] && best.rewardDamage <= points[index + 1][0]) {
      tieLow = Math.min(tieLow, points[index][0]); tieHigh = Math.max(tieHigh, points[index + 1][0]);
    }
    const equal = [`${expression(model.rewardDamage)} >= ${tieLow}`, `${expression(model.rewardDamage)} <= ${tieHigh}`,
      `${expression(model.damage)} ${best.scoreDamage >= hp ? ">=" : "="} ${Math.min(best.scoreDamage, hp)}`];
    for (const [terms, field] of [[model.profiles, "profiles"], [model.types, "types"]]) {
      const result = solve(terms, "Minimize", equal);
      if (result.preset) equal.push(`${expression(terms)} <= ${result.simplicity[field]}`);
    }
    const less = solve(model.nativeDamage, "Minimize", equal);
    if (less.preset) equal.push(`${expression(model.nativeDamage)} = ${less.damage}`);
    solve(model.mass, "Minimize", equal);
  }
  return {...best, status: complete ? "optimal" : "feasible", scoreUpper: Number.isFinite(scoreUpper) ? scoreUpper : null, scoreTolerance: tolerance};
}
