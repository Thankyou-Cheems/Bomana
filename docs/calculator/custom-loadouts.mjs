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
    if (!option) { add("unknown", `当前版本没有挂载 ${key}`); continue; }
    if (tiers.has(option.tier) || slots.has(option.slot)) add("occupied", `挂点 ${option.tier + 1} 只能选择一个配置`);
    tiers.add(option.tier); slots.add(option.slot); selected.push(option);
  }
  const has = relation => selected.some(option => option.slot === relation.slot && option.preset === relation.preset);
  for (const option of selected) {
    for (const relation of option.requires) if (!has(relation)) {
      const required = definition.options.find(item => item.slot === relation.slot && item.preset === relation.preset);
      // Native addDependentWeaponsParams also skips an absent target. Keep
      // the source defect visible; do not invent a replacement slot/preset.
      if (!required) {
        warnings.push(`源数据依赖 ${relation.preset}（槽 ${relation.slot}）不存在；游戏客户端跳过此项，网页无法确认这项条件。`);
        continue;
      }
      add("dependency", `${option.preset} 需要 ${relation.preset}（槽 ${relation.slot}）`, { option: option.key, required: required?.key });
    }
    for (const relation of option.bans) if (has(relation)) add("conflict", `${option.preset} 与 ${relation.preset}（槽 ${relation.slot}）冲突`);
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
  if (selected.some(option => option.massRange)) warnings.push("同挂点含多类装备，原生汇总顺序不固定；重量显示可能范围，仅整个范围通过时才确认静态限制。");
  const limits = definition.limits;
  if (Object.values(limits).some(value => value >= 0)) {
    for (const [field, value, minimum, label] of [
      ["maxloadMass", mass, minMass, "总挂载"], ["maxloadMassLeftConsoles", left, minLeft, "左侧载荷"],
      ["maxloadMassRightConsoles", right, minRight, "右侧载荷"], ["maxDisbalance", imbalance, minImbalance, "左右不平衡"],
    ]) if (value > limits[field]) add(field, minimum <= limits[field]
      ? `${label}范围 ${minimum.toFixed(1)}–${value.toFixed(1)} kg 跨过 ${limits[field]} kg 限制，需在游戏中核对`
      : `${label} ${minimum.toFixed(1)} kg 超过 ${limits[field]} kg`);
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
  return { validation, preset: { id: saved.id, customName: saved.name, keys: [...saved.keys], weapons: [...weapons], cells,
    columns: definition.columns, layout: "slots", other: cells.some(cell => !weapons.has(cell.weapon)) } };
}

export function customPreset(definition, saved) {
  const { validation, preset } = previewCustomPreset(definition, saved);
  return validation.valid ? preset : null;
}
