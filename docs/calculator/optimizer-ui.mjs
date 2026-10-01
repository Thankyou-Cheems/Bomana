import { t, numberLocale, localizeName } from "./i18n.mjs";
import { presetDiagram, presetZoneAllocations } from "./loadouts.mjs";
import { validateLoadout } from "./custom-loadouts.mjs";
import { toggleRecommendationFilter, preferredGuidanceMode } from "./recommendation-guidance.mjs";

const node = (tag, text, className) => {
  const element = document.createElement(tag);
  if (text != null) element.textContent = text;
  if (className) element.className = className;
  return element;
};
const format = value => value.toLocaleString(numberLocale(), {maximumFractionDigits: 2});
const colorZone = (element, zone) => element.style.setProperty("--zone-hue", String((205 + (zone - 1) * 137.5) % 360));

export function createLoadoutOptimizer(root, {load, apply}) {
  let context, mode = "reward", signature = "", generation = 0, timer, worker, result, names = {};
  let currentDefinition;
  let filters = {onlyGuided: false, noHighDrag: false, noRockets: false, noMissiles: false, noLaser: false, noOptical: false, noSatellite: false, simpleLoadout: false, strictReward: false, rewardTolerance: .2};
  const status = root.querySelector("[data-optimizer-status]");
  const contextNote = root.querySelector("[data-optimizer-context]");
  const output = root.querySelector("[data-optimizer-result]");
  const explanation = root.querySelector("[data-optimizer-explanation]");
  const applyButton = root.querySelector("[data-optimizer-apply]");
  const retry = root.querySelector("[data-optimizer-retry]");
  const actions = root.querySelector(".optimizer-actions");
  const describe = items => items.map(([id, count]) => t(context.weapons.get(id)?.dmg > 0 ? "optimizer.shotCount" : "optimizer.supportCount", "{{weapon}} ×{{count}}", {
    weapon: localizeName(context.weapons.get(id)?.short || names[id] || context.weapons.get(id)?.name || id), count,
  })).join(" + ");

  function reflectControls() {
    const priority = filters.simpleLoadout ? "simple" : filters.strictReward ? "reward" : "balanced";
    const priorities = [...root.querySelectorAll("[data-optimizer-priority]")];
    for (const control of priorities) control.checked = control.value === priority;
    root.querySelector(".optimizer-priority").style.setProperty("--priority-index", String(priorities.findIndex(control => control.value === priority)));
    for (const button of root.querySelectorAll("[data-optimizer-filter]")) {
      const allowed = !filters[button.dataset.optimizerFilter];
      button.setAttribute("aria-checked", String(allowed));
      button.querySelector("[data-optimizer-filter-state]").textContent = allowed ? t("optimizer.allowed", "允许") : t("optimizer.excluded", "排除");
    }
    const guided = root.querySelector("[data-optimizer-guided-only]");
    guided.setAttribute("aria-checked", String(filters.onlyGuided));
    guided.querySelector("[data-optimizer-filter-state]").textContent = filters.onlyGuided ? t("optimizer.on", "开启") : t("optimizer.off", "关闭");
    root.querySelector("[data-optimizer-priority-help]").textContent = filters.simpleLoadout
      ? t("optimizer.uniformHelp", "优先统一投放特性和弹种，允许降低收益；始终保留手动选择。")
      : filters.strictReward ? t("optimizer.strictRewardHelp", "优先收益系数；收益完全相同时再选择更简单的挂载。")
        : t("optimizer.balancedHelp", "收益系数 ≥ {{floor}} 时优先更省事的投放方案，再减少弹种；其他情况优先收益。", {floor: format((context?.reward.ui_decoration ?? 10) - filters.rewardTolerance)});
    if (!filters.simpleLoadout) root.querySelector("[data-optimizer-priority-help]").textContent += " " + t("optimizer.guidancePreference", "在收益范围内优先卫星导航，光电补足伤害；按实际投放枚数比较操作负担。");
  }

  function render(next, definition) {
    result = next; currentDefinition = definition; output.replaceChildren(); explanation.replaceChildren();
    const storesEqual = next.preset && [...new Set([...next.preset.weapons, ...(context.currentStores || [])].map(([id]) => id))].every(id =>
      next.preset.weapons.filter(([weapon]) => weapon === id).reduce((sum, [,count]) => sum + count, 0) === (context.currentStores || []).filter(([weapon]) => weapon === id).reduce((sum, [,count]) => sum + count, 0));
    root.querySelector("[data-optimizer-state-label]").textContent = storesEqual ? t("optimizer.currentlyUsed", "当前已使用") : t("optimizer.notApplied", "尚未应用的推荐");
    root.dataset.applied = String(Boolean(storesEqual));
    applyButton.disabled = Boolean(storesEqual);
    root.dataset.state = next.searching ? "searching" : next.status;
    applyButton.hidden = !next.preset;
    retry.hidden = next.searching || ["optimal", "infeasible"].includes(next.status);
    if (!next.preset) {
      status.textContent = next.status === "infeasible" ? next.unknown ? t("optimizer-ui.noFeasibleConfigurationAmongWeaponsWithKnownDamage", "已知伤害数据中没有可行方案。") : context.lockedKeys.length ? t("optimizer-ui.noFeasibleCompletionWhileKeepingTheSelectedStores", "保留当前挂载时，没有可行的补齐方案。") : Object.entries(filters).some(([key, value]) => value === true && (key === "onlyGuided" || key.startsWith("no"))) ? t("optimizer.noFeasibleWithFilters", "当前弹药筛选下没有可行方案，可放宽筛选后重试。") : t("optimizer-ui.thisAircraftCannotReachTheBaseBurnOutThreshold", "此机型无法在一架次达到当前战区自毁线。")
        : next.status === "unknown" ? t("optimizer-ui.noConfirmedConfigurationFoundYetContinueSearching", "搜索尚未找到可确认的方案，可继续求解。") : t("optimizer-ui.recommendationIncompleteRetry", "推荐暂未完成，请重试。");
      if (next.unknown) output.append(node("p", t("optimizer-ui.someAmmunitionLacksDamageDataAndCannotBeCompared", "部分弹药缺少伤害数据，无法参与比较。"), "optimizer-note"));
      const summary = node("div", null, "optimizer-metrics");
      summary.append(contextNote, actions);
      output.append(summary);
      return;
    }
    status.textContent = next.searching ? t("optimizer-ui.optimizing", "继续优化中…") : next.status === "optimal" ? t("optimizer-ui.recommendedLoadout", "推荐配置") : t("optimizer-ui.availableConfiguration", "可用配置");
    const metrics = node("div", null, "optimizer-metrics");
    metrics.append(contextNote);
    metrics.append(node("strong", t("optimizer-ui.bases", "理论可收 {{v0}} 个战区", {v0: next.targets})), node("span", t("optimizer.recommendedReward", "收益系数 {{value}}", {value: format(next.reward)})));
    metrics.append(actions);
    output.append(metrics);
    if (next.workload) {
      const modes = new Map();
      for (const row of next.plan) for (const [id, count] of row) {
        const mode = preferredGuidanceMode(context.weapons.get(id), filters) || "unguided";
        modes.set(mode, (modes.get(mode) || 0) + count);
      }
      const modeNames = {satellite: "全球卫星导航", infrared: "红外", tv: "电视", optical: "光电（类型未细分）", laser: "激光", unguided: "非制导／未分类"};
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
    row.setAttribute("role", "button"); row.tabIndex = 0;
    row.setAttribute("aria-label", `${t("optimizer-ui.applyRecommendedLoadout", "应用推荐挂载")}：${describe(next.preset.weapons)}`);
    row.setAttribute("aria-disabled", String(Boolean(storesEqual)));
    const choose = () => { if (!storesEqual) void apply(next); };
    row.addEventListener("click", choose);
    row.addEventListener("keydown", event => { if (["Enter", " "].includes(event.key)) { event.preventDefault(); choose(); } });
    const label = node("span", null, "loadout-row-name");
    label.append(node("small", t("optimizer.recommendedStores", "推荐挂载")), node("strong", describe(next.preset.weapons)));
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
    row.append(label, diagram); stores.append(row);
    output.append(stores);
    const plan = node("section", null, "optimizer-plan");
    plan.append(node("h4", t("optimizer.deliveryPlan", "逐战区投放")));
    const zones = node("ol", null, "optimizer-zone-plan");
    next.plan.forEach((items, index) => {
      const zone = node("li"); zone.dataset.planZone = String(index + 1);
      colorZone(zone, index + 1);
      zone.append(node("strong", t("optimizer.zonePlan", "战区 {{index}}", {index: index + 1})));
      for (const item of items) {
        const row = node("p", describe([item]));
        row.dataset.weaponId = item[0]; row.dataset.projectileCount = String(item[1]);
        zone.append(row);
      }
      zones.append(zone);
    });
    plan.append(zones);
    if (next.remaining?.length) plan.append(node("p", t("optimizer.remainingStores", "投放后剩余：{{stores}}", {stores: describe(next.remaining)}), "optimizer-note"));
    output.append(plan);
    if (next.status !== "optimal") explanation.append(node("p", t("optimizer-ui.rewardCoefficientUpperBound", "收益系数理论上限 {{v0}}{{v1}}。", {v0: format(next.rewardUpper), v1: mode === "targets" ? t("optimizer-ui.baseCountUpperBound", " · 战区数量上限 {{v0}}", {v0: next.targetUpper}) : ""}), "optimizer-note"));
    const warnings = definition ? validateLoadout(definition, next.keys).warnings : next.warnings;
    if (next.unknown || warnings.length) output.append(node("p", [next.unknown ? t("optimizer-ui.onlyEquipmentWithKnownDamageIsCompared", "仅比较伤害数据已知的装备。") : "", ...warnings].join(" "), "optimizer-note"));
    applyButton.textContent = context.lockedKeys.length ? t("optimizer-ui.fillRemainingStations", "补齐剩余挂点") : t("optimizer-ui.applyRecommendedLoadout", "应用推荐挂载");
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
      worker = new Worker(url, {type: "module"});
      worker.onmessage = event => {
        if (id !== generation) return;
        if (!event.data.searching) { worker.terminate(); worker = null; }
        render(event.data, definition);
      };
      worker.onerror = () => {
        if (id !== generation) return;
        worker.terminate(); worker = null; render({status: "error"}, definition);
      };
      worker.postMessage({definition, presets: current.aircraft.presets || [], lockedKeys: current.lockedKeys,
        weapons: [...current.weapons], reward: current.reward, threshold: current.threshold, mode, filters, timeLimit});
    } catch {
      if (id === generation) render({status: "error"}, null);
    }
  }
  function update(next, timeLimit = 20) {
    context = next;
    reflectControls();
    const nextSignature = `${next.aircraft?.id}|${next.aircraft?.presets?.length}|${next.threshold}|${mode}|${JSON.stringify(filters)}|${next.lockedKeys.join(",")}`;
    if (nextSignature === signature) { if (result) render(result, currentDefinition); return; }
    signature = nextSignature; generation++; clearTimeout(timer); worker?.terminate(); worker = null; result = null;
    root.hidden = !next.aircraft || !next.threshold;
    if (root.hidden) return;
    applyButton.hidden = true; retry.hidden = true; output.replaceChildren(); explanation.replaceChildren(); root.dataset.state = "searching";
    root.dataset.applied = "false";
    root.querySelector("[data-optimizer-state-label]").textContent = t("optimizer.notApplied", "尚未应用的推荐");
    contextNote.textContent = next.lockedKeys.length ? t("optimizer-ui.keepingSelectedStations", "保留已选 {{v0}} 个挂点", {v0: next.lockedKeys.length}) : "";
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
    } else if (button.hasAttribute("data-optimizer-guided-only")) {
      filters = toggleRecommendationFilter(filters, "onlyGuided"); reflectControls();
      if (context) update(context);
    } else if (button.dataset.optimizerFilter in filters) {
      const key = button.dataset.optimizerFilter;
      filters = toggleRecommendationFilter(filters, key); reflectControls();
      if (context) update(context);
    } else if (button === applyButton && result?.preset) void apply(result);
    else if (button === retry) { signature = ""; update(context, 60); }
  });
  root.addEventListener("change", event => {
    if (!event.target.matches("[data-optimizer-priority]")) return;
    filters.simpleLoadout = event.target.value === "simple";
    filters.strictReward = event.target.value === "reward";
    reflectControls();
    if (context) update(context);
  });
  document.addEventListener("calculator:language", () => {
    reflectControls();
    if (!context) return;
    contextNote.textContent = context.lockedKeys.length ? t("optimizer-ui.keepingSelectedStations", "保留已选 {{v0}} 个挂点", {v0: context.lockedKeys.length}) : "";
    if (result) render(result, currentDefinition);
    else if (root.dataset.state === "searching") status.textContent = t("optimizer-ui.calculating", "计算中…");
  });
  reflectControls();
  return {update};
}
