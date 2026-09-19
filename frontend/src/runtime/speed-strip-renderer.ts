import type { EditionSnapshot } from "./runtime-types";
import { overspeedDynamicProjection } from "./overspeed-scale";
import { speedWarningLevel } from "./speed-warning";

export interface SpeedStripPresentation {
  readonly levelClass: "safe" | "caution" | "warning" | "critical";
  readonly stateText: string;
  readonly valueText: string;
  readonly machText: string;
  readonly detail: string;
  readonly limitsKnown: boolean;
  readonly fillPercent: number;
  readonly markerPercents: readonly [number, number, number];
  readonly visualScale: number;
}

export interface SpeedStripElements {
  readonly root: HTMLElement;
  readonly state: HTMLElement;
  readonly value: HTMLElement;
  readonly mach: HTMLElement;
  readonly track: HTMLElement;
  readonly fill: HTMLElement;
  readonly markers: readonly [HTMLElement, HTMLElement, HTMLElement];
}

export function speedStripPresentation(snapshot: EditionSnapshot): SpeedStripPresentation {
  const overspeed = snapshot.flight.overspeed;
  const matched = snapshot.connected !== false && overspeed.matched;
  const machRatio = snapshot.flight.mach !== null && overspeed.machLimit > 0
    ? snapshot.flight.mach / overspeed.machLimit
    : 0;
  const speedRatio = Math.max(overspeed.ratio, machRatio);
  const projection = overspeedDynamicProjection(speedRatio);
  const level = matched ? speedWarningLevel(speedRatio) : "none";
  const levelClass = level === "none" ? "safe" : level;
  const stateText = matched
    ? { none: overspeed.iasLimitSource === "flaps" ? "襟翼参考" : overspeed.estimated ? "保守限速" : "限速参考", caution: "预警", warning: "减速", critical: "超限" }[level]
    : "";
  const valueText = matched && overspeed.iasLimitKmh > 0
    ? `IAS ${Math.round(snapshot.flight.iasKmh)}/${Math.round(overspeed.iasLimitKmh)}`
    : `IAS ${snapshot.connected === false ? "—" : Math.round(snapshot.flight.iasKmh)}`;
  const mach = snapshot.flight.mach !== null && overspeed.machLimit > 0
    ? `M${snapshot.flight.mach.toFixed(2)}/${overspeed.machLimit.toFixed(2)}` : "";
  const percent = speedRatio < 1 ? Math.min(99.9, Math.round(speedRatio * 1000) / 10) : Math.round(speedRatio * 1000) / 10;
  const machText = matched ? `${percent}%${mach ? ` · ${mach}` : ""}` : "";
  const detail = matched
    ? `IAS：当前指示空速 / ${overspeed.iasLimitSource === "flaps" ? "当前襟翼构型的原生参考限速" : "原生 VNE"}（km/h）；Mach 对照原生 MNE。取两项较高比例：90% 预警、95% 减速、100% 超限。前两档是提前提醒，100% 采用保守的原生限速基准，不追加随机损坏宽限。它不是所有载荷和战损下的最低断裂速度。右端 110% 仅为显示范围。${overspeed.estimated ? "后掠角未知，当前采用曲线中的最低限速。" : ""}`
    : "IAS 为指示空速（km/h）。当前未匹配机型限速，因此不显示限速刻度。";
  return Object.freeze({
    levelClass,
    stateText,
    valueText,
    machText,
    detail,
    limitsKnown: matched,
    fillPercent: matched ? Math.min(100, projection.fillRatio * 100) : 0,
    markerPercents: Object.freeze(projection.markerRatios.map((ratio) => Number((ratio * 100).toFixed(3)))) as unknown as readonly [number, number, number],
    visualScale: projection.visualScale,
  });
}

export class SpeedStripRenderer {
  readonly #elements: SpeedStripElements;

  constructor(elements: SpeedStripElements) { this.#elements = elements; }

  update(snapshot: EditionSnapshot): void {
    const presentation = speedStripPresentation(snapshot);
    this.#elements.root.classList.remove("level-safe", "level-caution", "level-warning", "level-critical", "level-unknown");
    this.#elements.root.classList.add("speed-strip", `level-${presentation.levelClass}`);
    this.#elements.state.textContent = presentation.stateText;
    this.#elements.state.hidden = !presentation.stateText;
    this.#elements.value.textContent = presentation.valueText;
    this.#elements.mach.textContent = presentation.machText;
    this.#elements.mach.hidden = !presentation.machText;
    this.#elements.root.title = presentation.detail;
    this.#elements.track.hidden = !presentation.limitsKnown;
    this.#elements.fill.style.width = `${presentation.fillPercent}%`;
    this.#elements.track.style.setProperty("--speed-scale", presentation.visualScale.toFixed(3));
    this.#elements.track.style.setProperty("--speed-caution", `${presentation.markerPercents[0]}%`);
    this.#elements.track.style.setProperty("--speed-warning", `${presentation.markerPercents[1]}%`);
    this.#elements.track.style.setProperty("--speed-limit", `${presentation.markerPercents[2]}%`);
    for (let index = 0; index < this.#elements.markers.length; index += 1) {
      this.#elements.markers[index]!.style.left = `${presentation.markerPercents[index]}%`;
    }
  }
}
