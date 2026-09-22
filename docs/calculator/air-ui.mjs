import { simulateEncounter, validateEncounter, launchReference } from "./air-model.mjs";

const MODES = { beam: "持续修正 39", cold: "水平转冷", descend: "下切 30°" };
const el = id => document.getElementById(id);
const number = id => el(id).value.trim() ? Number(el(id).value) : NaN;
const text = (tag, value, className) => {
  const node = document.createElement(tag); node.textContent = value;
  if (className) node.className = className;
  return node;
};
const fixed = (value, digits = 1) => value.toLocaleString("zh-CN", { maximumFractionDigits: digits, minimumFractionDigits: digits });
const distance = value => value < 5 ? "<5 m" : value < 1000 ? `${fixed(value, 0)} m` : `${fixed(value / 1000, 2)} km`;
const svgNode = (tag, attributes = {}, content = null) => {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  Object.entries(attributes).forEach(([key, value]) => node.setAttribute(key, String(value)));
  if (content !== null) node.textContent = content;
  return node;
};

function plotEncounter(result, timeS) {
  const svg = svgNode("svg", { viewBox: "0 0 760 420", "aria-hidden": "true" });
  const samples = result.samples;
  const current = samples.findIndex(sample => sample.t >= timeS);
  const index = current < 0 ? samples.length - 1 : current;
  const sample = samples[index], next = samples[Math.min(index + 1, samples.length - 1)];
  for (const [axis, top, height, title] of [[1, 28, 222, "俯视"], [2, 290, 104, "侧视"]]) {
    const points = samples.flatMap(row => [row.target, row.missile]);
    const minX = Math.min(...points.map(p => p[0])), maxX = Math.max(...points.map(p => p[0]));
    const minY = Math.min(...points.map(p => p[axis])), maxY = Math.max(...points.map(p => p[axis]));
    const scale = Math.min(670 / Math.max(maxX - minX, 500), (height - 28) / Math.max(maxY - minY, 300));
    const x = value => 380 + (value - (maxX + minX) / 2) * scale;
    const y = value => top + height / 2 - (value - (maxY + minY) / 2) * scale;
    svg.append(svgNode("text", { x: 16, y: top - 8, class: "air-plot-label" }, title));
    svg.append(svgNode("line", { x1: 16, y1: top + height + 8, x2: 744, y2: top + height + 8, class: "air-plot-grid" }));
    for (const [key, className] of [["target", "air-target-path"], ["missile", "air-missile-path"]]) {
      const path = samples.map((row, i) => `${i ? "L" : "M"}${x(row[key][0]).toFixed(2)},${y(row[key][axis]).toFixed(2)}`).join(" ");
      svg.append(svgNode("path", { d: path, class: className }));
      const from = sample[key], to = next[key], prev = samples[Math.max(0, index - 1)][key];
      const dx = to[0] - prev[0], dy = to[axis] - prev[axis];
      const angle = Math.atan2(-dy, dx) * 180 / Math.PI;
      svg.append(svgNode("path", { d: key === "target" ? "M10 0 L-7 -6 L-3 0 L-7 6 Z" : "M8 0 L-6 -4 L-3 0 L-6 4 Z",
        class: key === "target" ? "air-target-marker" : "air-missile-marker",
        transform: `translate(${x(from[0])} ${y(from[axis])}) rotate(${angle})` }));
    }
    svg.append(svgNode("line", { x1: x(sample.target[0]), y1: y(sample.target[axis]), x2: x(sample.missile[0]), y2: y(sample.missile[axis]), class: "air-los" }));
    const rawScaleM = 100 / scale, exponent = 10 ** Math.floor(Math.log10(rawScaleM));
    const scaleM = [1, 2, 5, 10].find(v => v * exponent >= rawScaleM) * exponent;
    const scalePx = scaleM * scale;
    svg.append(svgNode("path", { d: `M${730 - scalePx} ${top + 5}v5h${scalePx}v-5`, class: "air-scale" }));
    svg.append(svgNode("text", { x: 730 - scalePx / 2, y: top - 2, "text-anchor": "middle", class: "air-plot-label" }, distance(scaleM)));
    if (axis === 2) svg.append(svgNode("text", { x: 18, y: top + height - 2, class: "air-plot-label" }, `飞机 ${fixed(sample.target[2], 0)} m · 来弹 ${fixed(sample.missile[2], 0)} m`));
  }
  el("airPlot").replaceChildren(svg);
  el("airPlot").setAttribute("aria-label", `${MODES[result.mode]}，${fixed(timeS)} 秒，双方距离 ${distance(sample.rangeM)}。蓝色为飞机，红色为导弹。`);
  el("airTimeValue").textContent = `${fixed(timeS)} s`;
}

export async function initAirCalculator() {
  const form = el("airForm");
  if (!form) return;
  let data;
  try {
    const response = await fetch(new URL("./radar-data.json", import.meta.url), { cache: "no-cache" });
    if (!response.ok) throw new Error("radar data unavailable");
    data = await response.json();
    if (data.schema !== "bomana.radar-reference/v1" || !data.weapons?.length) throw new Error("radar data format");
  } catch {
    el("airSource").textContent = "空空弹参数加载失败，请刷新重试。";
    return;
  }
  el("airSource").textContent = `客户端 ${data.version} · ${data.weapons.length} 种已核查雷达弹 · 独立研究参考`;
  el("airWeapon").replaceChildren(...data.weapons.map(weapon => {
    const option = text("option", `${weapon.name} · ${weapon.kind === "ARH" ? "主动" : "半主动"}`);
    option.value = weapon.id; return option;
  }));
  el("airWeapon").value = "us_aim_120a";
  el("airWeapon").disabled = false;
  let results = null, selected = "beam", pending = 0, frame = 0, playbackStart = 0;
  const weapon = () => data.weapons.find(row => row.id === el("airWeapon").value);
  const input = () => ({ rangeM: number("airRange") * 1000,
    missileSpeedMps: number("airMissileSpeed"), targetSpeedMps: number("airTargetSpeed") / 3.6,
    targetAltitudeM: number("airTargetAltitude"), missileAltitudeM: number("airMissileAltitude"),
    aspectDeg: number("airAspect"), flightPathDeg: number("airFlightPath"), targetG: number("airTargetG"),
    delayS: number("airDelay"), observationGapS: number("airGap"), missileAgeS: number("airAge") });
  const stop = () => { cancelAnimationFrame(frame); frame = 0; el("airPlay").textContent = "▶ 播放"; el("airPlay").setAttribute("aria-label", "播放轨迹"); };
  const drawTime = () => { if (results) plotEncounter(results[selected], number("airTime") / 1000 * results[selected].durationS); };

  function renderLaunch() {
    const w = weapon(), tables = w.envelope?.tables;
    const result = launchReference(w, number("airLaunchAltitude"), number("airLaunchMach"), number("airLaunchTarget"));
    el("airLaunchResult").textContent = result
      ? `条件射程 ${fixed(result.minRangeM / 1000, 2)}–${fixed(result.maxRangeM / 1000, 1)} km · 最大射程表时长 ${fixed(result.tableTimeS)} s`
      : "输入超出原表覆盖范围或缺少相应表值，未外推射程。";
    el("airLaunchDomain").textContent = tables?.length
      ? `原表高度 ${tables.map(row => fixed(row.altitude_m, 0)).join(" / ")} m；载机 Mach ${[...new Set(tables.flatMap(row => row.fighter_mach))].join(" / ")}；目标两端速度按每行 targetMach 条件。表时长不是当前距离的命中倒计时；高度差／dogfight 分支未计算。`
      : "本弹缺少可用于此处的完整条件表。";
  }

  function renderParameters() {
    const w = weapon(), list = document.createElement("dl");
    for (const [label, value] of [
      ["比例导引倍率", String(w.navigationConstant)], ["控制请求上限", `${w.commandLimitG} g`],
      ["距离搜索半窗", w.rangeSearchHalfM === null ? "未启用距离观测" : `±${w.rangeSearchHalfM} m`],
      ["速度搜索半窗", `±${w.speedSearchHalfMps} m/s`],
      ["角门率", w.angleGateRateDegS === null ? "未配置" : `${w.angleGateRateDegS} °/s`],
      ["导引头角限", `${w.angleMaxDeg}°`], ["发动机阶段总时长", `${fixed(w.motorSeconds, 2)} s`],
      ["惯导 / 数据链配置", `${w.inertialNavigation ? "有" : "无"} / ${w.datalink ? "有" : "无"}`],
    ]) { const group = document.createElement("div"); group.append(text("dt", label), text("dd", value)); list.append(group); }
    el("airParameters").replaceChildren(list);
  }

  function selectResult(mode) {
    if (!results) return;
    stop(); selected = mode; el("airTime").value = "0";
    for (const button of el("airCompare").querySelectorAll("button")) button.setAttribute("aria-pressed", String(button.dataset.mode === mode));
    const result = results[mode], w = weapon();
    const stats = document.createElement("dl");
    for (const [label, value] of [["模型最近距离", distance(result.nearestM)],
      ["最近接近时刻", `${fixed(result.nearestTimeS)} s`],
      ["指令限幅累计", `${fixed(result.saturatedS)} s`]]) {
      const group = document.createElement("div"); group.append(text("dt", label), text("dd", value)); stats.append(group);
    }
    el("airResult").replaceChildren(stats, text("p", `初始接近 ${fixed(result.initial.closingMps, 0)} m/s · 目标对地径向投影 ${fixed(result.initial.targetRadialMps)} m/s · 指令峰值 ${fixed(result.peakRequestedG)} g`, "tool-note"));
    el("airAdvice").textContent = result.reason === "ground"
      ? "轨迹触及地面，计算已截断；此结果不能作为躲弹方案。"
      : mode === "beam" ? "39 争取干扰观测。本场景若仍有观测或旧预测仍正确，横向飞行可以保持碰撞航向。"
        : mode === "cold" ? "转冷改变接近条件。此处不模拟导弹耗能，因此不能用最近距离判定拖弹成功；越晚开始，留给转向的时间越少。"
          : "下切改变原交会平面，迫使导弹修正。这里的 30° 是对照动作，不是最佳俯冲角；实际还取决于速度损失、控制响应和地形。";
    if (result.reason === "horizon") el("airAdvice").append(" 仅计算前 30 秒，较晚交会未覆盖。");
    if (result.reason === "lifetime") el("airAdvice").append(" 已到配置寿命，模型在此截断；不是实战自毁时机保证。");
    const recovery = result.recovery;
    el("airRecovery").replaceChildren();
    if (number("airGap") > 0) {
      if (!recovery) el("airRecovery").append(text("p", "本次轨迹在假设恢复观测前已结束，未计算恢复时的候选误差。"));
      else {
        el("airRecovery").append(text("p", `假设恢复观测时：旧预测位置误差 ${distance(recovery.positionErrorM)}，视线方向差 ${fixed(recovery.angleResidualDeg, 2)}°。`));
        if (recovery.comparable) {
          const rangeInside = w.rangeSearchHalfM !== null && Math.abs(recovery.rangeResidualM) <= w.rangeSearchHalfM;
          const speedInside = Math.abs(recovery.speedResidualMps) <= w.speedSearchHalfMps;
          el("airRecovery").append(text("p", `距离残差 ${fixed(recovery.rangeResidualM)} m（${rangeInside ? "在" : "不在"}搜索半窗内）；速度残差 ${fixed(recovery.speedResidualMps)} m/s（${speedInside ? "在" : "不在"}搜索半窗内）。仅比较单站直线外推候选，不判定真实重捕。`));
        } else el("airRecovery").append(text("p", "半主动弹缺少照射端状态，未用单站几何代替双站距离／速度门。"));
      }
    }
    drawTime();
  }

  function calculate() {
    pending = 0; stop();
    const value = input();
    el("airAspectValue").textContent = `${value.aspectDeg}°${value.aspectDeg === 90 ? " · 横向" : ""}`;
    renderLaunch(); renderParameters();
    const error = form.checkValidity() ? validateEncounter(value, weapon()) : "请在标示范围内填写完整数值。";
    el("airPlay").disabled = Boolean(error); el("airTime").disabled = Boolean(error);
    if (error) {
      results = null; el("airResult").replaceChildren(text("p", error)); el("airCompare").replaceChildren();
      el("airPlot").replaceChildren(); el("airAdvice").textContent = ""; el("airRecovery").replaceChildren(); return;
    }
    results = Object.fromEntries(Object.keys(MODES).map(mode => [mode, simulateEncounter(weapon(), value, mode)]));
    el("airCompare").replaceChildren(...Object.entries(MODES).map(([mode, title]) => {
      const button = document.createElement("button"); button.type = "button"; button.dataset.mode = mode;
      button.append(text("span", title), text("strong", distance(results[mode].nearestM)), text("small", "模型最近距离"));
      button.addEventListener("click", () => selectResult(mode)); return button;
    }));
    selectResult(selected);
  }
  form.addEventListener("submit", event => event.preventDefault());
  form.addEventListener("input", () => { if (!pending) pending = requestAnimationFrame(calculate); });
  form.addEventListener("change", () => { if (!pending) pending = requestAnimationFrame(calculate); });
  el("airLaunchInputs").addEventListener("input", renderLaunch);
  el("airTime").addEventListener("input", () => { stop(); drawTime(); });
  el("airPlay").addEventListener("click", () => {
    if (frame) { stop(); return; }
    if (!results) return;
    if (number("airTime") >= 1000) el("airTime").value = "0";
    playbackStart = performance.now() - number("airTime") / 1000 * results[selected].durationS * 1000;
    el("airPlay").textContent = "Ⅱ 暂停"; el("airPlay").setAttribute("aria-label", "暂停轨迹");
    let lastPaint = -Infinity;
    const tick = now => {
      const progress = Math.min(1000, (now - playbackStart) / results[selected].durationS);
      el("airTime").value = String(progress);
      if (now - lastPaint >= 50 || progress >= 1000) { drawTime(); lastPaint = now; }
      if (progress >= 1000) stop(); else frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
  });
  document.addEventListener("visibilitychange", () => { if (document.hidden) stop(); });
  for (const button of document.querySelectorAll("[data-air-preset]")) button.addEventListener("click", () => {
    const preset = button.dataset.airPreset;
    const fields = { airRange: preset === "late" ? "2" : "5", airMissileSpeed: "1000", airTargetSpeed: "1080",
      airTargetG: "9", airTargetAltitude: "8000", airMissileAltitude: preset === "descending" ? "10000" : "8000",
      airAspect: "90", airFlightPath: preset === "descending" ? "-10" : "0", airDelay: "0", airGap: "0", airAge: "10" };
    Object.entries(fields).forEach(([id, value]) => { el(id).value = value; }); calculate();
  });
  calculate();
}
