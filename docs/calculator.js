const catalogUrl = "ec-calculator.json";
const defaultWeaponId = "us_1000lb_mk_83_ldgp";
const defaultBr = "14.7";

const brSelect = document.querySelector("#calcBr");
const targetSelect = document.querySelector("#calcTarget");
const kindSelect = document.querySelector("#calcKind");
const searchInput = document.querySelector("#calcSearch");
const weaponSelect = document.querySelector("#calcWeapon");
const metaEl = document.querySelector("#calcMeta");
const titleEl = document.querySelector("#calcTitle");
const detailEl = document.querySelector("#calcDetail");

const KIND_LABELS = {
  bomb: "炸弹",
  rocket: "火箭弹",
  missile: "导弹",
};

let catalog = null;
let visibleWeapons = [];

function requiredCount(hp, damage) {
  return Math.max(1, Math.ceil(hp / damage - 1e-9));
}

function missionHpFromTnte(tnteKg, hpToTntTons) {
  return tnteKg / (hpToTntTons * 1000);
}

function formatInt(value) {
  return Math.round(value).toLocaleString("zh-CN");
}

function fillSelect(select, items, getValue, getLabel, selected) {
  select.replaceChildren();
  for (const item of items) {
    const option = document.createElement("option");
    option.value = getValue(item);
    option.textContent = getLabel(item);
    if (option.value === selected) {
      option.selected = true;
    }
    select.append(option);
  }
}

function matchingWeapons() {
  const kind = kindSelect.value;
  const needle = searchInput.value.trim().toLowerCase();
  return catalog.weapons.filter((weapon) => {
    if (kind && weapon.kind !== kind) {
      return false;
    }
    if (!needle) {
      return true;
    }
    const haystack = [
      weapon.id,
      weapon.name,
      weapon.name_zh,
      weapon.explosive_type,
      KIND_LABELS[weapon.kind] || "",
    ]
      .join(" ")
      .toLowerCase();
    return haystack.includes(needle);
  });
}

function selectedWeapon() {
  return visibleWeapons.find((weapon) => weapon.id === weaponSelect.value) || visibleWeapons[0];
}

function selectedTarget() {
  return catalog.targets.find((target) => target.id === targetSelect.value) || catalog.targets[0];
}

function balanceLevel(brText) {
  const index = catalog.br_values.indexOf(brText);
  return index >= 0 ? index : catalog.br_values.length - 1;
}

function tierFor(tiers, rank) {
  return tiers.find((tier) => rank >= tier.balance_level[0] && rank <= tier.balance_level[1]);
}

function targetHp(target, rank) {
  if (target.kind === "bombing_point") {
    const tier = tierFor(catalog.bombing_point_tiers, rank);
    return target.mode === "heli" ? tier.heli_mission_hp : tier.planes_mission_hp;
  }
  const tier = tierFor(catalog.airport_tiers, rank);
  return target.module === "airfield" ? tier.runway_mission_hp : tier.auxiliary_module_mission_hp;
}

function refreshWeapons() {
  const previous = weaponSelect.value || defaultWeaponId;
  visibleWeapons = matchingWeapons();
  fillSelect(
    weaponSelect,
    visibleWeapons,
    (weapon) => weapon.id,
    (weapon) => `${weapon.name_zh}  ·  ${KIND_LABELS[weapon.kind]}  ·  ${weapon.id}`,
    previous,
  );
  if (visibleWeapons.length && !visibleWeapons.some((weapon) => weapon.id === weaponSelect.value)) {
    weaponSelect.value = visibleWeapons[0].id;
  }
  refreshResult();
}

function refreshResult() {
  if (!catalog) {
    return;
  }
  const weapon = selectedWeapon();
  const target = selectedTarget();
  const br = brSelect.value;
  const rank = balanceLevel(br);
  if (!weapon || !target) {
    titleEl.textContent = "没有匹配的武器";
    detailEl.textContent = "换一个搜索词，或把种类改回全部。";
    return;
  }
  const hp = targetHp(target, rank);
  metaEl.textContent = `${catalog.app_version} · ${visibleWeapons.length} / ${catalog.weapons.length} 种武器`;

  if (weapon.model !== "tnt_equivalent") {
    titleEl.textContent = "所需枚数：原生未知";
    const reason =
      weapon.model === "unsupported_napalm"
        ? "燃烧弹 / napalm 不走 HP↔TNT 当量公式。"
        : "该武器没有可用的 explosiveMass 与 strengthEquivalent。";
    detailEl.textContent = [
      `${weapon.name_zh} · ${weapon.id}`,
      `房间最高 BR ${br} → maxRank ${rank}`,
      `目标满血：${formatInt(hp)} mission_hp`,
      reason,
    ].join("\n");
    return;
  }

  const tnte = weapon.explosive_mass_kg * weapon.strength_equivalent;
  const damage = missionHpFromTnte(tnte, catalog.hp_to_tnt_equivalent_tons);
  const destroyCount = requiredCount(hp, damage);
  let title = `摧毁：${destroyCount} 枚`;
  const lines = [
    `${weapon.name_zh} · ${weapon.id}`,
    `房间最高 BR ${br} → maxRank ${rank}`,
    `目标满血：${formatInt(hp)} mission_hp（静态精确）`,
    `满额命中每枚 ${damage.toFixed(2)} mission_hp（${weapon.explosive_mass_kg} kg × ${weapon.strength_equivalent} TNT 当量，1 kg TNT = 8 HP）`,
  ];
  if (target.has_fire) {
    const fireHp = hp * (1 - catalog.hp_fire_mult);
    const fireCount = requiredCount(fireHp, damage);
    title = `摧毁：${destroyCount} 枚 · 触发燃烧：${fireCount} 枚`;
    lines.push(
      `战区燃烧参考：直接造成 ${formatInt(fireHp)} HP（90%）后触发；约 3 秒燃尽仅为参数推断。`,
    );
  } else {
    lines.push("机场模块未发现 90% 后燃烧自毁逻辑；必须按满血直接伤害计算。");
  }
  lines.push("这是满额命中当量，不是距离衰减的溅射曲线。");
  titleEl.textContent = title;
  detailEl.textContent = lines.join("\n");
}

async function boot() {
  const response = await fetch(catalogUrl, { headers: { Accept: "application/json" } });
  if (!response.ok) {
    titleEl.textContent = "目录加载失败";
    detailEl.textContent = "请稍后刷新页面。";
    return;
  }
  catalog = await response.json();
  fillSelect(brSelect, catalog.br_values, (value) => value, (value) => value, defaultBr);
  fillSelect(
    targetSelect,
    catalog.targets,
    (target) => target.id,
    (target) => target.label,
    catalog.targets[0].id,
  );
  refreshWeapons();
}

brSelect.addEventListener("change", refreshResult);
targetSelect.addEventListener("change", refreshResult);
kindSelect.addEventListener("change", refreshWeapons);
searchInput.addEventListener("input", refreshWeapons);
weaponSelect.addEventListener("change", refreshResult);

boot();
