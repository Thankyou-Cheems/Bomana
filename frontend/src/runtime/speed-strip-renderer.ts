import type { EditionSnapshot } from "./runtime-types";
import { overspeedDynamicProjection } from "./overspeed-scale";

export interface SpeedStripPresentation {
  readonly levelClass: "safe" | "caution" | "warning" | "critical";
  readonly stateText: string;
  readonly valueText: string;
  readonly machText: string;
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
  const machRatio = snapshot.flight.mach !== null && overspeed.machLimit > 0
    ? snapshot.flight.mach / overspeed.machLimit
    : 0;
  const speedRatio = Math.max(overspeed.ratio, machRatio);
  const projection = overspeedDynamicProjection(speedRatio);
  const levelClass = overspeed.level === "none" ? "safe" : overspeed.level;
  const stateText = overspeed.matched
    ? { none: overspeed.estimated ? "保守限速" : "速度安全", caution: "高速预警", warning: "接近极限", critical: "超速危险" }[overspeed.level]
    : "速度监视";
  const valueText = overspeed.matched && overspeed.iasLimitKmh > 0
    ? `极限 ${Math.round(speedRatio * 100)}% · IAS ${Math.round(snapshot.flight.iasKmh)}/${Math.round(overspeed.iasLimitKmh)}`
    : `IAS ${Math.round(snapshot.flight.iasKmh) || "--"}`;
  const machText = snapshot.flight.mach !== null && overspeed.machLimit > 0
    ? `M${snapshot.flight.mach.toFixed(2)}/${overspeed.machLimit.toFixed(2)}`
    : overspeed.matched ? snapshot.flight.aircraft : "阈值未匹配";
  return Object.freeze({
    levelClass,
    stateText,
    valueText,
    machText,
    fillPercent: Math.min(100, projection.fillRatio * 100),
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
    this.#elements.value.textContent = presentation.valueText;
    this.#elements.mach.textContent = presentation.machText;
    this.#elements.fill.style.width = `${presentation.fillPercent}%`;
    this.#elements.track.style.setProperty("--speed-scale", presentation.visualScale.toFixed(3));
    this.#elements.track.style.setProperty("--speed-caution", `${presentation.markerPercents[0]}%`);
    this.#elements.track.style.setProperty("--speed-warning", `${presentation.markerPercents[1]}%`);
    this.#elements.track.style.setProperty("--speed-critical", `${presentation.markerPercents[2]}%`);
    for (let index = 0; index < this.#elements.markers.length; index += 1) {
      this.#elements.markers[index]!.style.left = `${presentation.markerPercents[index]}%`;
    }
  }
}
