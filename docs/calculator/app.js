import { t, numberLocale, initializeLanguage, localizeName } from "./i18n.mjs";
import { airfieldDefenseMassAssessment, airportBarPositions, airportRepairVisit, airportPaletteBands, compareLoadouts, durabilityBrBuckets, equivalentWeaponCount, explosiveConversion, requiredCount, returnFuelPlan, rewardUi, sharedParameterSource, sortiePlan, usefulActionsReferences, usefulActionsReference, usefulActionsPlan, usefulActionsObservedFraction, usefulActionsCardRate, usefulActionsCurve } from "./model.mjs";
import { rankFuzzyMatches } from "./search.mjs";
import { reportDailyActive } from "./anonymous-daily-active.mjs";
import { readableVehicle } from "./vehicle-names.mjs";
import { presetTitle, presetTotals, presetDiagram, renderPresetRows } from "./loadouts.mjs";
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
const baseModeSelect = document.querySelector("#calcBaseMode");
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
    defenseSelection.textContent = t("app.selectAWeaponAboveToCompareItsMassWith", "在上方选择武器后，可对照本节两种防空的质量筛选窗。");
    return;
  }
  const state = airfieldDefenseMassAssessment({ massKg: weapon.kg, sourceVersion: defenseCatalogVersion });
  if (state === "version_mismatch") {
    defenseSelection.textContent = t("app.airDefenseResearchUses259013The", "防空研究为 2.59.0.13；当前武器目录为 {{v0}}，暂不关联弹种判断。", {v0: defenseCatalogVersion || t("app.unknownVersion", "未知版本")});
    return;
  }
  if (state === "unknown_mass") {
    defenseSelection.textContent = t("app.completeWeaponMassIsUnavailableSoTheInterceptionMass", "所选武器缺少整弹质量，无法对照拦截筛选窗。");
    return;
  }
  defenseSelection.textContent = t("app.weaponMassKg", "{{v0}} · 整弹 {{v1}} kg：{{v2}}", {v0: weaponName(weapon), v1: formatQuantity(weapon.kg), v2: state === "outside_mass_windows"
    ? t("app.outsideTheIto90MAndZa35Ammunition", "不落入本节 ItO 90M 与 ZA-35 的弹药优先级质量窗。这里只核对静态质量条件，不代表所有机场防空都忽略它。")
    : t("app.withinTheAmmunitionPriorityMassRangeSizeGlideCapability", "落入本节弹药优先级的质量范围；小型、滑翔或重型标签都不能单独证明免拦截。是否被选中还取决于制导组件、速度、航迹、探测与其他目标。")});
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

const KIND_LABELS = Object.freeze({ get bomb() { return t("app.bombs", "炸弹"); }, get rocket() { return t("app.rockets", "火箭弹"); }, get missile() { return t("app.missiles", "导弹"); } });

let catalog = null;
let selectedRoomBr = defaultBr;
let aircraftCatalog = [];
let visibleAircraft = [];
let visibleWeapons = [];
let visibleBrBuckets = [];
let selectedWeaponId = defaultWeaponId;
let selectedAircraftId = "";
let selectedPresetId = "";
let customPreview = null;
let currentCleared = false;
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
  preview: snapshot => { customPreview = snapshot; selectedPresetId = snapshot.preset.id === "draft" ? "" : snapshot.preset.id; renderPresets(); refreshResult(); },
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
  note.replaceChildren(conversionText("span", `${sample.label}。${sample.basis === "immediate" ? t("app.ratioOfImmediateSlToTheFullCycleStat", "比例为即时 SL / 卡片整周期基准，未代表活动率。") : t("app.ratioOfSlBeforeTheLandingSplitToThe", "比例为着陆拆分前的 SL / 卡片整周期基准。")} `));
  const link = conversionText("a", t("app.viewOriginalMeasurements", "查看原始实测")); link.href = sample.url; note.append(link);
  const rows = document.querySelector("#rewardReferenceRows"); rows.replaceChildren();
  sample.points.forEach(([score, fraction], index) => {
    const row = document.createElement("tr");
    for (const text of [String(score), `${(fraction * 100).toFixed(2)}%`, index ? t("app.percentagePoints", "+{{v0}} 个百分点", {v0: ((fraction - sample.points[index - 1][1]) * 100).toFixed(2)}) : "—"]) row.append(conversionText("td", text));
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
  rewardFields.Account.title = manualRate ? t("app.usingAManuallyEnteredStatCardRateIncludingAccount", "正在使用手填卡片值；账号加成已包含在该值中") : "";
  if (method === "reference") rewardFields.Minutes.value = String(rules.period_minutes);
  const minutes = inputNumber(rewardFields.Minutes), score = inputNumber(rewardFields.Score), slRate = inputNumber(rewardFields.SlRate);
  for (const [field, visible] of [["Minutes", method !== "reference"], ["Fraction", method === "manual"], ["Observed", method === "observed"]]) {
    document.querySelector(`#reward${field}Field`).hidden = !visible;
    rewardFields[field].disabled = !visible;
  }
  rewardSlider.max = String(Number.isFinite(score) ? Math.max(1200, score) : 1200);
  rewardSlider.value = String(Number.isFinite(score) ? Math.max(0, score) : 0);
  for (const button of document.querySelectorAll("button[data-score]")) button.setAttribute("aria-pressed", String(Number(button.dataset.score) === score));
  document.querySelector("#rewardPeriod").textContent = t("app.withinMinutes", "{{v0}} 分钟内", {v0: formatQuantity(minutes)});
  document.querySelector("#rewardChartPeriod").textContent = t("app.horizontalAxisScoreEarnedThisCycle", "横轴：本周期得分");
  const quality = document.querySelector(".reference-pill");
  quality.textContent = t("app.actualAwardsAreDeterminedByTheGame", "{{v0}}{{v1}} · 实际到账以游戏为准", {v0: method === "reference" ? t("app.historicalMeasurementsFrom2024", "2024 历史实测参考") : method === "observed" ? t("app.yourBattleRecord", "你的实战记录") : t("app.customRatioReference", "自定义比例参考"), v1: manualRate ? t("app.manualStatCardRate", " · 手填卡片基准") : ""});
  const origin = document.querySelector("#rewardSource");
  origin.textContent = row ? t("app.clientReferenceSlMinVehicleResearchMultiplierNotRp", "{{v0}} · 客户端 {{v1}} 基准 {{v2}} SL/min{{v3}} · 载具研发倍率 ×{{v4}}（不是 RP/min）{{v5}}", {v0: row.name, v1: rewardsCatalog.source.version, v2: formatQuantity(row.sl_per_min), v3: row.special ? t("app.premiumVehicle", " · 高级载具") : "", v4: row.rp_multiplier ?? t("app.unknown", "未知"), v5: manualRate ? t("app.manualStatCardRate2", " · 使用手填卡片值") : ""}) : t("app.noValidRewardVehicleSelected", "未选择有效收益机型");
  const preview = document.querySelector("#rewardCardPreview"); preview.replaceChildren();
  if (card) preview.append(conversionText("code", t("app.statCardReference1SlMin", "客户端卡片参考：{{v0}} × {{v1}} × (1 + {{v2}} + {{v3}}) = {{v4}} SL/min", {v0: formatQuantity(card.visualBase), v1: formatQuantity(card.visualMultiplier), v2: formatQuantity(card.accountBonus), v3: formatQuantity(card.boosterBonus), v4: formatQuantity(card.rate)})));
  else preview.textContent = t("app.missingStatCardParametersOrInvalidInputCheckThe", "卡片基准参数缺失或输入无效，请核对加成器效果。");
  rewardResult.replaceChildren();
  const formulas = document.querySelector("#rewardFormula"); formulas.replaceChildren();
  let basis = mode === "air_sim" ? "before_landing_split" : "immediate";
  let fraction = inputNumber(rewardFields.Fraction) / 100;
  let unavailable = t("app.enterAVerifiedRewardRatioInTheExpandedSection", "在展开区填写已核验的收益比例后计算。");
  if (method === "reference") {
    const ref = usefulActionsReference({ mode, score, minutes, vehicleId: rewardSelectedVehicle });
    fraction = ref?.fraction ?? NaN; basis = ref?.basis ?? basis;
    unavailable = mode === "air_sim" ? t("app.scoreIsOutsideTheHistorical2001050RangeRewards", "当前得分超出 200–1050 分的历史样本范围，不外推收益。") : rewardSelectedVehicle !== "ka_52" ? t("app.noMeasuredScoreCurveIsAvailableForThisHelicopter", "这台直升机还没有可用的得分实测曲线，不能套用 Ka-52 的结果。") : t("app.scoreIsOutsideTheKa52SampleRangeOf", "当前得分超出 Ka-52 的 200–800 分样本范围，不外推收益。");
  } else if (method === "observed") {
    fraction = usefulActionsObservedFraction({ slReceived: inputNumber(rewardFields.Observed), slRate, minutes, immediateShare: mode === "air_sim" ? rules.immediate_share : 1 }) ?? NaN;
    unavailable = fraction > 1 ? t("app.theCalculatedRatioIsAbove100CheckStatCard", "反算比例为 {{v0}}%，超过 100%；请核对卡片加成、周期时间和奖励口径。", {v0: formatQuantity(fraction * 100)}) : t("app.enterTheSlActuallyReceivedImmediatelyForThisUseful", "填入这次有用行动实际即时到账的 SL，即可核对记录。");
  }
  const rpRate = rewardFields.RpRate.value.trim() ? inputNumber(rewardFields.RpRate) : null;
  const rpFraction = rewardFields.RpFraction.value.trim() ? inputNumber(rewardFields.RpFraction) / 100 : null;
  const plan = usefulActionsPlan({ periodMinutes: rules.period_minutes, minutes, score, slRate, rpRate, rpFraction, fraction, basis, immediateShare: rules.immediate_share });
  const curve = method === "reference" ? usefulActionsCurve({ mode, vehicleId: rewardSelectedVehicle, minutes,
    periodMinutes: rules.period_minutes, slRate, immediateShare: rules.immediate_share, score }) : null;
  renderRewardChart(document.querySelector("#rewardChart"), curve,
    method !== "reference" ? t("app.battleRecordsAndCustomRatiosApplyToThisEntry", "实战核对与自定义比例只计算本条记录，不生成得分曲线。切回历史样本估算可查看曲线。") : !Number.isFinite(slRate) || slRate <= 0 ? t("app.invalidStatCardReferenceTheRewardChartIsUnavailable", "卡片基准无效，暂时无法绘制收益图。") : t("app.noScoreCurveIsAvailableForThisVehicleExpand", "这台机型暂无可用得分曲线，可展开高级选项核对实战记录。"));
  document.querySelector("#rewardChartHint").textContent = curve ? t("app.dragTheScoreToExploreChangesTheCurveCovers", "{{v0}}拖动得分可看变化；曲线仅覆盖已有样本，灰区没有估算。", {v0: curve.hasLanding ? t("app.blueIsTheImmediatePortionGoldIsTheAdditional", "蓝色为即时部分，金色为成功着陆后追加部分。") : t("app.onlyImmediateSlIsShownTheAircraftLandingSplit", "仅展示即时 SL，不套用空战的着陆分成。")}) : t("app.missingSamplesOrServerFormulasRemainUnknownTheMaximum", "样本和服务器公式缺失时保留未知，不以卡片最大值代替实际到账。");
  if (!plan) {
    if (!Number.isFinite(score) || score < 0) unavailable = t("app.enterNonnegativeMissionScoreEarnedDuringThisCycle", "请填写本周期新增任务分数，不能使用负数。");
    else if (!Number.isFinite(minutes) || minutes <= 0 || minutes > rules.period_minutes) unavailable = t("app.cycleDurationMustBeGreaterThan0AndAt", "本周期时长须大于 0 且不超过 {{v0}} 分钟。", {v0: rules.period_minutes});
    else if (!Number.isFinite(slRate) || slRate <= 0) unavailable = manualRate ? t("app.enterAPositiveSlMinReferenceRate", "请填写大于 0 的 SL/min 基准。") : t("app.invalidVehicleRateOrBoosterInputCheckAdvancedOptions", "机型基准或加成器输入无效，请在高级选项中核对。");
    else if (rpRate !== null && (!Number.isFinite(rpRate) || rpRate <= 0)) unavailable = t("app.rpMinMustBePositiveLeaveItBlankIf", "RP/min 基准须大于 0；未知时请留空。");
    else if (rpFraction !== null && (!Number.isFinite(rpFraction) || rpFraction < 0 || rpFraction > 1)) unavailable = t("app.theEffectiveRpRatioMustBe0100Leave", "RP 有效收益比例须在 0–100% 之间；未知时请留空。");
    else if (method === "manual" && (fraction < 0 || fraction > 1)) unavailable = t("app.theEffectiveRewardRatioMustBe0100Check", "有效收益比例须在 0–100% 之间；请先核对每分钟基准。");
    rewardResult.append(conversionText("h3", t("app.rewardEstimateUnavailable", "暂不能估算这次收益")), conversionText("p", unavailable));
    if (Number.isFinite(slRate * rules.period_minutes) && slRate > 0) rewardResult.append(conversionText("p", t("app.theFullCycleStatCardReferenceIsSlNot", "卡片整周期基准为 {{v0}} SL，不是实际到账预测。", {v0: formatInt(slRate * rules.period_minutes)}), "tool-note"));
    return;
  }
  rewardResult.append(conversionText("p", t("app.pointsMinutes", "{{v0}} 分 · {{v1}} 分钟{{v2}}", {v0: formatQuantity(score), v1: formatQuantity(minutes), v2: method === "observed" ? t("app.thisRecord", " · 本次记录") : t("app.rewardReference", " · 参考收益")}), "reward-context"));
  const stats = document.createElement("dl"); stats.className = "reward-stats";
  const add = (label, value) => { const pair = document.createElement("div"); pair.append(conversionText("dt", label), conversionText("dd", value)); stats.append(pair); };
  add(method === "observed" ? t("app.receivedImmediatelySl", "已即时到账 · SL") : t("app.estimatedImmediateSl", "即时获得约 · SL"), formatInt(plan.slImmediate));
  if (plan.slDeferred !== null) add(t("app.additionalAfterLandingSl", "成功着陆后追加约 · SL"), `+ ${formatInt(plan.slDeferred)}`);
  if (plan.rpImmediate !== null) add(t("app.immediateRpManualReference", "即时 RP · 自填参考"), formatInt(plan.rpImmediate));
  if (plan.rpDeferred !== null) add(t("app.landingRpManualReference", "着陆 RP · 自填参考"), `+ ${formatInt(plan.rpDeferred)}`);
  rewardResult.append(stats);
  if (plan.slDeferred !== null) rewardResult.append(conversionText("p", t("app.estimatedTotalIncludingTheLandingPortionSl", "本周期含着陆份额合计约 {{v0}} SL", {v0: formatInt(plan.slImmediate + plan.slDeferred)}), "reward-total"));
  const formula = document.createElement("p");
  formula.append(conversionText("code", t("app.immediateSlSlMinMin", "即时 SL ≈ {{v0}} SL/min × {{v1}} min × {{v2}}%{{v3}}", {v0: formatQuantity(slRate), v1: formatQuantity(minutes), v2: (fraction * 100).toFixed(2), v3: basis === "before_landing_split" ? " × 80%" : t("app.ratioIncludesTheImmediatePortion", "（比例已含即时份额）")}))); formulas.append(formula);
  if (plan.rpImmediate !== null) {
    const rpFormula = document.createElement("p");
    rpFormula.append(conversionText("code", t("app.immediateRpRpMinMin", "即时 RP ≈ {{v0}} RP/min × {{v1}} min × {{v2}}%{{v3}}", {v0: formatQuantity(rpRate), v1: formatQuantity(minutes), v2: formatQuantity(rpFraction * 100), v3: basis === "before_landing_split" ? " × 80%" : t("app.rpRatioIncludesTheImmediatePortion", "（RP 比例已含即时份额）")}))); formulas.append(rpFormula);
  }
  if (method === "observed") formulas.append(conversionText("p", t("app.thisRecordPointsImmediateSlTheSlPointRatio", "本条记录为 {{v0}} 分 → {{v1}} 即时 SL；每分 {{v2}} SL 只描述这条记录，不能线性外推。", {v0: formatQuantity(score), v1: formatQuantity(inputNumber(rewardFields.Observed)), v2: score > 0 ? formatQuantity(inputNumber(rewardFields.Observed) / score) : t("app.cannotCalculate", "无法计算")})));
  rewardResult.append(conversionText("p", t("app.excludesRepairSpawnCostsAndWinLossSettlement", "{{v0}}不含维修、出场费与胜负结算。{{v1}}", {v0: minutes < rules.period_minutes ? t("app.shortCyclesAreArithmeticReferencesOnlyDeathAndExit", "不足整周期仅作算术核对，死亡与退场规则未验证。") : "", v1: mode === "heli_pve" ? t("app.helicopterPostBattleRewardsAreUnknown", "直升机战后奖励未知。") : t("app.theLandingPortionRequiresASuccessfulAirfieldLanding", "着陆份额需满足成功机场着陆条件。")}), "tool-note"));
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
  return Math.round(value).toLocaleString(numberLocale());
}

function formatQuantity(value) {
  if (value !== 0 && (Math.abs(value) < 0.001 || Math.abs(value) >= 1e12)) return value.toExponential(5);
  return value.toLocaleString(numberLocale(), { maximumFractionDigits: 6 });
}

function formatApproximate(value) {
  if (value !== 0 && Math.abs(value) < 0.01) return value.toExponential(2);
  return value.toLocaleString(numberLocale(), { maximumFractionDigits: 2 });
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
    ? t("app.kgTntWeapon", "{{v0}} kg TNT / 枚", {v0: formatQuantity(equivalent)}) : t("app.fillerDataUnavailableExpandToEnterManually", "装药数据缺失，可展开自填");
  const special = weapon?.damage_model && weapon.damage_model !== "splash_tnte_curve"
    ? t("app.specialMissionDamageModelDoNotInferDamageFrom", " · 特殊任务伤害模型，请勿按当量推算伤害") : "";
  side.source.textContent = `${side.customCharge ? t("app.customFiller", "自定义装药") : t("app.readFromCatalog", "目录自动读取")} · ${amount}${special}`;
}

function renderChargeWeapons(side) {
  const weapons = catalog?.weapons ?? [], query = side.search.value.trim();
  const matches = query ? rankFuzzyMatches(weapons, query, item => [item.id, item.name, item.name_en]).slice(0, 100) : [...weapons];
  if (side.loadedWeapon && !matches.some(item => item.id === side.loadedWeapon.id)) matches.unshift(side.loadedWeapon);
  fillSelect(side.weapon, [null, ...matches], item => item?.id || "", item =>
    item ? `${weaponName(item)} · ${KIND_LABELS[item.kind] || item.kind}` : t("app.customFiller2", "自定义装药"), side.customCharge ? "" : side.loadedWeapon?.id || "");
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
      item ? `${item.type} · ×${formatQuantity(item.factor)}` : t("app.customFactor", "自定义系数"), previousType);
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
    chargeResult.append(conversionText("h3", t("app.conversionUnavailable", "暂不能换算")), conversionText("p", t("app.selectTwoWeaponsWithFillerDataOrExpandCustom", "请选择两种有装药数据的武器，或展开自定义参数，填写大于 0 的装药质量和 TNT 系数；A 的数量需为非负整数。")));
  } else {
    const name = (side, label) => side.customCharge ? t("app.customFiller3", "自定义装药 {{v0}}", {v0: label}) : weaponName(side.loadedWeapon);
    const headline = conversionText("p", t("app.wholeWeaponReplacementRequires", "整枚换装需要 "), "conversion-headline");
    headline.append(conversionText("strong", t("app.ofB", "{{v0}} 枚 B", {v0: q(result.wholeCount)})));
    chargeResult.append(headline,
      conversionText("p", t("app.weaponEquivalenceEquation", "{{v0}} 枚 {{v1}} ≈ {{v2}} 枚 {{v3}}", {v0: q(sourceCount), v1: name(a, "A"), v2: formatApproximate(result.exactCount), v3: name(b, "B")}), "conversion-equation"));
    const chart = document.createElement("div"); chart.className = "conversion-chart"; chargeResult.append(chart);
    renderConversionChart(chart, result, sourceCount);
    chargeResult.append(conversionText("p", t("app.roundedReplacementAddsKgTnt", "整枚取整后多出 {{v0}} kg TNT", {v0: formatApproximate(result.surplus)}), "conversion-surplus"));
    const quick = document.createElement("p"); quick.className = "conversion-quick-formula";
    quick.append(conversionText("code", t("app.kgTntKgTntWeaponOfB", "{{v0}} kg TNT ÷ {{v1}} kg TNT/枚 ≈ {{v2}} 枚 B", {v0: q(result.sourceTotal), v1: q(result.targetTntKg), v2: formatApproximate(result.exactCount)}))); chargeResult.append(quick);
    for (const line of [
      t("app.aPerWeaponEquivalenceEFillerMassMTnt", "A 单枚当量 Eₐ = 装药质量 mₐ × TNT 系数 rₐ = {{v0}} kg × {{v1}} = {{v2}} kg TNT", {v0: q(inputNumber(a.mass)), v1: q(inputNumber(a.factor)), v2: q(result.sourceTntKg)}),
      t("app.bPerWeaponEquivalenceEMRKgKg", "B 单枚当量 Eᵦ = mᵦ × rᵦ = {{v0}} kg × {{v1}} = {{v2}} kg TNT", {v0: q(inputNumber(b.mass)), v1: q(inputNumber(b.factor)), v2: q(result.targetTntKg)}),
      t("app.totalAEquivalenceNEKgTnt", "A 总当量 = Nₐ × Eₐ = {{v0}} × {{v1}} = {{v2}} kg TNT", {v0: q(sourceCount), v1: q(result.sourceTntKg), v2: q(result.sourceTotal)}),
      t("app.equivalentBCountNNEERoundedUp", "B 折算枚数 Nᵦ = Nₐ × Eₐ ÷ Eᵦ = {{v0}} ÷ {{v1}} ≈ {{v2}}；向上取整 ⌈Nᵦ⌉ = {{v3}}", {v0: q(result.sourceTotal), v1: q(result.targetTntKg), v2: q(result.exactCount), v3: q(result.wholeCount)}),
    ]) {
      const row = document.createElement("p"); row.append(conversionText("code", line)); formulas.append(row);
    }
  }
  document.querySelector("#chargeLess").disabled = !Number.isSafeInteger(sourceCount) || sourceCount <= 0;
  document.querySelector("#chargeMore").disabled = !Number.isSafeInteger(sourceCount) || sourceCount < 0 || sourceCount === Number.MAX_SAFE_INTEGER;
  const damage = equivalentWeaponCount({ sourcePerItem: inputNumber(a.damage), targetPerItem: inputNumber(b.damage), sourceCount });
  chargeDamageResult.replaceChildren(conversionText("strong", t("app.missionDamageConversionCalculatedSeparately", "按任务伤害换算（独立计算）")));
  const note = damage
    ? t("app.nNDDRoundedUpToOfB", "Nᵦ = Nₐ × Dₐ ÷ Dᵦ = {{v0}} × {{v1}} ÷ {{v2}} ≈ {{v3}} 枚；向上取整为 {{v4}} 枚 B。A 合计 {{v5}} HP，取整后 B 合计 {{v6}} HP。{{v7}}", {v0: q(sourceCount), v1: q(inputNumber(a.damage)), v2: q(inputNumber(b.damage)), v3: q(damage.exactCount), v4: q(damage.wholeCount), v5: q(damage.sourceTotal), v6: q(damage.targetTotal), v7: a.autoDamage && b.autoDamage ? t("app.usesEachWeaponSCatalogMissionDamage", "使用两种武器各自的目录任务伤害。") : t("app.includesCustomHpValuesComparisonUsesYourAssumptions", "包含自定义 HP，仅按所填假设比较。")})
    : t("app.enterValidPerWeaponHpForBothSidesTo", "补充两侧有效的单枚 HP 后可单独比较。不会从自定义 TNT 当量猜测任务伤害。");
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
  return weapon?.name || weapon?.id || t("app.unknownWeapon", "未知武器");
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
  const preset = customPreview?.preset || selectedPreset();
  return preset ? preset.weapons.find(([id]) => id === weaponId)?.[1] || null
    : aircraftWeaponCapacity(aircraft, weaponId);
}

function renderPresets() {
  const aircraft = selectedAircraft(), rows = (aircraft?.presets || []).filter(row => !row.customName);
  document.querySelector("#calcPresetPanel").hidden = !rows.length;
  document.querySelector("#calcLoadoutCaption").textContent = loadoutState === "loading"
    ? t("app.loadingLoadoutGrid", "正在读取挂载排列…") : loadoutState === "error" ? t("app.loadoutGridUnavailableSelectTheAircraftAgainToRetry", "挂载排列未就绪，请重新选择机型重试；仍可按单一武器计算")
    : rows.length
    ? t("app.eachRowIsOneGamePresetSelectionUsesIts", "每一行是一套游戏预设；选择后按实际弹数计算")
    : aircraft ? t("app.noPresetGridIsAvailableForThisAircraftView", "该机型暂无可用预设排列，可按单一武器查看上限") : t("app.selectAnAircraftForItsLoadoutGridOrSearch", "先选机型查看挂载网格，也可直接搜索武器");
  const weapons = new Map(catalog.weapons.map(row => [row.id, row]));
  const allowed = new Set(matchingWeapons(Number.POSITIVE_INFINITY).map(row => row.id));
  visiblePresets = rows.filter(row => row.weapons.some(([id]) => allowed.has(id)));
  const preset = selectedPreset();
  if (preset && !preset.weapons.some(([id]) => id === selectedWeaponId)) selectedWeaponId = preset.weapons[0]?.[0] || "";
  if (rows.length) renderPresetRows(presetList, visiblePresets, weapons, selectedPresetId, rows);
  document.querySelector("#calcPresetCount").textContent = t("app.presets", "{{v0}} / {{v1}} 套预设", {v0: visiblePresets.length, v1: rows.length});
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
  if (!currentCleared && !customPreview && !aircraft?.presets?.some(row => row.id === selectedPresetId)) selectedPresetId = aircraft?.presets?.[0]?.id || "";
  document.querySelector("#calcIndividualWeapons").open = !selectedPresetId;
  refreshWeapons();
  if (!currentCleared && selectedPreset()) void syncCurrentPreset(selectedPreset());
}

function renderPresetDetail(preset) {
  document.querySelector("#calcPresetDetail").hidden = !preset;
  if (!preset) { document.querySelector("#calcPresetStats").replaceChildren(); document.querySelector("#calcPresetTitle").textContent = t("currentLoadout.empty", "未挂载"); document.querySelector("#calcPresetDiagram").replaceChildren(); return; }
  const weapons = new Map(catalog.weapons.map(row => [row.id, row]));
  document.querySelector("#calcPresetTitle").textContent = preset.cells.length ? presetTitle(preset, weapons) : t("currentLoadout.empty", "未挂载");
  const detail = document.querySelector("#calcPresetDetail");
  detail.style.setProperty("--tier-count", preset.columns);
  document.querySelector("#calcPresetDiagram").replaceChildren(presetDiagram(preset, weapons));
  document.querySelector("#calcPresetDiagram").hidden = customEditor.editable;
  const totals = presetTotals(preset, weapons);
  const target = selectedTarget();
  const combined = combinationTotals(preset.weapons, weapons, targetHp(target, targetTier(target, balanceLevel(brSelect.value || defaultBr))));
  const stats = document.querySelector("#calcPresetStats"); stats.replaceChildren();
  for (const [label, value] of [
    [t("app.ammunitionMass", "弹药总重"), totals.mass === null ? t("app.unknown2", "未知") : `${formatQuantity(totals.mass)} kg`],
    [t("app.totalTntEquivalent", "总 TNT 当量"), combined?.tnt == null ? t("app.unknown3", "未知") : `${formatQuantity(combined.tnt)} kg`],
    [t("app.completeLoadoutDamage", "整套伤害"), totals.damage === null ? t("app.unknown4", "未知") : `${formatInt(totals.damage)} HP`],
  ]) {
    const item = conversionText("div", null);
    item.append(conversionText("dt", label), conversionText("dd", value));
    stats.append(item);
  }
  document.querySelector("#calcPresetNote").textContent = preset.other ? t("app.includesOtherEquipmentTotalsAboveCoverCalculableStrikeAmmunition", "含其他装备；上方仅统计可计算的对地弹药。") : "";
}

function choosePreset(id, focus = false) {
  currentCleared = false;
  customPreview = null;
  selectedPresetId = id;
  const row = selectedPreset();
  if (!row) return;
  if (!row.weapons.some(([weapon]) => weapon === selectedWeaponId)) selectedWeaponId = row.weapons[0]?.[0] || "";
  document.querySelector("#calcIndividualWeapons").open = false;
  renderPresets(); renderWeaponList(); refreshResult();
  void syncCurrentPreset(row);
  if (focus) [...presetList.querySelectorAll("[data-preset-id]")].find(button => button.dataset.presetId === id)?.focus();
}

async function syncCurrentPreset(preset) {
  const editable = await customEditor.usePreset(preset);
  if (!editable && selectedPresetId === preset.id) refreshResult();
}

document.querySelector(".current-loadout-clear").addEventListener("click", () => {
  const aircraft = selectedAircraft();
  if (!aircraft) return;
  currentCleared = true; selectedPresetId = "";
  const preset = {id: "draft", customName: t("currentLoadout.empty", "未挂载"), weapons: [], cells: [], columns: aircraft.presets?.[0]?.columns || 1, layout: "slots", other: false};
  customPreview = {preset, validation: {valid: true}, lockedKeys: []};
  renderPresets(); refreshResult();
  void customEditor.usePreset(preset);
});

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
  const target = catalog.targets.find((target) => target.id === targetSelect.value) || catalog.targets[0];
  if (target.id !== "bombing_point_planes") return { ...target, fireMultiplier: catalog.hp_fire_mult };
  const profile = catalog.bombing_point_profiles.find(row => row.id === baseModeSelect.value);
  return { ...target, tiers: profile.tiers, has_fire: profile.hp_fire_mult > 0,
    fireMultiplier: profile.hp_fire_mult, label: `${target.label} · ${baseModeLabel(profile.id)}` };
}

function baseModeLabel(id) {
  return t(`page.baseMode.${id}`);
}

function renderBaseModes() {
  fillSelect(baseModeSelect, catalog.bombing_point_profiles, row => row.id,
    row => baseModeLabel(row.id), baseModeSelect.value || catalog.bombing_point_profiles[0].id);
  renderSegments(baseModeSelect, document.querySelector("#calcBaseModeSegments"));
}

function balanceLevel(brText) {
  const index = catalog.br_values.indexOf(brText);
  return index >= 0 ? index : catalog.br_values.length - 1;
}

function tierFor(tiers, rank) {
  return tiers.find((tier) => rank >= tier.balance_level[0] && rank <= tier.balance_level[1]);
}

function targetTier(target, rank) {
  return tierFor(targetTiers(target), rank);
}

function targetHp(target, tier) {
  if (!tier) return 0;
  if (target.kind === "bombing_point") {
    return target.mode === "heli" ? tier.heli_mission_hp : tier.planes_mission_hp;
  }
  return target.module === "airfield" ? tier.runway_mission_hp : tier.auxiliary_module_mission_hp;
}

function targetTiers(target) {
  return target.tiers || (target.kind === "bombing_point" ? catalog.bombing_point_tiers : catalog.airport_tiers);
}

function renderBrOptions() {
  const target = selectedTarget();
  document.querySelector("#calcBaseModeControl").hidden = target.id !== "bombing_point_planes";
  const modeNote = document.querySelector("#calcBaseModeNote");
  modeNote.hidden = target.id !== "bombing_point_planes";
  modeNote.textContent = t(`page.baseModeHint.${baseModeSelect.value}`);
  const currentRank = balanceLevel(selectedRoomBr);
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

const targetSegmentNames = () => ({
  bombing_point_planes: t("app.airBattleBase", "战区基地"), bombing_point_heli: t("app.helicopterBase", "直升机基地"),
  airport_airfield: t("app.airfieldRunway", "机场跑道"), airport_storage: t("app.fuelStorage", "油库"), airport_parking: t("app.parkingArea", "停机区"), airport_dwelling: t("app.livingQuarters", "生活区"),
});

function renderSegments(select, track) {
  track.replaceChildren();
  const thumb = document.createElement("span"); thumb.className = "segment-thumb"; thumb.setAttribute("aria-hidden", "true");
  track.append(thumb); track.style.setProperty("--segments", select.options.length);
  for (const option of select.options) {
    const button = document.createElement("button"); button.type = "button";
    button.setAttribute("role", "radio"); button.dataset.value = option.value;
    button.setAttribute("aria-label", option.textContent);
    if (select === baseModeSelect) button.title = t(`page.baseModeHint.${option.value}`);
    const [title, detail] = select === brSelect ? option.textContent.split(" · ") : [targetSegmentNames()[option.value] || option.textContent];
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

for (const [select, trackId] of [[brSelect, "calcBrSegments"], [targetSelect, "calcTargetSegments"], [baseModeSelect, "calcBaseModeSegments"]]) {
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

function appendStat(label, value, key) {
  if (key === "reward") {
    document.querySelector("#calcRewardCard").hidden = false;
    document.querySelector("#calcRewardCount").textContent = value;
    document.querySelector("#calcRewardLabel").textContent = t("optimizer.coefficient", "收益系数");
    return;
  }
  const term = document.createElement("dt");
  term.textContent = label;
  const detail = document.createElement("dd");
  detail.textContent = value;
  const item = document.createElement("div");
  item.append(term, detail); statsEl.append(item);
}

function selectionContent(container, title, detail) {
  const strong = document.createElement("strong");
  strong.textContent = title;
  const span = document.createElement("span");
  span.textContent = detail;
  container.replaceChildren(strong, span);
}

function renderAircraftSelection(resetEditor = true) {
  if (resetEditor) { customPreview = null; currentCleared = false; }
  const aircraft = selectedAircraft();
  if (resetEditor) customEditor.select(aircraft, new Map(catalog.weapons.map(row => [row.id, row])));
  aircraftClear.setAttribute("aria-pressed", String(!aircraft));
  document.querySelector("#calcCustomCount").textContent = `（${aircraftCatalog.filter(row => row.custom).length}）`;
  if (!aircraft) {
    selectionContent(aircraftSelection, t("app.anyAircraft", "不限机型"), t("app.calculateWeaponCountFirst", "先按目标枚数计算"));
    return;
  }
  selectionContent(
    aircraftSelection,
    aircraft.name,
    t("app.weaponTypes", "{{v0}} 种武器{{v1}}{{v2}}", {v0: aircraft.w.length, v1: aircraft.m ? ` · ${formatInt(aircraft.m)} kg` : "", v2: aircraft.custom ? t("app.customLoadouts", " · 可自定义") : ""}),
  );
}

function renderAircraftList() {
  visibleAircraft = matchingAircraft();
  if (!aircraftSearchInput.value.trim() && !onlyCustomAircraft()) {
    const empty = document.createElement("p");
    empty.className = "hangar-weapon-empty";
    empty.textContent = t("app.searchByNamePinyinOrInitialsEGTaif", "支持名称、拼音和首字母，如 taif、j10。");
    aircraftList.replaceChildren(empty);
    return;
  }
  if (!visibleAircraft.length) {
    const empty = document.createElement("p");
    empty.className = "hangar-weapon-empty";
    empty.textContent = t("app.noAircraftFoundTryAShorterName", "没有找到机型，换个简称试试。");
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
    button.title = `${item.long || item.name} · ${item.countryName}`;
    const selected = item.id === selectedAircraftId;
    button.setAttribute("aria-selected", selected ? "true" : "false");
    if (selected) button.classList.add("is-selected");
    const name = document.createElement("span");
    name.className = "hangar-weapon-name";
    name.textContent = item.name;
    const detail = document.createElement("span");
    detail.className = "hangar-weapon-kind";
    detail.textContent = `${item.countryName} · ${t("app.types", "{{v0}} 种{{v1}}", {v0: item.w.length, v1: item.custom ? t("app.custom", " · 自定义") : ""})}`;
    button.append(name, detail);
    fragment.append(button);
  }
  aircraftList.replaceChildren(fragment);
}

function renderWeaponSelection() {
  const weapon = selectedWeapon();
  if (!weapon) {
    selectionContent(weaponSelection, t("app.noWeaponsAvailable", "没有可用武器"), t("app.changeTheAircraftTypeOrSearchTerms", "调整机型、种类或搜索词"));
    return;
  }
  const capacity = currentWeaponCapacity(selectedAircraft(), weapon.id);
  selectionContent(
    weaponSelection,
    weaponName(weapon),
    `${KIND_LABELS[weapon.kind] || weapon.kind}${capacity ? t("app.ammunitionQuantity", " · {{v0}} {{v1}} 枚", {v0: selectedPreset() ? t("app.currentPreset", "当前预设") : t("app.maximumPerSortie", "单次最多"), v1: capacity}) : ""}`,
  );
}

function renderWeaponList() {
  if (!shouldShowWeaponResults()) {
    const empty = document.createElement("p");
    empty.className = "hangar-weapon-empty";
    empty.textContent = t("app.enterAWeaponNameOrSelectAnAircraftType", "输入武器名，或先选机型 / 种类。");
    weaponList.replaceChildren(empty);
    renderWeaponSelection();
    return;
  }
  if (!visibleWeapons.length) {
    const empty = document.createElement("p");
    empty.className = "hangar-weapon-empty";
    empty.textContent = t("app.noWeaponsMatchTheCurrentFilters", "当前筛选下没有可用武器。");
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
    detail.textContent = capacity ? t("app.sortie", "{{v0}} 枚/次", {v0: capacity}) : KIND_LABELS[weapon.kind] || weapon.kind;
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
    repairSummary.textContent = t("app.noVerifiedRepairRuleForTheseParametersWeaponCounts", "当前参数没有已核对的修复规则；投弹枚数仍按不计回血计算。");
    repairDetail.textContent = "";
    return;
  }
  repairSummary.textContent = t("app.resultsExcludeRegenerationAllowAMarginForRepeatedAttacks", "投弹结果不计回血，连续攻击请留余量。");
  const base = Number(tier.repair_base_hp || 0);
  repairDetail.textContent = base > 0
    ? t("app.thisBracketRestoresHpPerRepairVisit", "本档每次修复 +{{v0}}～{{v1}} HP。", {v0: formatInt(base / 10), v1: formatInt(base)})
    : t("app.theRunwayAndOtherModulesReceiveTheSameIncrement", "跑道与其他模块每轮加值相同。");
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
    ? t("app.colorsIndicateRemainingHpGrayBarsOnlyShowPositions", "颜色表示剩余耐久；图中灰条仅示意位置。")
    : t("app.noVerifiedColorRulesAvailable", "当前没有已核对的颜色规则。");
  const tier = tierFor(catalog.airport_tiers, balanceLevel(brSelect.value || defaultBr));
  const dwellingPercent = Number(repairPercent.value);
  for (const button of document.querySelectorAll("[data-dwelling]")) button.setAttribute("aria-pressed", String(Number(button.dataset.dwelling) === dwellingPercent));
  const input = { rule: catalog.airport_repair, tier, dwellingPercent };
  const result = airportRepairVisit(input);
  document.querySelector("#repairPercentLabel").textContent = `${dwellingPercent}%`;
  document.querySelector("#repairResult").textContent = !result ? t("app.noVerifiedRepairRuleForTheseParameters", "当前参数没有已核对的修复规则。") : result.state === "intact"
    ? t("app.livingQuartersIntactTheReferenceRuleDoesNotTrigger", "生活区完好 · 当前参考规则不触发修复。")
    : result.state === "destroyed" ? t("app.livingQuartersDestroyedTheReferenceRuleStopsRegeneration", "生活区摧毁 · 当前参考规则停止回血。")
    : result.state === "below_threshold" ? t("app.livingQuartersBelow1BelowTheReferenceRepairThreshold", "生活区不足 1% · 未达到参考规则的修复门槛。")
    : t("app.eachRepairVisitHpToEachOfFourModules", "每次修复：四模块各 +{{v0}} HP。", {v0: result.gain.toLocaleString(numberLocale(), { maximumFractionDigits: 2 })});
  document.querySelector("#repairFormula").textContent = result
    ? t("app.dCurrentLivingQuartersHpMFullHpB", "D = 生活区当前 HP；M = 生活区满血 {{v0}} HP；B = 本档回血基数 {{v1}} HP。先计算 q = 截断(100 × D ÷ M)，仅当 0 < q < 100：每次加值 = B ÷ min(M ÷ (D + 1), 10)；否则为 0。原生比较参考：{{v2}}；不代表完整服务器修复。", {v0: formatInt(result.maximum), v1: formatInt(result.base), v2: catalog.airport_repair.native_reference?.client_version || t("app.unknownVersion2", "未知版本")})
    : t("app.historicalFormulasAreNotSubstitutedForMissingRules", "缺少规则时不套用历史公式。");
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
  destroyLabelEl.textContent = t("app.estimateUnavailable", "无法估算");
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
  const threshold = target.has_fire ? hp * (1 - target.fireMultiplier) : hp;
  const rows = compareLoadouts({ aircraft, weapons: catalog.weapons, hp: threshold });
  compareTable.hidden = rows.length === 0;
  compareContext.textContent = aircraft
    ? t("app.brLoadoutTypesWithDamageData", "{{v0}} · {{v1}} · BR {{v2}} · {{v3}} 种有伤害数据的挂载", {v0: aircraft.name, v1: target.label, v2: selectedBrRange(), v3: rows.length})
    : t("app.selectAnAircraftAboveToCompareItsAvailableLoadouts", "先在上方选择机型，即可对比它的全部可用挂载。");
  const fragment = document.createDocumentFragment();
  for (const row of rows) {
    const tr = document.createElement("tr");
    tr.dataset.selected = String(row.weapon.id === selectedWeaponId);
    const weaponCell = document.createElement("td");
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.weaponId = row.weapon.id;
    button.textContent = weaponName(row.weapon);
    button.title = t("app.selectThisWeaponAndViewTheCalculation", "选择此武器并查看详细计算");
    weaponCell.append(button);
    tr.append(weaponCell);
    for (const value of [row.required, row.capacity, `${row.targetsPerLoad}${row.remaining ? t("app.remaining", "（余 {{v0}} 枚）", {v0: row.remaining}) : ""}`, row.sorties, row.massKg === null ? t("app.unknown5", "未知") : `${formatInt(row.massKg)} kg`]) {
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
    note.textContent = t("app.enterValidFuelBurnGroundSpeedDistanceAndReserve", "填入有效的油耗、地速、距离与储备；空白输入不会当作零。当前燃油可留空。");
    fuelResult.append(note);
    return;
  }
  const dl = document.createElement("dl");
  for (const [label, value] of [[t("app.estimatedFlightTime", "预计航程时间"), `${plan.tripMin.toFixed(1)} min`], [t("app.enRouteFuel", "航程耗油"), `${formatInt(plan.tripKg)} kg`], [t("app.arrivalReserve", "到达后储备"), `${formatInt(plan.reserveKg)} kg`], [t("app.totalRequired", "合计所需"), `${formatInt(plan.requiredKg)} kg`]]) {
    const group = document.createElement("div");
    const dt = document.createElement("dt");
    const dd = document.createElement("dd");
    dt.textContent = label;
    dd.textContent = value;
    group.append(dt, dd);
    dl.append(group);
  }
  note.textContent = plan.marginKg === null
    ? t("app.enterCurrentFuelToSeeTheMarginAssumesConstant", "补充当前燃油可查看余量。以上按所填油耗和地速保持不变估算。")
    : t("app.afterFlightAndReserveKgBasedOnTheEntered", "扣除航程和储备后{{v0}} {{v1}} kg。仅按所填工况估算，油门、天气与航线改变后需要重算。", {v0: plan.marginKg < 0 ? t("app.shortfall", "缺少") : t("app.remaining2", "剩余"), v1: formatInt(Math.abs(plan.marginKg))});
  fuelResult.append(dl, note);
}

function refreshResult() {
  if (!catalog) return;
  document.querySelector("#calcRewardCard").hidden = true;
  const preset = customPreview?.preset || selectedPreset();
  renderPresetDetail(preset);
  refreshAirportRepair();
  const weapon = selectedWeapon();
  const target = selectedTarget();
  refreshDefenseSelection(weapon);
  const br = brSelect.value || defaultBr;
  const rank = balanceLevel(br);
  const tier = targetTier(target, rank);
  const targetThreshold = document.querySelector("#calcTargetThreshold");
  const zoneHp = targetHp(target, tier);
  if (target.has_fire && zoneHp > 0) {
    const remaining = zoneHp * target.fireMultiplier, damage = zoneHp * (1 - target.fireMultiplier);
    targetThreshold.dataset.burnoutHp = String(remaining);
    targetThreshold.dataset.requiredDamage = String(damage);
    targetThreshold.textContent = t("app.baseBurnoutHp", "自毁剩余 {{remaining}} HP · 需伤害 {{damage}} HP", {remaining: formatInt(remaining), damage: formatInt(damage)});
  } else {
    delete targetThreshold.dataset.burnoutHp; delete targetThreshold.dataset.requiredDamage;
    targetThreshold.textContent = t("page.startingFromFullHp", "按满血计算");
  }
  renderRepairNote(target, tier);
  renderComparison(target, tier);
  const aircraft = selectedAircraft();
  const brRange = selectedBrRange();
  document.querySelector("#calcApplicability").textContent = target.id === "bombing_point_planes" ? `${t(`page.baseModeHint.${baseModeSelect.value}`)} ${t("page.allHitsAssumption", "伤害结果假设全部命中，收益系数不是实际银狮或研发点。")}` : t("page.moduleScope", "当前使用 EC 机场／直升机目标参数；机场模块按满血且不计回血估算。伤害结果假设全部命中。");
  const context = aircraft
    ? `${target.label} · BR ${brRange} · ${aircraft.name}`
    : `${target.label} · BR ${brRange}`;
  combination.update({ weapons: new Map(catalog.weapons.map(row => [row.id, row])),
    hp: targetHp(target, tier), fireHp: target.has_fire ? targetHp(target, tier) * (1 - target.fireMultiplier) : null,
    targetLabel: context, preset });
  customEditor.updateHp(targetHp(target, tier));
  optimizer.update({aircraft, weapons: new Map(catalog.weapons.map(row => [row.id, row])), reward: catalog.reward,
    threshold: target.kind === "bombing_point" ? targetHp(target, tier) * (1 - (target.has_fire ? target.fireMultiplier : 0)) : null,
    currentStores: preset?.weapons || [], lockedKeys: customPreview?.lockedKeys ?? (preset?.customName ? preset.keys || [] : [])});
  if (preset && (preset.customName || preset.weapons.length > 1)) {
    const hp = targetHp(target, tier);
    const { damage, rewardDamage } = presetTotals(preset, new Map(catalog.weapons.map(row => [row.id, row])));
    if (!(hp > 0) || !(damage > 0)) {
      setHudUnknown(context, !preset.weapons.length ? t("app.thisLoadoutHasNoCalculableStrikeAmmunition", "当前挂载没有可计算的对地弹药。") : t("app.loadoutOrTargetDamageDataIsMissingCompleteLoad", "当前挂载或目标缺少伤害数据，无法估算整套轮次。"));
      return;
    }
    const fullRounds = requiredCount(hp, damage);
    const rounds = requiredCount(target.has_fire ? hp * (1 - target.fireMultiplier) : hp, damage);
    hudContext.textContent = context;
    destroyCountEl.textContent = String(rounds);
    destroyLabelEl.textContent = rounds < fullRounds ? t("app.burnOutThresholdLoads", "次出击才能触发战区自毁", {count: rounds}) : t("app.directDestructionLoads", "次出击才能直接摧毁目标", {count: rounds});
    sortieCountEl.textContent = String(rounds);
    fireLineEl.textContent = [t("app.eachRoundReleasesOneCompleteLoadout", "每次均携带整套挂载并全部命中"), rounds < fullRounds ? t("app.completeLoadsForDirectDestruction", "直接摧毁满血目标需 {{v0}} 次出击", {v0: fullRounds, count: fullRounds}) : ""].filter(Boolean).join(" · ");
    statsEl.replaceChildren();
    appendStat(t("app.targetHp", "目标耐久"), formatInt(hp));
    const reward = rewardUi(catalog.reward, rewardDamage);
    if (reward !== null) appendStat(t("app.loadoutRewardCoefficient", "整套收益系数"), reward.toFixed(1), "reward");
    hintEl.textContent = [
      customPreview && !customPreview.validation.valid ? t("app.thisConfigurationFailsLoadoutRestrictionsDamagePreviewOnly", "当前配置未通过挂载限制校验；此处仅预览伤害。") : "",
      target.kind === "airport_module" ? t("app.excludesAirfieldRegenerationMoreSortiesMayBeNeeded", "未计机场回血，实战可能需要更多架次。") : "",
    ].filter(Boolean).join(" ");
    return;
  }
  if (!weapon || !target) {
    setHudUnknown(context, t("app.changeTheAircraftTypeOrSearchTerms2", "调整机型、种类或搜索词。"));
    return;
  }
  const hp = targetHp(target, tier);
  if (!(hp > 0)) {
    setHudUnknown(context, t("app.noHpDataForThisBracket", "这一档没有耐久数据。"));
    return;
  }
  const damage = weaponDamage(weapon);
  if (!(damage > 0)) {
    setHudUnknown(context, t("app.missionDamageIsCurrentlyUnavailableFor", "{{v0}} 暂时没有可用的任务伤害数据。", {v0: weaponName(weapon)}));
    return;
  }

  const destroyCount = requiredCount(hp, damage);
  const fireCount = target.has_fire
    ? requiredCount(hp * (1 - target.fireMultiplier), damage)
    : null;
  const practicalCount = fireCount === null ? destroyCount : Math.min(destroyCount, fireCount);
  hudContext.textContent = context;
  destroyCountEl.textContent = String(practicalCount);
  destroyLabelEl.textContent = target.kind === "airport_module"
    ? t("app.effectiveHitsExcludingRegeneration", "枚有效命中可摧毁机场模块（未计回血）")
    : fireCount !== null && fireCount < destroyCount ? t("app.baseBurnOut", "枚全部命中，可触发战区自毁") : t("app.directDestruction", "枚全部命中，可直接摧毁目标");
  fireLineEl.textContent = fireCount !== null && fireCount < destroyCount
    ? t("app.weaponsForDirectDestructionFromFullHp", "满血直接摧毁需{{v0}}枚", {v0: destroyCount})
    : "";
  statsEl.replaceChildren();
  if (!preset) appendStat(t("app.weapon", "武器"), weaponName(weapon));
  appendStat(t("app.damagePerWeapon", "每枚伤害"), formatInt(damage));
  appendStat(t("app.targetHp2", "目标耐久"), formatInt(hp));

  const capacity = currentWeaponCapacity(aircraft, weapon.id);
  const plan = aircraft && capacity
    ? sortiePlan({ required: practicalCount, capacity, damage, rewardDamage: weapon.rewardDmg ?? damage, reward: catalog.reward })
    : null;
  if (plan) {
    sortieCountEl.textContent = String(plan.sorties);
    if (!preset) appendStat(t("app.maximumPerSortie2", "单次上限"), t("app.weapons", "{{v0}} 枚", {v0: plan.capacity}));
    if (plan.sorties > 1) appendStat(t("app.neededOnFinalSortie", "末次所需"), t("app.weapons2", "{{v0}} 枚", {v0: plan.lastSortieCount}));
    if (plan.fullLoadReward !== null) appendStat(t("app.fullLoadRewardCoefficient", "满载收益系数"), plan.fullLoadReward.toFixed(1), "reward");
    hintEl.textContent = target.kind === "airport_module"
      ? t("app.airfieldsRegenerateBetweenDropsMoreSortiesMayBeNeeded", "机场会在投弹间隙回血，实战可能需要更多架次。")
      : "";
  } else {
    sortieCountEl.textContent = "—";
    appendStat(t("app.aircraft", "机型"), t("app.notSelected", "未选择"));
    hintEl.textContent = target.kind === "airport_module"
      ? t("app.selectAnAircraftForLoadCapacityAndIdealSorties", "选择机型后显示挂载上限和理想架次；枚数指有效命中，未计防空拦截、脱靶与机场回血。")
      : t("app.selectAnAircraftForLoadCapacityFullLoadReward", "选择机型后显示挂载上限、满载收益系数和架次。");
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
    catalog.weapons = (weaponsBody.weapons || []).map(row => ({...row,
      get name() { return localizeName(row.name, row.name_en); },
      get short() { return localizeName(row.short, row.short_en); }}));
    catalog.targets = catalog.targets.map(row => ({...row, get label() { return localizeName(row.label); }}));
    aircraftCatalog = (aircraftBody.aircraft || []).filter(item => !item.id.endsWith("_missile_test") || !aircraftBody.aircraft.some(row => row.id === item.id.replace(/_missile_test$/, ""))).map(readableVehicle).filter((item) =>
      Array.isArray(item.w) && Array.isArray(item.n) && item.w.length === item.n.length &&
      item.n.every((count) => Number.isInteger(count) && count > 0));
    if (sourceEl) sourceEl.textContent = t("app.vAircraftWeapons", "v{{v0}} · {{v1}} 机型 · {{v2}} 武器", {v0: source.version, v1: aircraftCatalog.length.toLocaleString(numberLocale()), v2: catalog.weapons.length});
    fillSelect(targetSelect, catalog.targets, (target) => target.id, (target) => target.label, catalog.targets[0].id);
    renderSegments(targetSelect, document.querySelector("#calcTargetSegments"));
    renderBaseModes();
    renderBrOptions();
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
    if (location.origin === "https://bomana.ruikang.wang") void reportDailyActive("Calculator");
  } catch {
    catalog = null;
    rewardsCatalog = null;
    if (rewardResult) rewardResult.replaceChildren(conversionText("p", t("app.rewardDataFailedToLoadOrItsSourceIs", "收益数据加载失败或参数来源不一致，请刷新后重试。")));
    renderRewardChart(document.querySelector("#rewardChart"), null, t("app.rewardCatalogUnavailableNoCurveToDisplay", "收益目录未就绪，暂无曲线。"));
    document.querySelector("#rewardFormula").replaceChildren();
    if (sourceEl) sourceEl.textContent = t("app.dataUnavailableCatalogLoadingFailedOrSourceVersionsDisagree", "数据未就绪：目录加载失败或来源版本不一致，请刷新后重试。");
    setHudUnknown(t("app.catalogFailedToLoad", "目录加载失败"), t("app.missingOrMixedVersionDataWasNotUsedRefresh", "未使用缺失或混合版本的数据，刷新页面后再试。"));
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

brSelect.addEventListener("change", () => {
  selectedRoomBr = brSelect.value;
  syncSegments(brSelect, document.querySelector("#calcBrSegments")); refreshResult();
});
baseModeSelect.addEventListener("change", () => {
  if (!catalog) return;
  syncSegments(baseModeSelect, document.querySelector("#calcBaseModeSegments"));
  renderBrOptions();
  refreshResult();
});
targetSelect.addEventListener("change", () => {
  if (!catalog) return;
  syncSegments(targetSelect, document.querySelector("#calcTargetSegments"));
  renderBrOptions();
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

await initializeLanguage();
document.addEventListener("calculator:language", () => {
  if (!catalog) return;
  const aircraft = selectedAircraft();
  aircraftSearchInput.value = aircraft?.name || aircraftSearchInput.value;
  fillSelect(targetSelect, catalog.targets, target => target.id, target => target.label, targetSelect.value);
  renderSegments(targetSelect, document.querySelector("#calcTargetSegments"));
  renderBaseModes();
  renderBrOptions();
  renderAircraftSelection(false); renderAircraftList(); renderPresets(); renderWeaponList(); refreshResult();
  sourceEl.textContent = t("app.vAircraftWeapons", "v{{v0}} · {{v1}} 机型 · {{v2}} 武器", {v0: catalog.source.version, v1: aircraftCatalog.length.toLocaleString(numberLocale()), v2: catalog.weapons.length});
  renderRewardVehicles(); refreshReward(); renderRewardReference(); refreshFuel();
  for (const side of chargeSides) { renderChargeWeapons(side); refreshChargeSource(side); }
  refreshConversion();
});
bindConversion();
bindRewards();
initAirCalculator();
boot();
