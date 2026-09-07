import { compareLoadouts, durabilityBrBuckets, equivalentWeaponCount, explosiveConversion, requiredCount, returnFuelPlan, sharedParameterSource, sortiePlan } from "./model.mjs";
import { rankFuzzyMatches } from "./search.mjs";

const catalogUrl = "/api/v1/calculator/index.json";
const weaponsUrl = "/api/v1/calculator/weapons.json";
const aircraftUrl = "/api/v1/calculator/aircraft.json";
const defaultWeaponId = "us_1000lb_mk_83_ldgp";
const defaultBr = "14.7";

const brSelect = document.querySelector("#calcBr");
const targetSelect = document.querySelector("#calcTarget");
const kindSelect = document.querySelector("#calcKind");
const searchInput = document.querySelector("#calcSearch");
const aircraftSearchInput = document.querySelector("#calcAircraftSearch");
const aircraftClear = document.querySelector("#calcAircraftClear");
const aircraftList = document.querySelector("#calcAircraftList");
const aircraftSelection = document.querySelector("#calcAircraftSelection");
const weaponList = document.querySelector("#calcWeaponList");
const weaponSelection = document.querySelector("#calcWeaponSelection");
const hudContext = document.querySelector("#calcHudContext");
const destroyCountEl = document.querySelector("#calcDestroyCount");
const destroyLabelEl = document.querySelector("#calcDestroyLabel");
const sortieCountEl = document.querySelector("#calcSortieCount");
const fireLineEl = document.querySelector("#calcFireLine");
const statsEl = document.querySelector("#calcStats");
const hintEl = document.querySelector("#calcHint");
const repairNote = document.querySelector("#calcRepairNote");
const repairSummary = document.querySelector("#calcRepairSummary");
const repairDetail = document.querySelector("#calcRepairDetail");
const sourceEl = document.querySelector("#calcSource");
const compareContext = document.querySelector("#compareContext");
const compareTable = document.querySelector("#compareTable");
const compareRows = document.querySelector("#compareRows");
const fuelForm = document.querySelector("#fuelForm");
const fuelResult = document.querySelector("#fuelResult");
const conversionForm = document.querySelector("#conversionForm");
const chargeResult = document.querySelector("#chargeResult");
const chargeDamageResult = document.querySelector("#chargeDamageResult");
const chargeCount = document.querySelector("#chargeCount");
const chargeSides = conversionForm ? ["A", "B"].map(side => ({
  weapon: document.querySelector(`#chargeWeapon${side}`),
  type: document.querySelector(`#chargeType${side}`),
  mass: document.querySelector(`#chargeMass${side}`),
  factor: document.querySelector(`#chargeFactor${side}`),
  damage: document.querySelector(`#chargeDamage${side}`),
  source: document.querySelector(`#chargeSource${side}`),
  use: document.querySelector(`#chargeUse${side}`),
  loadedWeapon: null, customCharge: true, autoDamage: false, edited: false,
})) : [];

const KIND_LABELS = Object.freeze({ bomb: "炸弹", rocket: "火箭弹", missile: "导弹" });

let catalog = null;
let aircraftCatalog = [];
let visibleAircraft = [];
let visibleWeapons = [];
let visibleBrBuckets = [];
let selectedWeaponId = defaultWeaponId;
let selectedAircraftId = "";

function formatInt(value) {
  return Math.round(value).toLocaleString("zh-CN");
}

function formatQuantity(value) {
  if (value !== 0 && (Math.abs(value) < 0.001 || Math.abs(value) >= 1e12)) return value.toExponential(5);
  return value.toLocaleString("zh-CN", { maximumFractionDigits: 6 });
}

function inputNumber(input) {
  return input.value.trim() === "" ? NaN : Number(input.value);
}

function conversionText(tag, text, className) {
  const node = document.createElement(tag);
  node.textContent = text;
  if (className) node.className = className;
  return node;
}

function refreshChargeSource(side) {
  const weapon = side.loadedWeapon;
  const origin = weapon ? `${side.customCharge ? "修改自 " : ""}${weaponName(weapon)} · 原装药 ${weapon.charge?.type || "未提供"}` : "手动参数";
  const special = weapon?.damage_model && weapon.damage_model !== "splash_tnte_curve"
    ? "；特殊任务伤害模型，不能按 TNT 当量推算伤害" : "";
  side.source.textContent = `${origin} · ${side.customCharge ? "自定义装药参数" : "目录原始装药参数"}${special}。`;
}

function loadChargeWeapon(side, weapon) {
  side.loadedWeapon = weapon;
  side.customCharge = !weapon;
  side.weapon.value = weapon?.id || "";
  const charge = weapon?.charge;
  side.mass.value = charge?.mass_kg > 0 ? String(charge.mass_kg) : "";
  side.factor.value = charge?.strength_equivalent > 0 ? String(charge.strength_equivalent) : "";
  side.type.value = charge ? `${charge.type}:${charge.strength_equivalent}` : "";
  side.damage.value = weapon?.dmg > 0 ? String(weapon.dmg) : "";
  side.autoDamage = Boolean(weapon?.dmg > 0);
  refreshChargeSource(side);
  refreshConversion();
}

function editCharge(side) {
  side.customCharge = true;
  side.edited = true;
  // A catalog HP value belongs to the original weapon, not an edited filler.
  if (side.autoDamage) side.damage.value = "";
  side.autoDamage = false;
  refreshChargeSource(side);
  refreshConversion();
}

function fillConversionCatalog() {
  if (!conversionForm) return;
  const weapons = catalog.weapons;
  const presets = new Map([["tnt:1", { key: "tnt:1", type: "TNT", factor: 1 }]]);
  for (const weapon of weapons) {
    const charge = weapon.charge;
    if (charge?.type && Number.isFinite(charge.strength_equivalent) && charge.strength_equivalent > 0) {
      const key = `${charge.type}:${charge.strength_equivalent}`;
      presets.set(key, { key, type: charge.type, factor: charge.strength_equivalent });
    }
  }
  for (const [index, side] of chargeSides.entries()) {
    const previousType = side.type.value;
    fillSelect(side.weapon, [null, ...weapons], item => item?.id || "", item =>
      item ? `${weaponName(item)} · ${KIND_LABELS[item.kind] || item.kind}` : "自定义参数", "");
    fillSelect(side.type, [null, ...presets.values()], item => item?.key || "", item =>
      item ? `${item.type} · ×${formatQuantity(item.factor)}` : "自定义系数", previousType);
    side.use.disabled = false;
    if (!side.edited) loadChargeWeapon(side, weapons.find(item => item.id ===
      (index === 0 ? defaultWeaponId : "us_500lb_mk_82_ldgp")) || weapons.find(item => item.charge?.mass_kg > 0));
  }
}

function refreshConversion() {
  if (!conversionForm) return;
  const [a, b] = chargeSides;
  const sourceCount = inputNumber(chargeCount);
  const result = explosiveConversion({ sourceMassKg: inputNumber(a.mass), sourceFactor: inputNumber(a.factor),
    sourceCount, targetMassKg: inputNumber(b.mass), targetFactor: inputNumber(b.factor) });
  chargeResult.replaceChildren(conversionText("h3", "按 TNT 当量换算"));
  if (!result) {
    chargeResult.append(conversionText("p", "请填写两侧大于 0 的装药质量和 TNT 系数；A 的数量需为非负整数。空白、无效或超出计算范围的数值不会用于换算。"));
  } else {
    const q = formatQuantity;
    const summary = conversionText("p", `${q(sourceCount)} 枚 A ≈ ${q(result.exactCount)} 枚 B（按当量折算）；整枚换装至少需要 `);
    summary.append(conversionText("strong", `${q(result.wholeCount)} 枚 B`));
    chargeResult.append(summary);
    const formulas = document.createElement("div");
    formulas.className = "conversion-formulas";
    const lines = [
      `A 单枚当量 Eₐ = 装药质量 mₐ × TNT 系数 rₐ = ${q(inputNumber(a.mass))} kg × ${q(inputNumber(a.factor))} = ${q(result.sourceTntKg)} kg TNT`,
      `B 单枚当量 Eᵦ = mᵦ × rᵦ = ${q(inputNumber(b.mass))} kg × ${q(inputNumber(b.factor))} = ${q(result.targetTntKg)} kg TNT`,
      `A 总当量 = Nₐ × Eₐ = ${q(sourceCount)} × ${q(result.sourceTntKg)} = ${q(result.sourceTotal)} kg TNT`,
      `B 折算枚数 Nᵦ = Nₐ × Eₐ ÷ Eᵦ = ${q(result.sourceTotal)} ÷ ${q(result.targetTntKg)} ≈ ${q(result.exactCount)}；向上取整 ⌈Nᵦ⌉ = ${q(result.wholeCount)}`,
    ];
    for (const line of lines) {
      const row = document.createElement("p"); row.append(conversionText("code", line)); formulas.append(row);
    }
    chargeResult.append(formulas);
    const scale = Math.max(result.sourceTotal, result.targetTotal);
    for (const [side, label, value] of [["A", `A · ${q(sourceCount)} 枚`, result.sourceTotal], ["B", `B · ${q(result.wholeCount)} 枚（取整后）`, result.targetTotal]]) {
      const bar = document.createElement("div"), track = document.createElement("div"), fill = document.createElement("i");
      bar.className = "conversion-bar"; bar.dataset.side = side;
      fill.style.width = `${scale > 0 ? value / scale * 100 : 0}%`;
      track.setAttribute("aria-hidden", "true"); track.append(fill);
      bar.append(conversionText("span", `${label}：${q(value)} kg TNT`), track); chargeResult.append(bar);
    }
    chargeResult.append(conversionText("p", `整枚取整后多出 ${q(result.surplus)} kg TNT。当量相等不代表任务伤害相等；公式显示值经过缩写，取整使用完整精度。`));
  }
  const damage = equivalentWeaponCount({ sourcePerItem: inputNumber(a.damage), targetPerItem: inputNumber(b.damage), sourceCount });
  chargeDamageResult.replaceChildren(conversionText("strong", "按任务伤害换算（独立计算）"));
  const note = damage
    ? `Nᵦ = Nₐ × Dₐ ÷ Dᵦ = ${formatQuantity(sourceCount)} × ${formatQuantity(inputNumber(a.damage))} ÷ ${formatQuantity(inputNumber(b.damage))} ≈ ${formatQuantity(damage.exactCount)} 枚；向上取整为 ${formatQuantity(damage.wholeCount)} 枚 B。A 合计 ${formatQuantity(damage.sourceTotal)} HP，取整后 B 合计 ${formatQuantity(damage.targetTotal)} HP。${a.autoDamage && b.autoDamage ? "使用两种武器各自的目录任务伤害。" : "包含自定义 HP，仅按所填假设比较。"}`
    : "展开任务伤害参数，补充两侧有效的单枚 HP 后可单独比较。不会从自定义 TNT 当量猜测任务伤害。";
  chargeDamageResult.append(conversionText("p", note));
}

function bindConversion() {
  if (!conversionForm) return;
  conversionForm.addEventListener("submit", event => event.preventDefault());
  chargeCount.addEventListener("input", () => { chargeSides.forEach(side => { side.edited = true; }); refreshConversion(); });
  for (const side of chargeSides) {
    side.use.disabled = true;
    side.weapon.addEventListener("change", () => {
      side.edited = true;
      loadChargeWeapon(side, catalog?.weapons.find(item => item.id === side.weapon.value) || null);
    });
    side.use.addEventListener("click", () => { side.edited = true; loadChargeWeapon(side, selectedWeapon()); });
    side.type.addEventListener("change", () => {
      if (side.type.value) side.factor.value = side.type.value.slice(side.type.value.lastIndexOf(":") + 1);
      editCharge(side);
    });
    side.mass.addEventListener("input", () => editCharge(side));
    side.factor.addEventListener("input", () => { side.type.value = ""; editCharge(side); });
    side.damage.addEventListener("input", () => { side.autoDamage = false; side.edited = true; refreshConversion(); });
  }
  document.querySelector("#chargeSwap").addEventListener("click", () => {
    const [a, b] = chargeSides;
    for (const key of ["weapon", "type", "mass", "factor", "damage"]) [a[key].value, b[key].value] = [b[key].value, a[key].value];
    for (const key of ["loadedWeapon", "customCharge", "autoDamage"]) [a[key], b[key]] = [b[key], a[key]];
    chargeSides.forEach(side => { side.edited = true; refreshChargeSource(side); });
    refreshConversion();
  });
  refreshConversion();
}

function nextFrame() {
  return new Promise((resolve) => {
    if (typeof requestAnimationFrame === "function") requestAnimationFrame(resolve);
    else setTimeout(resolve, 0);
  });
}

function weaponDamage(weapon) {
  return weapon && typeof weapon.dmg === "number" ? weapon.dmg : 0;
}

function weaponName(weapon) {
  return weapon?.name || weapon?.id || "未知武器";
}

function fillSelect(select, items, getValue, getLabel, selected) {
  const fragment = document.createDocumentFragment();
  for (const item of items) {
    const option = document.createElement("option");
    option.value = getValue(item);
    option.textContent = getLabel(item);
    option.selected = option.value === selected;
    fragment.append(option);
  }
  select.replaceChildren(fragment);
}

function selectedAircraft() {
  return aircraftCatalog.find((item) => item.id === selectedAircraftId) || null;
}

function aircraftWeaponCapacity(aircraft, weaponId) {
  if (!aircraft || !Array.isArray(aircraft.w) || !Array.isArray(aircraft.n)) return null;
  const index = aircraft.w.indexOf(weaponId);
  const count = index >= 0 ? aircraft.n[index] : null;
  return Number.isInteger(count) && count > 0 ? count : null;
}

function matchingAircraft() {
  const query = aircraftSearchInput.value.trim();
  if (!query) return [];
  return rankFuzzyMatches(
    aircraftCatalog,
    query,
    (item) => [item.id, item.name, item.long || ""],
    24,
  );
}

function matchingWeapons() {
  const kind = kindSelect.value;
  const query = searchInput.value.trim();
  const aircraft = selectedAircraft();
  const allowed = aircraft ? new Set(aircraft.w) : null;
  const candidates = catalog.weapons.filter((weapon) =>
    (!allowed || allowed.has(weapon.id)) && (!kind || weapon.kind === kind));
  return rankFuzzyMatches(
    candidates,
    query,
    (weapon) => [weapon.id, weapon.name, KIND_LABELS[weapon.kind] || ""],
    80,
  );
}

function shouldShowWeaponResults() {
  return Boolean(selectedAircraftId || kindSelect.value || searchInput.value.trim());
}

function selectedWeapon() {
  if (!catalog) return null;
  if (shouldShowWeaponResults()) {
    return (
      visibleWeapons.find((weapon) => weapon.id === selectedWeaponId) ||
      visibleWeapons[0] ||
      null
    );
  }
  return (
    catalog.weapons.find((weapon) => weapon.id === selectedWeaponId) ||
    catalog.weapons[0] ||
    null
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

function targetTier(target, rank) {
  return target.kind === "bombing_point"
    ? tierFor(catalog.bombing_point_tiers, rank)
    : tierFor(catalog.airport_tiers, rank);
}

function targetHp(target, tier) {
  if (!tier) return 0;
  if (target.kind === "bombing_point") {
    return target.mode === "heli" ? tier.heli_mission_hp : tier.planes_mission_hp;
  }
  return target.module === "airfield" ? tier.runway_mission_hp : tier.auxiliary_module_mission_hp;
}

function targetTiers(target) {
  return target.kind === "bombing_point" ? catalog.bombing_point_tiers : catalog.airport_tiers;
}

function renderBrOptions(selectedBr = defaultBr) {
  const target = selectedTarget();
  const currentRank = balanceLevel(selectedBr);
  visibleBrBuckets = durabilityBrBuckets(catalog.br_values, targetTiers(target));
  const selectedBucket = visibleBrBuckets.find((bucket) =>
    currentRank >= bucket.startIndex && currentRank <= bucket.endIndex) || visibleBrBuckets.at(-1);
  fillSelect(
    brSelect,
    visibleBrBuckets,
    (bucket) => bucket.value,
    (bucket) => {
      const range = bucket.minBr === bucket.maxBr ? bucket.minBr : `${bucket.minBr}–${bucket.maxBr}`;
      return `${range} · ${formatInt(targetHp(target, bucket.tier))} HP`;
    },
    selectedBucket?.value || defaultBr,
  );
}

function selectedBrRange() {
  const bucket = visibleBrBuckets.find((item) => item.value === brSelect.value);
  if (!bucket) return brSelect.value || defaultBr;
  return bucket.minBr === bucket.maxBr ? bucket.minBr : `${bucket.minBr}–${bucket.maxBr}`;
}

function appendStat(label, value) {
  const term = document.createElement("dt");
  term.textContent = label;
  const detail = document.createElement("dd");
  detail.textContent = value;
  statsEl.append(term, detail);
}

function selectionContent(container, title, detail) {
  const strong = document.createElement("strong");
  strong.textContent = title;
  const span = document.createElement("span");
  span.textContent = detail;
  container.replaceChildren(strong, span);
}

function renderAircraftSelection() {
  const aircraft = selectedAircraft();
  if (!aircraft) {
    selectionContent(aircraftSelection, "不限机型", "先按目标枚数计算");
    aircraftClear.disabled = true;
    return;
  }
  selectionContent(
    aircraftSelection,
    aircraft.name,
    `${aircraft.w.length} 种可用武器${aircraft.m ? ` · 最大挂载质量 ${formatInt(aircraft.m)} kg` : ""}`,
  );
  aircraftClear.disabled = false;
}

function renderAircraftList() {
  visibleAircraft = matchingAircraft();
  if (!aircraftSearchInput.value.trim()) {
    const empty = document.createElement("p");
    empty.className = "hangar-weapon-empty";
    empty.textContent = "输入名称开始搜索，支持简称和模糊匹配。";
    aircraftList.replaceChildren(empty);
    return;
  }
  if (!visibleAircraft.length) {
    const empty = document.createElement("p");
    empty.className = "hangar-weapon-empty";
    empty.textContent = "没有找到机型，换个简称试试。";
    aircraftList.replaceChildren(empty);
    return;
  }
  const fragment = document.createDocumentFragment();
  for (const item of visibleAircraft) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "hangar-weapon";
    button.setAttribute("role", "option");
    button.dataset.aircraftId = item.id;
    const selected = item.id === selectedAircraftId;
    button.setAttribute("aria-selected", selected ? "true" : "false");
    if (selected) button.classList.add("is-selected");
    const name = document.createElement("span");
    name.className = "hangar-weapon-name";
    name.textContent = item.name;
    const detail = document.createElement("span");
    detail.className = "hangar-weapon-kind";
    detail.textContent = `${item.w.length} 种挂载`;
    button.append(name, detail);
    fragment.append(button);
  }
  aircraftList.replaceChildren(fragment);
}

function renderWeaponSelection() {
  const weapon = selectedWeapon();
  if (!weapon) {
    selectionContent(weaponSelection, "没有可用武器", "调整机型、种类或搜索词");
    return;
  }
  const capacity = aircraftWeaponCapacity(selectedAircraft(), weapon.id);
  selectionContent(
    weaponSelection,
    weaponName(weapon),
    `${KIND_LABELS[weapon.kind] || weapon.kind}${capacity ? ` · 单次最多 ${capacity} 枚` : ""}`,
  );
}

function renderWeaponList() {
  if (!shouldShowWeaponResults()) {
    const empty = document.createElement("p");
    empty.className = "hangar-weapon-empty";
    empty.textContent = "输入武器名，或先选机型 / 种类。";
    weaponList.replaceChildren(empty);
    renderWeaponSelection();
    return;
  }
  if (!visibleWeapons.length) {
    const empty = document.createElement("p");
    empty.className = "hangar-weapon-empty";
    empty.textContent = "当前筛选下没有可用武器。";
    weaponList.replaceChildren(empty);
    renderWeaponSelection();
    return;
  }
  const aircraft = selectedAircraft();
  const fragment = document.createDocumentFragment();
  for (const weapon of visibleWeapons) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "hangar-weapon";
    button.setAttribute("role", "option");
    button.dataset.weaponId = weapon.id;
    const selected = weapon.id === selectedWeaponId;
    button.setAttribute("aria-selected", selected ? "true" : "false");
    if (selected) button.classList.add("is-selected");
    const name = document.createElement("span");
    name.className = "hangar-weapon-name";
    name.textContent = weaponName(weapon);
    const detail = document.createElement("span");
    detail.className = "hangar-weapon-kind";
    const capacity = aircraftWeaponCapacity(aircraft, weapon.id);
    detail.textContent = capacity ? `${capacity} 枚/次` : KIND_LABELS[weapon.kind] || weapon.kind;
    button.append(name, detail);
    fragment.append(button);
  }
  weaponList.replaceChildren(fragment);
  renderWeaponSelection();
}

function refreshWeapons() {
  if (!catalog) return;
  visibleWeapons = matchingWeapons();
  if (shouldShowWeaponResults() && !visibleWeapons.some((weapon) => weapon.id === selectedWeaponId)) {
    selectedWeaponId = visibleWeapons[0]?.id || "";
  }
  renderWeaponList();
  refreshResult();
}

function renderRepairNote(target, tier) {
  const airport = target.kind === "airport_module";
  repairNote.hidden = !airport;
  if (!airport || !tier) return;
  repairSummary.textContent = "生活区状态影响模块恢复；本页按不计回血估算，实战可能需要更多弹药。";
  const base = Number(tier.repair_base_hp || 0);
  repairDetail.textContent = base > 0
    ? `当前 BR 每次机场修复轮询约 +${formatInt(base / 10)}～+${formatInt(base)} HP；跑道与其他模块每轮加值相同。`
    : "跑道与其他模块每轮加值相同。";
}

function setHudUnknown(context, hint) {
  hudContext.textContent = context;
  destroyCountEl.textContent = "—";
  destroyLabelEl.textContent = "无法估算";
  sortieCountEl.textContent = "—";
  fireLineEl.textContent = "";
  statsEl.replaceChildren();
  hintEl.textContent = hint;
}

function renderComparison(target, tier) {
  // An already cached pre-toolbox HTML page may load the new shared script.
  if (!compareRows) return;
  const aircraft = selectedAircraft();
  const hp = targetHp(target, tier);
  const threshold = target.has_fire ? hp * (1 - catalog.hp_fire_mult) : hp;
  const rows = compareLoadouts({ aircraft, weapons: catalog.weapons, hp: threshold });
  compareTable.hidden = rows.length === 0;
  compareContext.textContent = aircraft
    ? `${aircraft.name} · ${target.label} · BR ${selectedBrRange()} · ${rows.length} 种有伤害数据的挂载`
    : "先在上方选择机型，即可对比它的全部可用挂载。";
  const fragment = document.createDocumentFragment();
  for (const row of rows) {
    const tr = document.createElement("tr");
    tr.dataset.selected = String(row.weapon.id === selectedWeaponId);
    const weaponCell = document.createElement("td");
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.weaponId = row.weapon.id;
    button.textContent = weaponName(row.weapon);
    button.title = "选择此武器并查看详细计算";
    weaponCell.append(button);
    tr.append(weaponCell);
    for (const value of [row.required, row.capacity, `${row.targetsPerLoad}${row.remaining ? `（余 ${row.remaining} 枚）` : ""}`, row.sorties, row.massKg === null ? "未知" : `${formatInt(row.massKg)} kg`]) {
      const td = document.createElement("td");
      td.textContent = String(value);
      tr.append(td);
    }
    fragment.append(tr);
  }
  compareRows.replaceChildren(fragment);
}

function refreshFuel() {
  const number = (id) => {
    const input = document.querySelector(id);
    if (input.validity.badInput) return NaN;
    return input.value.trim() === "" ? null : input.valueAsNumber;
  };
  const plan = returnFuelPlan({
    fuelKg: number("#fuelKg"), burnKgMin: number("#fuelBurn"),
    groundSpeedKmh: number("#fuelSpeed"), distanceKm: number("#fuelDistance"),
    routePercent: number("#fuelRoute"), reserveMin: number("#fuelReserve"),
  });
  fuelResult.replaceChildren();
  fuelResult.dataset.deficit = String(plan?.marginKg !== null && plan?.marginKg < 0);
  const note = document.createElement("p");
  if (!plan) {
    note.textContent = "填入有效的油耗、地速、距离与储备；空白输入不会当作零。当前燃油可留空。";
    fuelResult.append(note);
    return;
  }
  const dl = document.createElement("dl");
  for (const [label, value] of [["预计航程时间", `${plan.tripMin.toFixed(1)} min`], ["航程耗油", `${formatInt(plan.tripKg)} kg`], ["到达后储备", `${formatInt(plan.reserveKg)} kg`], ["合计所需", `${formatInt(plan.requiredKg)} kg`]]) {
    const group = document.createElement("div");
    const dt = document.createElement("dt");
    const dd = document.createElement("dd");
    dt.textContent = label;
    dd.textContent = value;
    group.append(dt, dd);
    dl.append(group);
  }
  note.textContent = plan.marginKg === null
    ? "补充当前燃油可查看余量。以上按所填油耗和地速保持不变估算。"
    : `扣除航程和储备后${plan.marginKg < 0 ? "缺少" : "剩余"} ${formatInt(Math.abs(plan.marginKg))} kg。仅按所填工况估算，油门、天气与航线改变后需要重算。`;
  fuelResult.append(dl, note);
}

function refreshResult() {
  if (!catalog) return;
  const weapon = selectedWeapon();
  const target = selectedTarget();
  const br = brSelect.value || defaultBr;
  const rank = balanceLevel(br);
  const tier = targetTier(target, rank);
  renderRepairNote(target, tier);
  renderComparison(target, tier);
  const aircraft = selectedAircraft();
  const brRange = selectedBrRange();
  const context = aircraft
    ? `${target.label} · BR ${brRange} · ${aircraft.name}`
    : `${target.label} · BR ${brRange}`;
  if (!weapon || !target) {
    setHudUnknown(context, "调整机型、种类或搜索词。");
    return;
  }
  const hp = targetHp(target, tier);
  if (!(hp > 0)) {
    setHudUnknown(context, "这一档没有耐久数据。");
    return;
  }
  const damage = weaponDamage(weapon);
  if (!(damage > 0)) {
    setHudUnknown(context, `${weaponName(weapon)} 暂时没有可用的任务伤害数据。`);
    return;
  }

  const destroyCount = requiredCount(hp, damage);
  const fireCount = target.has_fire
    ? requiredCount(hp * (1 - catalog.hp_fire_mult), damage)
    : null;
  const practicalCount = fireCount === null ? destroyCount : Math.min(destroyCount, fireCount);
  hudContext.textContent = context;
  destroyCountEl.textContent = String(practicalCount);
  destroyLabelEl.textContent = target.kind === "airport_module"
    ? "满血摧毁（不计回血）"
    : fireCount < destroyCount ? "点燃 / 自毁" : "满血摧毁";
  fireLineEl.textContent = fireCount !== null && fireCount < destroyCount
    ? `直接打空需要 ${destroyCount} 枚`
    : "";
  statsEl.replaceChildren();
  appendStat("武器", weaponName(weapon));
  appendStat("每枚伤害", formatInt(damage));
  appendStat("目标耐久", formatInt(hp));

  const capacity = aircraftWeaponCapacity(aircraft, weapon.id);
  const plan = aircraft && capacity
    ? sortiePlan({ required: practicalCount, capacity, damage, reward: catalog.reward })
    : null;
  if (plan) {
    sortieCountEl.textContent = String(plan.sorties);
    appendStat("单次上限", `${plan.capacity} 枚`);
    appendStat("预计出击", `${plan.sorties} 次`);
    if (plan.sorties > 1) appendStat("末次所需", `${plan.lastSortieCount} 枚`);
    if (plan.fullLoadReward !== null) appendStat("满载收益系数", plan.fullLoadReward.toFixed(1));
    hintEl.textContent = target.kind === "airport_module"
      ? `按 ${plan.capacity} 枚/次需要 ${plan.sorties} 次；机场回血可能让实战多一轮。`
      : `${aircraft.name} 每次最多 ${plan.capacity} 枚，约 ${plan.sorties} 次。`;
  } else {
    sortieCountEl.textContent = "—";
    appendStat("机型", "未选择");
    hintEl.textContent = target.kind === "airport_module"
      ? "选择机型后显示挂载上限和架次；机场结果不含投弹间回血。"
      : "选择机型后显示挂载上限、满载收益系数和架次。";
  }
}

async function loadJson(url) {
  const response = await fetch(url, { cache: "no-cache" });
  if (!response.ok) throw new Error(`http_${response.status}`);
  return response.json();
}

async function boot() {
  try {
    const [catalogBody, weaponsBody, aircraftBody] = await Promise.all([
      loadJson(catalogUrl),
      loadJson(weaponsUrl),
      loadJson(aircraftUrl),
    ]);
    const source = sharedParameterSource([catalogBody, weaponsBody, aircraftBody]);
    if (!source) throw new Error("mixed_parameter_sources");
    catalog = catalogBody;
    catalog.weapons = weaponsBody.weapons || [];
    aircraftCatalog = (aircraftBody.aircraft || []).filter((item) =>
      Array.isArray(item.w) && Array.isArray(item.n) && item.w.length === item.n.length &&
      item.n.every((count) => Number.isInteger(count) && count > 0));
    if (sourceEl) sourceEl.textContent = `${source.kind === "local-client" ? "客户端提取" : "WTdatamine"} ${source.version} · ${aircraftCatalog.length.toLocaleString("zh-CN")} 种机型挂载 · ${catalog.weapons.length} 种武器 · 随 Bomana 发布更新`;
    fillSelect(targetSelect, catalog.targets, (target) => target.id, (target) => target.label, catalog.targets[0].id);
    renderBrOptions(defaultBr);
    visibleWeapons = matchingWeapons();
    renderAircraftSelection();
    renderAircraftList();
    renderWeaponList();
    refreshResult();
    fillConversionCatalog();
    await nextFrame();
  } catch {
    catalog = null;
    if (sourceEl) sourceEl.textContent = "数据未就绪：目录加载失败或来源版本不一致，请刷新后重试。";
    setHudUnknown("目录加载失败", "未使用缺失或混合版本的数据，刷新页面后再试。");
  }
}

aircraftList.addEventListener("click", (event) => {
  const button = event.target.closest("[data-aircraft-id]");
  if (!button || !aircraftList.contains(button)) return;
  selectedAircraftId = button.dataset.aircraftId;
  const aircraft = selectedAircraft();
  aircraftSearchInput.value = aircraft?.name || "";
  renderAircraftSelection();
  renderAircraftList();
  refreshWeapons();
});

compareRows?.addEventListener("click", (event) => {
  const button = event.target.closest("[data-weapon-id]");
  if (!button || !compareRows.contains(button)) return;
  selectedWeaponId = button.dataset.weaponId;
  kindSelect.value = "";
  searchInput.value = "";
  refreshWeapons();
  weaponSelection.scrollIntoView({ behavior: "smooth", block: "center" });
});

fuelForm?.addEventListener("submit", (event) => event.preventDefault());
fuelForm?.addEventListener("input", refreshFuel);

aircraftClear.addEventListener("click", () => {
  selectedAircraftId = "";
  aircraftSearchInput.value = "";
  renderAircraftSelection();
  renderAircraftList();
  refreshWeapons();
});

weaponList.addEventListener("click", (event) => {
  const button = event.target.closest("[data-weapon-id]");
  if (!button || !weaponList.contains(button)) return;
  selectedWeaponId = button.dataset.weaponId;
  renderWeaponList();
  refreshResult();
});

weaponList.addEventListener("keydown", (event) => {
  if (!visibleWeapons.length) return;
  const index = Math.max(0, visibleWeapons.findIndex((weapon) => weapon.id === selectedWeaponId));
  const offset = event.key === "ArrowDown" ? 1 : event.key === "ArrowUp" ? -1 : 0;
  if (!offset) return;
  const next = Math.max(0, Math.min(visibleWeapons.length - 1, index + offset));
  if (next === index) return;
  event.preventDefault();
  selectedWeaponId = visibleWeapons[next].id;
  renderWeaponList();
  refreshResult();
});

brSelect.addEventListener("change", refreshResult);
targetSelect.addEventListener("change", () => {
  if (!catalog) return;
  renderBrOptions(brSelect.value || defaultBr);
  refreshResult();
});
kindSelect.addEventListener("change", refreshWeapons);
searchInput.addEventListener("input", refreshWeapons);
aircraftSearchInput.addEventListener("input", renderAircraftList);

bindConversion();
boot();
