import { t } from "./i18n.mjs";
// Aircraft loadout rules and combined-store arithmetic have no DOM or storage
// dependencies, so saved presets are re-evaluated against the current catalog.
export function combinationTotals(items, weapons, hp) {
  let count = 0, mass = 0, tnt = 0, damage = 0;
  for (const [id, amount] of items) {
    if (!Number.isSafeInteger(amount) || amount < 0) return null;
    if (amount === 0) continue;
    const weapon = weapons.get(id);
    if (!weapon) return null;
    count += amount;
    mass = mass !== null && weapon.kg > 0 ? mass + amount * weapon.kg : null;
    damage = damage !== null && weapon.dmg > 0 ? damage + amount * weapon.dmg : null;
    const charge = weapon.charge;
    tnt = tnt !== null && charge?.mass_kg > 0 && charge?.strength_equivalent > 0
      ? tnt + amount * charge.mass_kg * charge.strength_equivalent : null;
  }
  if (!Number.isSafeInteger(count) || [mass, tnt, damage].some(value => value !== null && !Number.isFinite(value))) return null;
  const rounds = hp > 0 && damage > 0 ? Math.ceil(hp / damage) : null;
  if (rounds !== null && !Number.isSafeInteger(rounds)) return null;
  return { count, mass, tnt, damage, rounds };
}

export function validateLoadout(definition, keys) {
  const options = new Map(definition.options.map(option => [option.key, option]));
  const selected = [], errors = [], warnings = [], tiers = new Set(), slots = new Set();
  const add = (code, message, details = {}) => errors.push({ code, message, ...details });
  for (const key of keys) {
    const option = options.get(key);
    if (!option) { add("unknown", t("custom-loadouts.loadoutIsAbsentFromThisVersion", "当前版本没有挂载 {{v0}}", {v0: key})); continue; }
    if (tiers.has(option.tier) || slots.has(option.slot)) add("occupied", t("custom-loadouts.stationPermitsOnlyOneConfiguration", "挂点 {{v0}} 只能选择一个配置", {v0: option.tier + 1}));
    tiers.add(option.tier); slots.add(option.slot); selected.push(option);
  }
  const has = relation => selected.some(option => option.slot === relation.slot && option.preset === relation.preset);
  for (const option of selected) {
    for (const relation of option.requires) if (!has(relation)) {
      const required = definition.options.find(item => item.slot === relation.slot && item.preset === relation.preset);
      // Native addDependentWeaponsParams also skips an absent target. Keep
      // the source defect visible; do not invent a replacement slot/preset.
      if (!required) {
        warnings.push(t("custom-loadouts.sourceDependencySlotIsMissingTheGameClientSkips", "源数据依赖 {{v0}}（槽 {{v1}}）不存在；游戏客户端跳过此项，网页无法确认这项条件。", {v0: relation.preset, v1: relation.slot}));
        continue;
      }
      add("dependency", t("custom-loadouts.requiresSlot", "{{v0}} 需要 {{v1}}（槽 {{v2}}）", {v0: option.preset, v1: relation.preset, v2: relation.slot}), { option: option.key, required: required?.key });
    }
    for (const relation of option.bans) if (has(relation)) add("conflict", t("custom-loadouts.conflictsWithSlot", "{{v0}} 与 {{v1}}（槽 {{v2}}）冲突", {v0: option.preset, v1: relation.preset, v2: relation.slot}));
  }
  let left = 0, right = 0, center = 0, minLeft = 0, minRight = 0, minCenter = 0;
  for (const option of selected) {
    const minimum = option.massRange?.[0] ?? option.mass;
    if (definition.center.includes(option.tier)) { center += option.mass; minCenter += minimum; }
    else if (option.tier < Math.floor(definition.columns / 2)) { left += option.mass; minLeft += minimum; }
    else { right += option.mass; minRight += minimum; }
  }
  const mass = left + right + center, minMass = minLeft + minRight + minCenter;
  const imbalance = Math.max(Math.abs(left - minRight), Math.abs(right - minLeft));
  const minImbalance = Math.max(0, minLeft - right, minRight - left);
  const ranges = {mass: [minMass, mass], left: [minLeft, left], right: [minRight, right], imbalance: [minImbalance, imbalance]};
  if (selected.some(option => option.massRange)) warnings.push(t("custom-loadouts.thisStationCombinesEquipmentTypesWithAnUnorderedNative", "同挂点含多类装备，原生汇总顺序不固定；重量显示可能范围，仅整个范围通过时才确认静态限制。"));
  const limits = definition.limits;
  if (Object.values(limits).some(value => value >= 0)) {
    for (const [field, value, minimum, label] of [
      ["maxloadMass", mass, minMass, t("custom-loadouts.totalLoad", "总挂载")], ["maxloadMassLeftConsoles", left, minLeft, t("custom-loadouts.leftLoad", "左侧载荷")],
      ["maxloadMassRightConsoles", right, minRight, t("custom-loadouts.rightLoad", "右侧载荷")], ["maxDisbalance", imbalance, minImbalance, t("custom-loadouts.leftRightImbalance", "左右不平衡")],
    ]) if (value > limits[field]) add(field, minimum <= limits[field]
      ? t("custom-loadouts.rangeKgCrossesTheKgLimitCheckInThe", "{{v0}}范围 {{v1}}–{{v2}} kg 跨过 {{v3}} kg 限制，需在游戏中核对", {v0: label, v1: minimum.toFixed(1), v2: value.toFixed(1), v3: limits[field]})
      : t("custom-loadouts.kgExceedsKg", "{{v0}} {{v1}} kg 超过 {{v2}} kg", {v0: label, v1: minimum.toFixed(1), v2: limits[field]}));
  }
  return { valid: !errors.length, errors, warnings, selected, mass, left, right, center, imbalance, ranges };
}

export function previewCustomPreset(definition, saved) {
  const validation = validateLoadout(definition, saved.keys);
  const weapons = new Map(), cells = [];
  for (const option of validation.selected) {
    cells.push(...option.cells);
    for (const [id, count] of option.weapons) weapons.set(id, (weapons.get(id) || 0) + count);
  }
  const rewardDamage = validation.selected.every(option => Number.isFinite(option.rewardDamage))
    ? validation.selected.reduce((sum, option) => sum + option.rewardDamage, 0) : null;
  return { validation, preset: { id: saved.id, customName: saved.name, keys: [...saved.keys], weapons: [...weapons], cells,
    ...(validation.selected.some(option => Object.hasOwn(option, "rewardDamage")) ? {rewardDamage} : {}),
    columns: definition.columns, layout: "slots", other: cells.some(cell => !weapons.has(cell.weapon)) } };
}

export function customPreset(definition, saved) {
  const { validation, preset } = previewCustomPreset(definition, saved);
  return validation.valid ? preset : null;
}

// Match actual stores at each game tier, including support equipment. Never
// turn an unrepresentable preset into a partial editable configuration.
export function keysFromPreset(definition, preset) {
  if (preset.keys) return [...preset.keys];
  const tiers = new Map();
  for (const cell of preset.cells) {
    if (!tiers.has(cell.tier)) tiers.set(cell.tier, []);
    tiers.get(cell.tier).push(cell);
  }
  const counts = cells => {
    const result = new Map();
    for (const cell of cells) result.set(cell.weapon, (result.get(cell.weapon) || 0) + cell.count);
    return result;
  };
  const keys = [];
  for (const [tier, cells] of tiers) {
    const expected = counts(cells);
    const option = definition.options.find(item => item.tier + 1 === tier && (() => {
      const actual = counts(item.cells);
      return actual.size === expected.size && [...expected].every(([id, count]) => actual.get(id) === count);
    })());
    if (!option) return null;
    keys.push(option.key);
  }
  return keys;
}
