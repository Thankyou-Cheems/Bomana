import { t, numberLocale } from "./i18n.mjs";
import { simulateEncounter, validateEncounter, launchReference } from "./air-model.mjs";

const MODES = { get beam() { return t("air-ui.maintainTheBeam", "持续修正 39"); }, get cold() { return t("air-ui.turnColdLevel", "水平转冷"); }, get descend() { return t("air-ui.dive30", "下切 30°"); } };
const el = id => document.getElementById(id);
const number = id => el(id).value.trim() ? Number(el(id).value) : NaN;
const text = (tag, value, className) => {
  const node = document.createElement(tag); node.textContent = value;
  if (className) node.className = className;
  return node;
};
const fixed = (value, digits = 1) => value.toLocaleString(numberLocale(), { maximumFractionDigits: digits, minimumFractionDigits: digits });
const distance = value => value < 5 ? "<5 m" : value < 1000 ? `${fixed(value, 0)} m` : `${fixed(value / 1000, 2)} km`;
const svgNode = (tag, attributes = {}, content = null) => {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  Object.entries(attributes).forEach(([key, value]) => node.setAttribute(key, String(value)));
  if (content !== null) node.textContent = content;
  return node;
};

function createEncounterPlot(result) {
  const svg = svgNode("svg", { viewBox: "0 0 760 420", "aria-hidden": "true" });
  const samples = result.samples;
  const points = samples.flatMap(row => [row.target, row.missile]), axes = [];
  const minX = Math.min(...points.map(p => p[0])), maxX = Math.max(...points.map(p => p[0]));
  for (const [axis, top, height, title] of [[1, 28, 222, t("air-ui.topView", "俯视")], [2, 290, 104, t("air-ui.sideView", "侧视")]]) {
    const minY = Math.min(...points.map(p => p[axis])), maxY = Math.max(...points.map(p => p[axis]));
    const scale = Math.min(670 / Math.max(maxX - minX, 500), (height - 28) / Math.max(maxY - minY, 300));
    const x = value => 380 + (value - (maxX + minX) / 2) * scale;
    const y = value => top + height / 2 - (value - (maxY + minY) / 2) * scale;
    svg.append(svgNode("text", { x: 16, y: top - 8, class: "air-plot-label" }, title));
    svg.append(svgNode("line", { x1: 16, y1: top + height + 8, x2: 744, y2: top + height + 8, class: "air-plot-grid" }));
    const markers = [];
    for (const [key, className] of [["target", "air-target-path"], ["missile", "air-missile-path"]]) {
      const path = samples.map((row, i) => `${i ? "L" : "M"}${x(row[key][0]).toFixed(2)},${y(row[key][axis]).toFixed(2)}`).join(" ");
      svg.append(svgNode("path", { d: path, class: className }));
      const marker = svgNode("path", { d: key === "target" ? "M10 0 L-7 -6 L-3 0 L-7 6 Z" : "M8 0 L-6 -4 L-3 0 L-6 4 Z",
        class: key === "target" ? "air-target-marker" : "air-missile-marker" });
      svg.append(marker); markers.push({key, marker});
    }
    const los = svgNode("line", { class: "air-los" }); svg.append(los);
    const rawScaleM = 100 / scale, exponent = 10 ** Math.floor(Math.log10(rawScaleM));
    const scaleM = [1, 2, 5, 10].find(v => v * exponent >= rawScaleM) * exponent;
    const scalePx = scaleM * scale;
    svg.append(svgNode("path", { d: `M${730 - scalePx} ${top + 5}v5h${scalePx}v-5`, class: "air-scale" }));
    svg.append(svgNode("text", { x: 730 - scalePx / 2, y: top - 2, "text-anchor": "middle", class: "air-plot-label" }, distance(scaleM)));
    const altitude = axis === 2 ? svgNode("text", { x: 18, y: top + height - 2, class: "air-plot-label" }) : null;
    if (altitude) svg.append(altitude);
    axes.push({axis, x, y, markers, los, altitude});
  }
  el("airPlot").replaceChildren(svg);
  return timeS => {
    const current = samples.findIndex(sample => sample.t >= timeS);
    const index = current < 0 ? samples.length - 1 : current;
    const sample = samples[index], next = samples[Math.min(index + 1, samples.length - 1)];
    for (const {axis, x, y, markers, los, altitude} of axes) {
      for (const {key, marker} of markers) {
        const from = sample[key], to = next[key], prev = samples[Math.max(0, index - 1)][key];
        const angle = Math.atan2(-(to[axis] - prev[axis]), to[0] - prev[0]) * 180 / Math.PI;
        marker.setAttribute("transform", `translate(${x(from[0])} ${y(from[axis])}) rotate(${angle})`);
      }
      for (const [attribute, value] of Object.entries({x1:x(sample.target[0]), y1:y(sample.target[axis]), x2:x(sample.missile[0]), y2:y(sample.missile[axis])})) los.setAttribute(attribute, String(value));
      if (altitude) altitude.textContent = t("air-ui.aircraftMMissileM", "飞机 {{v0}} m · 来弹 {{v1}} m", {v0: fixed(sample.target[2], 0), v1: fixed(sample.missile[2], 0)});
    }
    el("airPlot").setAttribute("aria-label", t("air-ui.secondsSeparationAircraftInBlueMissileInRed", "{{v0}}，{{v1}} 秒，双方距离 {{v2}}。蓝色为飞机，红色为导弹。", {v0: MODES[result.mode], v1: fixed(timeS), v2: distance(sample.rangeM)}));
    el("airTimeValue").textContent = `${fixed(timeS)} s`;
  };
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
    el("airSource").textContent = t("air-ui.airToAirMissileParametersFailedToLoadRefresh", "空空弹参数加载失败，请刷新重试。");
    return;
  }
  el("airSource").textContent = t("air-ui.clientReviewedRadarMissilesIndependentResearchReference", "客户端 {{v0}} · {{v1}} 种已核查雷达弹 · 独立研究参考", {v0: data.version, v1: data.weapons.length});
  el("airWeapon").replaceChildren(...data.weapons.map(weapon => {
    const option = text("option", `${weapon.name} · ${weapon.kind === "ARH" ? t("air-ui.active", "主动") : t("air-ui.semiActive", "半主动")}`);
    option.value = weapon.id; return option;
  }));
  el("airWeapon").value = "us_aim_120a";
  el("airWeapon").disabled = false;
  let results = null, selected = "beam", pending = 0, frame = 0, playbackStart = 0, plot = null, plotVisible = false;
  const weapon = () => data.weapons.find(row => row.id === el("airWeapon").value);
  const input = () => ({ rangeM: number("airRange") * 1000,
    missileSpeedMps: number("airMissileSpeed"), targetSpeedMps: number("airTargetSpeed") / 3.6,
    targetAltitudeM: number("airTargetAltitude"), missileAltitudeM: number("airMissileAltitude"),
    aspectDeg: number("airAspect"), flightPathDeg: number("airFlightPath"), targetG: number("airTargetG"),
    delayS: number("airDelay"), observationGapS: number("airGap"), missileAgeS: number("airAge") });
  const stop = () => { cancelAnimationFrame(frame); frame = 0; el("airPlay").textContent = t("air-ui.play", "▶ 播放"); el("airPlay").setAttribute("aria-label", t("air-ui.playTrajectory", "播放轨迹")); };
  const drawTime = () => { if (results && plot) plot(number("airTime") / 1000 * results[selected].durationS); };
  new IntersectionObserver(([entry]) => {
    plotVisible = entry.isIntersecting;
    if (plotVisible) drawTime();
  }).observe(el("airPlot"));

  function renderLaunch() {
    const w = weapon(), tables = w.envelope?.tables;
    const result = launchReference(w, number("airLaunchAltitude"), number("airLaunchMach"), number("airLaunchTarget"));
    el("airLaunchResult").textContent = result
      ? t("air-ui.conditionalRangeKmMaximumRangeTableDurationS", "条件射程 {{v0}}–{{v1}} km · 最大射程表时长 {{v2}} s", {v0: fixed(result.minRangeM / 1000, 2), v1: fixed(result.maxRangeM / 1000, 1), v2: fixed(result.tableTimeS)})
      : t("air-ui.inputsExceedTheSourceTableCoverageOrATable", "输入超出原表覆盖范围或缺少相应表值，未外推射程。");
    el("airLaunchDomain").textContent = tables?.length
      ? t("air-ui.sourceAltitudeMLaunchAircraftMachTargetEndpointSpeeds", "原表高度 {{v0}} m；载机 Mach {{v1}}；目标两端速度按每行 targetMach 条件。表时长不是当前距离的命中倒计时；高度差／dogfight 分支未计算。", {v0: tables.map(row => fixed(row.altitude_m, 0)).join(" / "), v1: [...new Set(tables.flatMap(row => row.fighter_mach))].join(" / ")})
      : t("air-ui.thisMissileLacksACompleteConditionalTableForThis", "本弹缺少可用于此处的完整条件表。");
  }

  function renderParameters() {
    const w = weapon(), list = document.createElement("dl");
    for (const [label, value] of [
      [t("air-ui.navigationConstant", "比例导引倍率"), String(w.navigationConstant)], [t("air-ui.guidanceCommandLimit", "控制请求上限"), `${w.commandLimitG} g`],
      [t("air-ui.rangeSearchHalfWindow", "距离搜索半窗"), w.rangeSearchHalfM === null ? t("air-ui.rangeObservationDisabled", "未启用距离观测") : `±${w.rangeSearchHalfM} m`],
      [t("air-ui.velocitySearchHalfWindow", "速度搜索半窗"), `±${w.speedSearchHalfMps} m/s`],
      [t("air-ui.angularGateRate", "角门率"), w.angleGateRateDegS === null ? t("air-ui.notConfigured", "未配置") : `${w.angleGateRateDegS} °/s`],
      [t("air-ui.seekerAngleLimit", "导引头角限"), `${w.angleMaxDeg}°`], [t("air-ui.totalMotorStageDuration", "发动机阶段总时长"), `${fixed(w.motorSeconds, 2)} s`],
      [t("air-ui.insDatalinkConfiguration", "惯导 / 数据链配置"), `${w.inertialNavigation ? t("air-ui.yes", "有") : t("air-ui.no", "无")} / ${w.datalink ? t("air-ui.yes2", "有") : t("air-ui.no2", "无")}`],
    ]) { const group = document.createElement("div"); group.append(text("dt", label), text("dd", value)); list.append(group); }
    el("airParameters").replaceChildren(list);
  }

  function selectResult(mode) {
    if (!results) return;
    stop(); selected = mode; el("airTime").value = "0";
    for (const button of el("airCompare").querySelectorAll("button")) button.setAttribute("aria-pressed", String(button.dataset.mode === mode));
    const result = results[mode], w = weapon();
    const stats = document.createElement("dl");
    for (const [label, value] of [[t("air-ui.closestModeledApproach", "模型最近距离"), distance(result.nearestM)],
      [t("air-ui.timeOfClosestApproach", "最近接近时刻"), `${fixed(result.nearestTimeS)} s`],
      [t("air-ui.timeAtCommandLimit", "指令限幅累计"), `${fixed(result.saturatedS)} s`]]) {
      const group = document.createElement("div"); group.append(text("dt", label), text("dd", value)); stats.append(group);
    }
    el("airResult").replaceChildren(stats, text("p", t("air-ui.initialClosingSpeedMSTargetGroundRadialProjection", "初始接近 {{v0}} m/s · 目标对地径向投影 {{v1}} m/s · 指令峰值 {{v2}} g", {v0: fixed(result.initial.closingMps, 0), v1: fixed(result.initial.targetRadialMps), v2: fixed(result.peakRequestedG)}), "tool-note"));
    if (result.initialLeadTimeS === null) el("airResult").append(text("p", t("air-ui.theseSpeedsDoNotPermitAConstantSpeedIntercept", "当前速度组合无法建立匀速交会提前量，来弹从直指飞机初始位置开始。"), "tool-note"));
    el("airAdvice").textContent = result.reason === "ground"
      ? t("air-ui.theTrajectoryReachedTheGroundAndWasTruncatedDo", "轨迹触及地面，计算已截断；此结果不能作为躲弹方案。")
      : mode === "beam" ? t("air-ui.beamingAttemptsToDisruptObservationIfObservationsRemainAvailable", "39 争取干扰观测。本场景若仍有观测或旧预测仍正确，横向飞行可以保持碰撞航向。")
        : mode === "cold" ? t("air-ui.turningColdChangesClosingConditionsMissileEnergyLossIs", "转冷改变接近条件。此处不模拟导弹耗能，因此不能用最近距离判定拖弹成功；越晚开始，留给转向的时间越少。")
          : t("air-ui.divingChangesTheInterceptPlaneAndForcesCorrectionsThe", "下切改变原交会平面，迫使导弹修正。这里的 30° 是对照动作，不是最佳俯冲角；实际还取决于速度损失、控制响应和地形。");
    if (result.reason === "horizon") el("airAdvice").append(t("air-ui.onlyTheFirst30SecondsAreModeledLaterEncounters", " 仅计算前 30 秒，较晚交会未覆盖。"));
    if (result.reason === "lifetime") el("airAdvice").append(t("air-ui.configuredLifetimeReachedTheModelStopsHereThisDoes", " 已到配置寿命，模型在此截断；不是实战自毁时机保证。"));
    const recovery = result.recovery;
    el("airRecovery").replaceChildren();
    if (number("airGap") > 0) {
      if (!recovery) el("airRecovery").append(text("p", t("air-ui.theTrajectoryEndedBeforeTheAssumedObservationRecoverySo", "本次轨迹在假设恢复观测前已结束，未计算恢复时的候选误差。")));
      else {
        el("airRecovery").append(text("p", t("air-ui.atAssumedObservationRecoveryOldPredictionPositionErrorLine", "假设恢复观测时：旧预测位置误差 {{v0}}，视线方向差 {{v1}}°。", {v0: distance(recovery.positionErrorM), v1: fixed(recovery.angleResidualDeg, 2)})));
        if (recovery.comparable) {
          const rangeInside = w.rangeSearchHalfM !== null && Math.abs(recovery.rangeResidualM) <= w.rangeSearchHalfM;
          const speedInside = Math.abs(recovery.speedResidualMps) <= w.speedSearchHalfMps;
          el("airRecovery").append(text("p", t("air-ui.rangeResidualMTheSearchHalfWindowVelocityResidual", "距离残差 {{v0}} m（{{v1}}搜索半窗内）；速度残差 {{v2}} m/s（{{v3}}搜索半窗内）。仅比较单站直线外推候选，不判定真实重捕。", {v0: fixed(recovery.rangeResidualM), v1: rangeInside ? t("air-ui.inside", "在") : t("air-ui.outside", "不在"), v2: fixed(recovery.speedResidualMps), v3: speedInside ? t("air-ui.inside2", "在") : t("air-ui.outside2", "不在")})));
        } else el("airRecovery").append(text("p", t("air-ui.illuminatorStateIsMissingForSemiActiveMissilesMonostatic", "半主动弹缺少照射端状态，未用单站几何代替双站距离／速度门。")));
      }
    }
    plot = createEncounterPlot(result); drawTime();
  }

  function calculate() {
    pending = 0; stop();
    const value = input();
    el("airAspectValue").textContent = `${value.aspectDeg}°${value.aspectDeg === 90 ? t("air-ui.lateral", " · 横向") : ""}`;
    renderLaunch(); renderParameters();
    const error = form.checkValidity() ? validateEncounter(value, weapon()) : t("air-ui.completeAllValuesWithinTheIndicatedRanges", "请在标示范围内填写完整数值。");
    el("airPlay").disabled = Boolean(error); el("airTime").disabled = Boolean(error);
    if (error) {
      results = null; plot = null; el("airResult").replaceChildren(text("p", error)); el("airCompare").replaceChildren();
      el("airPlot").replaceChildren(); el("airAdvice").textContent = ""; el("airRecovery").replaceChildren(); return;
    }
    results = Object.fromEntries(Object.keys(MODES).map(mode => [mode, simulateEncounter(weapon(), value, mode)]));
    el("airCompare").replaceChildren(...Object.entries(MODES).map(([mode, title]) => {
      const button = document.createElement("button"); button.type = "button"; button.dataset.mode = mode;
      button.append(text("span", title), text("strong", distance(results[mode].nearestM)), text("small", t("air-ui.closestModeledApproach2", "模型最近距离")));
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
    el("airPlay").textContent = t("air-ui.pause", "Ⅱ 暂停"); el("airPlay").setAttribute("aria-label", t("air-ui.pauseTrajectory", "暂停轨迹"));
    let lastPaint = -Infinity;
    const tick = now => {
      const progress = Math.min(1000, (now - playbackStart) / results[selected].durationS);
      if (now - lastPaint >= 50 || progress >= 1000) {
        el("airTime").value = String(progress);
        if (plotVisible) drawTime();
        lastPaint = now;
      }
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
  document.addEventListener("calculator:language", () => {
    el("airSource").textContent = t("air-ui.clientReviewedRadarMissilesIndependentResearchReference", "客户端 {{v0}} · {{v1}} 种已核查雷达弹 · 独立研究参考", {v0: data.version, v1: data.weapons.length});
    for (const option of el("airWeapon").options) {
      const weapon = data.weapons.find(row => row.id === option.value);
      option.textContent = `${weapon.name} · ${weapon.kind === "ARH" ? t("air-ui.active", "主动") : t("air-ui.semiActive", "半主动")}`;
    }
    calculate();
  });
  calculate();
}
