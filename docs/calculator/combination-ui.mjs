import { combinationTotals } from "./custom-loadouts.mjs";

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text != null) node.textContent = text;
  if (className) node.className = className;
  return node;
}

export function createCombinationCalculator(root) {
  let context = null;
  let rows = [["us_1000lb_mk_83_ldgp", 1], ["us_500lb_mk_82_ldgp", 1]];
  const list = root.querySelector("[data-combination-rows]");
  const result = root.querySelector("[data-combination-result]");
  const reference = root.querySelector("[data-combination-reference]");
  const usePreset = root.querySelector("[data-combination-preset]");
  const format = value => value === null ? "未知" : value.toLocaleString("zh-CN", { maximumFractionDigits: 2 });

  function options(select, selected, includeTnt = false) {
    select.replaceChildren();
    if (includeTnt) select.append(new Option("仅显示 TNT 千克当量", ""));
    for (const weapon of context.weapons.values()) select.append(new Option(weapon.name, weapon.id));
    select.value = selected;
  }

  function renderRows() {
    list.replaceChildren();
    rows.forEach(([id, count], index) => {
      const row = element("div", null, "combination-row");
      const label = element("label", null, "hangar-field");
      label.append(element("span", `弹药 ${index + 1}`));
      const select = element("select"); select.dataset.combinationWeapon = index;
      options(select, id); label.append(select);
      const quantity = element("label", null, "hangar-field"); quantity.append(element("span", "数量（枚）"));
      const input = element("input"); input.type = "number"; input.min = "0"; input.step = "1";
      input.value = String(count); input.dataset.combinationCount = index; quantity.append(input);
      const remove = element("button", "移除", "hangar-clear"); remove.type = "button";
      remove.dataset.combinationRemove = index; remove.setAttribute("aria-label", `移除弹药 ${index + 1}`);
      row.append(label, quantity, remove); list.append(row);
    });
  }

  function renderResult() {
    if (!context) return;
    root.querySelector("[data-combination-target]").textContent = `当前目标：${context.targetLabel} · ${format(context.hp)} HP`;
    usePreset.disabled = !context.preset;
    const totals = combinationTotals(rows, context.weapons, context.hp);
    result.replaceChildren();
    if (!totals) {
      result.append(element("p", "请为每种弹药输入非负整数数量。")); return;
    }
    const stats = element("dl", null, "reward-stats");
    for (const [label, value] of [
      ["弹药总数", `${format(totals.count)} 枚`],
      ["TNT 当量", totals.tnt === null ? "未知" : `${format(totals.tnt)} kg`],
      ["弹药质量", totals.mass === null ? "未知" : `${format(totals.mass)} kg`],
      ["每轮任务伤害", totals.damage === null ? "未知" : `${format(totals.damage)} HP`],
      ["完整摧毁轮次", totals.rounds === null ? "—" : `${totals.rounds} 轮`],
    ]) {
      const entry = element("div"); entry.append(element("dt", label), element("dd", value)); stats.append(entry);
    }
    result.append(stats);
    if (context.fireHp && totals.damage > 0) result.append(element("p", `点燃 / 自毁参考：${Math.ceil(context.fireHp / totals.damage)} 轮。`));
    const comparison = context.weapons.get(reference.value);
    if (comparison) {
      const one = combinationTotals([[comparison.id, 1]], context.weapons, context.hp);
      result.append(element("p", `按 TNT 当量相当于 ${totals.tnt !== null && one.tnt > 0 ? format(totals.tnt / one.tnt) : "未知数量的"} 枚${comparison.name}；按任务伤害相当于 ${totals.damage !== null && one.damage > 0 ? format(totals.damage / one.damage) : "未知数量的"} 枚。`));
    }
  }

  root.addEventListener("input", event => {
    if (event.target.dataset.combinationCount !== undefined) {
      rows[Number(event.target.dataset.combinationCount)][1] = event.target.value === "" ? NaN : Number(event.target.value);
      renderResult();
    }
  });
  root.addEventListener("change", event => {
    if (event.target.dataset.combinationWeapon !== undefined) rows[Number(event.target.dataset.combinationWeapon)][0] = event.target.value;
    renderResult();
  });
  root.addEventListener("click", event => {
    const button = event.target.closest("button");
    if (!button || !context) return;
    if (button.dataset.combinationRemove !== undefined) rows.splice(Number(button.dataset.combinationRemove), 1);
    else if (button.hasAttribute("data-combination-add")) rows.push([rows[0]?.[0] || context.weapons.keys().next().value, 1]);
    else if (button === usePreset && context.preset) rows = context.preset.weapons.map(row => [...row]);
    else return;
    renderRows(); renderResult();
  });
  return {
    update(next) {
      const initialize = !context;
      context = next;
      if (initialize) { options(reference, "", true); renderRows(); }
      renderResult();
    },
  };
}
