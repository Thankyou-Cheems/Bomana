import { t, numberLocale, localizeName } from "./i18n.mjs";
import { customPreset, previewCustomPreset, validateLoadout, combinationTotals, keysFromPreset } from "./custom-loadouts.mjs";
import { ordnance, storesTitle } from "./loadouts.mjs";
import { rankFuzzyMatches } from "./search.mjs";

const STORAGE = "bomana.custom-loadouts.v1";
const el = (tag, text, className) => {
  const node = document.createElement(tag);
  if (text != null) node.textContent = text;
  if (className) node.className = className;
  return node;
};
const format = value => value.toLocaleString(numberLocale(), { maximumFractionDigits: 1 });
const rangeText = (range, value) => range && range[0] !== range[1] ? `${format(range[0])}–${format(range[1])}` : format(value);

export function createCustomLoadoutEditor(root, { load, apply, remove, preview }) {
  let aircraft, definition, weapons, names = {}, keys = [], editingId = "", saved = [], storageError = "";
  let hp = null, pendingPreset = null, originPreset = null, initializing = null, manual = false, retainedKeys = [];
  const open = root.querySelector("[data-custom-open]");
  const body = root.querySelector("[data-custom-body]");
  const status = root.querySelector("[data-custom-status]");
  const list = root.querySelector("[data-custom-slots]");
  const savedList = root.querySelector("[data-custom-saved]");
  const name = root.querySelector("[data-custom-name]");
  const save = root.querySelector("[data-custom-save]");
  const depend = root.querySelector("[data-custom-dependencies]");
  const notice = root.querySelector("[data-custom-notice]");
  const picker = root.querySelector("[data-custom-picker]");
  const pickerSearch = root.querySelector("[data-custom-picker-search]");
  const pickerOptions = root.querySelector("[data-custom-picker-options]");
  let activeTier = null;

  function publishPreview() {
    const snapshot = previewCustomPreset(definition, { id: editingId || "draft", name: name.value.trim() || t("custom-loadout-ui.customLoadout", "自定义挂载"), keys });
    if (originPreset && !manual) snapshot.preset = {...originPreset, keys: [...keys]};
    snapshot.lockedKeys = manual ? [...keys] : [...retainedKeys];
    preview(snapshot);
  }

  function records() {
    const data = JSON.parse(localStorage.getItem(STORAGE) || "{}");
    if (!data || typeof data !== "object" || Array.isArray(data)) throw new Error("invalid_storage");
    return data;
  }
  function readSaved() {
    try {
      saved = records()[aircraft.id] || [];
      if (!Array.isArray(saved) || saved.some(row => !row || typeof row.id !== "string" || typeof row.name !== "string" || !Array.isArray(row.keys))) throw new Error("invalid_storage");
      storageError = "";
    } catch { saved = []; storageError = t("custom-loadout-ui.savedLoadoutsCouldNotBeReadEditingAndCalculations", "无法读取本机已保存挂载；本次仍可编辑和计算。"); }
  }
  function persist() {
    try {
      const data = records(); data[aircraft.id] = saved;
      localStorage.setItem(STORAGE, JSON.stringify(data)); storageError = "";
    } catch { storageError = t("custom-loadout-ui.browserStorageUnavailableThisConfigurationWillBeLostOn", "浏览器无法保存：当前配置仅在本次页面有效，刷新会丢失。"); }
    notice.textContent = storageError;
  }
  function optionName(option) {
    const counts = new Map();
    for (const cell of option.cells) counts.set(cell.weapon, (counts.get(cell.weapon) || 0) + cell.count);
    return storesTitle([...counts], weapons, names);
  }
  function appendIcons(container, option) {
    // Each icon already represents its rack/group; use one preview per icon type.
    const icons = new Set();
    for (const cell of option.cells) if (!icons.has(cell.icon)) {
      icons.add(cell.icon); container.append(ordnance(cell));
    }
  }
  function errorMessage(error) {
    if (error.required) {
      const required = definition.options.find(option => option.key === error.required);
      return t("custom-loadout-ui.stationRequires", "需在挂点 {{v0}} 配备 {{v1}}", {v0: required.tier + 1, v1: optionName(required)});
    }
    if (error.code === "conflict") return t("custom-loadout-ui.stationEquipmentConflictsReplaceOrRemoveConflictingStores", "挂点装备互相冲突，请更换或移除冲突的挂载。");
    return error.message;
  }
  function keysForTier(tier, key) {
    const next = keys.filter(value => definition.options.find(option => option.key === value)?.tier !== tier);
    if (key) next.push(key);
    return next;
  }
  function closePicker() {
    const tier = activeTier;
    picker.close(); activeTier = null;
    list.querySelector(`[data-custom-tier="${tier}"]`)?.focus({ preventScroll: true });
  }
  function renderChoices() {
    const choices = definition.options.filter(option => option.tier === activeTier);
    const visible = rankFuzzyMatches(choices, pickerSearch.value, option => [optionName(option), option.preset]);
    root.querySelector("[data-custom-picker-count]").textContent = t("custom-loadout-ui.types", "{{v0}} / {{v1}} 种", {v0: visible.length, v1: choices.length});
    pickerOptions.replaceChildren();
    const selectedKey = choices.find(option => keys.includes(option.key))?.key || "";
    const empty = el("button", null, "custom-choice custom-choice-empty");
    empty.type = "button"; empty.dataset.customOption = "";
    empty.setAttribute("aria-pressed", String(!selectedKey));
    empty.append(el("span", "∅", "custom-choice-icon"), el("span", t("custom-loadout-ui.empty", "不挂载"), "custom-choice-name"), el("small", t("custom-loadout-ui.emptyStation", "空挂点")));
    pickerOptions.append(empty);
    for (const option of visible) {
      const button = el("button", null, "custom-choice"); button.type = "button";
      button.dataset.customOption = option.key;
      button.setAttribute("aria-pressed", String(selectedKey === option.key));
      const title = optionName(option);
      const check = validateLoadout(definition, keysForTier(activeTier, option.key));
      button.dataset.limited = String(!check.valid);
      const icon = el("span", null, "custom-choice-icon"); appendIcons(icon, option);
      button.append(icon, el("span", title, "custom-choice-name"), el("small", `${rangeText(option.displayMassRange, option.displayMass)} kg`, "custom-choice-mass"));
      if (!check.valid) button.append(el("span", check.errors.some(error => error.required) ? t("custom-loadout-ui.requiresSupportingEquipment", "需要配套装备") : t("custom-loadout-ui.adjustTheLoadout", "需调整挂载"), "custom-choice-limit"));
      const detail = check.errors.map(errorMessage).join("；");
      button.title = [title, detail].filter(Boolean).join("\n");
      button.setAttribute("aria-label", [title, `${rangeText(option.displayMassRange, option.displayMass)} kg`, detail].filter(Boolean).join("，"));
      pickerOptions.append(button);
    }
    if (!visible.length) pickerOptions.append(el("p", t("custom-loadout-ui.noMatchingStoresTryAnotherName", "没有匹配的挂载，试试其他名称。"), "custom-picker-empty"));
  }
  function openPicker(tier) {
    activeTier = tier;
    root.querySelector("[data-custom-picker-aircraft]").textContent = aircraft.name;
    root.querySelector("[data-custom-picker-title]").textContent = t("custom-loadout-ui.stationSelectStores", "挂点 {{v0}} · 选择挂载", {v0: tier + 1});
    pickerSearch.value = ""; renderChoices(); picker.showModal(); pickerSearch.focus();
  }
  function renderSaved() {
    savedList.replaceChildren();
    root.querySelector("[data-custom-saved-count]").textContent = saved.length;
    for (const record of saved) {
      const valid = validateLoadout(definition, record.keys).valid;
      const row = el("div", null, "custom-saved-row");
      const edit = el("button", `${record.name}${valid ? "" : t("custom-loadout-ui.revalidationRequired", " · 需重新校验")}`, "conversion-use");
      edit.type = "button"; edit.dataset.customEdit = record.id;
      const del = el("button", t("custom-loadout-ui.delete", "删除"), "hangar-clear"); del.type = "button"; del.dataset.customDelete = record.id;
      del.setAttribute("aria-label", t("custom-loadout-ui.deleteLoadout", "删除挂载 {{v0}}", {v0: record.name}));
      row.append(edit, del); savedList.append(row);
    }
  }
  function renderSummary() {
    if (!definition || body.hidden) return;
    const check = validateLoadout(definition, keys);
    const stats = root.querySelector("[data-custom-mass]"); stats.replaceChildren();
    for (const [label, value, limit, range] of [
      [t("custom-loadout-ui.totalLoad", "总挂载"), check.mass, definition.limits.maxloadMass, check.ranges.mass],
      [t("custom-loadout-ui.left", "左侧"), check.left, definition.limits.maxloadMassLeftConsoles, check.ranges.left],
      [t("custom-loadout-ui.right", "右侧"), check.right, definition.limits.maxloadMassRightConsoles, check.ranges.right],
      [t("custom-loadout-ui.imbalance", "左右差"), check.imbalance, definition.limits.maxDisbalance, check.ranges.imbalance],
    ]) {
      const entry = el("div"); entry.append(el("dt", label), el("dd", `${rangeText(range, value)}${limit >= 0 ? ` / ${format(limit)}` : ""} kg`)); stats.append(entry);
    }
    const errors = root.querySelector("[data-custom-errors]"); errors.replaceChildren();
    for (const error of check.errors) errors.append(el("li", errorMessage(error)));
    for (const warning of check.warnings) errors.append(el("li", warning));
    const validName = name.value.trim() && name.value.trim().length <= 40 && !/[;|\\<>^]/u.test(name.value);
    save.disabled = !check.valid || !validName || (!editingId && saved.length >= 20);
    depend.hidden = !check.errors.some(error => error.required);
    status.textContent = !check.valid ? t("custom-loadout-ui.restrictionsAreNotSatisfied", "有 {{v0}} 项限制尚未满足", {v0: check.errors.length})
      : !validName ? t("custom-loadout-ui.enter140CharactersExcluding", "请填写 1–40 字名称，避开 ; | \\ < > ^")
      : !editingId && saved.length >= 20 ? t("custom-loadout-ui.maximum20LoadoutsPerAircraftEditOrDeleteAn", "每机最多保存 20 套，请编辑已有挂载或删除一套")
      : check.warnings.length ? t("custom-loadout-ui.checkConfigurationNotes", "请留意配置提示") : t("custom-loadout-ui.configurationValid", "配置可用");
    status.dataset.valid = String(check.valid);
    const requirements = [...new Set(check.selected.flatMap(option => [...option.modifications, ...option.requiredWeapons]))];
    root.querySelector("[data-custom-requirements]").textContent = requirements.length
      ? t("custom-loadout-ui.requiredModificationsWeaponsConfirmTheyAreUnlockedInThe", "所需改装 / 武器：{{v0}}。请在游戏中确认已解锁。", {v0: requirements.join("、")}) : t("custom-loadout-ui.noAdditionalStaticModificationPrerequisitesRecordedForThisConfiguration", "此配置没有额外的静态改装前置记录。");
    const counts = new Map();
    for (const option of check.selected) for (const [id, count] of option.weapons) counts.set(id, (counts.get(id) || 0) + count);
    const total = combinationTotals([...counts], weapons, hp);
    root.querySelector("[data-custom-total]").textContent = total
      ? t("custom-loadout-ui.strikeWeaponsTntPerLoadLoadsForDirectDestruction", "对地弹药 {{v0}} 枚 · TNT {{v1}} · 每轮 {{v2}} · 完整摧毁 {{v3}} 轮{{v4}}", {v0: total.count, v1: total.tnt === null ? t("custom-loadout-ui.unknown", "未知") : `${format(total.tnt)} kg`, v2: total.damage === null ? t("custom-loadout-ui.unknown2", "未知") : `${format(total.damage)} HP`, v3: total.rounds ?? "—", v4: check.valid ? "" : t("custom-loadout-ui.notYetValidated", "（尚未通过校验）")}) : t("custom-loadout-ui.cannotCalculateThisCombination", "无法计算当前组合");
  }
  function renderSlots() {
    list.replaceChildren();
    list.style.setProperty("--custom-columns", definition.columns);
    for (let tier = 0; tier < definition.columns; tier++) {
      const choices = definition.options.filter(option => option.tier === tier);
      const card = el("button", null, "custom-slot"); card.type = "button";
      card.dataset.customTier = tier; card.disabled = !choices.length;
      card.setAttribute("aria-haspopup", "dialog");
      card.append(el("span", String(tier + 1), "custom-slot-number"));
      const selected = choices.find(option => keys.includes(option.key));
      card.dataset.customSelected = selected?.key || "";
      card.dataset.filled = String(Boolean(selected));
      card.dataset.center = String(definition.center.includes(tier));
      const title = selected ? optionName(selected) : choices.length ? t("custom-loadout-ui.emptyStation2", "空挂点") : t("custom-loadout-ui.notEditable", "不可编辑");
      card.title = t("custom-loadout-ui.station", "挂点 {{v0}} · {{v1}}", {v0: tier + 1, v1: title});
      card.setAttribute("aria-label", card.title);
      const icon = el("span", null, "custom-slot-icon");
      if (selected) appendIcons(icon, selected);
      else icon.append(el("span", choices.length ? "+" : "—", "custom-slot-empty"));
      card.append(icon, el("span", selected ? title : choices.length ? t("custom-loadout-ui.selectStores", "选择挂载") : t("custom-loadout-ui.fixed", "固定"), "custom-slot-caption"));
      list.append(card);
    }
    renderSummary();
    publishPreview();
  }
  function adoptPreset(preset) {
    const next = keysFromPreset(definition, preset);
    if (next === null) {
      body.hidden = true;
      open.hidden = true;
      status.textContent = t("currentLoadout.fixedPreset", "当前预设无对应挂点规则，按完整预设计算。");
      return false;
    }
    keys = next; editingId = preset.customName && preset.id.startsWith("user:") ? preset.id : "";
    manual = false; retainedKeys = []; originPreset = preset;
    name.value = preset.cells.length && preset.customName || t("custom-loadout-ui.customLoadout", "自定义挂载");
    body.hidden = false; open.hidden = true;
    renderSlots();
    return true;
  }
  async function initialize() {
    if (!aircraft?.custom) return;
    const unitId = aircraft.id;
    open.disabled = true; status.textContent = t("custom-loadout-ui.loadingCustomLoadoutRulesForThisVersion", "正在读取该版本的自定义挂载规则…");
    try {
      const data = await load();
      if (unitId !== aircraft?.id) return;
      definition = data.aircraft[unitId]; names = data.names || {};
      if (!definition) throw new Error("missing_definition");
      readSaved();
      for (const record of saved) {
        const preset = customPreset(definition, record);
        if (preset) apply(unitId, preset, false);
      }
      body.hidden = false; open.hidden = true; name.value = t("custom-loadout-ui.customLoadout2", "自定义挂载");
      keys = []; editingId = "";
      renderSaved();
      if (pendingPreset) adoptPreset(pendingPreset); else renderSlots();
      notice.textContent = storageError;
    } catch { if (unitId === aircraft?.id) { open.hidden = false; status.textContent = t("custom-loadout-ui.customRulesCouldNotBeLoadedRetry", "自定义规则未能载入，请重试。"); } }
    finally { if (unitId === aircraft?.id) { open.disabled = false; initializing = null; } }
  }
  open.addEventListener("click", () => {
    if (!definition) void initialize();
  });
  name.addEventListener("input", () => { originPreset = null; renderSummary(); publishPreview(); });
  list.addEventListener("click", event => {
    const button = event.target.closest("[data-custom-tier]");
    if (button && !button.disabled) openPicker(Number(button.dataset.customTier));
  });
  pickerSearch.addEventListener("input", renderChoices);
  pickerOptions.addEventListener("click", event => {
    const button = event.target.closest("[data-custom-option]");
    if (!button) return;
    keys = keysForTier(activeTier, button.dataset.customOption);
    manual = true;
    renderSlots(); closePicker();
  });
  root.querySelector("[data-custom-picker-close]").addEventListener("click", closePicker);
  picker.addEventListener("cancel", event => { event.preventDefault(); closePicker(); });
  picker.addEventListener("keydown", event => {
    if (event.key === "Escape") { event.preventDefault(); closePicker(); }
  });
  picker.addEventListener("click", event => {
    if (event.target !== picker) return;
    const rect = picker.getBoundingClientRect();
    if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) closePicker();
  });
  root.addEventListener("click", event => {
    const button = event.target.closest("button");
    if (!button || !definition) return;
    if (button === depend) {
      for (const error of validateLoadout(definition, keys).errors) if (error.required) {
        const option = definition.options.find(item => item.key === error.required);
        keys = keys.filter(key => definition.options.find(item => item.key === key)?.tier !== option.tier);
        keys.push(option.key);
      }
      keys = [...new Set(keys)]; manual = true; renderSlots();
    } else if (button === save && !save.disabled) {
      const record = { id: editingId || `user:${crypto.randomUUID()}`, name: name.value.trim(), keys: [...keys] };
      saved = saved.filter(item => item.id !== record.id); saved.push(record); editingId = record.id;
      originPreset = null;
      persist(); renderSaved(); renderSummary(); root.querySelector(".custom-saved").open = true;
      apply(aircraft.id, customPreset(definition, record), false);
      publishPreview();
      notice.textContent = storageError || t("custom-loadout-ui.savedInThisBrowserAndAppliedToTheCalculation", "已保存到此浏览器，并应用到挂载计算。");
    } else if (button.dataset.customEdit) {
      const record = saved.find(item => item.id === button.dataset.customEdit);
      editingId = record.id; keys = [...record.keys]; manual = false; retainedKeys = []; originPreset = null; name.value = record.name; renderSlots();
    } else if (button.dataset.customDelete) {
      const id = button.dataset.customDelete;
      saved = saved.filter(item => item.id !== id); persist(); remove(aircraft.id, id);
      if (id === editingId) { editingId = ""; keys = []; manual = false; retainedKeys = []; originPreset = null; name.value = t("custom-loadout-ui.customLoadout4", "自定义挂载"); }
      renderSaved(); renderSlots();
    }
  });
  document.addEventListener("calculator:language", () => {
    if (!definition) return;
    if (body.hidden) status.textContent = t("currentLoadout.fixedPreset", "当前预设无对应挂点规则，按完整预设计算。");
    else { renderSlots(); renderSaved(); if (picker.open) renderChoices(); }
  });
  return {
    async usePreset(preset) {
      pendingPreset = preset;
      if (!aircraft?.custom) return false;
      if (!definition) await (initializing ||= initialize());
      return definition && pendingPreset === preset ? adoptPreset(preset) : false;
    },
    async recommend(nextKeys) {
      const id = aircraft?.id;
      if (!definition) await (initializing ||= initialize());
      if (!definition || aircraft?.id !== id) return;
      retainedKeys = manual ? [...keys] : retainedKeys;
      keys = [...nextKeys]; editingId = ""; manual = false; originPreset = null; name.value = t("custom-loadout-ui.customLoadout", "自定义挂载"); body.hidden = false; open.hidden = true;
      renderSlots();
    },
    select(next, weaponMap) {
      if (picker.open) picker.close(); activeTier = null;
      aircraft = next; weapons = weaponMap; definition = null; keys = []; editingId = ""; pendingPreset = null; originPreset = null; initializing = null; manual = false; retainedKeys = [];
      body.hidden = true; open.disabled = false; open.hidden = !aircraft?.custom;
      delete status.dataset.valid;
      status.textContent = aircraft && !aircraft.custom ? t("optimizer.fixedOnly", "固定挂载") : "";
    },
    get editable() { return Boolean(definition && !body.hidden); },
    updateHp(value) { hp = value; renderSummary(); },
  };
}
