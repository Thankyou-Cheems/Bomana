import { airfieldDefenseMassAssessment, airportBarPositions, airportRepairVisit, airportPaletteBands, compareLoadouts, durabilityBrBuckets, equivalentWeaponCount, explosiveConversion, requiredCount, returnFuelPlan, rewardUi, sharedParameterSource, sortiePlan, usefulActionsReferences, usefulActionsReference, usefulActionsPlan, usefulActionsObservedFraction, usefulActionsCardRate, usefulActionsCurve } from "./model.mjs";
import { rankFuzzyMatches } from "./search.mjs";
import { readableVehicle } from "./vehicle-names.mjs";
import { presetTitle, presetTotals, renderPresetRows } from "./loadouts.mjs";
import { createCombinationCalculator } from "./combination-ui.mjs";
import { createCustomLoadoutEditor } from "./custom-loadout-ui.mjs";
import { createLoadoutOptimizer } from "./optimizer-ui.mjs";
import { combinationTotals } from "./custom-loadouts.mjs";
import { initAirCalculator } from "./air-ui.mjs";
import { renderRewardChart, renderConversionChart, renderAirportRepairChart, renderAirportBars } from "./charts.mjs";

const catalogUrl = "/api/v1/calculator/index.json";
const weaponsUrl = "/api/v1/calculator/weapons.json";
const aircraftUrl = "/api/v1/calculator/aircraft.json";
const rewardsUrl = "/api/v1/calculator/rewards.json";
const defaultWeaponId = "us_1000lb_mk_83_ldgp";
const defaultBr = "14.7";

const directory = document.querySelector(".tool-directory");
const directoryToggle = document.querySelector("#toolDirectoryToggle");
const directoryLinks = [...directory.querySelectorAll("a")];
const closeDirectory = () => directoryToggle.setAttribute("aria-expanded", "false");
directoryToggle.addEventListener("click", () => directoryToggle.setAttribute("aria-expanded", String(directoryToggle.getAttribute("aria-expanded") !== "true")));
directory.addEventListener("click", event => {
  const link = event.target.closest("a");
  if (!link) return;
  const target = document.querySelector(link.hash);
  if (target?.tagName === "DETAILS") target.open = true;
  closeDirectory();
});
document.addEventListener("click", event => { if (!directory.contains(event.target)) closeDirectory(); });
directory.addEventListener("keydown", event => { if (event.key === "Escape") { closeDirectory(); directoryToggle.focus(); } });
const markDirectoryLocation = () => {
  const location = window.location.hash || "#calcForm";
  for (const link of directoryLinks) {
    if (link.hash === location) link.setAttribute("aria-current", "location");
    else link.removeAttribute("aria-current");
  }
};
window.addEventListener("hashchange", markDirectoryLocation);
markDirectoryLocation();

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
const repairPercent = document.querySelector("#repairPercent");
const defenseSelection = document.querySelector("#defenseSelection");
let defenseCatalogVersion = null;

function refreshDefenseSelection(weapon) {
  if (!defenseSelection) return;
  if (!weapon) {
    defenseSelection.textContent = "在上方选择武器后，可对照本节两种防空的质量筛选窗。";
    return;
  }
  const state = airfieldDefenseMassAssessment({ massKg: weapon.kg, sourceVersion: defenseCatalogVersion });
  if (state === "version_mismatch") {
    defenseSelection.textContent = `防空研究为 2.59.0.13；当前武器目录为 ${defenseCatalogVersion || "未知版本"}，暂不关联弹种判断。`;
    return;
  }
  if (state === "unknown_mass") {
    defenseSelection.textContent = "所选武器缺少整弹质量，无法对照拦截筛选窗。";
    return;
  }
  defenseSelection.textContent = `${weaponName(weapon)} · 整弹 ${formatQuantity(weapon.kg)} kg：${state === "outside_mass_windows"
    ? "不落入本节 ItO 90M 与 ZA-35 的弹药优先级质量窗。这里只核对静态质量条件，不代表所有机场防空都忽略它。"
    : "落入本节弹药优先级的质量范围；小型、滑翔或重型标签都不能单独证明免拦截。是否被选中还取决于制导组件、速度、航迹、探测与其他目标。"}`;
}
let airportDiagramAngle = 270;
function refreshAirportDiagram() {
  if (!catalog) return;
  for (const [id, offset] of [["airportDiagram", 0], ["airportDiagramReversed", 180]]) {
    const container = document.getElementById(id), angle = (airportDiagramAngle + offset) % 360;
    if (container) renderAirportBars(container, airportBarPositions(catalog.airport_display, angle), angle);
  }
}
for (const button of document.querySelectorAll("[data-airport-rotate]")) button.addEventListener("click", () => {
  airportDiagramAngle = (airportDiagramAngle + Number(button.dataset.airportRotate)) % 360;
  refreshAirportDiagram();
});
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
  search: document.querySelector(`#chargeSearch${side}`),
  custom: document.querySelector(`#chargeCustom${side}`),
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
let selectedPresetId = "";
let customPreview = null;
let visiblePresets = [];
let loadoutRequest = null;
let loadoutState = "idle";
const presetList = document.querySelector("#calcPresetList");
const combination = createCombinationCalculator(document.querySelector("#combinationCalculator"));
let customRequest = null;
const customOnly = document.querySelector("#calcCustomOnly");
const onlyCustomAircraft = () => customOnly.getAttribute("aria-pressed") === "true";
function loadCustomRules() {
  return customRequest ||= loadJson("/api/v1/calculator/custom-loadouts.json").then(body => {
    if (!sharedParameterSource([catalog, body])) throw new Error("mixed_custom_source");
    return body;
  }).catch(error => { customRequest = null; throw error; });
}
const customEditor = createCustomLoadoutEditor(document.querySelector("#customLoadoutEditor"), {
  preview: snapshot => { customPreview = snapshot; refreshResult(); },
  load: loadCustomRules,
  apply: (unitId, preset, select) => {
    const aircraft = aircraftCatalog.find(row => row.id === unitId);
    aircraft.presets = [...(aircraft.presets || []).filter(row => row.id !== preset.id), preset];
    if (select) { searchInput.value = ""; kindSelect.value = ""; choosePreset(preset.id); }
    else renderPresets();
  },
  remove: (unitId, id) => {
    const aircraft = aircraftCatalog.find(row => row.id === unitId);
    aircraft.presets = (aircraft.presets || []).filter(row => row.id !== id);
    if (selectedPresetId === id) selectedPresetId = aircraft.presets[0]?.id || "";
    refreshWeapons();
  },
});
const optimizer = createLoadoutOptimizer(document.querySelector("#loadoutOptimizer"), {
  load: loadCustomRules,
  apply: result => result.kind === "custom" ? customEditor.recommend(result.keys) : choosePreset(result.presetId),
});
let rewardsCatalog = null;
let rewardSelectedVehicle = "f_15e";
const rewardsForm = document.querySelector("#rewardsForm");
const rewardFields = Object.fromEntries(["Mode", "Search", "Vehicle", "Score", "Minutes", "SlRate", "Method", "Fraction", "Observed", "RpRate", "RpFraction", "Account", "Booster"].map(key => [key, document.querySelector(`#reward${key}`)]));
const rewardResult = document.querySelector("#rewardResult");
const rewardManualRate = document.querySelector("#rewardManualRate");
const rewardSlider = document.querySelector("#rewardScoreSlider");

function rewardVehicle() {
  return rewardsCatalog?.vehicles.find(row => row.id === rewardSelectedVehicle && row.mode === rewardFields.Mode.value);
}

function renderRewardVehicles() {
  if (!rewardsCatalog) return;
  const rows = rewardsCatalog.vehicles.filter(row => row.mode === rewardFields.Mode.value);
  const query = rewardFields.Search.value.trim();
  const matches = query ? rankFuzzyMatches(rows, query, row => [row.id, row.name, row.name_en, row.countryName, ...row.searchTerms]).slice(0, 100) : rows.slice(0, 100);
  let selected = rewardVehicle();
  if (!selected && rows.length) { selected = rows[0]; rewardSelectedVehicle = selected.id; }
  if (selected && !matches.some(row => row.id === selected.id)) matches.unshift(selected);
  fillSelect(rewardFields.Vehicle, matches, row => row.id, row => row.name, rewardSelectedVehicle);
}

function loadRewardVehicle() {
  rewardManualRate.checked = false;
  rewardFields.Method.value = "reference";
  for (const key of ["Fraction", "Observed", "RpRate", "RpFraction"]) rewardFields[key].value = "";
  refreshReward();
}

function rewardCardReference() {
  const row = rewardVehicle(), params = rewardsCatalog?.card_parameters;
  return usefulActionsCardRate({ rawRate: row?.sl_per_min, special: row?.special,
    premiumAccount: rewardFields.Account.value === "premium", boosterPercent: inputNumber(rewardFields.Booster),
    premiumMultiplier: params?.premium_account_multiplier, premiumVisualPart: params?.premium_visual_part });
}

function renderRewardReference() {
  const sample = usefulActionsReferences[rewardFields.Mode.value];
  const note = document.querySelector("#rewardReferenceNote");
  note.replaceChildren(conversionText("span", `${sample.label}。${sample.basis === "immediate" ? "比例为即时 SL / 卡片整周期基准，未代表活动率。" : "比例为着陆拆分前的 SL / 卡片整周期基准。"} `));
  const link = conversionText("a", "查看原始实测"); link.href = sample.url; note.append(link);
  const rows = document.querySelector("#rewardReferenceRows"); rows.replaceChildren();
  sample.points.forEach(([score, fraction], index) => {
    const row = document.createElement("tr");
    for (const text of [String(score), `${(fraction * 100).toFixed(2)}%`, index ? `+${((fraction - sample.points[index - 1][1]) * 100).toFixed(2)} 个百分点` : "—"]) row.append(conversionText("td", text));
    rows.append(row);
  });
}

function refreshReward() {
  if (!rewardsForm || !rewardsCatalog) return;
  const mode = rewardFields.Mode.value, rules = rewardsCatalog.mechanics[mode], row = rewardVehicle();
  const method = rewardFields.Method.value, card = rewardCardReference();
  const manualRate = rewardManualRate.checked;
  if (!manualRate) rewardFields.SlRate.value = card ? String(card.rate) : "";
  rewardFields.SlRate.disabled = !manualRate;
  rewardFields.Account.disabled = manualRate;
  rewardFields.Booster.disabled = manualRate;
  rewardFields.Account.title = manualRate ? "正在使用手填卡片值；账号加成已包含在该值中" : "";
  if (method === "reference") rewardFields.Minutes.value = String(rules.period_minutes);
  const minutes = inputNumber(rewardFields.Minutes), score = inputNumber(rewardFields.Score), slRate = inputNumber(rewardFields.SlRate);
  for (const [field, visible] of [["Minutes", method !== "reference"], ["Fraction", method === "manual"], ["Observed", method === "observed"]]) {
    document.querySelector(`#reward${field}Field`).hidden = !visible;
    rewardFields[field].disabled = !visible;
  }
  rewardSlider.max = String(Number.isFinite(score) ? Math.max(1200, score) : 1200);
  rewardSlider.value = String(Number.isFinite(score) ? Math.max(0, score) : 0);
  for (const button of document.querySelectorAll("button[data-score]")) button.setAttribute("aria-pressed", String(Number(button.dataset.score) === score));
  document.querySelector("#rewardPeriod").textContent = `${formatQuantity(minutes)} 分钟内`;
  document.querySelector("#rewardChartPeriod").textContent = "横轴：本周期得分";
  const quality = document.querySelector(".reference-pill");
  quality.textContent = `${method === "reference" ? "2024 历史实测参考" : method === "observed" ? "你的实战记录" : "自定义比例参考"}${manualRate ? " · 手填卡片基准" : ""} · 实际到账以游戏为准`;
  const origin = document.querySelector("#rewardSource");
  origin.textContent = row ? `${row.name} · 客户端 ${rewardsCatalog.source.version} 基准 ${formatQuantity(row.sl_per_min)} SL/min${row.special ? " · 高级载具" : ""} · 载具研发倍率 ×${row.rp_multiplier ?? "未知"}（不是 RP/min）${manualRate ? " · 使用手填卡片值" : ""}` : "未选择有效收益机型";
  const preview = document.querySelector("#rewardCardPreview"); preview.replaceChildren();
  if (card) preview.append(conversionText("code", `客户端卡片参考：${formatQuantity(card.visualBase)} × ${formatQuantity(card.visualMultiplier)} × (1 + ${formatQuantity(card.accountBonus)} + ${formatQuantity(card.boosterBonus)}) = ${formatQuantity(card.rate)} SL/min`));
  else preview.textContent = "卡片基准参数缺失或输入无效，请核对加成器效果。";
  rewardResult.replaceChildren();
  const formulas = document.querySelector("#rewardFormula"); formulas.replaceChildren();
  let basis = mode === "air_sim" ? "before_landing_split" : "immediate";
  let fraction = inputNumber(rewardFields.Fraction) / 100;
  let unavailable = "在展开区填写已核验的收益比例后计算。";
  if (method === "reference") {
    const ref = usefulActionsReference({ mode, score, minutes, vehicleId: rewardSelectedVehicle });
    fraction = ref?.fraction ?? NaN; basis = ref?.basis ?? basis;
    unavailable = mode === "air_sim" ? "当前得分超出 200–1050 分的历史样本范围，不外推收益。" : rewardSelectedVehicle !== "ka_52" ? "这台直升机还没有可用的得分实测曲线，不能套用 Ka-52 的结果。" : "当前得分超出 Ka-52 的 200–800 分样本范围，不外推收益。";
  } else if (method === "observed") {
    fraction = usefulActionsObservedFraction({ slReceived: inputNumber(rewardFields.Observed), slRate, minutes, immediateShare: mode === "air_sim" ? rules.immediate_share : 1 }) ?? NaN;
    unavailable = fraction > 1 ? `反算比例为 ${formatQuantity(fraction * 100)}%，超过 100%；请核对卡片加成、周期时间和奖励口径。` : "填入这次有用行动实际即时到账的 SL，即可核对记录。";
  }
  const rpRate = rewardFields.RpRate.value.trim() ? inputNumber(rewardFields.RpRate) : null;
  const rpFraction = rewardFields.RpFraction.value.trim() ? inputNumber(rewardFields.RpFraction) / 100 : null;
  const plan = usefulActionsPlan({ periodMinutes: rules.period_minutes, minutes, score, slRate, rpRate, rpFraction, fraction, basis, immediateShare: rules.immediate_share });
  const curve = method === "reference" ? usefulActionsCurve({ mode, vehicleId: rewardSelectedVehicle, minutes,
    periodMinutes: rules.period_minutes, slRate, immediateShare: rules.immediate_share, score }) : null;
  renderRewardChart(document.querySelector("#rewardChart"), curve,
    method !== "reference" ? "实战核对与自定义比例只计算本条记录，不生成得分曲线。切回历史样本估算可查看曲线。" : !Number.isFinite(slRate) || slRate <= 0 ? "卡片基准无效，暂时无法绘制收益图。" : "这台机型暂无可用得分曲线，可展开高级选项核对实战记录。");
  document.querySelector("#rewardChartHint").textContent = curve ? `${curve.hasLanding ? "蓝色为即时部分，金色为成功着陆后追加部分。" : "仅展示即时 SL，不套用空战的着陆分成。"}拖动得分可看变化；曲线仅覆盖已有样本，灰区没有估算。` : "样本和服务器公式缺失时保留未知，不以卡片最大值代替实际到账。";
  if (!plan) {
    if (!Number.isFinite(score) || score < 0) unavailable = "请填写本周期新增任务分数，不能使用负数。";
    else if (!Number.isFinite(minutes) || minutes <= 0 || minutes > rules.period_minutes) unavailable = `本周期时长须大于 0 且不超过 ${rules.period_minutes} 分钟。`;
    else if (!Number.isFinite(slRate) || slRate <= 0) unavailable = manualRate ? "请填写大于 0 的 SL/min 基准。" : "机型基准或加成器输入无效，请在高级选项中核对。";
    else if (rpRate !== null && (!Number.isFinite(rpRate) || rpRate <= 0)) unavailable = "RP/min 基准须大于 0；未知时请留空。";
    else if (rpFraction !== null && (!Number.isFinite(rpFraction) || rpFraction < 0 || rpFraction > 1)) unavailable = "RP 有效收益比例须在 0–100% 之间；未知时请留空。";
    else if (method === "manual" && (fraction < 0 || fraction > 1)) unavailable = "有效收益比例须在 0–100% 之间；请先核对每分钟基准。";
    rewardResult.append(conversionText("h3", "暂不能估算这次收益"), conversionText("p", unavailable));
    if (Number.isFinite(slRate * rules.period_minutes) && slRate > 0) rewardResult.append(conversionText("p", `卡片整周期基准为 ${formatInt(slRate * rules.period_minutes)} SL，不是实际到账预测。`, "tool-note"));
    return;
  }
  rewardResult.append(conversionText("p", `${formatQuantity(score)} 分 · ${formatQuantity(minutes)} 分钟${method === "observed" ? " · 本次记录" : " · 参考收益"}`, "reward-context"));
  const stats = document.createElement("dl"); stats.className = "reward-stats";
  const add = (label, value) => { const pair = document.createElement("div"); pair.append(conversionText("dt", label), conversionText("dd", value)); stats.append(pair); };
  add(method === "observed" ? "已即时到账 · SL" : "即时获得约 · SL", formatInt(plan.slImmediate));
  if (plan.slDeferred !== null) add("成功着陆后追加约 · SL", `+ ${formatInt(plan.slDeferred)}`);
  if (plan.rpImmediate !== null) add("即时 RP · 自填参考", formatInt(plan.rpImmediate));
  if (plan.rpDeferred !== null) add("着陆 RP · 自填参考", `+ ${formatInt(plan.rpDeferred)}`);
  rewardResult.append(stats);
  if (plan.slDeferred !== null) rewardResult.append(conversionText("p", `本周期含着陆份额合计约 ${formatInt(plan.slImmediate + plan.slDeferred)} SL`, "reward-total"));
  const formula = document.createElement("p");
  formula.append(conversionText("code", `即时 SL ≈ ${formatQuantity(slRate)} SL/min × ${formatQuantity(minutes)} min × ${(fraction * 100).toFixed(2)}%${basis === "before_landing_split" ? " × 80%" : "（比例已含即时份额）"}`)); formulas.append(formula);
  if (plan.rpImmediate !== null) {
    const rpFormula = document.createElement("p");
    rpFormula.append(conversionText("code", `即时 RP ≈ ${formatQuantity(rpRate)} RP/min × ${formatQuantity(minutes)} min × ${formatQuantity(rpFraction * 100)}%${basis === "before_landing_split" ? " × 80%" : "（RP 比例已含即时份额）"}`)); formulas.append(rpFormula);
  }
  if (method === "observed") formulas.append(conversionText("p", `本条记录为 ${formatQuantity(score)} 分 → ${formatQuantity(inputNumber(rewardFields.Observed))} 即时 SL；每分 ${score > 0 ? formatQuantity(inputNumber(rewardFields.Observed) / score) : "无法计算"} SL 只描述这条记录，不能线性外推。`));
  rewardResult.append(conversionText("p", `${minutes < rules.period_minutes ? "不足整周期仅作算术核对，死亡与退场规则未验证。" : ""}不含维修、出场费与胜负结算。${mode === "heli_pve" ? "直升机战后奖励未知。" : "着陆份额需满足成功机场着陆条件。"}`, "tool-note"));
}

function bindRewards() {
  rewardsForm?.addEventListener("submit", event => event.preventDefault());
  rewardFields.Account?.addEventListener("change", refreshReward);
  rewardFields.Booster?.addEventListener("input", refreshReward);
  rewardManualRate?.addEventListener("change", refreshReward);
  rewardSlider?.addEventListener("input", () => { rewardFields.Score.value = rewardSlider.value; refreshReward(); });
  for (const button of document.querySelectorAll("button[data-score]")) button.addEventListener("click", () => { rewardFields.Score.value = button.dataset.score; refreshReward(); });
  rewardFields.Search?.addEventListener("input", renderRewardVehicles);
  rewardFields.Vehicle?.addEventListener("change", () => { rewardSelectedVehicle = rewardFields.Vehicle.value; loadRewardVehicle(); });
  rewardFields.Mode?.addEventListener("change", () => {
    rewardSelectedVehicle = rewardFields.Mode.value === "air_sim" ? "f_15e" : "ka_52";
    rewardFields.Search.value = "";
    const period = rewardsCatalog?.mechanics[rewardFields.Mode.value]?.period_minutes;
    if (period) rewardFields.Minutes.max = String(period);
    renderRewardVehicles(); loadRewardVehicle(); renderRewardReference();
  });
  for (const key of ["Score", "Minutes", "SlRate", "Method", "Fraction", "Observed", "RpRate", "RpFraction"]) rewardFields[key]?.addEventListener(key === "Method" ? "change" : "input", refreshReward);
}

function formatInt(value) {
  return Math.round(value).toLocaleString("zh-CN");
}

function formatQuantity(value) {
  if (value !== 0 && (Math.abs(value) < 0.001 || Math.abs(value) >= 1e12)) return value.toExponential(5);
  return value.toLocaleString("zh-CN", { maximumFractionDigits: 6 });
}

function formatApproximate(value) {
  if (value !== 0 && Math.abs(value) < 0.01) return value.toExponential(2);
  return value.toLocaleString("zh-CN", { maximumFractionDigits: 2 });
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
  const weapon = side.loadedWeapon, mass = inputNumber(side.mass), factor = inputNumber(side.factor);
  const equivalent = mass * factor;
  const amount = mass > 0 && factor > 0 && Number.isFinite(equivalent)
    ? `${formatQuantity(equivalent)} kg TNT / 枚` : "装药数据缺失，可展开自填";
  const special = weapon?.damage_model && weapon.damage_model !== "splash_tnte_curve"
    ? " · 特殊任务伤害模型，请勿按当量推算伤害" : "";
  side.source.textContent = `${side.customCharge ? "自定义装药" : "目录自动读取"} · ${amount}${special}`;
}

function renderChargeWeapons(side) {
  const weapons = catalog?.weapons ?? [], query = side.search.value.trim();
  const matches = query ? rankFuzzyMatches(weapons, query, item => [item.id, item.name, item.name_en]).slice(0, 100) : [...weapons];
  if (side.loadedWeapon && !matches.some(item => item.id === side.loadedWeapon.id)) matches.unshift(side.loadedWeapon);
  fillSelect(side.weapon, [null, ...matches], item => item?.id || "", item =>
    item ? `${weaponName(item)} · ${KIND_LABELS[item.kind] || item.kind}` : "自定义装药", side.customCharge ? "" : side.loadedWeapon?.id || "");
}

function loadChargeWeapon(side, weapon) {
  side.loadedWeapon = weapon;
  side.customCharge = !weapon;
  if (weapon) {
    const charge = weapon.charge;
    side.mass.value = charge?.mass_kg > 0 ? String(charge.mass_kg) : "";
    side.factor.value = charge?.strength_equivalent > 0 ? String(charge.strength_equivalent) : "";
    side.type.value = charge ? `${charge.type}:${charge.strength_equivalent}` : "";
  }
  // Choosing custom keeps the shown filler as a starting point, but clears HP.
  side.damage.value = weapon?.dmg > 0 ? String(weapon.dmg) : "";
  side.autoDamage = Boolean(weapon?.dmg > 0);
  if (!weapon || !side.mass.value || !side.factor.value) side.custom.open = true;
  renderChargeWeapons(side);
  refreshChargeSource(side);
  refreshConversion();
}

function editCharge(side) {
  side.customCharge = true;
  side.edited = true;
  side.weapon.value = "";
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
    renderChargeWeapons(side);
    fillSelect(side.type, [null, ...presets.values()], item => item?.key || "", item =>
      item ? `${item.type} · ×${formatQuantity(item.factor)}` : "自定义系数", previousType);
    side.use.disabled = false;
    if (!side.edited) loadChargeWeapon(side, weapons.find(item => item.id ===
      (index === 0 ? defaultWeaponId : "us_500lb_mk_82_ldgp")) || weapons.find(item => item.charge?.mass_kg > 0));
  }
}

function refreshConversion() {
  if (!conversionForm) return;
  const [a, b] = chargeSides, q = formatQuantity;
  const sourceCount = inputNumber(chargeCount);
  const result = explosiveConversion({ sourceMassKg: inputNumber(a.mass), sourceFactor: inputNumber(a.factor),
    sourceCount, targetMassKg: inputNumber(b.mass), targetFactor: inputNumber(b.factor) });
  const formulas = document.querySelector("#chargeFormula"); formulas.replaceChildren();
  chargeResult.replaceChildren();
  if (!result) {
    chargeResult.append(conversionText("h3", "暂不能换算"), conversionText("p", "请选择两种有装药数据的武器，或展开自定义参数，填写大于 0 的装药质量和 TNT 系数；A 的数量需为非负整数。"));
  } else {
    const name = (side, label) => side.customCharge ? `自定义装药 ${label}` : weaponName(side.loadedWeapon);
    const headline = conversionText("p", "整枚换装需要 ", "conversion-headline");
    headline.append(conversionText("strong", `${q(result.wholeCount)} 枚 B`));
    chargeResult.append(headline,
      conversionText("p", `${q(sourceCount)} 枚 ${name(a, "A")} ≈ ${formatApproximate(result.exactCount)} 枚 ${name(b, "B")}`, "conversion-equation"));
    const chart = document.createElement("div"); chart.className = "conversion-chart"; chargeResult.append(chart);
    renderConversionChart(chart, result, sourceCount);
    chargeResult.append(conversionText("p", `整枚取整后多出 ${formatApproximate(result.surplus)} kg TNT`, "conversion-surplus"));
    const quick = document.createElement("p"); quick.className = "conversion-quick-formula";
    quick.append(conversionText("code", `${q(result.sourceTotal)} kg TNT ÷ ${q(result.targetTntKg)} kg TNT/枚 ≈ ${formatApproximate(result.exactCount)} 枚 B`)); chargeResult.append(quick);
    for (const line of [
      `A 单枚当量 Eₐ = 装药质量 mₐ × TNT 系数 rₐ = ${q(inputNumber(a.mass))} kg × ${q(inputNumber(a.factor))} = ${q(result.sourceTntKg)} kg TNT`,
      `B 单枚当量 Eᵦ = mᵦ × rᵦ = ${q(inputNumber(b.mass))} kg × ${q(inputNumber(b.factor))} = ${q(result.targetTntKg)} kg TNT`,
      `A 总当量 = Nₐ × Eₐ = ${q(sourceCount)} × ${q(result.sourceTntKg)} = ${q(result.sourceTotal)} kg TNT`,
      `B 折算枚数 Nᵦ = Nₐ × Eₐ ÷ Eᵦ = ${q(result.sourceTotal)} ÷ ${q(result.targetTntKg)} ≈ ${q(result.exactCount)}；向上取整 ⌈Nᵦ⌉ = ${q(result.wholeCount)}`,
    ]) {
      const row = document.createElement("p"); row.append(conversionText("code", line)); formulas.append(row);
    }
  }
  document.querySelector("#chargeLess").disabled = !Number.isSafeInteger(sourceCount) || sourceCount <= 0;
  document.querySelector("#chargeMore").disabled = !Number.isSafeInteger(sourceCount) || sourceCount < 0 || sourceCount === Number.MAX_SAFE_INTEGER;
  const damage = equivalentWeaponCount({ sourcePerItem: inputNumber(a.damage), targetPerItem: inputNumber(b.damage), sourceCount });
  chargeDamageResult.replaceChildren(conversionText("strong", "按任务伤害换算（独立计算）"));
  const note = damage
    ? `Nᵦ = Nₐ × Dₐ ÷ Dᵦ = ${q(sourceCount)} × ${q(inputNumber(a.damage))} ÷ ${q(inputNumber(b.damage))} ≈ ${q(damage.exactCount)} 枚；向上取整为 ${q(damage.wholeCount)} 枚 B。A 合计 ${q(damage.sourceTotal)} HP，取整后 B 合计 ${q(damage.targetTotal)} HP。${a.autoDamage && b.autoDamage ? "使用两种武器各自的目录任务伤害。" : "包含自定义 HP，仅按所填假设比较。"}`
    : "补充两侧有效的单枚 HP 后可单独比较。不会从自定义 TNT 当量猜测任务伤害。";
  chargeDamageResult.append(conversionText("p", note));
}

function bindConversion() {
  if (!conversionForm) return;
  conversionForm.addEventListener("submit", event => event.preventDefault());
  chargeCount.addEventListener("input", refreshConversion);
  for (const [id, delta] of [["chargeLess", -1], ["chargeMore", 1]]) document.querySelector(`#${id}`).addEventListener("click", () => {
    const count = inputNumber(chargeCount);
    if (Number.isSafeInteger(count) && count + delta >= 0 && Number.isSafeInteger(count + delta)) { chargeCount.value = String(count + delta); refreshConversion(); }
  });
  for (const side of chargeSides) {
    side.use.disabled = true;
    side.search.addEventListener("input", () => renderChargeWeapons(side));
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
    for (const key of ["type", "mass", "factor", "damage"]) [a[key].value, b[key].value] = [b[key].value, a[key].value];
    for (const key of ["loadedWeapon", "customCharge", "autoDamage"]) [a[key], b[key]] = [b[key], a[key]];
    chargeSides.forEach(side => {
      side.edited = true; side.search.value = ""; renderChargeWeapons(side); refreshChargeSource(side);
      if (side.customCharge) side.custom.open = true;
    });
    refreshConversion();
  });
  window.addEventListener("resize", () => { refreshReward(); refreshConversion(); });
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

function selectedPreset() {
  return selectedAircraft()?.presets?.find(row => row.id === selectedPresetId) || null;
}

function currentWeaponCapacity(aircraft, weaponId) {
  const preset = selectedPreset();
  return preset ? preset.weapons.find(([id]) => id === weaponId)?.[1] || null
    : aircraftWeaponCapacity(aircraft, weaponId);
}

function renderPresets() {
  const aircraft = selectedAircraft(), rows = aircraft?.presets || [];
  document.querySelector("#calcPresetPanel").hidden = !rows.length;
  document.querySelector("#calcLoadoutCaption").textContent = loadoutState === "loading"
    ? "正在读取挂载排列…" : loadoutState === "error" ? "挂载排列未就绪，请重新选择机型重试；仍可按单一武器计算"
    : rows.length
    ? "每一行是一套游戏预设；选择后按实际弹数计算"
    : aircraft ? "该机型暂无可用预设排列，可按单一武器查看上限" : "先选机型查看挂载网格，也可直接搜索武器";
  const weapons = new Map(catalog.weapons.map(row => [row.id, row]));
  const allowed = new Set(matchingWeapons(Number.POSITIVE_INFINITY).map(row => row.id));
  visiblePresets = rows.filter(row => row.weapons.some(([id]) => allowed.has(id)) || row.customName && !row.weapons.length);
  if (selectedPresetId && !visiblePresets.some(row => row.id === selectedPresetId)) {
    selectedPresetId = visiblePresets[0]?.id || "";
  }
  const preset = selectedPreset();
  if (preset && !preset.weapons.some(([id]) => id === selectedWeaponId)) selectedWeaponId = preset.weapons[0]?.[0] || "";
  if (rows.length) renderPresetRows(presetList, visiblePresets, weapons, selectedPresetId, rows);
  document.querySelector("#calcPresetCount").textContent = `${visiblePresets.length} / ${rows.length} 套预设`;
}

async function loadAircraftPresets() {
  if (!selectedAircraft()) return;
  if (!loadoutRequest) {
    loadoutState = "loading"; renderPresets();
    loadoutRequest = loadJson("/api/v1/calculator/loadouts.json").then(body => {
      if (!sharedParameterSource([catalog, body])) throw new Error("mixed_loadout_source");
      for (const aircraft of aircraftCatalog) aircraft.presets = [...(body.aircraft[aircraft.id] || []), ...(aircraft.presets || []).filter(row => row.customName)];
      loadoutState = "ready";
    }).catch(() => { loadoutState = "error"; loadoutRequest = null; });
  }
  await loadoutRequest;
  const aircraft = selectedAircraft();
  if (!aircraft?.presets?.some(row => row.id === selectedPresetId)) selectedPresetId = aircraft?.presets?.[0]?.id || "";
  document.querySelector("#calcIndividualWeapons").open = !selectedPresetId;
  refreshWeapons();
}

function renderPresetDetail(preset) {
  document.querySelector("#calcPresetDetail").hidden = !preset;
  if (!preset) return;
  const weapons = new Map(catalog.weapons.map(row => [row.id, row]));
  document.querySelector("#calcPresetTitle").textContent = presetTitle(preset, weapons);
  const totals = presetTotals(preset, weapons);
  const target = selectedTarget();
  const combined = combinationTotals(preset.weapons, weapons, targetHp(target, targetTier(target, balanceLevel(brSelect.value || defaultBr))));
  const stats = document.querySelector("#calcPresetStats"); stats.replaceChildren();
  for (const [label, value] of [
    ["弹药总重", totals.mass === null ? "未知" : `${formatQuantity(totals.mass)} kg`],
    ["总 TNT 当量", combined?.tnt == null ? "未知" : `${formatQuantity(combined.tnt)} kg`],
    ["整套伤害", totals.damage === null ? "未知" : `${formatInt(totals.damage)} HP`],
  ]) stats.append(conversionText("dt", label), conversionText("dd", value));
  document.querySelector("#calcPresetNote").textContent = preset.other ? "含其他装备；上方仅统计可计算的对地弹药。" : "";
}

function choosePreset(id, focus = false) {
  customPreview = null;
  selectedPresetId = id;
  const row = selectedPreset();
  if (!row) return;
  if (!row.weapons.some(([weapon]) => weapon === selectedWeaponId)) selectedWeaponId = row.weapons[0]?.[0] || "";
  document.querySelector("#calcIndividualWeapons").open = false;
  renderPresets(); renderWeaponList(); refreshResult();
  if (focus) [...presetList.querySelectorAll("[data-preset-id]")].find(button => button.dataset.presetId === id)?.focus();
}

function matchingAircraft() {
  const query = aircraftSearchInput.value.trim();
  const candidates = onlyCustomAircraft() ? aircraftCatalog.filter(item => item.custom) : aircraftCatalog;
  if (!query) return onlyCustomAircraft() ? candidates : [];
  return rankFuzzyMatches(
    candidates,
    query,
    (item) => [item.id, item.name, item.long || "", item.countryName, ...item.searchTerms],
    24,
  );
}

function matchingWeapons(limit = 80) {
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
    limit,
  );
}

function shouldShowWeaponResults() {
  return Boolean(selectedAircraftId || kindSelect.value || searchInput.value.trim());
}

function selectedWeapon() {
  if (!catalog) return null;
  if (selectedPreset()) return catalog.weapons.find(weapon => weapon.id === selectedWeaponId) || null;
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
  renderSegments(brSelect, document.querySelector("#calcBrSegments"));
}

const targetSegmentNames = {
  bombing_point_planes: "战区基地", bombing_point_heli: "直升机基地",
  airport_airfield: "机场跑道", airport_storage: "油库", airport_parking: "停机区", airport_dwelling: "生活区",
};

function renderSegments(select, track) {
  track.replaceChildren();
  const thumb = document.createElement("span"); thumb.className = "segment-thumb"; thumb.setAttribute("aria-hidden", "true");
  track.append(thumb); track.style.setProperty("--segments", select.options.length);
  for (const option of select.options) {
    const button = document.createElement("button"); button.type = "button";
    button.setAttribute("role", "radio"); button.dataset.value = option.value;
    button.setAttribute("aria-label", option.textContent);
    const [title, detail] = select === brSelect ? option.textContent.split(" · ") : [targetSegmentNames[option.value] || option.textContent];
    button.append(conversionText("span", title));
    if (detail) button.append(conversionText("small", detail));
    track.append(button);
  }
  syncSegments(select, track);
  requestAnimationFrame(() => revealSegment(track.querySelector('[aria-checked="true"]')));
}

function revealSegment(button) {
  const scroller = button.closest(".segment-scroll");
  const bounds = scroller.getBoundingClientRect(), selected = button.getBoundingClientRect();
  if (selected.left < bounds.left) scroller.scrollLeft -= bounds.left - selected.left;
  else if (selected.right > bounds.right) scroller.scrollLeft += selected.right - bounds.right;
}

function syncSegments(select, track) {
  track.style.setProperty("--selected-segment", Math.max(0, select.selectedIndex));
  for (const button of track.querySelectorAll("button")) {
    const active = button.dataset.value === select.value;
    button.setAttribute("aria-checked", String(active)); button.tabIndex = active ? 0 : -1;
  }
}

for (const [select, trackId] of [[brSelect, "calcBrSegments"], [targetSelect, "calcTargetSegments"]]) {
  const track = document.getElementById(trackId);
  const choose = button => {
    select.value = button.dataset.value;
    syncSegments(select, track);
    select.dispatchEvent(new Event("change", { bubbles: true }));
    revealSegment(button);
  };
  track.addEventListener("click", event => { const button = event.target.closest("button"); if (button) choose(button); });
  track.addEventListener("keydown", event => {
    const buttons = [...track.querySelectorAll("button")], index = buttons.indexOf(event.target);
    if (index < 0) return;
    const next = event.key === "Home" ? 0 : event.key === "End" ? buttons.length - 1
      : ["ArrowRight", "ArrowDown"].includes(event.key) ? (index + 1) % buttons.length
      : ["ArrowLeft", "ArrowUp"].includes(event.key) ? (index + buttons.length - 1) % buttons.length : -1;
    if (next < 0) return;
    event.preventDefault(); choose(buttons[next]); buttons[next].focus({preventScroll: true});
  });
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
  customPreview = null;
  const aircraft = selectedAircraft();
  customEditor.select(aircraft, new Map(catalog.weapons.map(row => [row.id, row])));
  aircraftClear.setAttribute("aria-pressed", String(!aircraft));
  document.querySelector("#calcCustomCount").textContent = `（${aircraftCatalog.filter(row => row.custom).length}）`;
  if (!aircraft) {
    selectionContent(aircraftSelection, "不限机型", "先按目标枚数计算");
    return;
  }
  selectionContent(
    aircraftSelection,
    aircraft.name,
    `${aircraft.w.length} 种武器${aircraft.m ? ` · ${formatInt(aircraft.m)} kg` : ""}${aircraft.custom ? " · 可自定义" : ""}`,
  );
}

function renderAircraftList() {
  visibleAircraft = matchingAircraft();
  if (!aircraftSearchInput.value.trim() && !onlyCustomAircraft()) {
    const empty = document.createElement("p");
    empty.className = "hangar-weapon-empty";
    empty.textContent = "支持名称、拼音和首字母，如 taif、j10。";
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
    button.title = item.name;
    const selected = item.id === selectedAircraftId;
    button.setAttribute("aria-selected", selected ? "true" : "false");
    if (selected) button.classList.add("is-selected");
    const name = document.createElement("span");
    name.className = "hangar-weapon-name";
    name.textContent = item.name;
    const detail = document.createElement("span");
    detail.className = "hangar-weapon-kind";
    detail.textContent = `${item.w.length} 种${item.custom ? " · 自定义" : ""}`;
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
  const capacity = currentWeaponCapacity(selectedAircraft(), weapon.id);
  selectionContent(
    weaponSelection,
    weaponName(weapon),
    `${KIND_LABELS[weapon.kind] || weapon.kind}${capacity ? ` · ${selectedPreset() ? "当前预设" : "单次最多"} ${capacity} 枚` : ""}`,
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
  renderPresets();
  if (!selectedPreset() && shouldShowWeaponResults() && !visibleWeapons.some((weapon) => weapon.id === selectedWeaponId)) {
    selectedWeaponId = visibleWeapons[0]?.id || "";
  }
  renderWeaponList();
  refreshResult();
}

function renderRepairNote(target, tier) {
  const airport = target.kind === "airport_module";
  repairNote.hidden = !airport;
  if (!airport || !tier) return;
  if (!airportRepairVisit({ rule: catalog.airport_repair, tier, dwellingPercent: 50 })) {
    repairSummary.textContent = "当前参数没有已核对的修复规则；投弹枚数仍按不计回血计算。";
    repairDetail.textContent = "";
    return;
  }
  repairSummary.textContent = "投弹结果不计回血，连续攻击请留余量。";
  const base = Number(tier.repair_base_hp || 0);
  repairDetail.textContent = base > 0
    ? `本档每次修复 +${formatInt(base / 10)}～${formatInt(base)} HP。`
    : "跑道与其他模块每轮加值相同。";
}

function refreshAirportRepair() {
  if (!catalog || !repairPercent) return;
  refreshAirportDiagram();
  const palette = airportPaletteBands(catalog.airport_display);
  const paletteContainer = document.querySelector("#airportPalette");
  paletteContainer.replaceChildren();
  if (palette) for (const [index, band] of palette.entries()) {
    const item = document.createElement("span"), swatch = document.createElement("i");
    swatch.style.backgroundColor = band.color;
    const label = document.createElement("span");
    label.textContent = index === 0 ? "0%" : index === 3 ? `>${band.lower}%` : `>${band.lower}～${band.upper}%`;
    item.append(swatch, label); paletteContainer.append(item);
  }
  document.querySelector("#airportPaletteSource").textContent = palette
    ? "颜色表示剩余耐久；图中灰条仅示意位置。"
    : "当前没有已核对的颜色规则。";
  const tier = tierFor(catalog.airport_tiers, balanceLevel(brSelect.value || defaultBr));
  const dwellingPercent = Number(repairPercent.value);
  for (const button of document.querySelectorAll("[data-dwelling]")) button.setAttribute("aria-pressed", String(Number(button.dataset.dwelling) === dwellingPercent));
  const input = { rule: catalog.airport_repair, tier, dwellingPercent };
  const result = airportRepairVisit(input);
  document.querySelector("#repairPercentLabel").textContent = `${dwellingPercent}%`;
  document.querySelector("#repairResult").textContent = !result ? "当前参数没有已核对的修复规则。" : result.state === "intact"
    ? "生活区完好 · 当前参考规则不触发修复。"
    : result.state === "destroyed" ? "生活区摧毁 · 当前参考规则停止回血。"
    : result.state === "below_threshold" ? "生活区不足 1% · 未达到参考规则的修复门槛。"
    : `每次修复：四模块各 +${result.gain.toLocaleString("zh-CN", { maximumFractionDigits: 2 })} HP。`;
  document.querySelector("#repairFormula").textContent = result
    ? `D = 生活区当前 HP；M = 生活区满血 ${formatInt(result.maximum)} HP；B = 本档回血基数 ${formatInt(result.base)} HP。先计算 q = 截断(100 × D ÷ M)，仅当 0 < q < 100：每次加值 = B ÷ min(M ÷ (D + 1), 10)；否则为 0。原生比较参考：${catalog.airport_repair.native_reference?.client_version || "未知版本"}；不代表完整服务器修复。`
    : "缺少规则时不套用历史公式。";
  renderAirportRepairChart(document.querySelector("#repairChart"), result ? {
    points: Array.from({ length: 99 }, (_, index) => ({ percent: index + 1, gain: airportRepairVisit({ ...input, dwellingPercent: index + 1 }).gain })),
    result, percent: dwellingPercent,
  } : null);
}

repairPercent?.addEventListener("input", refreshAirportRepair);
for (const button of document.querySelectorAll("[data-dwelling]")) button.addEventListener("click", () => {
  repairPercent.value = button.dataset.dwelling;
  refreshAirportRepair();
});
window.addEventListener("resize", refreshAirportRepair);

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
  const preset = customPreview?.preset || selectedPreset();
  renderPresetDetail(preset);
  refreshAirportRepair();
  const weapon = selectedWeapon();
  const target = selectedTarget();
  refreshDefenseSelection(weapon);
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
  combination.update({ weapons: new Map(catalog.weapons.map(row => [row.id, row])),
    hp: targetHp(target, tier), fireHp: target.has_fire ? targetHp(target, tier) * (1 - catalog.hp_fire_mult) : null,
    targetLabel: context, preset });
  customEditor.updateHp(targetHp(target, tier));
  optimizer.update({aircraft, weapons: new Map(catalog.weapons.map(row => [row.id, row])), reward: catalog.reward,
    threshold: target.kind === "bombing_point" ? targetHp(target, tier) * (1 - catalog.hp_fire_mult) : null,
    lockedKeys: preset?.customName ? preset.keys || [] : []});
  if (preset && (preset.customName || preset.weapons.length > 1)) {
    const hp = targetHp(target, tier);
    const { damage } = presetTotals(preset, new Map(catalog.weapons.map(row => [row.id, row])));
    if (!(hp > 0) || !(damage > 0)) {
      setHudUnknown(context, !preset.weapons.length ? "当前挂载没有可计算的对地弹药。" : "当前挂载或目标缺少伤害数据，无法估算整套轮次。");
      return;
    }
    const fullRounds = requiredCount(hp, damage);
    const rounds = requiredCount(target.has_fire ? hp * (1 - catalog.hp_fire_mult) : hp, damage);
    hudContext.textContent = context;
    destroyCountEl.textContent = String(rounds);
    destroyLabelEl.textContent = rounds < fullRounds ? "战区掉血自毁（轮）" : "满血摧毁（轮）";
    sortieCountEl.textContent = String(rounds);
    fireLineEl.textContent = rounds < fullRounds ? `满血直接摧毁需${fullRounds}轮` : "每轮投放整套挂载";
    statsEl.replaceChildren();
    appendStat("目标耐久", formatInt(hp));
    const reward = rewardUi(catalog.reward, damage);
    if (reward !== null) appendStat("整套收益系数", reward.toFixed(1));
    hintEl.textContent = [
      customPreview && !customPreview.validation.valid ? "当前配置未通过挂载限制校验；此处仅预览伤害。" : "",
      target.kind === "airport_module" ? "未计机场回血，实战可能需要更多架次。" : "",
    ].filter(Boolean).join(" ");
    return;
  }
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
    ? "有效命中枚数（不计回血）"
    : fireCount < destroyCount ? "战区掉血自毁" : "满血摧毁";
  fireLineEl.textContent = fireCount !== null && fireCount < destroyCount
    ? `满血直接摧毁需${destroyCount}枚`
    : "";
  statsEl.replaceChildren();
  if (!preset) appendStat("武器", weaponName(weapon));
  appendStat("每枚伤害", formatInt(damage));
  appendStat("目标耐久", formatInt(hp));

  const capacity = currentWeaponCapacity(aircraft, weapon.id);
  const plan = aircraft && capacity
    ? sortiePlan({ required: practicalCount, capacity, damage, reward: catalog.reward })
    : null;
  if (plan) {
    sortieCountEl.textContent = String(plan.sorties);
    if (!preset) appendStat("单次上限", `${plan.capacity} 枚`);
    if (plan.sorties > 1) appendStat("末次所需", `${plan.lastSortieCount} 枚`);
    if (plan.fullLoadReward !== null) appendStat("满载收益系数", plan.fullLoadReward.toFixed(1));
    hintEl.textContent = target.kind === "airport_module"
      ? "机场会在投弹间隙回血，实战可能需要更多架次。"
      : "";
  } else {
    sortieCountEl.textContent = "—";
    appendStat("机型", "未选择");
    hintEl.textContent = target.kind === "airport_module"
      ? "选择机型后显示挂载上限和理想架次；枚数指有效命中，未计防空拦截、脱靶与机场回血。"
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
    const [catalogBody, weaponsBody, aircraftBody, rewardsBody] = await Promise.all([
      loadJson(catalogUrl),
      loadJson(weaponsUrl),
      loadJson(aircraftUrl),
      loadJson(rewardsUrl),
    ]);
    const source = sharedParameterSource([catalogBody, weaponsBody, aircraftBody, rewardsBody]);
    if (!source) throw new Error("mixed_parameter_sources");
    defenseCatalogVersion = source.version;
    catalog = catalogBody;
    rewardsCatalog = { ...rewardsBody, vehicles: rewardsBody.vehicles.map(readableVehicle) };
    catalog.weapons = weaponsBody.weapons || [];
    aircraftCatalog = (aircraftBody.aircraft || []).map(readableVehicle).filter((item) =>
      Array.isArray(item.w) && Array.isArray(item.n) && item.w.length === item.n.length &&
      item.n.every((count) => Number.isInteger(count) && count > 0));
    if (sourceEl) sourceEl.textContent = `v${source.version} · ${aircraftCatalog.length.toLocaleString("zh-CN")} 机型 · ${catalog.weapons.length} 武器`;
    fillSelect(targetSelect, catalog.targets, (target) => target.id, (target) => target.label, catalog.targets[0].id);
    renderSegments(targetSelect, document.querySelector("#calcTargetSegments"));
    renderBrOptions(defaultBr);
    selectedAircraftId = aircraftCatalog.find(item => item.id === "pe-8_m82")?.id || "";
    selectedPresetId = selectedAircraft()?.presets?.[0]?.id || "";
    document.querySelector("#calcIndividualWeapons").open = !selectedPresetId;
    aircraftSearchInput.value = selectedAircraft()?.name || "";
    visibleWeapons = matchingWeapons();
    renderPresets();
    renderAircraftSelection();
    renderAircraftList();
    renderWeaponList();
    refreshResult();
    fillConversionCatalog();
    renderRewardVehicles(); loadRewardVehicle(); renderRewardReference();
    await loadAircraftPresets();
    await nextFrame();
  } catch {
    catalog = null;
    rewardsCatalog = null;
    if (rewardResult) rewardResult.replaceChildren(conversionText("p", "收益数据加载失败或参数来源不一致，请刷新后重试。"));
    renderRewardChart(document.querySelector("#rewardChart"), null, "收益目录未就绪，暂无曲线。");
    document.querySelector("#rewardFormula").replaceChildren();
    if (sourceEl) sourceEl.textContent = "数据未就绪：目录加载失败或来源版本不一致，请刷新后重试。";
    setHudUnknown("目录加载失败", "未使用缺失或混合版本的数据，刷新页面后再试。");
  }
}

aircraftList.addEventListener("click", (event) => {
  const button = event.target.closest("[data-aircraft-id]");
  if (!button || !aircraftList.contains(button)) return;
  selectedAircraftId = button.dataset.aircraftId;
  const aircraft = selectedAircraft();
  selectedPresetId = aircraft?.presets?.[0]?.id || "";
  kindSelect.value = ""; searchInput.value = "";
  document.querySelector("#calcIndividualWeapons").open = !selectedPresetId;
  aircraftSearchInput.value = aircraft?.name || "";
  renderAircraftSelection();
  renderAircraftList();
  refreshWeapons();
  loadAircraftPresets();
});

compareRows?.addEventListener("click", (event) => {
  const button = event.target.closest("[data-weapon-id]");
  if (!button || !compareRows.contains(button)) return;
  selectedWeaponId = button.dataset.weaponId;
  selectedPresetId = "";
  customPreview = null;
  document.querySelector("#calcIndividualWeapons").open = true;
  kindSelect.value = "";
  searchInput.value = "";
  refreshWeapons();
  weaponSelection.scrollIntoView({ behavior: "smooth", block: "center" });
});

fuelForm?.addEventListener("submit", (event) => event.preventDefault());
fuelForm?.addEventListener("input", refreshFuel);

aircraftClear.addEventListener("click", () => {
  selectedAircraftId = "";
  selectedPresetId = "";
  document.querySelector("#calcIndividualWeapons").open = true;
  aircraftSearchInput.value = "";
  renderAircraftSelection();
  renderAircraftList();
  refreshWeapons();
});

weaponList.addEventListener("click", (event) => {
  const button = event.target.closest("[data-weapon-id]");
  if (!button || !weaponList.contains(button)) return;
  selectedWeaponId = button.dataset.weaponId;
  selectedPresetId = "";
  customPreview = null;
  renderPresets();
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
  selectedPresetId = "";
  customPreview = null;
  renderPresets();
  renderWeaponList();
  refreshResult();
});

brSelect.addEventListener("change", () => { syncSegments(brSelect, document.querySelector("#calcBrSegments")); refreshResult(); });
targetSelect.addEventListener("change", () => {
  if (!catalog) return;
  syncSegments(targetSelect, document.querySelector("#calcTargetSegments"));
  renderBrOptions(brSelect.value || defaultBr);
  refreshResult();
});
kindSelect.addEventListener("change", refreshWeapons);
searchInput.addEventListener("input", refreshWeapons);
aircraftSearchInput.addEventListener("input", renderAircraftList);
customOnly.addEventListener("click", () => {
  customOnly.setAttribute("aria-pressed", String(!onlyCustomAircraft()));
  renderAircraftList();
});

presetList.addEventListener("click", event => {
  const button = event.target.closest("[data-preset-id]");
  if (button) choosePreset(button.dataset.presetId, true);
});
presetList.addEventListener("keydown", event => {
  if (!visiblePresets.length) return;
  const index = visiblePresets.findIndex(row => row.id === selectedPresetId);
  const next = event.key === "Home" ? 0 : event.key === "End" ? visiblePresets.length - 1
    : event.key === "ArrowDown" ? Math.min(visiblePresets.length - 1, index + 1)
    : event.key === "ArrowUp" ? Math.max(0, index - 1) : null;
  if (next === null) return;
  event.preventDefault(); choosePreset(visiblePresets[next].id, true);
});
document.querySelector("#calcForm").addEventListener("submit", event => event.preventDefault());

bindConversion();
bindRewards();
initAirCalculator();
boot();
