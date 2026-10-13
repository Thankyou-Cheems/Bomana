import { t, numberLocale } from "./i18n.mjs";
import { measuredFuelBurn, workflowIds, workflowFromHash } from "./workflow-model.mjs";

const byId = id => document.getElementById(id);
const toolbox = byId("sortieTools");
if (toolbox) {
  let active = workflowFromHash(location.hash) || "returnFuel";
  const links = [...toolbox.querySelectorAll("[data-workflow]")];
  function showTool(id, { scroll = false, focus = false } = {}) {
    if (!workflowIds.includes(id)) return;
    active = id;
    for (const panelId of workflowIds) byId(panelId).hidden = panelId !== id;
    for (const link of links) {
      if (link.dataset.workflow === id) link.setAttribute("aria-current", "location");
      else link.removeAttribute("aria-current");
    }
    const heading = byId(id).querySelector("h2");
    if (focus) { heading.tabIndex = -1; heading.focus({ preventScroll: true }); }
    if (scroll) byId(id).scrollIntoView({ block: "start", behavior: "auto" });
    document.dispatchEvent(new CustomEvent("calculator:tool", { detail: { id } }));
  }
  toolbox.querySelector(".workflow-nav").addEventListener("click", event => {
    const link = event.target.closest("[data-workflow]");
    if (!link || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || event.button > 0) return;
    event.preventDefault();
    if (location.hash !== link.hash) history.pushState(null, "", link.hash);
    showTool(link.dataset.workflow, { scroll: true, focus: true });
    // The existing directory uses hashchange for its selected-link indicator.
    window.dispatchEvent(new HashChangeEvent("hashchange"));
  });
  const followHash = () => {
    const id = workflowFromHash(location.hash);
    if (id) showTool(id, { scroll: true });
  };
  window.addEventListener("hashchange", followHash);
  window.addEventListener("popstate", followHash);
  document.addEventListener("calculator:language", () => showTool(active));
  // A repeated directory link still needs to reveal a hidden panel.
  document.querySelector(".tool-directory")?.addEventListener("click", event => {
    const id = workflowFromHash(event.target.closest("a")?.hash || "");
    if (id) showTool(id, { scroll: true, focus: true });
  });
  showTool(active);

  const measure = () => measuredFuelBurn(Object.fromEntries([
    ["startKg", "fuelMeasureStart"], ["endKg", "fuelMeasureEnd"], ["seconds", "fuelMeasureSeconds"],
  ].map(([name, id]) => {
    const field = byId(id);
    return [name, field.validity.badInput ? NaN : field.value.trim() === "" ? null : field.valueAsNumber];
  })));
  function renderMeasurement() {
    const result = measure();
    byId("fuelMeasureApply").disabled = Boolean(result.error);
    const message = result.error === "empty" ? t("workflow.measureEmpty", "填入两次燃油读数和间隔秒数。")
      : result.error === "increase" ? t("workflow.measureIncrease", "第二次读数应小于第一次；加油、抛副油箱或相同读数不能作为本次油耗样本。")
      : result.error ? t("workflow.measureInvalid", "读数需为非负数，间隔必须大于 0。")
      : t("workflow.measureValue", "实测平均油耗 {{value}} kg/min。只适用于这段飞行工况。", { value: result.burnKgMin.toLocaleString(numberLocale(), { maximumFractionDigits: 2 }) });
    byId("fuelMeasureResult").textContent = message;
  }
  for (const id of ["fuelMeasureStart", "fuelMeasureEnd", "fuelMeasureSeconds"]) byId(id).addEventListener("input", renderMeasurement);
  const updateFuel = () => byId("fuelForm").dispatchEvent(new Event("input", { bubbles: true }));
  let fuelNotice = "", measuredBurn = null;
  const exampleFields = new Set();
  const noticeFallbacks = {exampleStatus: "仍包含示例数据，请逐项换成本次飞行读数。", measureUsed: "已填入测得油耗；当前燃油请填写最新读数。", clearedStatus: "已清空飞行读数，保留默认 20% 绕行和 5 分钟储备。"};
  const renderFuelNotice = () => {
    const key = exampleFields.size ? "exampleStatus" : fuelNotice;
    byId("fuelWorkflowStatus").textContent = key ? t(`workflow.${key}`, noticeFallbacks[key]) : "";
  };
  byId("fuelForm").addEventListener("input", event => {
    if (!event.target.matches("input")) return;
    exampleFields.delete(event.target.id);
    if (event.target.id === "fuelBurn") measuredBurn = null;
    fuelNotice = measuredBurn === null ? "" : "measureUsed";
    renderFuelNotice();
  });
  byId("fuelMeasureApply").addEventListener("click", () => {
    const result = measure();
    if (result.error) { renderMeasurement(); return; }
    byId("fuelBurn").value = String(result.burnKgMin);
    measuredBurn = result.burnKgMin; exampleFields.delete("fuelBurn");
    fuelNotice = "measureUsed";
    renderFuelNotice(); updateFuel(); byId("fuelBurn").focus();
  });
  byId("fuelExample").addEventListener("click", () => {
    for (const [id, value] of Object.entries({fuelKg: 1000, fuelBurn: 60, fuelSpeed: 720, fuelDistance: 36, fuelRoute: 20, fuelReserve: 5})) {
      byId(id).value = String(value); exampleFields.add(id); delete byId(id).dataset.touched;
    }
    measuredBurn = null; fuelNotice = ""; renderFuelNotice(); updateFuel();
  });
  byId("fuelClear").addEventListener("click", () => {
    for (const id of ["fuelKg", "fuelBurn", "fuelSpeed", "fuelDistance", "fuelMeasureStart", "fuelMeasureEnd", "fuelMeasureSeconds"]) byId(id).value = "";
    byId("fuelRoute").value = "20"; byId("fuelReserve").value = "5";
    for (const field of byId("fuelForm").querySelectorAll("input")) delete field.dataset.touched;
    exampleFields.clear(); measuredBurn = null;
    fuelNotice = "clearedStatus"; renderFuelNotice(); renderMeasurement(); updateFuel();
  });

  let scenario = "High";
  const renderScenario = () => {
    const key = `workflow.airScenario${scenario}`;
    const fallback = {High: "示例：高空横向 · 假设值", Late: "示例：近距来弹 · 假设值", Descending: "示例：上下交会 · 假设值", Custom: "自定义假设 · 修改的是学习场景"};
    byId("airScenarioStatus").textContent = t(key, fallback[scenario]);
    for (const button of document.querySelectorAll("[data-air-preset]")) {
      const selected = {high:"High",late:"Late",descending:"Descending"}[button.dataset.airPreset] === scenario;
      button.setAttribute("aria-pressed", String(selected));
    }
  };
  for (const button of document.querySelectorAll("[data-air-preset]")) button.addEventListener("click", () => {
    scenario = {high:"High",late:"Late",descending:"Descending"}[button.dataset.airPreset]; renderScenario();
  });
  byId("airForm").addEventListener("input", () => { scenario = "Custom"; renderScenario(); });
  byId("airForm").addEventListener("change", () => { scenario = "Custom"; renderScenario(); });

  const questions = [...byId("fieldGuide").querySelectorAll(":scope > details:not(.workflow-checklist)")];
  function filterGuide() {
    const query = byId("guideSearch").value.trim().toLocaleLowerCase();
    let count = 0;
    for (const question of questions) {
      question.hidden = Boolean(query) && !question.textContent.toLocaleLowerCase().includes(query);
      if (!question.hidden) count++;
    }
    byId("guideSearchStatus").textContent = !query ? t("workflow.guideAll", "按问题展开，查看解释与来源。")
      : count ? t("workflow.guideCount", "找到 {{count}} 个机制问题", { count })
      : t("workflow.guideNoMatch", "没有匹配的问题。试试“机场”“TNT”或“CCRP”。");
  }
  byId("guideSearch").addEventListener("input", filterGuide);
  document.addEventListener("calculator:language", () => { renderMeasurement(); renderFuelNotice(); renderScenario(); filterGuide(); });
  renderMeasurement(); renderScenario(); filterGuide();
}
