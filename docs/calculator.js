const catalogUrl = "ec-calculator.json";
const defaultWeaponId = "us_1000lb_mk_83_ldgp";
const defaultBr = "14.7";

const brSelect = document.querySelector("#calcBr");
const targetSelect = document.querySelector("#calcTarget");
const kindSelect = document.querySelector("#calcKind");
const searchInput = document.querySelector("#calcSearch");
const weaponList = document.querySelector("#calcWeaponList");
const hudContext = document.querySelector("#calcHudContext");
const destroyCountEl = document.querySelector("#calcDestroyCount");
const destroyLabelEl = document.querySelector("#calcDestroyLabel");
const fireLineEl = document.querySelector("#calcFireLine");
const statsEl = document.querySelector("#calcStats");
const hintEl = document.querySelector("#calcHint");

const KIND_LABELS = {
  bomb: "炸弹",
  rocket: "火箭弹",
  missile: "导弹",
};

let catalog = null;
let visibleWeapons = [];
let selectedWeaponId = defaultWeaponId;

function requiredCount(hp, damage) {
  return Math.max(1, Math.ceil(hp / damage - 1e-9));
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
  return (
    visibleWeapons.find((weapon) => weapon.id === selectedWeaponId) || visibleWeapons[0] || null
  );
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

function interpolate(points, value) {
  if (!points || points.length < 2) {
    return 0;
  }
  if (value <= points[0][0]) {
    return points[0][1];
  }
  if (value >= points[points.length - 1][0]) {
    return points[points.length - 1][1];
  }
  for (let index = 0; index < points.length - 1; index += 1) {
    const [x0, y0] = points[index];
    const [x1, y1] = points[index + 1];
    if (value >= x0 && value <= x1) {
      if (x1 === x0) {
        return y1;
      }
      return y0 + ((value - x0) * (y1 - y0)) / (x1 - x0);
    }
  }
  return points[points.length - 1][1];
}

function rewardUi(totalDamage) {
  const reward = catalog.reward;
  if (!reward || totalDamage <= 0) {
    return null;
  }
  const floor = reward.piecewise_linear[0][0];
  let multiplier;
  if (totalDamage >= floor) {
    multiplier = interpolate(reward.piecewise_linear, totalDamage);
  } else {
    const span = reward.preset_dmg_max - reward.preset_dmg_min;
    const scale =
      1 + ((reward.bombing_reward_modifier - 1) * (totalDamage - reward.preset_dmg_min)) / span;
    multiplier = Math.min((scale * reward.preset_dmg_min) / totalDamage, 1);
  }
  return multiplier * reward.ui_decoration;
}

function appendStat(label, value) {
  const term = document.createElement("dt");
  term.textContent = label;
  const detail = document.createElement("dd");
  detail.textContent = value;
  statsEl.append(term, detail);
}

function renderWeaponList() {
  weaponList.replaceChildren();
  if (!visibleWeapons.length) {
    const empty = document.createElement("p");
    empty.className = "hangar-weapon-empty";
    empty.textContent = "没有匹配的武器";
    weaponList.append(empty);
    return;
  }
  for (const weapon of visibleWeapons) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "hangar-weapon";
    button.setAttribute("role", "option");
    button.dataset.weaponId = weapon.id;
    const selected = weapon.id === selectedWeaponId;
    button.setAttribute("aria-selected", selected ? "true" : "false");
    if (selected) {
      button.classList.add("is-selected");
    }
    const name = document.createElement("span");
    name.className = "hangar-weapon-name";
    name.textContent = weapon.name_zh || weapon.name;
    const kind = document.createElement("span");
    kind.className = "hangar-weapon-kind";
    kind.textContent = KIND_LABELS[weapon.kind] || weapon.kind;
    button.append(name, kind);
    button.addEventListener("click", () => {
      selectedWeaponId = weapon.id;
      renderWeaponList();
      refreshResult();
    });
    weaponList.append(button);
  }
  const active = weaponList.querySelector(".is-selected");
  if (active && typeof active.scrollIntoView === "function") {
    active.scrollIntoView({ block: "nearest" });
  }
}

function refreshWeapons() {
  visibleWeapons = matchingWeapons();
  if (visibleWeapons.length && !visibleWeapons.some((weapon) => weapon.id === selectedWeaponId)) {
    selectedWeaponId = visibleWeapons[0].id;
  }
  renderWeaponList();
  refreshResult();
}

function setHudUnknown(context, hint) {
  hudContext.textContent = context;
  destroyCountEl.textContent = "—";
  destroyLabelEl.textContent = "无法估算";
  fireLineEl.textContent = "";
  statsEl.replaceChildren();
  hintEl.textContent = hint;
}

function refreshResult() {
  if (!catalog) {
    return;
  }
  const weapon = selectedWeapon();
  const target = selectedTarget();
  const br = brSelect.value;
  if (!weapon || !target) {
    setHudUnknown("没有匹配的武器", "换一个搜索词，或把种类改回全部。");
    return;
  }
  const rank = balanceLevel(br);
  const hp = targetHp(target, rank);
  const context = `${target.label}  ·  BR ${br}`;
  if (!(weapon.hangar_damage > 0)) {
    setHudUnknown(
      context,
      `${weapon.name_zh || weapon.name} 暂时算不出对战区伤害。`,
    );
    return;
  }

  const damage = weapon.hangar_damage;
  const destroyCount = requiredCount(hp, damage);
  hudContext.textContent = context;
  destroyCountEl.textContent = String(destroyCount);
  destroyLabelEl.textContent = "摧毁所需";
  statsEl.replaceChildren();
  appendStat("武器", weapon.name_zh || weapon.name);
  appendStat("每枚伤害", formatInt(damage));
  appendStat("目标耐久", formatInt(hp));
  const total = damage * destroyCount;
  const reward = rewardUi(total);
  if (reward !== null) {
    appendStat("收益系数", reward.toFixed(1));
  }

  if (target.has_fire) {
    const fireHp = hp * (1 - catalog.hp_fire_mult);
    const fireCount = requiredCount(fireHp, damage);
    fireLineEl.textContent = `点燃 ${fireCount} 枚`;
    hintEl.textContent = "打到大约九成会起火。数字是满额命中。";
  } else {
    fireLineEl.textContent = "";
    hintEl.textContent = "机场会回血，连续投弹时可能要多带几枚。";
  }
}

async function boot() {
  const response = await fetch(catalogUrl, { headers: { Accept: "application/json" } });
  if (!response.ok) {
    setHudUnknown("目录加载失败", "请稍后刷新页面。");
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

weaponList.addEventListener("keydown", (event) => {
  if (!visibleWeapons.length) {
    return;
  }
  const index = Math.max(
    0,
    visibleWeapons.findIndex((weapon) => weapon.id === selectedWeaponId),
  );
  if (event.key === "ArrowDown" && index < visibleWeapons.length - 1) {
    event.preventDefault();
    selectedWeaponId = visibleWeapons[index + 1].id;
    renderWeaponList();
    refreshResult();
  } else if (event.key === "ArrowUp" && index > 0) {
    event.preventDefault();
    selectedWeaponId = visibleWeapons[index - 1].id;
    renderWeaponList();
    refreshResult();
  }
});

brSelect.addEventListener("change", refreshResult);
targetSelect.addEventListener("change", refreshResult);
kindSelect.addEventListener("change", refreshWeapons);
searchInput.addEventListener("input", refreshWeapons);

boot();
