import { compareLoadouts, durabilityBrBuckets, equivalentWeaponCount, explosiveConversion, requiredCount, returnFuelPlan, sharedParameterSource, sortiePlan, usefulActionsReferences, usefulActionsReference, usefulActionsPlan, usefulActionsObservedFraction, usefulActionsCardRate } from "./model.mjs";
import { rankFuzzyMatches } from "./search.mjs";

const catalogUrl = "/api/v1/calculator/index.json";
const weaponsUrl = "/api/v1/calculator/weapons.json";
const aircraftUrl = "/api/v1/calculator/aircraft.json";
const rewardsUrl = "/api/v1/calculator/rewards.json";
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
let rewardsCatalog = null;
let rewardSelectedVehicle = "f_15e";
const rewardsForm = document.querySelector("#rewardsForm");
const rewardFields = Object.fromEntries(["Mode", "Search", "Vehicle", "Score", "Minutes", "SlRate", "Method", "Fraction", "Observed", "RpRate", "RpFraction", "Account", "Booster"].map(key => [key, document.querySelector(`#reward${key}`)]));
const rewardResult = document.querySelector("#rewardResult");
const rewardUseCard = document.querySelector("#rewardUseCard");

function rewardVehicle() {
  return rewardsCatalog?.vehicles.find(row => row.id === rewardSelectedVehicle && row.mode === rewardFields.Mode.value);
}

function renderRewardVehicles() {
  if (!rewardsCatalog) return;
  const rows = rewardsCatalog.vehicles.filter(row => row.mode === rewardFields.Mode.value);
  const query = rewardFields.Search.value.trim();
  const matches = query ? rankFuzzyMatches(rows, query, row => [row.id, row.name, row.name_en]).slice(0, 100) : rows.slice(0, 100);
  let selected = rewardVehicle();
  if (!selected && rows.length) { selected = rows[0]; rewardSelectedVehicle = selected.id; }
  if (selected && !matches.some(row => row.id === selected.id)) matches.unshift(selected);
  fillSelect(rewardFields.Vehicle, matches, row => row.id, row => `${row.name} · ${row.id}`, rewardSelectedVehicle);
}

function loadRewardVehicle() {
  const row = rewardVehicle();
  rewardFields.SlRate.value = row ? String(row.sl_per_min) : "";
  for (const key of ["Fraction", "Observed", "RpRate", "RpFraction"]) rewardFields[key].value = "";
  refreshReward();
}

function rewardCardReference() {
  const row = rewardVehicle(), params = rewardsCatalog?.card_parameters;
  return usefulActionsCardRate({ rawRate: row?.sl_per_min, special: row?.special,
    premiumAccount: rewardFields.Account.value === "premium", boosterPercent: inputNumber(rewardFields.Booster),
    premiumMultiplier: params?.premium_account_multiplier, premiumVisualPart: params?.premium_visual_part });
}

function renderRewardCard() {
  const card = rewardCardReference(), preview = document.querySelector("#rewardCardPreview");
  rewardUseCard.disabled = !card;
  preview.replaceChildren();
  if (!card) { preview.textContent = "卡片基准参数缺失或输入无效，请核对加成器效果。"; return; }
  preview.append(conversionText("code", `${formatQuantity(card.visualBase)} × ${formatQuantity(card.visualMultiplier)} × (1 + ${formatQuantity(card.accountBonus)} + ${formatQuantity(card.boosterBonus)}) = ${formatQuantity(card.rate)} SL/min`));
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
  const chart = document.querySelector("#rewardChart"); chart.replaceChildren();
  chart.setAttribute("aria-label", `${sample.label}，各得分档比例见下表；折线仅连接历史样本。`);
  const ns = "http://www.w3.org/2000/svg", svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 600 155"); svg.setAttribute("aria-hidden", "true");
  const polyline = document.createElementNS(ns, "polyline");
  const xy = ([score, fraction]) => [30 + score / sample.points.at(-1)[0] * 535, 135 - fraction * 115];
  polyline.setAttribute("points", sample.points.map(p => xy(p).join(",")).join(" ")); svg.append(polyline);
  for (const p of sample.points) {
    const [x, y] = xy(p), circle = document.createElementNS(ns, "circle"), label = document.createElementNS(ns, "text");
    circle.setAttribute("cx", String(x)); circle.setAttribute("cy", String(y)); circle.setAttribute("r", "4");
    label.setAttribute("x", String(x)); label.setAttribute("y", String(y + 22)); label.textContent = `${p[0]}分`;
    svg.append(circle, label);
  }
  chart.append(svg);
}

function refreshReward() {
  if (!rewardsForm || !rewardsCatalog) return;
  renderRewardCard();
  const mode = rewardFields.Mode.value, rules = rewardsCatalog.mechanics[mode], row = rewardVehicle();
  const method = rewardFields.Method.value, minutes = inputNumber(rewardFields.Minutes), score = inputNumber(rewardFields.Score), slRate = inputNumber(rewardFields.SlRate);
  rewardFields.Fraction.disabled = method !== "manual";
  rewardFields.Observed.disabled = method !== "observed";
  const origin = document.querySelector("#rewardSource");
  origin.textContent = row ? `${row.name} · 客户端 ${rewardsCatalog.source.version} 基准 ${formatQuantity(row.sl_per_min)} SL/min${row.special ? " · 高级载具" : ""} · 载具研发倍率 ×${row.rp_multiplier ?? "未知"}（不是 RP/min）${slRate !== row.sl_per_min ? " · 使用调整后的 SL/min" : ""}` : "未选择有效收益机型";
  rewardResult.replaceChildren();
  const title = method === "observed" ? "本次结算核对" : method === "reference" ? "历史样本参考 · 非原生公式" : "自定义比例参考";
  rewardResult.append(conversionText("h3", title));
  let basis = mode === "air_sim" ? "before_landing_split" : "immediate";
  let fraction = inputNumber(rewardFields.Fraction) / 100;
  let unavailable = "填写有效收益比例后计算；目前无法从任务得分准确推导服务器活动率。也可选择实战反算或历史样本参考。";
  if (method === "reference") {
    const ref = usefulActionsReference({ mode, score, minutes, vehicleId: rewardSelectedVehicle });
    fraction = ref?.fraction ?? NaN;
    basis = ref?.basis ?? basis;
    unavailable = mode === "air_sim" ? "参考仅覆盖完整 15 分钟、200–1050 分；不外推低分、封顶和提前死亡。" : "参考仅覆盖 Ka-52 完整 10 分钟、200–800 分；其他机型和提前死亡不能套用。";
  } else if (method === "observed") {
    fraction = usefulActionsObservedFraction({ slReceived: inputNumber(rewardFields.Observed), slRate, minutes, immediateShare: mode === "air_sim" ? rules.immediate_share : 1 }) ?? NaN;
    unavailable = fraction > 1 ? `反算比例为 ${formatQuantity(fraction * 100)}%，超过 100%；请核对卡片加成、周期时间和奖励口径，不把它当作游戏活动率。` : "填入该周期实际即时 SL、正确的基准和时长后反算。";
  }
  const rpRate = rewardFields.RpRate.value.trim() ? inputNumber(rewardFields.RpRate) : null;
  const rpFraction = rewardFields.RpFraction.value.trim() ? inputNumber(rewardFields.RpFraction) / 100 : null;
  const plan = usefulActionsPlan({ periodMinutes: rules.period_minutes, minutes, score, slRate, rpRate, rpFraction, fraction, basis, immediateShare: rules.immediate_share });
  if (!plan) {
    if (!Number.isFinite(score) || score < 0) unavailable = "请填写本周期新增任务分数，不能使用负数。";
    else if (!Number.isFinite(minutes) || minutes <= 0 || minutes > rules.period_minutes) unavailable = `本周期时长须大于 0 且不超过 ${rules.period_minutes} 分钟。`;
    else if (!Number.isFinite(slRate) || slRate <= 0) unavailable = "请填写大于 0 的 SL/min 基准。";
    else if (rpRate !== null && (!Number.isFinite(rpRate) || rpRate <= 0)) unavailable = "RP/min 基准须大于 0；未知时请留空。";
    else if (rpFraction !== null && (!Number.isFinite(rpFraction) || rpFraction < 0 || rpFraction > 1)) unavailable = "RP 有效收益比例须在 0–100% 之间；未知时请留空。";
    else if (method === "manual" && (fraction < 0 || fraction > 1)) unavailable = "有效收益比例须在 0–100% 之间；若含有额外加成，请先核对每分钟基准。";
    rewardResult.append(conversionText("p", unavailable));
    if (Number.isFinite(slRate * rules.period_minutes) && slRate > 0) rewardResult.append(conversionText("p", `卡片完整周期基准：${formatQuantity(slRate)} × ${rules.period_minutes} = ${formatQuantity(slRate * rules.period_minutes)} SL。这是 100% 基准，不是实际到账承诺。`, "tool-note"));
    return;
  }
  const stats = document.createElement("dl"); stats.className = "reward-stats";
  const add = (label, value) => { const pair = document.createElement("div"); pair.append(conversionText("dt", label), conversionText("dd", value)); stats.append(pair); };
  add("有效 SL 比例", `${(fraction * 100).toFixed(2)}%`);
  add("即时 SL · 参考", `≈ ${formatInt(plan.slImmediate)}`);
  if (plan.slDeferred !== null) add("成功着陆 SL · 条件份额", `≈ ${formatInt(plan.slDeferred)}`);
  add("周期得分 / 分钟", formatQuantity(plan.scorePerMinute));
  if (plan.rpImmediate !== null) add("即时 RP · 自填参考", `≈ ${formatInt(plan.rpImmediate)}`);
  if (plan.rpDeferred !== null) add("成功着陆 RP · 条件份额", `≈ ${formatInt(plan.rpDeferred)}`);
  rewardResult.append(stats);
  const formulas = document.createElement("div"); formulas.className = "conversion-formulas";
  const text = `即时 SL ≈ ${formatQuantity(slRate)} SL/min × ${formatQuantity(minutes)} min × ${(fraction * 100).toFixed(2)}%${basis === "before_landing_split" ? " × 80%" : "（比例已含即时份额）"}`;
  const formula = document.createElement("p"); formula.append(conversionText("code", text)); formulas.append(formula);
  if (plan.rpImmediate !== null) {
    const rpFormula = document.createElement("p");
    rpFormula.append(conversionText("code", `即时 RP ≈ ${formatQuantity(rpRate)} RP/min × ${formatQuantity(minutes)} min × ${formatQuantity(rpFraction * 100)}%${basis === "before_landing_split" ? " × 80%" : "（RP 比例已含即时份额）"}`)); formulas.append(rpFormula);
  }
  rewardResult.append(formulas);
  if (method === "observed") rewardResult.append(conversionText("p", `本条记录为 ${formatQuantity(score)} 分 → ${formatQuantity(inputNumber(rewardFields.Observed))} 即时 SL；每分 ${score > 0 ? formatQuantity(inputNumber(rewardFields.Observed) / score) : "无法计算"} SL 只描述这条记录，不能线性外推。`));
  rewardResult.append(conversionText("p", `${minutes < rules.period_minutes ? "不足整周期：仅按输入做算术核对，死亡与退场规则未验证。" : ""}${method === "reference" ? "历史数据插值未按当前服务器校准，不能证明分数封顶。" : "有效比例按你的输入或记录计算，未提取服务器活动率。"}${mode === "heli_pve" ? "直升机的战后奖励及分成未知，未套用空战 80/20。" : "20% 仅展示成功机场着陆条件下的份额，未计算多周期累积或死亡损失。"}RP 独立使用手填参数；结果不含出场费、维修、胜利奖励和其他后处理。`, "tool-note"));
}

function bindRewards() {
  rewardsForm?.addEventListener("submit", event => event.preventDefault());
  rewardFields.Account?.addEventListener("change", renderRewardCard);
  rewardFields.Booster?.addEventListener("input", renderRewardCard);
  rewardUseCard?.addEventListener("click", () => {
    const card = rewardCardReference();
    if (card) { rewardFields.SlRate.value = String(card.rate); refreshReward(); }
  });
  rewardFields.Search?.addEventListener("input", renderRewardVehicles);
  rewardFields.Vehicle?.addEventListener("change", () => { rewardSelectedVehicle = rewardFields.Vehicle.value; loadRewardVehicle(); });
  rewardFields.Mode?.addEventListener("change", () => {
    rewardSelectedVehicle = rewardFields.Mode.value === "air_sim" ? "f_15e" : "ka_52";
    rewardFields.Search.value = "";
    const period = rewardsCatalog?.mechanics[rewardFields.Mode.value]?.period_minutes;
    if (period) { rewardFields.Minutes.value = String(period); rewardFields.Minutes.max = String(period); }
    renderRewardVehicles(); loadRewardVehicle(); renderRewardReference();
  });
  for (const key of ["Score", "Minutes", "SlRate", "Method", "Fraction", "Observed", "RpRate", "RpFraction"]) {
    rewardFields[key]?.addEventListener(key === "Method" ? "change" : "input", refreshReward);
  }
}

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
    const [catalogBody, weaponsBody, aircraftBody, rewardsBody] = await Promise.all([
      loadJson(catalogUrl),
      loadJson(weaponsUrl),
      loadJson(aircraftUrl),
      loadJson(rewardsUrl),
    ]);
    const source = sharedParameterSource([catalogBody, weaponsBody, aircraftBody, rewardsBody]);
    if (!source) throw new Error("mixed_parameter_sources");
    catalog = catalogBody;
    rewardsCatalog = rewardsBody;
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
    renderRewardVehicles(); loadRewardVehicle(); renderRewardReference();
    await nextFrame();
  } catch {
    catalog = null;
    rewardsCatalog = null;
    if (rewardResult) rewardResult.replaceChildren(conversionText("p", "收益数据加载失败或参数来源不一致，请刷新后重试。"));
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
bindRewards();
boot();
