const ns = "http://www.w3.org/2000/svg";
const number = value => value.toLocaleString("zh-CN", { maximumFractionDigits: 2 });
const axisNumber = value => value.toLocaleString("zh-CN", { notation: "compact", maximumFractionDigits: 1 });

function element(tag, attributes = {}, text) {
  const node = document.createElementNS(ns, tag);
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, String(value));
  if (text !== undefined) node.textContent = text;
  return node;
}

function canvas(container, height, description) {
  container.replaceChildren();
  container.setAttribute("role", "img");
  container.setAttribute("aria-label", description);
  // Use the rendered width so phone labels stay at 12px instead of shrinking.
  const width = Math.max(180, Math.floor(container.clientWidth));
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

export function renderRewardChart(container, curve, emptyText) {
  if (!curve) {
    container.replaceChildren(); container.setAttribute("aria-label", emptyText);
    const note = document.createElement("p"); note.className = "chart-empty"; note.textContent = emptyText;
    container.append(note); return;
  }
  const { points, current, hasLanding } = curve;
  const { svg, width } = canvas(container, 240,
    `历史得分与 SL 参考曲线，${points[0].score} 至 ${points.at(-1).score} 分。${current ? `当前 ${number(current.score)} 分，即时约 ${number(current.immediate)} SL${hasLanding ? `，含成功着陆份额约 ${number(current.total)} SL` : ""}。` : "当前得分没有可用样本。"}`);
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
  svg.append(element("text", { x: left, y: 16 }, "收益 · SL"));
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
  legend(container, [["即时收益", "legend-immediate"], ...(hasLanding ? [["成功着陆后追加", "legend-landing"]] : []), ["灰区无样本", "legend-unknown"]]);
}

export function renderConversionChart(container, result, sourceCount) {
  const { svg, width } = canvas(container, 200,
    `${number(sourceCount)} 枚 A：${number(result.sourceTotal)} kg TNT；${number(result.wholeCount)} 枚 B：${number(result.targetTotal)} kg TNT。取整后多出 ${number(result.surplus)} kg TNT。`);
  const left = 8, right = width - 8, maximum = Math.max(result.sourceTotal, result.targetTotal);
  const x = value => left + (maximum > 0 ? value / maximum : 0) * (right - left);
  const defs = element("defs"), pattern = element("pattern", { id: "charge-surplus", width: 6, height: 6, patternUnits: "userSpaceOnUse", patternTransform: "rotate(45)" });
  pattern.append(element("rect", { width: 6, height: 6, fill: "#e8cfa1" }), element("line", { x1: 0, x2: 0, y1: 0, y2: 6, stroke: "#997131", "stroke-width": 2 }));
  defs.append(pattern); svg.append(defs);
  for (const [label, count, value, py, style] of [["A", sourceCount, result.sourceTotal, 43, "chart-bar-a"], ["B", result.wholeCount, result.targetTotal, 116, "chart-bar-b"]]) {
    svg.append(element("text", { x: left, y: py - 14 }, `${label} · ${number(count)} 枚`),
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
  legend(container, [["总 TNT 当量 · 同一刻度", "legend-immediate"], ["斜纹：整枚取整余量", "legend-surplus"]]);
}
