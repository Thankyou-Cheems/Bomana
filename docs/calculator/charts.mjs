import { t, numberLocale } from "./i18n.mjs";
const ns = "http://www.w3.org/2000/svg";
const number = value => value.toLocaleString(numberLocale(), { maximumFractionDigits: 2 });
const axisNumber = value => value.toLocaleString(numberLocale(), { notation: "compact", maximumFractionDigits: 1 });

function element(tag, attributes = {}, text) {
  const node = document.createElementNS(ns, tag);
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, String(value));
  if (text !== undefined) node.textContent = text;
  return node;
}

function canvas(container, height, description, minimumWidth = 180) {
  container.replaceChildren();
  container.setAttribute("role", "img");
  container.setAttribute("aria-label", description);
  // Use the rendered width so phone labels stay at 12px instead of shrinking.
  const width = Math.max(minimumWidth, Math.floor(container.clientWidth));
  const svg = element("svg", { viewBox: `0 0 ${width} ${height}`, "aria-hidden": "true" });
  container.append(svg);
  return { svg, width };
}

function legend(container, items) {
  const list = document.createElement("div"); list.className = "chart-legend";
  for (const [label, style] of items) {
    const item = document.createElement("span"); item.className = style; item.textContent = label; list.append(item);
  }
  container.append(list);
}

export function renderAirportRepairChart(container, data) {
  if (!data) { container.replaceChildren(); container.removeAttribute("aria-label"); return; }
  const { result, points, percent } = data;
  const { svg, width } = canvas(container, 230,
    t("charts.livingQuartersHpAndPerVisitRepairBranchBelow", "生活区耐久与单次分支回血曲线。不足 1% 与 100% 均跳过，当前 {{v0}}%：每模块 {{v1}} HP。", {v0: percent, v1: number(result.gain)}));
  const left = 48, right = width - 30, top = 30, bottom = 184;
  const x = value => left + value / 100 * (right - left);
  const y = value => bottom - value / (result.base * 1.1) * (bottom - top);
  for (const fraction of [0, .5, 1]) {
    const value = result.base * fraction;
    svg.append(element("line", { x1: left, x2: right, y1: y(value), y2: y(value), class: "chart-grid" }),
      element("text", { x: left - 7, y: y(value) + 4, "text-anchor": "end" }, axisNumber(value)));
  }
  svg.append(element("text", { x: left, y: 16 }, t("charts.incrementPerVisitHpModule", "单次加值 · HP / 模块")));
  for (const value of [0, 50, 100]) svg.append(element("text", { x: x(value), y: 207, "text-anchor": "middle" }, `${value}%`));
  const curve = [...points, { percent: 100, gain: result.base * (result.maximum + 1) / result.maximum }];
  svg.append(element("polyline", { points: curve.map(point => `${x(point.percent)},${y(point.gain)}`).join(" "), class: "chart-immediate-line" }));
  for (const point of [{ percent: 1, gain: 0 }, curve.at(-1)]) svg.append(element("circle", {
    cx: x(point.percent), cy: y(point.gain), r: 4, class: "repair-open-end",
  }));
  for (const value of [0, 100]) svg.append(element("circle", { cx: x(value), cy: y(0), r: 4, class: "chart-sample" }));
  svg.append(element("circle", { cx: x(1), cy: y(curve[0].gain), r: 4, class: "chart-sample" }));
  svg.append(element("circle", { cx: x(percent), cy: y(result.gain), r: 6, class: "chart-current", "data-repair-gain": result.gain }));
  legend(container, [[t("charts.horizontalAxisLivingQuartersHpRemaining", "横轴：生活区剩余耐久"), "legend-immediate"], [t("charts.below1AndFullHpAreSkippedHollowPoints", "不足 1% 与满血跳过；空心点不含端点"), "legend-unknown"]]);
}

export function renderAirportBars(container, positions, angleDegrees) {
  if (!positions) { container.replaceChildren(); container.textContent = t("charts.noVerifiedBarPositionsAvailable", "当前没有已核对的条带位置。"); return; }
  const { svg, width } = canvas(container, 176, t("charts.fourAirfieldModulePositionsArrowRunsFromStartTo", "机场四模块位置；箭头从起点指向终点，不是实时血量。"), 110);
  const scale = Math.min(47, width * .32), cx = width / 2, cy = 88;
  const angle = angleDegrees * Math.PI / 180, dx = Math.cos(angle), dy = Math.sin(angle);
  const x = value => cx + value * scale, y = value => cy + value * scale;
  svg.append(element("line", { x1: x(-dx), y1: y(-dy), x2: x(dx), y2: y(dy), class: "airport-runway" }));
  svg.append(element("polygon", { points: `${x(dx)},${y(dy)} ${x(dx)-dx*11-dy*5},${y(dy)-dy*11+dx*5} ${x(dx)-dx*11+dy*5},${y(dy)-dy*11-dx*5}`, class: "airport-arrow" }));
  for (const [label, sign] of [[t("charts.start", "起点"), -1], [t("charts.end", "终点"), 1]]) svg.append(element("text", {
    x: x(sign * dx * .55), y: y(sign * dy * .55) + 5, "text-anchor": "middle", class: "airport-endpoint",
  }, label));
  const labels = { airfield: t("charts.runway", "跑道"), storage: t("charts.fuelStorage", "油库"), parking: t("charts.parking", "停机区"), dwelling: t("charts.livingQuarters", "生活区") };
  for (const position of positions) {
    const px = x(position.x), py = y(position.y);
    svg.append(element("line", { x1: px - dx * 12, y1: py - dy * 12, x2: px + dx * 12, y2: py + dy * 12,
      class: "airport-module-bar", "data-module": position.module }));
    svg.append(element("text", { x: px, y: py + (position.y < 0 ? -18 : 27), "text-anchor": "middle" }, labels[position.module]));
  }
}

export function renderRewardChart(container, curve, emptyText) {
  if (!curve) {
    container.replaceChildren(); container.setAttribute("aria-label", emptyText);
    const note = document.createElement("p"); note.className = "chart-empty"; note.textContent = emptyText;
    container.append(note); return;
  }
  const { points, current, hasLanding } = curve;
  const { svg, width } = canvas(container, 240,
    t("charts.historicalScoreSlReferenceCurvePoints", "历史得分与 SL 参考曲线，{{v0}} 至 {{v1}} 分。{{v2}}", {v0: points[0].score, v1: points.at(-1).score, v2: current ? t("charts.currentPointsApproximatelyImmediateSl", "当前 {{v0}} 分，即时约 {{v1}} SL{{v2}}。", {v0: number(current.score), v1: number(current.immediate), v2: hasLanding ? t("charts.approximatelySlIncludingSuccessfulLanding", "，含成功着陆份额约 {{v0}} SL", {v0: number(current.total)}) : ""}) : t("charts.noSamplesAvailableForThisScore", "当前得分没有可用样本。")}));
  const left = 48, right = width - 18, top = 28, bottom = 204;
  const maximum = Math.max(...points.map(point => point.total));
  const rawStep = maximum / 3 || 1, magnitude = 10 ** Math.floor(Math.log10(rawStep));
  const step = Math.ceil(rawStep / magnitude) * magnitude, yMax = step * 3;
  const x = score => left + score / 1200 * (right - left);
  const y = value => bottom - value / yMax * (bottom - top);
  for (const [start, end] of [[0, points[0].score], [points.at(-1).score, 1200]]) {
    svg.append(element("rect", { x: x(start), y: top, width: x(end) - x(start), height: bottom - top, class: "chart-unknown" }));
  }
  for (let index = 0; index <= 3; index++) {
    const value = step * index, py = y(value);
    svg.append(element("line", { x1: left, y1: py, x2: right, y2: py, class: "chart-grid" }),
      element("text", { x: left - 7, y: py + 4, "text-anchor": "end" }, axisNumber(value)));
  }
  svg.append(element("text", { x: left, y: 16 }, t("charts.rewardSl", "收益 · SL")));
  for (const score of [0, 400, 800, 1200]) svg.append(element("text", { x: x(score), y: 225, "text-anchor": "middle" }, String(score)));
  const line = key => points.map(point => `${x(point.score)},${y(point[key])}`).join(" ");
  svg.append(element("polygon", { points: `${x(points[0].score)},${bottom} ${line("immediate")} ${x(points.at(-1).score)},${bottom}`, class: "chart-immediate-area" }));
  if (hasLanding) svg.append(element("polygon", { points: `${line("total")} ${[...points].reverse().map(point => `${x(point.score)},${y(point.immediate)}`).join(" ")}`, class: "chart-landing-area" }),
    element("polyline", { points: line("total"), class: "chart-landing-line" }));
  svg.append(element("polyline", { points: line("immediate"), class: "chart-immediate-line" }));
  for (const point of points) svg.append(element("circle", { cx: x(point.score), cy: y(point.immediate), r: 3, class: "chart-sample" }));
  if (current) {
    svg.append(element("line", { x1: x(current.score), x2: x(current.score), y1: top, y2: bottom, class: "chart-current-line" }),
      element("circle", { cx: x(current.score), cy: y(current.immediate), r: 6, class: "chart-current", "data-score": current.score, "data-immediate": current.immediate }));
    if (hasLanding) svg.append(element("circle", { cx: x(current.score), cy: y(current.total), r: 4, class: "chart-current-landing" }));
  }
  legend(container, [[t("charts.immediateReward", "即时收益"), "legend-immediate"], ...(hasLanding ? [[t("charts.additionalAfterLanding", "成功着陆后追加"), "legend-landing"]] : []), [t("charts.noSamplesInGrayAreas", "灰区无样本"), "legend-unknown"]]);
}

export function renderConversionChart(container, result, sourceCount) {
  const { svg, width } = canvas(container, 200,
    t("charts.ofAKgTntOfBKgTntRounding", "{{v0}} 枚 A：{{v1}} kg TNT；{{v2}} 枚 B：{{v3}} kg TNT。取整后多出 {{v4}} kg TNT。", {v0: number(sourceCount), v1: number(result.sourceTotal), v2: number(result.wholeCount), v3: number(result.targetTotal), v4: number(result.surplus)}));
  const left = 8, right = width - 8, maximum = Math.max(result.sourceTotal, result.targetTotal);
  const x = value => left + (maximum > 0 ? value / maximum : 0) * (right - left);
  const defs = element("defs"), pattern = element("pattern", { id: "charge-surplus", width: 6, height: 6, patternUnits: "userSpaceOnUse", patternTransform: "rotate(45)" });
  pattern.append(element("rect", { width: 6, height: 6, fill: "#e8cfa1" }), element("line", { x1: 0, x2: 0, y1: 0, y2: 6, stroke: "#997131", "stroke-width": 2 }));
  defs.append(pattern); svg.append(defs);
  for (const [label, count, value, py, style] of [["A", sourceCount, result.sourceTotal, 43, "chart-bar-a"], ["B", result.wholeCount, result.targetTotal, 116, "chart-bar-b"]]) {
    svg.append(element("text", { x: left, y: py - 14 }, t("charts.weapons", "{{v0}} · {{v1}} 枚", {v0: label, v1: number(count)})),
      element("text", { x: right, y: py - 14, "text-anchor": "end" }, `${number(value)} kg TNT`),
      element("rect", { x: left, y: py, width: right - left, height: 25, rx: 5, class: "chart-bar-track" }),
      element("rect", { x: left, y: py, width: x(value) - left, height: 25, rx: 5, class: style, "data-total": value }));
  }
  if (result.surplus > 0) svg.append(element("rect", { x: x(result.sourceTotal), y: 116, width: x(result.targetTotal) - x(result.sourceTotal), height: 25, fill: "url(#charge-surplus)", "data-surplus": result.surplus }));
  for (const fraction of [0, .5, 1]) {
    const px = left + fraction * (right - left);
    svg.append(element("line", { x1: px, x2: px, y1: 157, y2: 162, class: "chart-grid" }),
      element("text", { x: px, y: 181, "text-anchor": fraction === 0 ? "start" : fraction === 1 ? "end" : "middle" }, axisNumber(maximum * fraction)));
  }
  legend(container, [[t("charts.totalTntEquivalenceSharedScale", "总 TNT 当量 · 同一刻度"), "legend-immediate"], [t("charts.hatchingWholeWeaponRoundingSurplus", "斜纹：整枚取整余量"), "legend-surplus"]]);
}
