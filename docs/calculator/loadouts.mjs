// Presentation of complete preset rows. Cells are exported from game UI tiers;
// they are not aircraft geometry or a free-form loadout builder.
export function presetTitle(preset, weapons) {
  const contents = preset.weapons.map(([id, count]) => `${weapons.get(id)?.short || weapons.get(id)?.name || id} ×${count}`).join(" + ");
  return preset.customName ? `${preset.customName} · ${contents || "其他装备"}` : contents;
}

export function presetTotals(preset, weapons) {
  let damage = 0, mass = 0, count = 0;
  let knownDamage = true, knownMass = true;
  for (const [id, amount] of preset.weapons) {
    const weapon = weapons.get(id);
    count += amount;
    if (!(weapon?.dmg > 0)) knownDamage = false;
    else damage += weapon.dmg * amount;
    if (!(weapon?.kg > 0)) knownMass = false;
    else mass += weapon.kg * amount;
  }
  return { count, damage: knownDamage ? damage : null, mass: knownMass ? mass : null };
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

export function renderPresetRows(container, rows, weapons, selectedId, allRows = rows) {
  container.replaceChildren();
  if (!rows.length) {
    container.append(node("p", "没有匹配的预设。试试其他弹种或清空搜索。", "loadout-empty"));
    return;
  }
  const minTier = 1, maxTier = Math.max(...allRows.map(row => row.columns));
  container.style.setProperty("--tier-count", maxTier - minTier + 1);
  const heading = node("div", null, "loadout-table-head");
  heading.setAttribute("aria-hidden", "true");
  heading.append(node("span", "挂载预设", "loadout-row-name"));
  const ruler = node("span", null, "loadout-cells loadout-ruler");
  for (let tier = minTier; tier <= maxTier; tier++) ruler.append(node("span", String(tier)));
  heading.append(ruler); container.append(heading);
  for (const row of rows) {
    const title = presetTitle(row, weapons);
    const button = node("button", null, "loadout-row");
    button.type = "button"; button.dataset.presetId = row.id;
    button.setAttribute("role", "option");
    button.setAttribute("aria-selected", String(row.id === selectedId));
    button.setAttribute("aria-label", title + (row.other ? "，含其他装备" : ""));
    button.tabIndex = row.id === selectedId ? 0 : -1;
    const label = node("span", null, "loadout-row-name");
    label.append(node("strong", title));
    if (row.other) label.append(node("small", "含其他装备"));
    button.append(label);
    const diagram = node("span", null, "loadout-cells");
    for (let tier = minTier; tier <= maxTier; tier++) {
      const slot = node("span", null, "loadout-cell");
      const cells = row.cells.filter(cell => cell.tier === tier);
      if (cells.length) {
        slot.title = cells.map(cell => weapons.has(cell.weapon)
          ? `${weapons.get(cell.weapon).name} ×${cell.count}`
          : `其他装备 ×${cell.count}（不计入对地伤害）`).join("\n");
        // Native getPredefinedTiers keeps the first tier image; subsequent
        // weapon blocks on that tier contribute to its tooltip, not extra icons.
        slot.append(ordnance(cells[0]));
      }
      diagram.append(slot);
    }
    button.append(diagram); container.append(button);
  }
}
