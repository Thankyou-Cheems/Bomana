"use strict";

const $ = (id) => document.getElementById(id);
const state = { payload: null, zoom: 1, follow: true, panX: 0, panY: 0, dragging: false, pointerX: 0, pointerY: 0 };
let pollTimer = null;
let requestActive = false;

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

async function poll() {
  if (requestActive) return;
  requestActive = true;
  try {
    const response = await fetch("/api/v1/snapshot", { credentials: "same-origin", cache: "no-store" });
    if (response.status === 401) {
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

function render(payload) {
  const age = Math.max(0, Date.now() / 1000 - finite(payload.generated_at));
  const connected = payload.status.connected && age < 3;
  setConnection(connected ? "online" : "offline", connected ? "实时" : "数据暂停", age < 1 ? "刚刚更新" : `${age.toFixed(1)} 秒前`);
  renderCapabilities(payload.capabilities);

  text("phaseLabel", payload.status.phase_label);
  text("timerValue", fmtTime(payload.timer.remaining_sec));
  text("timerMeta", payload.timer.cycle ? `第 ${payload.timer.cycle} 轮 · 第 ${payload.timer.life_index || "-"} 次复活` : "等待任务计时");
  $("timerProgress").style.width = `${Math.max(0, Math.min(100, finite(payload.timer.progress) * 100))}%`;

  text("iasValue", Math.round(finite(payload.flight.ias_kmh)) || "---");
  text("altValue", Math.round(finite(payload.flight.altitude_m)) || "---");
  text("headingValue", String(Math.round((finite(payload.flight.heading_deg) + 360) % 360)).padStart(3, "0"));
  text("fuelValue", payload.capabilities.fuel ? Math.round(finite(payload.fuel.percent)) : "---");
  text("aircraftName", payload.flight.aircraft || "未识别机型");

  renderMap(payload.map, payload.flight.heading_deg);
  renderHeadingTape(payload);
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

function renderWeapon(weapon) {
  text("weaponName", weapon.name || "未选择武器");
  text("weaponModel", weapon.model || "无可用模型");
  text("weaponTarget", weapon.target_name || "--");
  text("weaponDistance", weapon.target_distance_km > 0 ? fmt(weapon.target_distance_km, 1, " km") : "--");
  const envelope = weapon.max_range_km > 0 ? `${fmt(weapon.min_range_km, 1)}–${fmt(weapon.max_range_km, 1)} km` : "--";
  text("weaponEnvelope", envelope);
  text("weaponTti", weapon.time_to_target_s > 0 ? fmt(weapon.time_to_target_s, 0, " s") : "--");
  text("weaponStatus", weapon.reason || weapon.status || "等待有效解算");
  text("weaponQuality", weapon.quality || "待机");
  const chip = $("weaponQuality");
  chip.className = "quality-chip";
  if (weapon.quality === "experimental") chip.classList.add("experimental");
  else if (weapon.valid) chip.classList.add("valid");
  else if (weapon.status && !["unknown_weapon", "unavailable"].includes(weapon.status)) chip.classList.add("danger");
  const max = Math.max(weapon.max_range_km, weapon.target_distance_km, 1);
  $("weaponRangeBar").style.width = `${Math.min(100, Math.max(0, weapon.max_range_km / max * 100))}%`;
  $("weaponTargetMark").style.left = `${Math.min(100, Math.max(0, weapon.target_distance_km / max * 100))}%`;
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
  $("mapEmpty").classList.toggle("hidden", map.available);
  if (!map.available) return;

  const pointsById = new Map(map.points.map((point) => [point.id, point]));
  const target = map.points.find((point) => point.kind === "poi" && point.is_target)
    || map.points.find((point) => point.is_target && point.kind !== "traceback");
  if (map.player && target) {
    const from = mapTransform(map, width, height, map.player.x, map.player.y);
    const to = mapTransform(map, width, height, target.x, target.y);
    ctx.save();
    ctx.setLineDash([8 * ratio, 7 * ratio]);
    ctx.strokeStyle = "rgba(112,183,255,.42)";
    ctx.lineWidth = ratio;
    ctx.beginPath(); ctx.moveTo(from.x, from.y); ctx.lineTo(to.x, to.y); ctx.stroke();
    ctx.restore();
  }

  for (const point of pointsById.values()) drawMapPoint(ctx, map, point, width, height, ratio);
  if (map.player) drawPlayer(ctx, map, map.player, width, height, ratio);
}

function drawMapBackground(ctx, width, height, ratio) {
  const gradient = ctx.createRadialGradient(width * .5, height * .42, 0, width * .5, height * .5, Math.max(width, height) * .72);
  gradient.addColorStop(0, "#10253b");
  gradient.addColorStop(1, "#06111e");
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, width, height);
  ctx.strokeStyle = "rgba(118,161,207,.10)";
  ctx.lineWidth = ratio;
  const step = 48 * ratio;
  for (let x = width % step; x < width; x += step) { ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, height); ctx.stroke(); }
  for (let y = height % step; y < height; y += step) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(width, y); ctx.stroke(); }
  ctx.fillStyle = "rgba(143,164,190,.46)";
  ctx.font = `${9 * ratio}px Segoe UI`;
  ctx.fillText("N", 12 * ratio, 18 * ratio);
  ctx.beginPath(); ctx.moveTo(15 * ratio, 24 * ratio); ctx.lineTo(15 * ratio, 38 * ratio); ctx.strokeStyle = "rgba(112,183,255,.7)"; ctx.stroke();
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
    showPairing("请输入 Bomana 托盘显示的 8 位配对码");
    return;
  }
  window.location.assign(`/?pair=${encodeURIComponent(code)}`);
});

installMapControls();
if ("ResizeObserver" in window) new ResizeObserver(renderCurrentMap).observe($("mapStage"));
window.addEventListener("resize", renderCurrentMap, { passive: true });
poll();
pollTimer = window.setInterval(poll, 350);
window.addEventListener("pagehide", () => window.clearInterval(pollTimer), { once: true });
