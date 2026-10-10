import { empiricalSimScore, rewardUi } from "./model.mjs";
import { t, numberLocale, localizeName } from "./i18n.mjs";
import { presetDiagram, presetZoneAllocations, storesTitle } from "./loadouts.mjs";
import { validateLoadout } from "./custom-loadouts.mjs";
import { toggleRecommendationFilter, selectRecommendationGuidance, preferredGuidanceMode, normalizeGuidanceSelection, recommendationWeaponExcluded } from "./recommendation-guidance.mjs";

const node = (tag, text, className) => {
  const element = document.createElement(tag);
  if (text != null) element.textContent = text;
  if (className) element.className = className;
  return element;
};
const format = value => value.toLocaleString(numberLocale(), {maximumFractionDigits: 2});
const colorZone = (element, zone) => element.style.setProperty("--zone-hue", String((205 + (zone - 1) * 137.5) % 360));

export function createLoadoutOptimizer(root, {load, apply}) {
  let context, mode = "reward", baseMode = "reward", targetCount = 3, signature = "", generation = 0, timer, worker, workerBusy = false, workerContextKey = "", result, names = {};
  let currentDefinition;
  let displayedStores = "";
  let filters = {onlyGuided: false, noGuided: false, noHighDrag: false, noRockets: false, noMissiles: false, noLaser: false, noOptical: false, noSatellite: false, noManual: false, simpleLoadout: false, strictReward: false, rewardTolerance: .2};
  const storageKey = "bomana:calculator:optimizerFilters";
  try {
    const saved = JSON.parse(localStorage.getItem(storageKey) || "{}");
    for (const key of Object.keys(filters)) if (typeof filters[key] === "boolean" && typeof saved[key] === "boolean") filters[key] = saved[key];
    filters = normalizeGuidanceSelection(filters);
  } catch { /* Keep session defaults when storage is unavailable. */ }
  const persistFilters = () => { try { localStorage.setItem(storageKey, JSON.stringify(filters)); } catch { /* Session-only choice. */ } };
  const status = root.querySelector("[data-optimizer-status]");
  const contextNote = root.querySelector("[data-optimizer-context]");
  const output = root.querySelector("[data-optimizer-result]");
  const explanation = root.querySelector("[data-optimizer-explanation]");
  const applyButton = root.querySelector("[data-optimizer-apply]");
  const retry = root.querySelector("[data-optimizer-retry]");
  const actions = root.querySelector(".optimizer-actions");
  const stateLabel = root.querySelector("[data-optimizer-state-label]");
  const countInput = root.querySelector("[data-optimizer-target-count]");
  const describe = items => storesTitle(items, context.weapons, names);
  const scoreMode = () => ["sim_score", "global_sim_score"].includes(mode);
  const targetName = id => t(`simScore.target.${id}`, id);

  function reflectControls() {
    const rewardCap = context ? rewardUi(context.reward, 1, context.aircraft) : 10;
    const balancedHelp = rewardCap === null
      ? t("optimizer.strictRewardHelp", "优先收益系数；收益完全相同时再选择更简单的挂载。")
      : t("optimizer.balancedHelp", "收益系数 ≥ {{floor}} 时优先更省事的投放方案，再减少弹种；其他情况优先收益。", {floor: format(rewardCap - filters.rewardTolerance)});
    root.dataset.objective = mode;
    for (const button of root.querySelectorAll("[data-optimizer-mode]")) {
      button.hidden = button.dataset.optimizerMode === "global_sim_score" ? false : context ? button.dataset.optimizerMode === "sim_score" ? Boolean(context.threshold) : !context.threshold : false;
      button.setAttribute("aria-pressed", String(button.dataset.optimizerMode === mode));
    }
    root.querySelector("[data-optimizer-target-controls]").hidden = mode !== "custom_targets";
    countInput.setAttribute("aria-invalid", String(!Number.isSafeInteger(targetCount) || targetCount < 1));
    for (const button of root.querySelectorAll("[data-optimizer-target-preset]")) button.setAttribute("aria-pressed", String(Number(button.dataset.optimizerTargetPreset) === targetCount));
    const priority = mode === "global_sim_score" ? mode : filters.simpleLoadout ? "simple" : filters.strictReward ? "reward" : "balanced";
    const priorities = [...root.querySelectorAll("[data-optimizer-priority]")];
    for (const control of priorities) control.checked = control.value === priority;
    root.querySelector(".optimizer-priority").style.setProperty("--priority-index", String(priorities.findIndex(control => control.value === priority)));
    for (const button of root.querySelectorAll("[data-optimizer-filter]")) {
      const allowed = !filters[button.dataset.optimizerFilter];
      button.setAttribute("aria-checked", String(allowed));
      button.querySelector("[data-optimizer-filter-state]").textContent = allowed ? t("optimizer.allowed", "允许") : t("optimizer.excluded", "排除");
    }
    const guidance = filters.onlyGuided ? "guided" : filters.noGuided ? "unguided" : "any";
    const guidanceControls = [...root.querySelectorAll("[data-optimizer-guidance]")];
    for (const control of guidanceControls) control.checked = control.dataset.optimizerGuidance === guidance;
    root.querySelector(".optimizer-guidance-selection").style.setProperty("--guidance-index", String(guidanceControls.findIndex(control => control.checked)));
    root.querySelector("[data-optimizer-priority-help]").textContent = filters.simpleLoadout
      ? t("optimizer.uniformHelp", "优先统一投放特性和弹种，允许降低收益；始终保留手动选择。")
      : filters.strictReward ? t("optimizer.strictRewardHelp", "优先收益系数；收益完全相同时再选择更简单的挂载。")
        : balancedHelp;
    if (scoreMode()) { root.querySelector("[data-optimizer-priority-help]").textContent = mode === "global_sim_score"
      ? t("simScore.globalHelp", "比较整架飞机的合法挂载；每次出击只攻击1个满血战区，或1个满血机场模块。机场只用明确非制导弹药；当前手选挂点不固定。假设全部命中、燃烧完成，不计回血和机场摧毁奖励。")
      : t("simScore.objectiveHelp", "严格最大化同一目标剩余 HP、房间 BR 下的全挂载预计分数；已找到的同分候选优先减少投放类型、弹种、多余伤害及质量。收益偏好不降低分数目标。"); return; }
    if (!filters.simpleLoadout) root.querySelector("[data-optimizer-priority-help]").textContent += " " + t("optimizer.guidancePreference", "在收益范围内优先卫星导航，光电补足伤害；按实际投放枚数比较操作负担。");
    if (mode === "custom_targets") root.querySelector("[data-optimizer-priority-help]").textContent = t("optimizer.customHelp", "先完成目标数量，再比较实际覆盖数 × 整套挂载收益系数；多余容量不计奖。同收益优先减少冗余伤害、载荷。统一挂载偏好仍生效。") + (!filters.simpleLoadout && !filters.strictReward ? " " + balancedHelp : "");
  }

  function render(next, definition) {
    result = next; currentDefinition = definition; output.replaceChildren(); explanation.replaceChildren();
    const storesEqual = next.preset && (mode !== "global_sim_score" || next.targetId === context.scenario.targetId && context.scenario.remainingHp === next.scenario.remainingHp) && [...new Set([...next.preset.weapons, ...(context.currentStores || [])].map(([id]) => id))].every(id =>
      next.preset.weapons.filter(([weapon]) => weapon === id).reduce((sum, [,count]) => sum + count, 0) === (context.currentStores || []).filter(([weapon]) => weapon === id).reduce((sum, [,count]) => sum + count, 0));
    stateLabel.textContent = storesEqual ? t("optimizer.currentlyUsed", "当前已使用") : t("optimizer.notApplied", "尚未应用的推荐");
    root.dataset.applied = String(Boolean(storesEqual));
    applyButton.disabled = Boolean(storesEqual);
    root.dataset.state = next.searching ? "searching" : next.status;
    applyButton.hidden = !next.preset;
    retry.hidden = next.searching || ["optimal", "infeasible", "invalid"].includes(next.status);
    if (!next.preset) {
      if (next.reason === "invalid_target_count") {
        status.textContent = t("optimizer.targetInvalid", "请输入正整数战区数量。");
        output.append(contextNote, actions); return;
      }
      status.textContent = scoreMode() ? t("simScore.noRecommendation", "当前约束中没有可确认的分数推荐；请检查合法挂载、已知伤害与倍率参数，或继续求解。") : next.status === "infeasible" ? next.unknown ? t("optimizer-ui.noFeasibleConfigurationAmongWeaponsWithKnownDamage", "已知伤害数据中没有可行方案。") : context.lockedKeys.length ? t("optimizer-ui.noFeasibleCompletionWhileKeepingTheSelectedStores", "保留当前挂载时，没有可行的补齐方案。") : Object.entries(filters).some(([key, value]) => value === true && (key === "onlyGuided" || key.startsWith("no"))) ? t("optimizer.noFeasibleWithFilters", "当前弹药筛选下没有可行方案，可放宽筛选后重试。") : t("optimizer-ui.thisAircraftCannotReachTheBaseBurnOutThreshold", "此机型无法在一架次达到当前战区自毁线。")
        : next.status === "unknown" ? t("optimizer-ui.noConfirmedConfigurationFoundYetContinueSearching", "搜索尚未找到可确认的方案，可继续求解。") : t("optimizer-ui.recommendationIncompleteRetry", "推荐暂未完成，请重试。");
      if (next.unknown) output.append(node("p", t("optimizer-ui.someAmmunitionLacksDamageDataAndCannotBeCompared", "部分弹药缺少伤害数据，无法参与比较。"), "optimizer-note"));
      if (mode === "custom_targets") {
        output.append(node("strong", t("optimizer.customSummary", "目标 {{requested}} 区 · 本次覆盖 {{covered}} 区", {requested: targetCount, covered: next.targets || 0})));
        output.append(node("span", next.status === "infeasible" && !next.unknown ? t("optimizer.targetUnreachable", "单次不可达 · 最高 {{count}} 区", {count: 0}) : t("optimizer.targetUnproved", "已确认 {{count}} 区 · 目标可达性待确认", {count: next.targets || 0})));
      }
      const summary = node("div", null, "optimizer-metrics");
      summary.append(contextNote, actions);
      output.append(summary);
      return;
    }
    status.textContent = next.searching ? t("optimizer-ui.optimizing", "继续优化中…") : next.status === "optimal" ? t("optimizer-ui.recommendedLoadout", "推荐配置") : t("optimizer-ui.availableConfiguration", "可用配置");
    const metrics = node("div", null, "optimizer-metrics");
    metrics.append(contextNote);
    if (scoreMode()) {
      metrics.append(node("strong", t("simScore.recommendedScore", "全挂载预计 {{score}} 分", {score: format(next.score)})));
      if (mode === "global_sim_score") {
        metrics.append(node("span", targetName(next.targetId)));
        const comparison = node("ul", null, "global-score-comparison");
        for (const row of next.comparisons || []) comparison.append(node("li", `${targetName(row.targetId)} · ${Number.isFinite(row.score) ? format(row.score) : t("simScore.unavailable", "暂无估算")}`));
        explanation.append(comparison);
      }
    } else {
      if (mode === "custom_targets") {
        metrics.append(node("strong", t("optimizer.customSummary", "目标 {{requested}} 区 · 本次覆盖 {{covered}} 区", {requested: next.requestedTargets, covered: next.targets})));
        metrics.append(node("span", next.targetReached ? t("optimizer.targetReached", "可达 · 1 次出击") : next.coverageProven && !next.unknown ? t("optimizer.targetUnreachable", "单次不可达 · 最高 {{count}} 区", {count: next.targets}) : t("optimizer.targetUnproved", "已确认 {{count}} 区 · 目标可达性待确认", {count: next.targets})));
        if (!next.targetReached) metrics.append(node("span", t("optimizer.repeatSorties", "按同挂载重复：预计 {{count}} 次出击", {count: next.estimatedSorties})));
      } else metrics.append(node("strong", t("optimizer-ui.bases", "理论可收 {{v0}} 个战区", {v0: next.targets})));
      metrics.append(node("span", t("optimizer.recommendedReward", "收益系数 {{value}}", {value: format(next.reward)})));
    }
    const scoreScenario = mode === "global_sim_score" ? next.scenario : context.scenario;
    const estimated = scoreMode() ? next.estimate : empiricalSimScore({...scoreScenario,carried:next.preset.weapons,weapons:context.weapons,reward:context.reward});
    if (!scoreMode() && Number.isFinite(estimated?.totalScore)) metrics.append(node("span", t("simScore.recommendedScore", "全挂载预计 {{score}} 分", {score:format(estimated.totalScore)})));
    const sortieHp = scoreScenario?.destructionThreshold || scoreScenario?.remainingHp;
    if (sortieHp > 0 && next.damage > 0) metrics.append(node("span", t("optimizer.sorties", "预计 {{count}} 次出击", {count:Math.ceil(sortieHp / next.damage)})));
    if (scoreMode()) explanation.append(node("p", mode === "global_sim_score" ? t("simScore.globalHelp") : t("simScore.moduleEstimate", "按模块剩余 HP 封顶的经验估算；假设全部命中、燃烧完成，不计回血。"), "optimizer-note"));
    if (filters.noGuided) explanation.append(node("p", t("optimizer.unguidedHelp", "“不使用制导”仅自动选择明确非制导的弹药；未知分类不参与。手动锁定冲突会提示并保留。"), "optimizer-note"));
    const conflicts = next.preset.weapons.filter(([id]) => recommendationWeaponExcluded(context.weapons.get(id), filters));
    if (conflicts.length) output.append(node("p", t("optimizer.lockedGuidanceConflict", "保留的手动挂点含筛选外弹药：{{stores}}；自动补齐仍遵守筛选。", {stores: describe(conflicts)}), "optimizer-warning"));
    if (next.workload) {
      const modes = new Map();
      for (const row of next.plan) for (const [id, count] of row) {
        const mode = preferredGuidanceMode(context.weapons.get(id), filters) || "unguided";
        modes.set(mode, (modes.get(mode) || 0) + count);
      }
      const modeNames = {satellite: "全球卫星导航", infrared: "红外", tv: "电视", optical: "光电（类型未细分）", laser: "激光", manual: "手动指令制导", unguided: "非制导／未分类"};
      const summary = [...modes].map(([mode, count]) => `${t(`optimizer.mode.${mode}`, modeNames[mode])} ×${count}`).join(" + ");
      explanation.append(node("p", t("optimizer.deliveryModes", "投放方案的可用制导方式：{{modes}}", {modes: summary}), "optimizer-note"));
    }
    if (next.simplicity) explanation.append(node("p", t("optimizer.simpleLoadoutResult", "{{types}} 种弹药 · {{profiles}} 类投放特性", next.simplicity), "optimizer-note"));
    if (next.maximumReward > next.reward + 1e-6) explanation.append(node("p", t("optimizer.simplerNearCap", "收益系数 {{chosen}}，收益优先方案为 {{maximum}}；优先更省事的投放方案。", {chosen: format(next.reward), maximum: format(next.maximumReward)}), "optimizer-note"));
    if (mode === "targets" && next.singleZone) {
      explanation.append(node("p", t("optimizer-ui.basesSingleBase", "{{v0}} 个战区 × {{v1}} = {{v2}}；单战区 {{v3}}", {v0: next.targets, v1: format(next.reward), v2: format(next.totalReward), v3: format(next.singleZone.totalReward)}), "optimizer-note"));
      if (next.targets > 1 && !next.moreLoadoutUseful) output.append(node("p", t("optimizer-ui.moreStoresOfferNoRewardAdvantageUseTheSingle", "更多挂载无收益优势，建议使用单战区配置。"), "optimizer-warning"));
    }
    const stores = node("div", null, "optimizer-stores");
    stores.style.setProperty("--tier-count", next.preset.columns);
    const row = node("div", null, "loadout-row optimizer-preset-row");
    row.dataset.optimizerPreset = "";
    const label = node("span", null, "loadout-row-name");
    label.append(node("small", t("optimizer.recommendedStores", "推荐挂载")), stateLabel, actions, node("strong", describe(next.preset.weapons)));
    const diagram = presetDiagram(next.preset, context.weapons);
    const allocations = presetZoneAllocations(next.preset, next.plan);
    [...diagram.children].forEach((slot, index) => {
      const cells = allocations.filter(cell => cell.tier === index + 1);
      if (next.plan.length > 1) {
        const shares = node("span", null, "optimizer-slot-shares");
        for (const cell of cells) {
          for (const share of cell.zones) {
            const badge = node("small", t("optimizer.zoneShare", "{{zone}}区 ×{{count}}", share), "optimizer-zone-share");
            colorZone(badge, share.zone);
            badge.dataset.planZone = String(share.zone);
            badge.dataset.weaponId = cell.weapon;
            badge.dataset.projectileCount = String(share.count);
            badge.title = `${t("optimizer.zonePlan", "战区 {{index}}", {index: share.zone})} · ${describe([[cell.weapon, share.count]])}`;
            shares.append(badge);
          }
          if (cell.remaining && context.weapons.get(cell.weapon)?.dmg > 0) shares.append(node("small", t("optimizer.spareShare", "余 ×{{count}}", {count: cell.remaining}), "optimizer-spare-share"));
        }
        slot.append(shares);
      } else if (cells.length) slot.append(node("small", cells.map(cell => `×${cell.count}`).join(" + ")));
    });
    const recommended = node("div", null, "recommended-slot-area");
    recommended.append(diagram);
    row.append(label, recommended); stores.append(row);
    output.append(metrics, stores);
    const plan = node("section", null, "optimizer-plan");
    plan.append(node("h4", scoreMode() ? t("simScore.sortiePlan", "本轮投放方案") : t("optimizer.deliveryPlan", "逐战区投放")));
    const zones = node("ol", null, "optimizer-zone-plan");
    next.plan.forEach((items, index) => {
      const zone = node("li"); zone.dataset.planZone = String(index + 1);
      colorZone(zone, index + 1);
      zone.append(node("strong", mode === "global_sim_score" && next.targetId.startsWith("airport_") ? targetName(next.targetId) : mode === "sim_score" ? t("simScore.oneTarget", "1 个所选目标") : t("optimizer.zonePlan", "战区 {{index}}", {index: index + 1})));
      if (mode === "global_sim_score" && next.estimates?.[index]) zone.append(node("small", t("simScore.planScore", "预计 {{score}} 分 · 摧毁 {{destruction}} 分", {score:format(next.estimates[index].score),destruction:format(next.estimates[index].destructionScore)})));
      for (const item of items) {
        const row = node("p", describe([item]));
        row.dataset.weaponId = item[0]; row.dataset.projectileCount = String(item[1]);
        zone.append(row);
      }
      zones.append(zone);
    });
    plan.append(zones);
    if (next.remaining?.length) plan.append(node("p", t("optimizer.remainingStores", "投放后剩余：{{stores}}", {stores: describe(next.remaining)}), "optimizer-note"));
    explanation.append(plan);
    if (scoreMode() && next.status !== "optimal") explanation.append(node("p", Number.isFinite(next.scoreUpper) ? t("simScore.scoreUpper", "预计分数理论上限 {{score}}；尚未证明最高，可继续求解。", {score: format(next.scoreUpper)}) : t("simScore.maximumUnproved", "尚未证明最高预计分数，可继续求解。"), "optimizer-note"));
    if (!scoreMode() && next.status !== "optimal") explanation.append(node("p", t("optimizer-ui.rewardCoefficientUpperBound", "收益系数理论上限 {{v0}}{{v1}}。", {v0: format(next.rewardUpper), v1: mode === "targets" ? t("optimizer-ui.baseCountUpperBound", " · 战区数量上限 {{v0}}", {v0: next.targetUpper}) : ""}), "optimizer-note"));
    const warnings = definition ? validateLoadout(definition, next.keys).warnings : next.warnings;
    if (next.unknown || warnings.length) output.append(node("p", [next.unknown ? t("optimizer-ui.onlyEquipmentWithKnownDamageIsCompared", "仅比较伤害数据已知的装备。") : "", ...warnings].join(" "), "optimizer-note"));
    applyButton.textContent = mode !== "global_sim_score" && context.lockedKeys.length ? t("optimizer-ui.fillRemainingStations", "补齐剩余挂点") : t("optimizer-ui.applyRecommendedLoadout", "应用推荐挂载");
  }

  async function start(id, timeLimit) {
    const current = context;
    try {
      const catalog = current.aircraft.custom ? await load() : null;
      if (id !== generation) return;
      const definition = catalog?.aircraft[current.aircraft.id] || null;
      names = catalog?.names || {};
      if (current.aircraft.custom && !definition) throw new Error("missing_custom_rules");
      const url = new URL("./optimizer-worker.mjs", import.meta.url); url.search = new URL(import.meta.url).search;
      if (!worker) { worker = new Worker(url, {type: "module"}); workerContextKey = ""; }
      workerBusy = true;
      worker.onmessage = event => {
        if (id !== generation || event.data.requestId !== id) return;
        if (!event.data.searching) workerBusy = false;
        render(event.data, definition);
      };
      worker.onerror = () => {
        if (id !== generation) return;
        worker.terminate(); worker = null; workerBusy = false; render({status: "error"}, definition);
      };
      const contextKey = `${current.aircraft.id}|${current.threshold}|${JSON.stringify(filters)}|${current.lockedKeys.join(",")}|${JSON.stringify(current.scenario)}|${JSON.stringify(current.scenarios)}`;
      const message = {contextKey, requestId: id, mode, targetCount: mode === "global_sim_score" ? 1 : targetCount, filters, timeLimit};
      if (contextKey !== workerContextKey) {
        message.context = {definition, presets: current.aircraft.presets || [], lockedKeys: current.lockedKeys,
          weapons: [...current.weapons], reward: current.reward, aircraft: {id: current.aircraft.id, reward: current.aircraft.reward}, threshold: current.threshold, scenario: current.scenario, scenarios:current.scenarios, filters};
        workerContextKey = contextKey;
      }
      worker.postMessage(message);
    } catch {
      if (id === generation) render({status: "error"}, null);
    }
  }
  function update(next, timeLimit = 20) {
    context = next;
    if (mode !== "global_sim_score" && !next.threshold) { if (mode !== "sim_score") baseMode = mode; mode = "sim_score"; }
    else if (mode === "sim_score") mode = baseMode;
    const nextSignature = `${next.aircraft?.id}|${next.aircraft?.presets?.length}|${next.threshold}|${mode}|${mode === "custom_targets" ? targetCount : ""}|${JSON.stringify(filters)}|${next.lockedKeys.join(",")}|${JSON.stringify(next.scenario)}|${JSON.stringify(next.scenarios)}`;
    const stores = JSON.stringify(next.currentStores || []);
    if (nextSignature === signature) {
      if (stores !== displayedStores && result) render(result, currentDefinition);
      displayedStores = stores; return;
    }
    displayedStores = stores;
    reflectControls();
    signature = nextSignature; generation++; clearTimeout(timer);
    if (workerBusy) { worker?.terminate(); worker = null; workerBusy = false; }
    result = null;
    root.hidden = false;
    root.dataset.available = String(Boolean(next.aircraft));
    applyButton.hidden = true; retry.hidden = true; output.replaceChildren(); explanation.replaceChildren(); root.dataset.state = "searching";
    if (!next.aircraft) { status.textContent = ""; contextNote.textContent = ""; return; }
    root.dataset.applied = "false";
    stateLabel.textContent = t("optimizer.notApplied", "尚未应用的推荐");
    contextNote.textContent = mode === "global_sim_score" ? t("simScore.globalContext", "每次出击1个满血目标 · 机场排除制导") : next.lockedKeys.length ? t("optimizer-ui.keepingSelectedStations", "保留已选 {{v0}} 个挂点", {v0: next.lockedKeys.length}) : "";
    status.textContent = t("optimizer-ui.calculating", "计算中…");
    const id = generation;
    timer = setTimeout(() => start(id, timeLimit), 300);
  }
  root.addEventListener("click", event => {
    const button = event.target.closest("button");
    if (!button) return;
    if (button.dataset.optimizerMode) {
      mode = button.dataset.optimizerMode;
      for (const item of root.querySelectorAll("[data-optimizer-mode]")) item.setAttribute("aria-pressed", String(item === button));
      update(context);
    } else if (button.dataset.optimizerTargetPreset) {
      targetCount = Number(button.dataset.optimizerTargetPreset); countInput.value = String(targetCount); update(context);
    } else if (button.dataset.optimizerFilter in filters) {
      const key = button.dataset.optimizerFilter;
      filters = toggleRecommendationFilter(filters, key); persistFilters(); reflectControls();
      if (context) update(context);
    } else if (button === applyButton && result?.preset) void apply(result);
    else if (button === retry) { signature = ""; update(context, 60); }
  });
  root.addEventListener("change", event => {
    if (event.target.matches("[data-optimizer-guidance]")) {
      const selection = event.target.dataset.optimizerGuidance;
      filters = selectRecommendationGuidance(filters, selection);
      persistFilters();
      reflectControls();
      if (context) update(context);
      return;
    }
    if (!event.target.matches("[data-optimizer-priority]")) return;
    if (event.target.value === "global_sim_score") { if (mode !== "global_sim_score" && mode !== "sim_score") baseMode = mode; mode = "global_sim_score"; }
    else if (mode === "global_sim_score") mode = context?.threshold ? baseMode : "sim_score";
    filters.simpleLoadout = event.target.value === "simple";
    filters.strictReward = event.target.value === "reward";
    persistFilters();
    reflectControls();
    if (context) update(context);
  });
  countInput.addEventListener("input", () => {
    targetCount = countInput.value === "" ? NaN : Number(countInput.value);
    countInput.setAttribute("aria-invalid", String(!Number.isSafeInteger(targetCount) || targetCount < 1));
    if (context) update(context);
  });
  document.addEventListener("calculator:language", () => {
    reflectControls();
    if (!context) return;
    contextNote.textContent = mode === "global_sim_score" ? t("simScore.globalContext") : context.lockedKeys.length ? t("optimizer-ui.keepingSelectedStations", "保留已选 {{v0}} 个挂点", {v0: context.lockedKeys.length}) : "";
    if (result) render(result, currentDefinition);
    else if (root.dataset.state === "searching") status.textContent = t("optimizer-ui.calculating", "计算中…");
  });
  reflectControls();
  return {update};
}

export function createSimScoreEstimator(root, {changeRoomBr, changeScenario, summary}) {
  let context, signature = "", delivered = [];
  const br = root.querySelector("[data-sim-score-br]");
  const percent = root.querySelector("[data-sim-score-hp]");
  const rows = root.querySelector("[data-sim-score-rows]");
  const output = root.querySelector("[data-sim-score-result]");
  const scenario = () => ({aircraftId: context?.aircraft?.id, targetId: context?.targetId,
    battleMode: "simulator", targetFullHp: context?.hp, destructionThreshold: context?.destructionThreshold,
    roomMaxBr: Number(br.value), remainingHp: percent.value === "" ? NaN :
      Number(percent.value) >= 0 && Number(percent.value) <= 100 ? context?.hp * Number(percent.value) / 100 : NaN});
  function renderRows() {
    rows.replaceChildren();
    for (const [id, count] of context.carried) {
      const label = node("label", null, "sim-score-delivery");
      const weapon = context.weapons.get(id);
      label.append(node("span", t("simScore.deliveredCount", "{{weapon}}：投放 / 命中枚数（携带 {{count}}）", {weapon: localizeName(weapon?.short || weapon?.name || id), count})));
      const input = node("input"); input.type = "number"; input.min = "0"; input.max = String(count); input.step = "1";
      input.dataset.simScoreDelivered = id; input.value = String(delivered.find(([weapon]) => weapon === id)?.[1] ?? count);
      label.append(input); rows.append(label);
    }
  }
  function render() {
    if (!context) return;
    output.replaceChildren();
    const current = scenario();
    summary.replaceChildren();
    const full = context.validLoadout && empiricalSimScore({...current, carried: context.carried, weapons: context.weapons, reward: context.reward});
    const actual = full && empiricalSimScore({...current, carried: context.carried, delivered, weapons: context.weapons, reward: context.reward});
    if (!full || !actual) {
      root.dataset.coverage = "unavailable";
      summary.textContent = t("simScore.unavailable", "暂无估算");
      return;
    }
    root.dataset.coverage = actual.coverage;
    root.dataset.confidence = actual.confidence;
    const fullScore = node("strong", format(full.score));
    fullScore.dataset.simScoreFull = "";
    summary.append(node("span", full.scoreKind === "damage_only"
      ? t("simScore.estimatedDamage", "预计轰炸得分") : t("simScore.estimatedScore", "预计得分")), fullScore);
    const stats = node("dl", null, "reward-stats");
    const row = node("div"), deliveredScore = node("dd", format(actual.score));
    deliveredScore.dataset.simScoreDeliveredScore = "";
    row.append(node("dt", actual.scoreKind === "damage_only" ? t("simScore.deliveredDamage", "当前投放轰炸得分")
      : t("simScore.deliveredScore", "当前投放预计分数")), deliveredScore);
    stats.append(row);
    if (current.targetId === "bombing_point_planes") {
      for (const [key, label, value] of [
        ["simScoreDamage", t("simScore.damageScore", "轰炸基地"), actual.damageScore],
        ["simScoreDestruction", t("simScore.destructionScore", "摧毁基地"), actual.destructionScore],
      ]) {
        const detail = node("div"), amount = node("dd", value === null ? t("simScore.uncalibratedDestruction", "未校准") : format(value));
        amount.dataset[key] = ""; detail.append(node("dt", label), amount); stats.append(detail);
      }
    }
    const scope = current.targetId === "bombing_point_planes"
      ? t("simScore.baseScope", "满血战区按本轮独立摧毁估算轰炸＋摧毁分；已受损战区的摧毁归属未知。经验估算，跨条件精度未知；不计其他奖励。")
      : t("simScore.airportScope", "机场只估算轰炸伤害分，不计摧毁奖励；伤害不足以摧毁时，摧毁分为零。经验估算，跨条件精度未知。");
    output.append(stats, node("p", scope, "optimizer-note"));
  }
  rows.addEventListener("input", event => {
    const id = event.target.dataset.simScoreDelivered;
    if (!id) return;
    const row = delivered.find(([weapon]) => weapon === id);
    row[1] = event.target.value === "" ? NaN : Number(event.target.value);
    render();
  });
  percent.addEventListener("input", () => { render(); changeScenario(); });
  br.addEventListener("change", () => changeRoomBr(br.value));
  root.querySelector("[data-sim-score-full-delivery]").addEventListener("click", () => { delivered = context.carried.map(row => [...row]); renderRows(); render(); });
  document.addEventListener("calculator:language", () => { if (context) { renderRows(); render(); } });
  return {scenario, update(next) {
    const nextSignature = `${next.aircraft?.id}|${JSON.stringify(next.carried)}`;
    context = next;
    if (br.options.length !== next.brValues.length) br.replaceChildren(...next.brValues.map(value => new Option(value, value)));
    br.value = String(next.roomMaxBr);
    if (nextSignature !== signature) { signature = nextSignature; delivered = next.carried.map(row => [...row]); renderRows(); }
    render();
    return scenario();
  }};
}
