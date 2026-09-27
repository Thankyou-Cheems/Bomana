import { ordnance, presetTitle } from "./loadouts.mjs";

const node = (tag, text, className) => {
  const element = document.createElement(tag);
  if (text != null) element.textContent = text;
  if (className) element.className = className;
  return element;
};
const format = value => value.toLocaleString("zh-CN", {maximumFractionDigits: 2});

export function createLoadoutOptimizer(root, {load, apply}) {
  let context, mode = "reward", signature = "", generation = 0, timer, worker, result, names = {};
  const status = root.querySelector("[data-optimizer-status]");
  const output = root.querySelector("[data-optimizer-result]");
  const applyButton = root.querySelector("[data-optimizer-apply]");
  const retry = root.querySelector("[data-optimizer-retry]");
  const describe = items => items.map(([id, count]) => `${context.weapons.get(id)?.short || names[id] || context.weapons.get(id)?.name || id} ×${count}`).join(" + ");

  function render(next, definition) {
    result = next; output.replaceChildren();
    root.dataset.state = next.searching ? "searching" : next.status;
    applyButton.hidden = !next.preset;
    retry.hidden = next.searching || ["optimal", "infeasible"].includes(next.status);
    if (!next.preset) {
      status.textContent = next.status === "infeasible" ? next.unknown ? "已知伤害数据中没有可行方案。" : context.lockedKeys.length ? "保留当前挂载时，没有可行的补齐方案。" : "此机型无法在一架次达到当前战区自毁线。"
        : next.status === "unknown" ? "搜索尚未找到可确认的方案，可继续求解。" : "推荐暂未完成，请重试。";
      if (next.unknown) output.append(node("p", "部分弹药缺少伤害数据，无法参与比较。", "optimizer-note"));
      return;
    }
    status.textContent = next.searching ? "已找到可行方案，继续核验最优解…" : next.status === "optimal" ? "已验证最优配置" : "当前可行方案 · 尚未证明最优";
    const metrics = node("div", null, "optimizer-metrics");
    metrics.append(node("strong", `可收 ${next.targets} 个战区`), node("span", `收益系数 ${format(next.reward)}`));
    output.append(metrics);
    const stores = node("div", null, "optimizer-stores");
    const cells = next.kind === "custom" ? next.keys.map(key => definition.options.find(option => option.key === key)).map(option => {
      const contents = new Map();
      for (const cell of option.cells) contents.set(cell.weapon, (contents.get(cell.weapon) || 0) + cell.count);
      return {...option.cells[0], label: `挂点 ${option.tier + 1} · ${describe([...contents])}`};
    })
      : next.preset.cells.filter((cell, index, cells) => cells.findIndex(other => other.weapon === cell.weapon) === index).map(cell => ({...cell, label: describe(next.preset.weapons.filter(([id]) => id === cell.weapon)) || "配套装备"}));
    for (const cell of cells) {
      const card = node("span", null, "optimizer-store"); card.title = cell.label;
      card.append(ordnance(cell), node("small", cell.label)); stores.append(card);
    }
    output.append(stores);
    if (next.kind === "preset") output.append(node("p", presetTitle(next.preset, context.weapons), "optimizer-note"));
    const plan = node("details", null, "optimizer-plan");
    plan.append(node("summary", `投放方案 · 总伤害 ${format(next.damage)} HP`));
    const groups = new Map();
    next.plan.forEach((items, index) => {
      const label = describe(items);
      if (!groups.has(label)) groups.set(label, []);
      groups.get(label).push(index + 1);
    });
    for (const [label, targets] of groups) plan.append(node("p", `战区 ${targets.join("、")}：${label}`));
    output.append(plan);
    if (next.status !== "optimal") output.append(node("p", `收益系数理论上限 ${format(next.rewardUpper)}${mode === "targets" ? ` · 战区数量上限 ${next.targetUpper}` : ""}。`, "optimizer-note"));
    if (next.unknown || next.warnings.length) output.append(node("p", [next.unknown ? "仅比较伤害数据已知的装备。" : "", ...next.warnings].join(" "), "optimizer-note"));
    applyButton.textContent = context.lockedKeys.length ? "补齐剩余挂点" : "应用推荐挂载";
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
        weapons: [...current.weapons], reward: current.reward, threshold: current.threshold, mode, timeLimit});
    } catch {
      if (id === generation) render({status: "error"}, null);
    }
  }
  function update(next, timeLimit = 20) {
    context = next;
    const nextSignature = `${next.aircraft?.id}|${next.aircraft?.presets?.length}|${next.threshold}|${mode}|${next.lockedKeys.join(",")}`;
    if (nextSignature === signature) return;
    signature = nextSignature; generation++; clearTimeout(timer); worker?.terminate(); worker = null; result = null;
    root.hidden = !next.aircraft || !next.threshold;
    if (root.hidden) return;
    applyButton.hidden = true; retry.hidden = true; output.replaceChildren(); root.dataset.state = "searching";
    root.querySelector("[data-optimizer-context]").textContent = `自毁线 ${format(next.threshold)} HP${next.lockedKeys.length ? ` · 保留已选 ${next.lockedKeys.length} 个挂点` : " · 比较全部可用挂载"}`;
    status.textContent = "正在寻找可行的最优配置…";
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
    } else if (button === applyButton && result?.preset) void apply(result);
    else if (button === retry) { signature = ""; update(context, 60); }
  });
  return {update};
}
