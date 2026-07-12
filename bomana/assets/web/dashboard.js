"use strict";

const $ = (id) => document.getElementById(id);
const state = {
  payload: null,
  control: null,
  pendingCommands: new Map(),
  submittingCommands: new Set(),
  weaponSignature: "",
  weaponListSignature: "",
  zoom: 1,
  follow: true,
  panX: 0,
  panY: 0,
  dragging: false,
  pointerX: 0,
  pointerY: 0,
  mapImage: null,
  mapImageRevision: 0,
  mapImagePendingRevision: 0,
  mapFilters: {
    player: true,
    navigation: true,
    hostile_aircraft: true,
    hostile_armor: true,
    hostile_air_defense: true,
    hostile_naval: true,
    hostile_other: true,
    weapon_range: true,
  },
};
let pollTimer = null;
let controlPollTimer = null;
let requestActive = false;
let controlRequestActive = false;
let pollsStopped = false;
// Match App UI_REFRESH_MS / logic cadence (~20 Hz) for map + heading smoothness.
const SNAPSHOT_POLL_MS = 50;
const CONTROL_POLL_MS = 400;

const PANEL_CONTROLS = Object.freeze([
  Object.freeze({ inputId: "panelZones", labelId: "panelZonesLabel", target: "zones", label: "战区" }),
  Object.freeze({ inputId: "panelAirfields", labelId: "panelAirfieldsLabel", target: "airfields", label: "机场" }),
  Object.freeze({ inputId: "panelFuel", labelId: "panelFuelLabel", target: "fuel", label: "燃油" }),
  Object.freeze({ inputId: "panelSpeed", labelId: "panelSpeedLabel", target: "speed", label: "速度" }),
  Object.freeze({ inputId: "panelChecklist", labelId: "panelChecklistLabel", target: "checklist", label: "检查清单" }),
  Object.freeze({ inputId: "panelWeapon", labelId: "panelWeaponLabel", target: "weapon_solution", label: "武器解算" }),
]);

const HOSTILE_MAP_KINDS = Object.freeze(new Set([
  "hostile_aircraft", "hostile_ground", "hostile_naval", "hostile_unit",
]));

const COMMAND_ERROR_TEXT = Object.freeze({
  pairing_required: "会话已失效，请重新配对",
  control_required: "当前会话只有查看权限",
  host_invalid: "请求主机与 Bomana 监听地址不匹配",
  origin_required: "浏览器未提供同源证明，操作已拒绝",
  origin_mismatch: "页面来源与 Bomana 不匹配，操作已拒绝",
  csrf_required: "当前会话缺少控制证明，请刷新状态",
  csrf_invalid: "控制证明已失效，请刷新状态",
  content_type_required: "命令格式不受支持",
  content_length_required: "命令长度无效",
  body_too_large: "命令内容超过限制",
  chunked_not_allowed: "命令传输方式不受支持",
  invalid_json: "命令内容不是有效 JSON",
  schema_invalid: "命令字段不符合 Bomana 合同",
  idempotency_required: "命令缺少防重复标识",
  idempotency_invalid: "命令防重复标识无效",
  idempotency_conflict: "防重复标识对应了不同操作",
  idempotency_capacity: "本次会话的操作记录已满，请重新配对",
  capability_unavailable: "当前构建或状态不允许此操作",
  queue_unavailable: "Bomana 控制队列暂不可用，请稍后重试",
});

const COMPLETION_REASON_TEXT = Object.freeze({
  authorization_revoked: "控制授权已被撤销",
  feature_disabled: "当前构建未启用此功能",
  invalid_target: "目标状态已不可用",
  weapon_not_found: "所选武器已不在目录中",
  weapon_incompatible: "所选武器与当前机型不兼容",
  state_unavailable: "Bomana 当前状态无法执行该操作",
  persistence_failed: "配置保存失败，原状态已保留",
  execution_failed: "Bomana 执行操作失败",
});

function text(id, value) {
  const node = $(id);
  if (node) node.textContent = value;
}

function finite(value, fallback = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function fmt(value, digits = 0, suffix = "") {
  const number = Number(value);
  return Number.isFinite(number) ? `${number.toFixed(digits)}${suffix}` : "--";
}

function fmtTime(seconds) {
  if (seconds === null || seconds === undefined || !Number.isFinite(Number(seconds))) return "--:--";
  const total = Math.max(0, Math.floor(Number(seconds)));
  return `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
}

function showPairing(message = "") {
  $("pairingPanel").classList.remove("hidden");
  if (message) {
    text("pairingError", message);
    $("pairingError").classList.add("error");
  }
}

function hidePairing() {
  $("pairingPanel").classList.add("hidden");
  $("pairingError").classList.remove("error");
}

function setConnection(mode, label, freshness) {
  const badge = $("connectionBadge");
  badge.classList.toggle("online", mode === "online");
  badge.classList.toggle("offline", mode === "offline");
  text("connectionText", label);
  text("freshnessText", freshness);
}

async function pollSnapshot() {
  if (requestActive) return;
  requestActive = true;
  try {
    const response = await fetch("/api/v1/snapshot", {
      credentials: "same-origin",
      cache: "no-store",
      mode: "same-origin",
      headers: { Accept: "application/json" },
    });
    if (response.status === 401) {
      state.pendingCommands.clear();
      setControlUnavailable("需要配对", "控制状态需要有效的独立配对会话。");
      showPairing();
      setConnection("offline", "需要配对", "等待授权");
      return;
    }
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    state.payload = payload;
    hidePairing();
    render(payload);
  } catch (_error) {
    setConnection("offline", "连接中断", "正在重试");
  } finally {
    requestActive = false;
  }
}

function scheduleSnapshotPoll() {
  if (pollsStopped) return;
  window.clearTimeout(pollTimer);
  pollTimer = window.setTimeout(async () => {
    const started = performance.now();
    await pollSnapshot();
    if (pollsStopped) return;
    const wait = Math.max(0, SNAPSHOT_POLL_MS - (performance.now() - started));
    pollTimer = window.setTimeout(scheduleSnapshotPoll, wait);
  }, 0);
}

function setCommandStatus(message, tone = "") {
  const node = $("commandStatus");
  const visible = Boolean(message);
  node.className = `command-status${tone ? ` ${tone}` : ""}${visible ? " is-visible" : ""}`;
  node.textContent = message || "";
}

function setWeaponPickersDisabled(disabled) {
  for (const id of ["weaponChip", "dockWeaponButton", "weaponCardOpen"]) {
    const node = $(id);
    if (node) node.disabled = disabled;
  }
}

function setControlUnavailable(scopeLabel, helpText) {
  state.control = null;
  const scope = $("controlScope");
  scope.className = "scope-chip pending";
  scope.textContent = scopeLabel;
  text("controlHelp", helpText);
  for (const node of document.querySelectorAll(".control-deck button, .control-deck input, .control-deck select")) {
    node.disabled = true;
  }
  for (const id of ["resetTimerButtonDesktop", "cycleCornerButtonDesktop"]) {
    const node = $(id);
    if (node) node.disabled = true;
  }
  setWeaponPickersDisabled(true);
}

function controlGranted() {
  const payload = state.control;
  return Boolean(
    payload
    && payload.permissions
    && payload.permissions.scope === "control"
    && typeof payload.csrf === "string"
    && payload.csrf.length > 0,
  );
}

function commandIsBusy(commandName) {
  if (state.submittingCommands.has(commandName)) return true;
  for (const pending of state.pendingCommands.values()) {
    if (pending.command === commandName) return true;
  }
  return false;
}

function commandIsAvailable(commandName) {
  const commands = state.control && state.control.capabilities && state.control.capabilities.commands;
  return controlGranted() && Array.isArray(commands) && commands.includes(commandName);
}

function setCommandButtons(ids, commandName) {
  const available = commandIsAvailable(commandName);
  const busy = commandIsBusy(commandName);
  for (const id of ids) {
    const node = $(id);
    if (node) node.disabled = !available || busy;
  }
  return available;
}

function setPressed(id, pressed) {
  $(id).setAttribute("aria-pressed", pressed ? "true" : "false");
}

function renderWeaponChoices(weapons, selectedWeaponId) {
  const select = $("weaponSelect");
  const signature = JSON.stringify(weapons.map((weapon) => [
    weapon.weapon_id,
    weapon.display_name,
    weapon.role,
    weapon.compatible,
  ]));
  if (signature !== state.weaponSignature) {
    state.weaponSignature = signature;
    select.replaceChildren();
    if (!weapons.length) {
      const option = document.createElement("option");
      option.value = "";
      option.textContent = "当前没有可选武器";
      select.append(option);
    } else {
      const placeholder = document.createElement("option");
      placeholder.value = "";
      placeholder.textContent = "请选择武器";
      placeholder.disabled = true;
      select.append(placeholder);
      for (const weapon of weapons) {
        const option = document.createElement("option");
        option.value = weapon.weapon_id;
        option.textContent = `${weapon.display_name} · ${weapon.role}${weapon.compatible ? "" : "（当前机型不兼容）"}`;
        option.disabled = !weapon.compatible;
        select.append(option);
      }
    }
  }
  select.value = selectedWeaponId;
  if (select.value !== selectedWeaponId) select.value = "";
  const selected = weapons.find((weapon) => weapon.weapon_id === selectedWeaponId);
  if (selected) {
    text("weaponChipName", selected.display_name);
    text("dockWeaponName", selected.display_name);
    text("weaponChipMeta", selected.compatible ? `${selected.role} · 点击切换` : "当前机型不兼容");
  }
  const canSelect = commandIsAvailable("weapon.select") && !commandIsBusy("weapon.select");
  const listSignature = `${signature}|${selectedWeaponId || ""}|${canSelect}|${controlGranted()}`;
  if (listSignature !== state.weaponListSignature) {
    state.weaponListSignature = listSignature;
    renderWeaponList(weapons, selectedWeaponId, canSelect);
  }
}

function renderWeaponList(weapons, selectedWeaponId, canSelect) {
  const list = $("weaponList");
  if (!list) return;
  list.replaceChildren();
  if (!weapons.length) {
    const empty = document.createElement("p");
    empty.className = "weapon-empty";
    empty.textContent = "当前没有可选武器";
    list.append(empty);
    return;
  }
  const viewOnly = !controlGranted();
  for (const weapon of weapons) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "weapon-option";
    button.setAttribute("role", "option");
    button.dataset.weaponId = weapon.weapon_id;
    if (weapon.weapon_id === selectedWeaponId) button.classList.add("is-current");
    if (!weapon.compatible) button.classList.add("incompatible");
    const name = document.createElement("strong");
    name.textContent = weapon.display_name;
    const detail = document.createElement("small");
    detail.textContent = weapon.compatible
      ? `${weapon.role}`
      : `${weapon.role} · 当前机型不兼容`;
    const badge = document.createElement("span");
    badge.className = "weapon-badge";
    badge.textContent = weapon.weapon_id === selectedWeaponId
      ? "当前"
      : (weapon.compatible ? "选择" : "不可用");
    button.append(name, badge, detail);
    if (!weapon.compatible) {
      button.disabled = true;
    } else if (viewOnly) {
      button.disabled = false;
    } else {
      button.disabled = !canSelect;
    }
    button.addEventListener("click", () => {
      if (!controlGranted()) {
        setCommandStatus("当前会话只有查看权限", "error");
        return;
      }
      if (!weapon.compatible) {
        setCommandStatus("该武器当前不可选择", "error");
        return;
      }
      if (weapon.weapon_id === selectedWeaponId) {
        closeSheet("weaponSheet");
        return;
      }
      void submitCommand(
        { schema_version: 1, command: "weapon.select", weapon_id: weapon.weapon_id },
        `选择武器：${weapon.display_name}`,
      );
      closeSheet("weaponSheet");
    });
    list.append(button);
  }
}

function renderControlState(payload) {
  const permissions = payload.permissions;
  const targetState = payload.state;
  const commands = new Set(payload.capabilities.commands);
  const panelTargets = new Set(payload.capabilities.panel_targets);
  const granted = controlGranted();
  const scope = $("controlScope");
  scope.className = `scope-chip ${permissions.scope}`;

  if (permissions.scope === "control" && permissions.transport === "loopback") {
    scope.textContent = "本机控制";
    text("controlHelp", "本机控制会话已授权；每项操作仍会在 Bomana 主线程重新校验。");
  } else if (permissions.scope === "control") {
    scope.textContent = "LAN 控制";
    text("controlHelp", "Bomana 已开启局域网访问与控制；关闭局域网后现有授权会立即失效。");
  } else {
    scope.textContent = "只读会话";
    text("controlHelp", permissions.transport === "lan"
      ? "当前局域网授权已失效。请在 Bomana 本机重新开启局域网访问与控制并配对。"
      : "此会话只有查看权限，所有设置均显示当前值但不可修改。");
  }

  setCommandButtons(["resetTimerButton", "resetTimerButtonDesktop"], "action.reset_timer");
  setCommandButtons(["cycleCornerButton", "cycleCornerButtonDesktop"], "action.cycle_corner");

  setCommandButtons(["lockedOnButton", "lockedOffButton"], "state.set_locked");
  setPressed("lockedOnButton", targetState.locked);
  setPressed("lockedOffButton", !targetState.locked);
  $("lockedOnButton").closest(".target-setting").classList.toggle("unavailable", !commands.has("state.set_locked"));

  setCommandButtons(["beepOnButton", "beepOffButton"], "state.set_beep_enabled");
  setPressed("beepOnButton", targetState.beep_enabled);
  setPressed("beepOffButton", !targetState.beep_enabled);
  $("beepOnButton").closest(".target-setting").classList.toggle("unavailable", !commands.has("state.set_beep_enabled"));

  const timerCommand = "config.set_timer_cycle_minutes";
  const timerAvailable = granted && commands.has(timerCommand);
  const timerBusy = commandIsBusy(timerCommand);
  const timerInput = $("timerCycleMinutes");
  if (document.activeElement !== timerInput) {
    timerInput.value = String(targetState.timer_cycle_minutes || 15);
  }
  timerInput.disabled = !timerAvailable || timerBusy;
  $("timerCycleApplyButton").disabled = !timerAvailable || timerBusy;
  $("timerCycleSetting").classList.toggle("unavailable", !commands.has(timerCommand));

  setCommandButtons(
    ["zoneSoundOnButton", "zoneSoundOffButton"],
    "state.set_zone_sound_enabled",
  );
  setPressed("zoneSoundOnButton", targetState.zone_sound_enabled);
  setPressed("zoneSoundOffButton", !targetState.zone_sound_enabled);
  $("zoneSoundSetting").classList.toggle("unavailable", !commands.has("state.set_zone_sound_enabled"));

  const panelCommandAvailable = granted && commands.has("config.set_panel_visibility");
  const panelBusy = commandIsBusy("config.set_panel_visibility");
  for (const panel of PANEL_CONTROLS) {
    const input = $(panel.inputId);
    const available = panelCommandAvailable && panelTargets.has(panel.target);
    input.checked = Boolean(targetState.panel_visibility[panel.target]);
    input.disabled = !available || panelBusy;
    $(panel.labelId).classList.toggle("unavailable", !panelTargets.has(panel.target));
  }

  const weapons = Array.isArray(payload.weapons) ? payload.weapons : [];
  renderWeaponChoices(weapons, targetState.selected_weapon_id);
  const hasCompatibleWeapon = weapons.some((weapon) => weapon.compatible);
  $("weaponSelect").disabled = !commandIsAvailable("weapon.select")
    || commandIsBusy("weapon.select")
    || !hasCompatibleWeapon;
  const weaponBusy = commandIsBusy("weapon.select");
  setWeaponPickersDisabled(weaponBusy);
  text(
    "weaponSheetHelp",
    granted
      ? "选择与当前机型兼容的武器。官方数据始终优先。"
      : "当前为只读会话，可浏览武器列表但无法切换。",
  );

  setCommandButtons(
    ["modelCompatibleButton", "modelOfficialButton"],
    "weapon.set_ballistic_model",
  );
  setPressed("modelCompatibleButton", targetState.ballistic_model === "foxthree_compatible");
  setPressed("modelOfficialButton", targetState.ballistic_model === "strict_official");

}

function processCommandCompletions(recentCommands) {
  if (!Array.isArray(recentCommands) || !state.pendingCommands.size) return;
  let latest = null;
  for (const [commandId, pending] of state.pendingCommands) {
    const completion = recentCommands.find((item) => item.command_id === commandId);
    if (!completion) continue;
    state.pendingCommands.delete(commandId);
    latest = { completion, pending };
  }
  if (!latest) return;
  if (latest.completion.status === "succeeded") {
    setCommandStatus(`${latest.pending.label}已完成`, "success");
  } else {
    const detail = COMPLETION_REASON_TEXT[latest.completion.reason] || "Bomana 拒绝了此操作";
    setCommandStatus(`${latest.pending.label}未执行：${detail}`, "error");
  }
}

async function pollControlState() {
  if (controlRequestActive) return;
  controlRequestActive = true;
  try {
    const response = await fetch("/api/v1/control-state", {
      credentials: "same-origin",
      cache: "no-store",
      mode: "same-origin",
      headers: { Accept: "application/json" },
    });
    if (response.status === 401) {
      state.pendingCommands.clear();
      setControlUnavailable("需要配对", "控制状态需要有效的独立配对会话。");
      showPairing();
      return;
    }
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    state.control = payload;
    hidePairing();
    processCommandCompletions(payload.recent_commands);
    renderControlState(payload);
  } catch (_error) {
    setControlUnavailable("状态不可用", "暂时无法读取控制状态；所有写操作已禁用，正在重试。");
  } finally {
    controlRequestActive = false;
  }
}

function scheduleControlPoll() {
  if (pollsStopped) return;
  window.clearTimeout(controlPollTimer);
  controlPollTimer = window.setTimeout(async () => {
    const started = performance.now();
    await pollControlState();
    if (pollsStopped) return;
    const wait = Math.max(0, CONTROL_POLL_MS - (performance.now() - started));
    controlPollTimer = window.setTimeout(scheduleControlPoll, wait);
  }, 0);
}

function createIdempotencyKey() {
  if (!window.crypto || typeof window.crypto.getRandomValues !== "function") {
    throw new Error("secure_random_unavailable");
  }
  const bytes = new Uint8Array(12);
  window.crypto.getRandomValues(bytes);
  const randomPart = Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
  return `web-${Date.now().toString(36)}-${randomPart}`;
}

function rememberPendingCommand(commandId, commandName, label, submittedRevision = null) {
  state.pendingCommands.set(commandId, {
    command: commandName,
    label,
    submittedRevision,
  });
}

async function submitCommand(commandBody, label) {
  const commandName = commandBody.command;
  if (!commandIsAvailable(commandName)) {
    setCommandStatus("当前会话或构建不允许此操作", "error");
    return;
  }
  if (commandIsBusy(commandName)) return;
  if (state.pendingCommands.size >= 16) {
    setCommandStatus("仍有较多操作等待完成，请稍后再试", "error");
    return;
  }

  let commandId;
  try {
    commandId = createIdempotencyKey();
  } catch (_error) {
    setCommandStatus("浏览器无法生成安全的防重复标识，操作未发送", "error");
    return;
  }

  state.submittingCommands.add(commandName);
  renderControlState(state.control);
  setCommandStatus(`正在提交：${label}`, "pending");
  try {
    const response = await fetch("/api/v1/commands", {
      method: "POST",
      credentials: "same-origin",
      cache: "no-store",
      mode: "same-origin",
      redirect: "error",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
        "X-Bomana-CSRF": state.control.csrf,
        "Idempotency-Key": commandId,
      },
      body: JSON.stringify(commandBody),
    });
    let payload = null;
    try {
      payload = await response.json();
    } catch (_error) {
      // The stable fallback below handles a malformed or empty server response.
    }
    if (response.status === 401 || (payload && payload.error === "pairing_required")) {
      state.pendingCommands.clear();
      setControlUnavailable("需要配对", "会话已失效，请使用 Bomana 当前配对码重新连接。");
      showPairing("会话已失效，请重新配对");
      setCommandStatus("操作未发送：会话已失效", "error");
      return;
    }
    if (response.status !== 202) {
      const errorCode = payload && typeof payload.error === "string" ? payload.error : "";
      const detail = COMMAND_ERROR_TEXT[errorCode] || `Bomana 拒绝了请求（HTTP ${response.status}）`;
      setCommandStatus(`操作未入队：${detail}`, "error");
      if (["csrf_required", "csrf_invalid", "control_required"].includes(errorCode)) {
        void pollControlState();
      }
      return;
    }
    if (!payload || payload.status !== "queued") {
      rememberPendingCommand(commandId, commandName, label);
      setCommandStatus("Bomana 未返回有效的排队确认；操作状态未知，正在查询完成记录", "error");
      void pollControlState();
      return;
    }
    if (payload.command_id !== commandId || !Number.isInteger(payload.submitted_revision)) {
      rememberPendingCommand(commandId, commandName, label);
      setCommandStatus("Bomana 返回了无效的排队响应；操作状态未知，正在查询完成记录", "error");
      void pollControlState();
      return;
    }
    rememberPendingCommand(commandId, commandName, label, payload.submitted_revision);
    setCommandStatus(`${label}已入队，等待 Bomana 完成`, "pending");
    void pollControlState();
  } catch (_error) {
    rememberPendingCommand(commandId, commandName, label);
    setCommandStatus("未收到排队确认；操作状态未知，正在查询完成记录，请勿立即重复", "error");
    void pollControlState();
  } finally {
    state.submittingCommands.delete(commandName);
    if (state.control) renderControlState(state.control);
  }
}

function render(payload) {
  const age = Math.max(0, Date.now() / 1000 - finite(payload.generated_at));
  const connected = payload.status.connected && age < 3;
  setConnection(
    connected ? "online" : "offline",
    connected ? "实时" : "数据暂停",
    age < 0.15 ? "刚刚" : `${age.toFixed(2)}s`,
  );
  renderCapabilities(payload.capabilities);

  // Tactical surfaces first so map/heading stay on the high-rate path.
  renderMap(payload.map, payload.flight.heading_deg);
  renderHeadingTape(payload);

  text("phaseLabel", payload.status.phase_label);
  text("timerValue", fmtTime(payload.timer.remaining_sec));
  text("timerMeta", payload.timer.cycle ? `第 ${payload.timer.cycle} 轮 · ${payload.timer.cycle_minutes} 分钟周期 · 第 ${payload.timer.life_index || "-"} 次复活` : `等待任务计时 · ${payload.timer.cycle_minutes} 分钟周期`);
  $("timerProgress").style.width = `${Math.max(0, Math.min(100, finite(payload.timer.progress) * 100))}%`;

  text("iasValue", Math.round(finite(payload.flight.ias_kmh)) || "---");
  text("altValue", Math.round(finite(payload.flight.altitude_m)) || "---");
  text("headingValue", String(Math.round((finite(payload.flight.heading_deg) + 360) % 360)).padStart(3, "0"));
  text("fuelValue", payload.capabilities.fuel ? Math.round(finite(payload.fuel.percent)) : "---");
  const aircraft = payload.flight.aircraft || "未识别机型";
  text("aircraftName", aircraft);
  text("airframeAircraft", aircraft);
  renderOverspeed(payload.flight);

  renderWeapon(payload.weapon);
  renderBombing(payload.bombing);
  renderNavigation(payload.navigation);
  renderAirframe(payload);
  renderChecklist(payload.checklist.items);
  renderAlerts(payload.alerts);
}

function renderCapabilities(capabilities) {
  for (const node of document.querySelectorAll("[data-capability]")) {
    node.classList.toggle("capability-hidden", !Boolean(capabilities[node.dataset.capability]));
  }
  document.querySelector(".airframe-card").classList.toggle("fuel-disabled", !capabilities.fuel);
}

function renderOverspeed(flight) {
  const strip = $("speedStrip");
  const fill = $("speedFill");
  if (!strip || !fill) return;
  const overspeed = flight && flight.overspeed ? flight.overspeed : {};
  const level = String(overspeed.level || "unknown");
  const matched = Boolean(overspeed.matched);
  const ratio = Math.max(0, finite(overspeed.ratio));
  const ias = Math.round(finite(flight.ias_kmh));
  const limit = Math.round(finite(overspeed.limit_kmh));
  const mach = finite(flight.mach, NaN);
  const limitMach = finite(overspeed.limit_mach, NaN);

  let stateText = "速度监视";
  let tone = "unknown";
  if (level === "critical") {
    stateText = "超速危险";
    tone = "critical";
  } else if (level === "warning") {
    stateText = "接近极限";
    tone = "warning";
  } else if (level === "caution") {
    stateText = "高速预警";
    tone = "caution";
  } else if (matched) {
    stateText = "速度安全";
    tone = "safe";
  } else if (!matched) {
    stateText = "限速未匹配";
    tone = "unknown";
  }

  const fillPct = matched ? Math.min(100, Math.max(0, ratio * 100)) : 0;
  fill.style.width = `${fillPct}%`;
  strip.className = `speed-strip level-${tone}`;
  text("speedState", stateText);

  let value = ias > 0 ? `IAS ${ias}` : "IAS --";
  if (matched && limit > 0) value = `IAS ${ias}/${limit}`;
  if (matched) value += ` · ${Math.round(fillPct)}%`;
  text("speedValue", value);

  const metaParts = [];
  if (Number.isFinite(mach) && Number.isFinite(limitMach) && limitMach > 0) {
    metaParts.push(`M${mach.toFixed(2)}/${limitMach.toFixed(2)}`);
  } else if (Number.isFinite(mach) && mach > 0) {
    metaParts.push(`M${mach.toFixed(2)}`);
  }
  if (!matched) metaParts.push("无可用机型限速");
  else if (limit > 0) metaParts.push(`极限 ${limit} km/h`);
  text("speedMeta", metaParts.join(" · ") || "等待限速数据");
}

function renderWeapon(weapon) {
  const weaponName = weapon.name || "未选择武器";
  text("weaponName", weaponName);
  text("weaponModel", weaponModelLabel(weapon));
  text("weaponTarget", weapon.target_name || "--");
  text("weaponDistance", weapon.target_distance_km > 0 ? fmt(weapon.target_distance_km, 1, " km") : "--");
  const envelope = weapon.max_range_km > 0 ? `${fmt(weapon.min_range_km, 1)}–${fmt(weapon.max_range_km, 1)} km` : "--";
  text("weaponEnvelope", envelope);
  text("weaponTti", weapon.time_to_target_s > 0 ? fmt(weapon.time_to_target_s, 0, " s") : "--");
  text("weaponStatus", weaponStatusLabel(weapon));
  text("weaponQuality", weaponQualityLabel(weapon));
  text("weaponChipName", weaponName);
  text("dockWeaponName", weaponName === "未选择武器" ? "未选择" : weaponName);
  text("weaponChipMeta", weapon.max_range_km > 0 ? `包线 ${envelope}` : weaponModelLabel(weapon));
  const chip = $("weaponQuality");
  chip.className = "quality-chip";
  if (weapon.quality === "experimental") chip.classList.add("experimental");
  else if (weapon.valid) chip.classList.add("valid");
  else if (weapon.status && !["unknown_weapon", "unavailable"].includes(weapon.status)) chip.classList.add("danger");
  const max = Math.max(weapon.max_range_km, weapon.target_distance_km, 1);
  $("weaponRangeBar").style.width = `${Math.min(100, Math.max(0, weapon.max_range_km / max * 100))}%`;
  $("weaponTargetMark").style.left = `${Math.min(100, Math.max(0, weapon.target_distance_km / max * 100))}%`;
}

function weaponModelLabel(weapon) {
  if (weapon.reason === "datamine_guidance_envelope") return "官方包线";
  if (weapon.reason === "foxthree_compatible_glide") return "推测替代";
  if (weapon.model === "strict_official" && !weapon.valid) return "未使用替代模型";
  return weapon.valid ? "Bomana 估算" : "等待可用数据";
}

function weaponQualityLabel(weapon) {
  if (weapon.reason === "datamine_guidance_envelope") return "官方";
  if (weapon.quality === "experimental") return "推测";
  if (weapon.quality === "two_dimensional") return "二维参考";
  return weapon.valid ? "估算" : "待机";
}

function weaponStatusLabel(weapon) {
  const labels = {
    datamine_guidance_envelope: "官方条件包线",
    foxthree_compatible_glide: "无官方包线，使用推测替代",
    glide_envelope_unavailable: "无官方包线，未应用替代模型",
    no_target: "尚未选择有效目标",
    invalid_telemetry: "等待稳定飞行数据",
    weapon_incompatible: "当前武器与机型不匹配",
  };
  return labels[weapon.reason] || (weapon.valid ? "当前解算可用" : "等待有效解算");
}

function renderBombing(bombing) {
  text("bombName", bombing.bomb_name || "--");
  text("bombTarget", bombing.target_name || "--");
  text("releaseDistance", bombing.release_distance_km > 0 ? fmt(bombing.release_distance_km, 1, " km") : "--");
  text("releaseTime", bombing.time_to_release_s > 0 ? fmt(bombing.time_to_release_s, 0, " s") : "--");
  text("bombReason", bombing.unavailable_reason || (bombing.valid ? "投放解算有效" : "等待计算"));
  text("releaseStatus", bombing.release_status || "待机");
  const chip = $("releaseStatus");
  chip.className = "release-chip";
  if (["ready", "approaching"].includes(bombing.release_status)) chip.classList.add("ready");
  if (["passed", "invalid"].includes(bombing.release_status) && bombing.enabled) chip.classList.add("danger");
}

function renderNavigation(nav) {
  text("deviationValue", `${finite(nav.deviation_deg) >= 0 ? "+" : ""}${fmt(nav.deviation_deg, 1, "°")}`);
  const items = [...nav.zones, ...nav.airfields];
  if (nav.poi) items.push(nav.poi);
  if (nav.traceback) items.push(nav.traceback);
  const container = $("navigationList");
  container.replaceChildren();
  if (!items.length) {
    const empty = document.createElement("p");
    empty.className = "empty-line";
    empty.textContent = "暂无导航目标";
    container.append(empty);
    return;
  }
  for (const item of items.slice(0, 8)) {
    const row = document.createElement("div");
    row.className = `nav-row${item.is_target ? " target" : ""}`;
    const dot = document.createElement("i");
    const copy = document.createElement("div");
    const name = document.createElement("strong");
    name.textContent = item.name;
    const detail = document.createElement("span");
    detail.textContent = `${item.direction || "--"} · ${item.relative_deg >= 0 ? "+" : ""}${item.relative_deg.toFixed(1)}°${item.ete ? ` · ${item.ete}` : ""}`;
    copy.append(name, detail);
    const distance = document.createElement("strong");
    distance.textContent = `${item.distance_km.toFixed(1)} km`;
    row.append(dot, copy, distance);
    container.append(row);
  }
}

function renderAirframe(payload) {
  const fuel = payload.capabilities.fuel ? finite(payload.fuel.percent) : 0;
  const speed = Math.min(100, finite(payload.flight.overspeed.ratio) * 100);
  const gear = finite(payload.flight.gear.percent);
  setRing("fuelRing", "fuelRingValue", fuel, `${Math.round(fuel)}%`);
  setRing("speedRing", "speedRingValue", speed, payload.flight.overspeed.matched ? `${Math.round(speed)}%` : "--%");
  setRing("gearRing", "gearRingValue", gear, `${Math.round(gear)}%`);
  text("fuelRate", payload.fuel.rate_stable ? fmt(payload.fuel.rate_kg_min, 1, " kg/min") : "稳定中");
  text("fuelTime", payload.fuel.remaining_min !== null ? fmt(payload.fuel.remaining_min, 0, " min") : "--");
  text("returnFuel", payload.fuel.return_needed_kg > 0 ? fmt(payload.fuel.return_needed_kg, 0, " kg") : "--");
  text("attitudeValue", payload.flight.attitude.reliable ? `${fmt(payload.flight.attitude.pitch_deg, 0)}° / ${fmt(payload.flight.attitude.roll_deg, 0)}°` : "不可靠");
}

function setRing(ringId, valueId, value, label) {
  $(ringId).style.setProperty("--value", String(Math.max(0, Math.min(100, value))));
  text(valueId, label);
}

function renderChecklist(items) {
  text("checklistCount", `${items.length} 项`);
  const list = $("checklist");
  list.replaceChildren();
  if (!items.length) {
    const item = document.createElement("li");
    item.textContent = "当前构建未启用检查清单";
    list.append(item);
    return;
  }
  for (const value of items) {
    const item = document.createElement("li");
    item.textContent = value;
    list.append(item);
  }
}

function renderAlerts(alerts) {
  text("alertCount", String(alerts.length));
  const list = $("alertList");
  list.replaceChildren();
  if (!alerts.length) {
    const clear = document.createElement("p");
    clear.className = "all-clear";
    clear.textContent = "当前无告警";
    list.append(clear);
    return;
  }
  for (const alert of alerts) {
    const item = document.createElement("div");
    item.className = `alert ${alert.level}`;
    const copy = document.createElement("span");
    copy.textContent = alert.text;
    item.append(copy);
    list.append(item);
  }
}

function canvasSize(canvas) {
  const rect = canvas.getBoundingClientRect();
  const ratio = Math.min(2, window.devicePixelRatio || 1);
  const width = Math.max(1, Math.round(rect.width * ratio));
  const height = Math.max(1, Math.round(rect.height * ratio));
  if (canvas.width !== width || canvas.height !== height) {
    canvas.width = width;
    canvas.height = height;
  }
  return { width, height, ratio };
}

function mapTransform(map, width, height, x, y) {
  const padding = 28;
  const span = Math.min(width, height) - padding * 2;
  let centerX = .5 + state.panX;
  let centerY = .5 + state.panY;
  if (state.follow && map.player) {
    centerX = map.player.x;
    centerY = map.player.y;
  }
  return {
    x: width / 2 + (x - centerX) * span * state.zoom,
    y: height / 2 + (y - centerY) * span * state.zoom,
  };
}

function renderMap(map) {
  const canvas = $("tacticalMap");
  const { width, height, ratio } = canvasSize(canvas);
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, width, height);
  drawMapBackground(ctx, width, height, ratio);
  void syncMapImage(map);
  drawMapImage(ctx, map, width, height);
  $("mapEmpty").classList.toggle("hidden", map.available);
  if (!map.available) return;

  syncHostileLegendIcons(map.points);
  if (state.mapFilters.weapon_range) drawWeaponRange(ctx, map, width, height, ratio);

  const pointsById = new Map(map.points.map((point) => [point.id, point]));
  const target = map.points.find((point) => point.kind === "poi" && point.is_target)
    || map.points.find((point) => point.is_target && point.kind !== "traceback");
  if (state.mapFilters.navigation && map.player && target) {
    const from = mapTransform(map, width, height, map.player.x, map.player.y);
    const to = mapTransform(map, width, height, target.x, target.y);
    ctx.save();
    ctx.setLineDash([8 * ratio, 7 * ratio]);
    ctx.strokeStyle = "rgba(112,183,255,.42)";
    ctx.lineWidth = ratio;
    ctx.beginPath(); ctx.moveTo(from.x, from.y); ctx.lineTo(to.x, to.y); ctx.stroke();
    ctx.restore();
  }

  for (const point of pointsById.values()) {
    if (state.mapFilters[mapPointFilterKey(point)]) drawMapPoint(ctx, map, point, width, height, ratio);
  }
  if (state.mapFilters.player && map.player) drawPlayer(ctx, map, map.player, width, height, ratio);
}

function hostileIconFamily(point) {
  const icon = String(point.icon || "").toLowerCase();
  if (point.kind === "hostile_aircraft" || /(fighter|assault|bomber|helicopter|aircraft|plane)/.test(icon)) return "aircraft";
  if (/(spaa|sam|aaa|air.?defen)/.test(icon)) return "air_defense";
  if (/(tank|vehicle|artillery|armou?r|bunker)/.test(icon)) return "armor";
  if (point.kind === "hostile_naval" || /(ship|naval|boat|destroyer|cruiser|carrier|frigate|submarine|torpedo)/.test(icon)) return "naval";
  return "other";
}

function officialMapGlyph(iconValue) {
  const icon = String(iconValue || "");
  const fixed = Object.freeze({
    Airdefence: "4", Structure: "5", waypoint: "6", capture_zone: "7",
    bombing_point: "8", defending_point: "9", respawn_base_tank: "0",
    respawn_base_fighter: ".", respawn_base_bomber: ":",
  });
  return fixed[icon] || icon.charAt(0) || "?";
}

function syncHostileLegendIcons(points) {
  const representatives = { aircraft: "Fighter", armor: "MediumTank", air_defense: "SPAA", naval: "Frigate", other: "?" };
  const found = new Set();
  for (const point of points) {
    if (!HOSTILE_MAP_KINDS.has(String(point.kind || ""))) continue;
    const family = hostileIconFamily(point);
    if (!found.has(family)) {
      representatives[family] = point.icon || "?";
      found.add(family);
    }
  }
  for (const marker of document.querySelectorAll("[data-map-icon-family]")) {
    const icon = representatives[marker.dataset.mapIconFamily] || "?";
    marker.textContent = officialMapGlyph(icon);
    marker.title = icon;
  }
}

function mapPointFilterKey(point) {
  if (!HOSTILE_MAP_KINDS.has(String(point.kind || ""))) return "navigation";
  return `hostile_${hostileIconFamily(point)}`;
}

async function syncMapImage(map) {
  const image = map && map.image;
  if (!image || !image.available || image.revision <= 0) return;
  if (state.mapImageRevision === image.revision || state.mapImagePendingRevision === image.revision) return;
  state.mapImagePendingRevision = image.revision;
  try {
    const response = await fetch("/api/v1/map-image", {
      credentials: "same-origin",
      cache: "no-store",
      mode: "same-origin",
      headers: { Accept: "image/png,image/jpeg" },
    });
    if (!response.ok) return;
    const blob = await response.blob();
    let decoded;
    if ("createImageBitmap" in window) {
      decoded = await window.createImageBitmap(blob);
    } else {
      decoded = await imageElementFromBlob(blob);
    }
    if (state.mapImage && typeof state.mapImage.close === "function") state.mapImage.close();
    state.mapImage = decoded;
    state.mapImageRevision = image.revision;
    renderCurrentMap();
  } catch (_error) {
    // The abstract tactical grid remains usable while the image is unavailable.
  } finally {
    if (state.mapImagePendingRevision === image.revision) state.mapImagePendingRevision = 0;
  }
}

function imageElementFromBlob(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = reject;
    reader.onload = () => {
      const image = new Image();
      image.onload = () => resolve(image);
      image.onerror = reject;
      image.src = String(reader.result || "");
    };
    reader.readAsDataURL(blob);
  });
}

function drawMapImage(ctx, map, width, height) {
  if (!state.mapImage || !map.image || state.mapImageRevision !== map.image.revision) return;
  const topLeft = mapTransform(map, width, height, 0, 0);
  const bottomRight = mapTransform(map, width, height, 1, 1);
  ctx.save();
  ctx.globalAlpha = .42;
  ctx.imageSmoothingEnabled = true;
  ctx.drawImage(
    state.mapImage,
    topLeft.x,
    topLeft.y,
    bottomRight.x - topLeft.x,
    bottomRight.y - topLeft.y,
  );
  ctx.restore();
}

function drawWeaponRange(ctx, map, width, height, ratio) {
  const range = map.weapon_range;
  if (!map.player || !range) return;
  const center = mapTransform(map, width, height, map.player.x, map.player.y);
  const maxX = mapTransform(map, width, height, map.player.x + finite(range.max_radius_x), map.player.y);
  const maxY = mapTransform(map, width, height, map.player.x, map.player.y + finite(range.max_radius_y));
  const radiusX = Math.abs(maxX.x - center.x);
  const radiusY = Math.abs(maxY.y - center.y);
  if (radiusX < ratio || radiusY < ratio) return;
  ctx.save();
  ctx.fillStyle = "rgba(112,183,255,.07)";
  ctx.strokeStyle = range.quality === "experimental" ? "rgba(245,198,101,.72)" : "rgba(112,183,255,.74)";
  ctx.lineWidth = 1.4 * ratio;
  ctx.beginPath();
  ctx.ellipse(center.x, center.y, radiusX, radiusY, 0, 0, Math.PI * 2);
  ctx.fill();
  ctx.stroke();
  if (finite(range.min_radius_x) > 0 && finite(range.min_radius_y) > 0) {
    const minX = mapTransform(map, width, height, map.player.x + finite(range.min_radius_x), map.player.y);
    const minY = mapTransform(map, width, height, map.player.x, map.player.y + finite(range.min_radius_y));
    ctx.setLineDash([5 * ratio, 4 * ratio]);
    ctx.beginPath();
    ctx.ellipse(center.x, center.y, Math.abs(minX.x - center.x), Math.abs(minY.y - center.y), 0, 0, Math.PI * 2);
    ctx.stroke();
  }
  ctx.restore();
}

function drawMapBackground(ctx, width, height, ratio) {
  const gradient = ctx.createRadialGradient(width * .5, height * .42, 0, width * .5, height * .5, Math.max(width, height) * .72);
  gradient.addColorStop(0, "#14110c");
  gradient.addColorStop(1, "#050608");
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, width, height);
  ctx.strokeStyle = "rgba(240,160,32,.06)";
  ctx.lineWidth = ratio;
  const step = 56 * ratio;
  for (let x = width % step; x < width; x += step) { ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, height); ctx.stroke(); }
  for (let y = height % step; y < height; y += step) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(width, y); ctx.stroke(); }
  ctx.fillStyle = "rgba(240,160,32,.55)";
  ctx.font = `${9 * ratio}px Segoe UI`;
  ctx.fillText("N", 12 * ratio, 18 * ratio);
  ctx.beginPath(); ctx.moveTo(15 * ratio, 24 * ratio); ctx.lineTo(15 * ratio, 38 * ratio); ctx.strokeStyle = "rgba(61,224,208,.75)"; ctx.stroke();
}

function drawMapPoint(ctx, map, point, width, height, ratio) {
  const p = mapTransform(map, width, height, point.x, point.y);
  if (p.x < -40 || p.y < -40 || p.x > width + 40 || p.y > height + 40) return;
  const palette = { zone: "#f5c665", friendly: "#69d3e8", enemy: "#ff7078", poi: "#ff7078", traceback: "#a99af6", target: "#70b7ff" };
  const color = palette[point.color] || palette[point.kind] || "#8fa4be";
  ctx.save();
  ctx.strokeStyle = color;
  ctx.fillStyle = color;
  ctx.lineWidth = (point.is_target ? 2 : 1.4) * ratio;
  if (point.kind === "zone") {
    ctx.beginPath(); ctx.arc(p.x, p.y, (point.is_target ? 10 : 7) * ratio, 0, Math.PI * 2); ctx.stroke();
    if (point.is_target) { ctx.globalAlpha = .18; ctx.fill(); ctx.globalAlpha = 1; }
  } else if (point.kind === "airfield") {
    ctx.translate(p.x, p.y); ctx.rotate(-Math.PI / 4); ctx.strokeRect(-11 * ratio, -2 * ratio, 22 * ratio, 4 * ratio);
  } else if (point.kind === "poi") {
    const s = 7 * ratio, g = 3 * ratio;
    for (const [sx, sy] of [[-1,-1],[1,-1],[-1,1],[1,1]]) {
      ctx.beginPath(); ctx.moveTo(p.x + sx * s, p.y + sy * (s-g)); ctx.lineTo(p.x + sx * s, p.y + sy * s); ctx.lineTo(p.x + sx * (s-g), p.y + sy * s); ctx.stroke();
    }
  } else if (point.kind === "traceback") {
    ctx.beginPath(); ctx.arc(p.x, p.y, 8 * ratio, 0, Math.PI * 2); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(p.x - 11*ratio,p.y); ctx.lineTo(p.x + 11*ratio,p.y); ctx.moveTo(p.x,p.y-11*ratio); ctx.lineTo(p.x,p.y+11*ratio); ctx.stroke();
  } else if (HOSTILE_MAP_KINDS.has(String(point.kind || ""))) {
    ctx.font = `bold ${24 * ratio}px Bomana8111Icons, sans-serif`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    const glyph = officialMapGlyph(point.icon);
    ctx.fillText(glyph, p.x, p.y);
    ctx.strokeStyle = "#000";
    ctx.lineWidth = ratio;
    ctx.strokeText(glyph, p.x, p.y);
  }
  if (point.is_target || state.zoom >= 1.7 || point.kind === "traceback") {
    ctx.font = `${9 * ratio}px Segoe UI`;
    ctx.fillStyle = color;
    ctx.fillText(point.label, p.x + 12 * ratio, p.y - 9 * ratio);
  }
  ctx.restore();
}

function drawPlayer(ctx, map, player, width, height, ratio) {
  const p = mapTransform(map, width, height, player.x, player.y);
  ctx.save();
  ctx.translate(p.x, p.y);
  ctx.rotate(finite(player.heading_deg) * Math.PI / 180);
  ctx.fillStyle = "#70b7ff";
  ctx.shadowColor = "#70b7ff";
  ctx.shadowBlur = 12 * ratio;
  ctx.beginPath(); ctx.moveTo(0, -13*ratio); ctx.lineTo(8*ratio, 10*ratio); ctx.lineTo(0, 6*ratio); ctx.lineTo(-8*ratio, 10*ratio); ctx.closePath(); ctx.fill();
  ctx.restore();
}

function renderHeadingTape(payload) {
  const canvas = $("headingTape");
  const { width, height, ratio } = canvasSize(canvas);
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, width, height);
  ctx.strokeStyle = "rgba(143,181,226,.22)";
  ctx.fillStyle = "#8fa4be";
  ctx.lineWidth = ratio;
  ctx.font = `${8 * ratio}px Segoe UI`;
  const heading = (finite(payload.flight.heading_deg) + 360) % 360;
  for (let offset = -60; offset <= 60; offset += 10) {
    const x = width / 2 + offset / 120 * width;
    const absolute = (heading + offset + 360) % 360;
    const tall = offset % 30 === 0;
    ctx.beginPath(); ctx.moveTo(x, height); ctx.lineTo(x, height - (tall ? 13 : 7) * ratio); ctx.stroke();
    if (tall) ctx.fillText(String(Math.round(absolute)).padStart(3,"0"), x - 10*ratio, 11*ratio);
  }
  const items = [...payload.navigation.zones, ...payload.navigation.airfields];
  if (payload.navigation.poi) items.push(payload.navigation.poi);
  if (payload.navigation.traceback) items.push(payload.navigation.traceback);
  for (const item of items) {
    if (Math.abs(item.relative_deg) > 60) continue;
    const x = width / 2 + item.relative_deg / 120 * width;
    ctx.fillStyle = item.kind === "traceback" ? "#a99af6" : item.kind === "poi" ? "#ff7078" : item.is_target ? "#70b7ff" : "#f5c665";
    ctx.beginPath(); ctx.arc(x, height - 17*ratio, (item.is_target ? 4 : 3)*ratio, 0, Math.PI*2); ctx.fill();
  }
  ctx.strokeStyle = "#70b7ff";
  ctx.beginPath(); ctx.moveTo(width/2, height); ctx.lineTo(width/2, height-18*ratio); ctx.stroke();
}

function bindResetTimer(id) {
  const node = $(id);
  if (!node) return;
  node.addEventListener("click", () => {
    if (!window.confirm("确定立即重置 Bomana 任务计时器吗？此操作只执行一次。")) return;
    void submitCommand(
      { schema_version: 1, command: "action.reset_timer", confirmed: true },
      "重置计时器",
    );
  });
}

function bindCycleCorner(id) {
  const node = $(id);
  if (!node) return;
  node.addEventListener("click", () => {
    void submitCommand(
      { schema_version: 1, command: "action.cycle_corner" },
      "切换界面位置",
    );
  });
}

function installControlHandlers() {
  bindResetTimer("resetTimerButton");
  bindResetTimer("resetTimerButtonDesktop");
  bindCycleCorner("cycleCornerButton");
  bindCycleCorner("cycleCornerButtonDesktop");
  $("lockedOnButton").addEventListener("click", () => {
    void submitCommand(
      { schema_version: 1, command: "state.set_locked", locked: true },
      "锁定窗口",
    );
  });
  $("lockedOffButton").addEventListener("click", () => {
    void submitCommand(
      { schema_version: 1, command: "state.set_locked", locked: false },
      "解除窗口锁定",
    );
  });
  $("beepOnButton").addEventListener("click", () => {
    void submitCommand(
      { schema_version: 1, command: "state.set_beep_enabled", enabled: true },
      "开启提示音",
    );
  });
  $("beepOffButton").addEventListener("click", () => {
    void submitCommand(
      { schema_version: 1, command: "state.set_beep_enabled", enabled: false },
      "关闭提示音",
    );
  });
  $("timerCycleApplyButton").addEventListener("click", () => {
    const minutes = Number($("timerCycleMinutes").value);
    if (!Number.isInteger(minutes) || minutes < 1 || minutes > 180) {
      setCommandStatus("计时周期必须是 1–180 分钟的整数", "error");
      return;
    }
    void submitCommand(
      { schema_version: 1, command: "config.set_timer_cycle_minutes", minutes },
      `设置 ${minutes} 分钟计时周期`,
    );
  });
  $("zoneSoundOnButton").addEventListener("click", () => {
    void submitCommand(
      { schema_version: 1, command: "state.set_zone_sound_enabled", enabled: true },
      "开启战区提示音",
    );
  });
  $("zoneSoundOffButton").addEventListener("click", () => {
    void submitCommand(
      { schema_version: 1, command: "state.set_zone_sound_enabled", enabled: false },
      "关闭战区提示音",
    );
  });
  for (const panel of PANEL_CONTROLS) {
    $(panel.inputId).addEventListener("change", (event) => {
      const enabled = event.currentTarget.checked;
      if (state.control) renderControlState(state.control);
      void submitCommand(
        {
          schema_version: 1,
          command: "config.set_panel_visibility",
          target: panel.target,
          enabled,
        },
        `${enabled ? "显示" : "隐藏"}${panel.label}面板`,
      );
    });
  }
  $("weaponSelect").addEventListener("change", (event) => {
    const weaponId = event.currentTarget.value;
    const choice = state.control && state.control.weapons.find((weapon) => weapon.weapon_id === weaponId);
    if (state.control) renderControlState(state.control);
    if (!choice || !choice.compatible) {
      setCommandStatus("该武器当前不可选择", "error");
      return;
    }
    void submitCommand(
      { schema_version: 1, command: "weapon.select", weapon_id: weaponId },
      `选择武器：${choice.display_name}`,
    );
  });
  $("modelCompatibleButton").addEventListener("click", () => {
    void submitCommand(
      { schema_version: 1, command: "weapon.set_ballistic_model", model: "foxthree_compatible" },
      "允许在缺少官方数据时使用推测替代",
    );
  });
  $("modelOfficialButton").addEventListener("click", () => {
    void submitCommand(
      { schema_version: 1, command: "weapon.set_ballistic_model", model: "strict_official" },
      "缺少官方数据时不应用替代模型",
    );
  });
}

function updateLegendCount() {
  const enabled = Object.values(state.mapFilters).filter(Boolean).length;
  text("mapLegendCount", String(enabled));
}

function setLegendOpen(open) {
  const legend = $("mapLegend");
  const toggle = $("mapLegendToggle");
  if (!legend || !toggle) return;
  legend.hidden = !open;
  toggle.setAttribute("aria-expanded", open ? "true" : "false");
}

function openSheet(sheetId) {
  const sheet = $(sheetId);
  if (!sheet) return;
  closeSheet("controlSheet", true);
  closeSheet("weaponSheet", true);
  sheet.hidden = false;
  $("sheetBackdrop").hidden = false;
  document.body.classList.add("sheet-open");
}

function closeSheet(sheetId, quiet = false) {
  const sheet = $(sheetId);
  if (sheet) sheet.hidden = true;
  if (quiet) return;
  const controlOpen = $("controlSheet") && !$("controlSheet").hidden;
  const weaponOpen = $("weaponSheet") && !$("weaponSheet").hidden;
  if (!controlOpen && !weaponOpen) {
    $("sheetBackdrop").hidden = true;
    document.body.classList.remove("sheet-open");
  }
}

function closeAllSheets() {
  closeSheet("controlSheet", true);
  closeSheet("weaponSheet", true);
  $("sheetBackdrop").hidden = true;
  document.body.classList.remove("sheet-open");
}

function installSheetHandlers() {
  $("dockOpsButton").addEventListener("click", () => openSheet("controlSheet"));
  $("controlSheetClose").addEventListener("click", () => closeSheet("controlSheet"));
  $("dockWeaponButton").addEventListener("click", () => openSheet("weaponSheet"));
  $("weaponChip").addEventListener("click", () => openSheet("weaponSheet"));
  $("weaponCardOpen").addEventListener("click", () => openSheet("weaponSheet"));
  $("weaponSheetClose").addEventListener("click", () => closeSheet("weaponSheet"));
  $("dockLegendButton").addEventListener("click", () => {
    const legend = $("mapLegend");
    const next = legend.hidden;
    setLegendOpen(next);
    if (next) $("mapStage").scrollIntoView({ block: "nearest", behavior: "smooth" });
  });
  $("mapLegendToggle").addEventListener("click", () => {
    setLegendOpen($("mapLegend").hidden);
  });
  $("sheetBackdrop").addEventListener("click", () => closeAllSheets());
  for (const tab of document.querySelectorAll("[data-control-tab]")) {
    tab.addEventListener("click", () => {
      const name = tab.dataset.controlTab;
      for (const node of document.querySelectorAll("[data-control-tab]")) {
        const active = node.dataset.controlTab === name;
        node.classList.toggle("active", active);
        node.setAttribute("aria-selected", active ? "true" : "false");
      }
      for (const panel of document.querySelectorAll("[data-control-panel]")) {
        panel.hidden = panel.dataset.controlPanel !== name;
        panel.classList.toggle("active", panel.dataset.controlPanel === name);
      }
    });
  }
  window.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeAllSheets();
      setLegendOpen(false);
    }
  });
}

function installMapControls() {
  $("mapZoomIn").addEventListener("click", () => { state.zoom = Math.min(4, state.zoom * 1.25); renderCurrentMap(); });
  $("mapZoomOut").addEventListener("click", () => { state.zoom = Math.max(.75, state.zoom / 1.25); renderCurrentMap(); });
  $("mapFollow").addEventListener("click", () => {
    state.follow = !state.follow;
    $("mapFollow").classList.toggle("active", state.follow);
    if (state.follow) { state.panX = 0; state.panY = 0; }
    renderCurrentMap();
  });
  const stage = $("mapStage");
  const legend = $("mapLegend");
  const legendShell = legend.closest(".map-legend-shell");
  const stopMapGesture = (event) => event.stopPropagation();
  if (legendShell) {
    legendShell.addEventListener("pointerdown", stopMapGesture);
    legendShell.addEventListener("wheel", stopMapGesture, { passive: true });
  }
  legend.addEventListener("pointerdown", stopMapGesture);
  legend.addEventListener("wheel", stopMapGesture, { passive: true });
  for (const button of legend.querySelectorAll("[data-map-filter]")) {
    button.addEventListener("click", () => {
      const key = button.dataset.mapFilter;
      state.mapFilters[key] = !state.mapFilters[key];
      button.classList.toggle("is-off", !state.mapFilters[key]);
      button.setAttribute("aria-pressed", String(state.mapFilters[key]));
      updateLegendCount();
      renderCurrentMap();
    });
  }
  updateLegendCount();
  stage.addEventListener("wheel", (event) => {
    event.preventDefault();
    state.zoom = Math.max(.75, Math.min(4, state.zoom * (event.deltaY < 0 ? 1.12 : .89)));
    renderCurrentMap();
  }, { passive: false });
  stage.addEventListener("pointerdown", (event) => {
    state.dragging = true; state.pointerX = event.clientX; state.pointerY = event.clientY; state.follow = false;
    $("mapFollow").classList.remove("active"); stage.setPointerCapture(event.pointerId);
  });
  stage.addEventListener("pointermove", (event) => {
    if (!state.dragging) return;
    const rect = stage.getBoundingClientRect();
    state.panX -= (event.clientX - state.pointerX) / Math.max(1, rect.width) / state.zoom;
    state.panY -= (event.clientY - state.pointerY) / Math.max(1, rect.height) / state.zoom;
    state.pointerX = event.clientX; state.pointerY = event.clientY; renderCurrentMap();
  });
  stage.addEventListener("pointerup", (event) => { state.dragging = false; stage.releasePointerCapture(event.pointerId); });
  stage.addEventListener("pointercancel", () => { state.dragging = false; });
}

function renderCurrentMap() {
  if (!state.payload) return;
  renderMap(state.payload.map, state.payload.flight.heading_deg);
  renderHeadingTape(state.payload);
}

$("pairingForm").addEventListener("submit", (event) => {
  event.preventDefault();
  const code = $("pairingCode").value.trim().toUpperCase();
  if (!/^[A-Z2-9]{4}-?[A-Z2-9]{4}$/.test(code)) {
    showPairing("请输入 Bomana 主窗口底部显示的 8 位配对码");
    return;
  }
  window.location.assign(`/?pair=${encodeURIComponent(code)}`);
});

installControlHandlers();
installMapControls();
installSheetHandlers();
const systemsToggle = $("systemsToggle");
const systemsGrid = $("systemsGrid");
if (systemsToggle && systemsGrid) {
  systemsToggle.addEventListener("click", () => {
    const open = systemsGrid.hidden;
    systemsGrid.hidden = !open;
    systemsToggle.setAttribute("aria-expanded", open ? "true" : "false");
    systemsToggle.textContent = open ? "收起系统" : "更多系统";
  });
}
if (document.fonts) document.fonts.load("bold 18px Bomana8111Icons").then(renderCurrentMap, () => {});
if ("ResizeObserver" in window) new ResizeObserver(renderCurrentMap).observe($("mapStage"));
window.addEventListener("resize", renderCurrentMap, { passive: true });
scheduleSnapshotPoll();
scheduleControlPoll();
window.addEventListener("pagehide", () => {
  pollsStopped = true;
  window.clearTimeout(pollTimer);
  window.clearTimeout(controlPollTimer);
}, { once: true });
