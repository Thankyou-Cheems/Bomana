import { t, localizeName } from "./i18n.mjs";

function equalParameters(a, b) {
  if (a === b) return true;
  if (!a || !b || typeof a !== "object" || typeof b !== "object" || Array.isArray(a) !== Array.isArray(b)) return false;
  const keys = Object.keys(a);
  return keys.length === Object.keys(b).length && keys.every(key => Object.hasOwn(b, key) && equalParameters(a[key], b[key]));
}

function equivalentStores(a, b) {
  // An equal label alone proves nothing. Compare every exported field except
  // identity; require known strike parameters before combining different IDs.
  const known = row => row && [row.kg, row.dmg].every(value => Number.isFinite(value) && value > 0)
    && Number.isFinite(row.rewardDmg) && Array.isArray(row.guidanceModes) && Object.hasOwn(row, "deliveryProfile");
  if (!known(a) || !known(b)) return false;
  const {id: aId, ...aParameters} = a, {id: bId, ...bParameters} = b;
  return equalParameters(aParameters, bParameters);
}

export function storesTitle(stores, weapons, names = {}) {
  const groups = [];
  for (const [id, count] of stores) {
    const group = groups.find(([other]) => id === other || equivalentStores(weapons.get(id), weapons.get(other)));
    if (group) group[1] += count;
    else groups.push([id, count]);
  }
  return groups.map(([id, count]) => `${localizeName(weapons.get(id)?.short || names[id] || weapons.get(id)?.name || id)} ×${count}`).join(" + ");
}

// Presentation of complete preset rows. Cells are exported from game UI tiers;
// they are not aircraft geometry or a free-form loadout builder.
export function presetTitle(preset, weapons) {
  const contents = storesTitle(preset.weapons, weapons);
  return preset.customName ? `${preset.customName}: ${contents || t("loadouts.otherEquipment", "其他装备")}` : contents;
}

export function presetTotals(preset, weapons) {
  let damage = 0, rewardDamage = 0, mass = 0, count = 0;
  let knownDamage = true, knownMass = true;
  for (const [id, amount] of preset.weapons) {
    const weapon = weapons.get(id);
    count += amount;
    if (!(weapon?.dmg > 0)) knownDamage = false;
    else damage += weapon.dmg * amount;
    rewardDamage += (weapon?.rewardDmg ?? weapon?.dmg ?? 0) * amount;
    if (!(weapon?.kg > 0)) knownMass = false;
    else mass += weapon.kg * amount;
  }
  return { count, damage: knownDamage ? damage : null,
    rewardDamage: Object.hasOwn(preset, "rewardDamage") ? preset.rewardDamage : knownDamage ? rewardDamage : null,
    mass: knownMass ? mass : null };
}

function node(tag, text, className) {
  const element = document.createElement(tag);
  if (text != null) element.textContent = text;
  if (className) element.className = className;
  return element;
}

export function ordnance(cell) {
  // iconType describes the whole native tier: a six-bomb rack or a nineteen-
  // tube rocket pod is one image. Ammunition count must not multiply that image.
  const icon = cell.icon;
  const image = node("img", null, "ordnance-icon");
  image.src = new URL(`./ordnance-icons/${encodeURIComponent(icon)}.webp`, import.meta.url).href + new URL(import.meta.url).search;
  image.alt = ""; image.width = 100; image.height = 100;
  image.loading = "lazy"; image.decoding = "async";
  image.dataset.icon = icon;
  return image;
}

export function presetDiagram(row, weapons, maxTier = row.columns) {
  const diagram = node("span", null, "loadout-cells");
  for (let tier = 1; tier <= maxTier; tier++) {
    const slot = node("span", null, "loadout-cell");
    const cells = row.cells.filter(cell => cell.tier === tier);
    if (cells.length) {
      slot.title = cells.map(cell => weapons.has(cell.weapon)
        ? `${weapons.get(cell.weapon).name} ×${cell.count}`
        : t("loadouts.otherEquipmentExcludedFromStrikeDamage", "其他装备 ×{{v0}}（不计入对地伤害）", {v0: cell.count})).join("\n");
      // Native tiers use the first image; subsequent blocks contribute to the tooltip.
      slot.append(ordnance(cells[0]));
    }
    diagram.append(slot);
  }
  return diagram;
}

// Assign indivisible projectiles across native tiers. A rack may supply several
// targets; keep each share instead of treating a weapon type as one target.
export function presetZoneAllocations(preset, plan) {
  const remaining = plan.map(items => new Map(items));
  return [...preset.cells].sort((a, b) => a.tier - b.tier).map(cell => {
    let count = cell.count;
    const zones = [];
    remaining.forEach((items, index) => {
      const assigned = Math.min(count, items.get(cell.weapon) || 0);
      if (!assigned) return;
      zones.push({zone: index + 1, count: assigned});
      count -= assigned;
      items.set(cell.weapon, items.get(cell.weapon) - assigned);
    });
    return {...cell, zones, remaining: count};
  });
}

export function renderPresetRows(container, rows, weapons, selectedId, allRows = rows) {
  container.replaceChildren();
  if (!rows.length) {
    container.append(node("p", t("loadouts.noMatchingPresetsTryAnotherWeaponTypeOrClear", "没有匹配的预设。试试其他弹种或清空搜索。"), "loadout-empty"));
    return;
  }
  const minTier = 1, maxTier = Math.max(...allRows.map(row => row.columns));
  container.style.setProperty("--tier-count", maxTier - minTier + 1);
  const heading = node("div", null, "loadout-table-head");
  heading.setAttribute("aria-hidden", "true");
  heading.append(node("span", t("loadouts.loadoutPreset", "挂载预设"), "loadout-row-name"));
  const ruler = node("span", null, "loadout-cells loadout-ruler");
  for (let tier = minTier; tier <= maxTier; tier++) ruler.append(node("span", String(tier)));
  heading.append(ruler); container.append(heading);
  for (const row of rows) {
    const title = presetTitle(row, weapons);
    const button = node("button", null, "loadout-row");
    button.type = "button"; button.dataset.presetId = row.id;
    button.setAttribute("role", "option");
    button.setAttribute("aria-selected", String(row.id === selectedId));
    button.setAttribute("aria-label", title + (row.other ? t("loadouts.includingOtherEquipment", "，含其他装备") : ""));
    button.tabIndex = row.id === selectedId ? 0 : -1;
    const label = node("span", null, "loadout-row-name");
    label.append(node("strong", title));
    if (row.other) label.append(node("small", t("loadouts.includesOtherEquipment", "含其他装备")));
    button.append(label);
    button.append(presetDiagram(row, weapons, maxTier)); container.append(button);
  }
}
