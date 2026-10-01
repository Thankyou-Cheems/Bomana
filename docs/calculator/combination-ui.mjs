import { t, numberLocale } from "./i18n.mjs";
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
  const format = value => value === null ? t("combination-ui.unknown", "未知") : value.toLocaleString(numberLocale(), { maximumFractionDigits: 2 });

  function options(select, selected, includeTnt = false) {
    select.replaceChildren();
    if (includeTnt) select.append(new Option(t("combination-ui.showTntMassEquivalenceOnly", "仅显示 TNT 千克当量"), ""));
    for (const weapon of context.weapons.values()) select.append(new Option(weapon.name, weapon.id));
    select.value = selected;
  }

  function renderRows() {
    list.replaceChildren();
    rows.forEach(([id, count], index) => {
      const row = element("div", null, "combination-row");
      const label = element("label", null, "hangar-field");
      label.append(element("span", t("combination-ui.weapon", "弹药 {{v0}}", {v0: index + 1})));
      const select = element("select"); select.dataset.combinationWeapon = index;
      options(select, id); label.append(select);
      const quantity = element("label", null, "hangar-field"); quantity.append(element("span", t("combination-ui.quantity", "数量（枚）")));
      const input = element("input"); input.type = "number"; input.min = "0"; input.step = "1";
      input.value = String(count); input.dataset.combinationCount = index; quantity.append(input);
      const remove = element("button", t("combination-ui.remove", "移除"), "hangar-clear"); remove.type = "button";
      remove.dataset.combinationRemove = index; remove.setAttribute("aria-label", t("combination-ui.removeWeapon", "移除弹药 {{v0}}", {v0: index + 1}));
      row.append(label, quantity, remove); list.append(row);
    });
  }

  function renderResult() {
    if (!context) return;
    root.querySelector("[data-combination-target]").textContent = t("combination-ui.currentTargetHp", "当前目标：{{v0}} · {{v1}} HP", {v0: context.targetLabel, v1: format(context.hp)});
    usePreset.disabled = !context.preset;
    const totals = combinationTotals(rows, context.weapons, context.hp);
    result.replaceChildren();
    if (!totals) {
      result.append(element("p", t("combination-ui.enterANonnegativeIntegerQuantityForEachWeapon", "请为每种弹药输入非负整数数量。"))); return;
    }
    const stats = element("dl", null, "reward-stats");
    for (const [label, value] of [
      [t("combination-ui.totalAmmunition", "弹药总数"), t("combination-ui.weapons", "{{v0}} 枚", {v0: format(totals.count)})],
      [t("combination-ui.tntEquivalence", "TNT 当量"), totals.tnt === null ? t("combination-ui.unknown2", "未知") : `${format(totals.tnt)} kg`],
      [t("combination-ui.ammunitionMass", "弹药质量"), totals.mass === null ? t("combination-ui.unknown3", "未知") : `${format(totals.mass)} kg`],
      [t("combination-ui.missionDamagePerLoad", "每轮任务伤害"), totals.damage === null ? t("combination-ui.unknown4", "未知") : `${format(totals.damage)} HP`],
      [t("combination-ui.loadsForDirectDestruction", "完整摧毁轮次"), totals.rounds === null ? "—" : t("combination-ui.loads", "{{v0}} 轮", {v0: totals.rounds})],
    ]) {
      const entry = element("div"); entry.append(element("dt", label), element("dd", value)); stats.append(entry);
    }
    result.append(stats);
    if (context.fireHp && totals.damage > 0) result.append(element("p", t("combination-ui.burnOutReferenceLoads", "点燃 / 自毁参考：{{v0}} 轮。", {v0: Math.ceil(context.fireHp / totals.damage)})));
    const comparison = context.weapons.get(reference.value);
    if (comparison) {
      const one = combinationTotals([[comparison.id, 1]], context.weapons, context.hp);
      result.append(element("p", t("combination-ui.tntEquivalenceMissionDamageEquivalenceWeapons", "按 TNT 当量相当于 {{v0}} 枚{{v1}}；按任务伤害相当于 {{v2}} 枚。", {v0: totals.tnt !== null && one.tnt > 0 ? format(totals.tnt / one.tnt) : t("combination-ui.anUnknownNumberOf", "未知数量的"), v1: comparison.name, v2: totals.damage !== null && one.damage > 0 ? format(totals.damage / one.damage) : t("combination-ui.anUnknownNumberOf2", "未知数量的")})));
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
  document.addEventListener("calculator:language", () => { if (context) { options(reference, reference.value, true); renderRows(); renderResult(); } });
  return {
    update(next) {
      const initialize = !context;
      context = next;
      if (initialize) { options(reference, "", true); renderRows(); }
      renderResult();
    },
  };
}
