import type { EditionSnapshot } from "./runtime-types";
import { landingPresentation } from "./landing-presentation";
import { PictureInPictureHeadingRenderer } from "./pip-heading-renderer";
import { headingGuidance, type HeadingTapeTargetInput } from "./heading-tape";
import { SpeedStripRenderer } from "./speed-strip-renderer";
import { FlightStatusBadgeRenderer, type FlightStatusPresentation } from "./flight-status-badges";

export function instrumentElement<T extends Element = HTMLElement>(root: ParentNode, selector: string): T {
  const element = root.querySelector<T>(selector);
  if (!element) throw new Error(`Flight instrument is missing: ${selector}`);
  return element;
}

export function pictureInPictureStatus(snapshot: EditionSnapshot) {
  const target = snapshot.connected ? snapshot.strikeSelection?.target ?? snapshot.navigation?.target ?? null : null;
  const seconds = snapshot.timer.remainingSec === null ? null : Math.max(0, Math.ceil(snapshot.timer.remainingSec));
  return {
    connectionText: snapshot.connected ? "已连接" : "待连接",
    aircraftText: snapshot.flight.aircraft || "机型待识别",
    targetText: target ? `${target.label} · ${target.distanceKm.toFixed(1)} km · ${target.relativeDeg >= 0 ? "+" : ""}${target.relativeDeg.toFixed(1)}°` : null,
    timerText: seconds === null ? "--:--" : `${Math.floor(seconds / 60).toString().padStart(2, "0")}:${(seconds % 60).toString().padStart(2, "0")}`,
    suppressReleasePrompt: !target,
  };
}
export type PictureInPictureStatus = ReturnType<typeof pictureInPictureStatus>;

/** The complete instrument layout. Hosts own window controls and optional maps;
 * editions may add instruments, but never replace the shared layout or renderers. */
export class FlightInstruments {
  readonly root: HTMLElement;
  readonly #heading: PictureInPictureHeadingRenderer;
  readonly #speed: SpeedStripRenderer;
  readonly #badges: FlightStatusBadgeRenderer;
  readonly #resize: ResizeObserver;

  constructor(host: HTMLElement, options: { guidance?: typeof headingGuidance; onCycleTarget?: () => void; trailingAction?: HTMLElement }) {
    const document = host.ownerDocument;
    host.classList.add("flight-instruments-host");
    this.root = document.createElement("section");
    this.root.className = "flight-instruments pip-primary";
    this.root.setAttribute("aria-label", "综合飞行仪表");
    this.root.innerHTML = `
      <header class="pip-header">
        <strong class="pip-timer" id="pip-timer">--:--</strong>
        <strong class="pip-target" id="pip-target" hidden></strong>
        <div class="pip-actions" aria-label="状态与快捷操作">
          <div class="instrument-badges pip-instrument-badges" aria-label="飞行状态"><span class="instrument-badge flight-phase-badge" id="pip-flight-phase-badge" hidden></span><span class="instrument-badge gear-status-badge" id="pip-gear-status-badge" hidden></span></div>
          <details class="pip-aircraft-info" id="pip-aircraft-info" hidden><summary title="点击查看完整机型名称"><span id="pip-aircraft"></span><i aria-hidden="true">ⓘ</i></summary><p id="pip-aircraft-full"></p></details>
          <span class="pip-status-badge" id="pip-limit-status" title="尚未匹配当前机型的速度限制；速度读数仍可显示。" hidden>限速待匹配</span>
          <span class="pip-status-badge" id="pip-connection" role="status">待连接</span>
        </div>
      </header>
      <section class="pip-heading"><canvas id="pip-heading-canvas" aria-label="航向带"></canvas><div class="pip-heading-value"><span>HDG</span><strong id="pip-heading-value">000</strong></div></section>
      <footer class="pip-footer">
        <section class="speed-strip level-safe pip-speed" id="pip-speed-strip" aria-label="超速提示">
          <div class="speed-strip-head"><span class="speed-state" id="pip-speed-state" hidden></span><strong class="speed-value" id="pip-speed-value">IAS —</strong></div>
          <div class="speed-track" id="pip-speed-track" aria-hidden="true" hidden><i id="pip-speed-fill"></i><b class="mark caution" id="pip-speed-caution"></b><b class="mark warning" id="pip-speed-warning"></b><b class="mark critical" id="pip-speed-limit"></b></div>
          <div class="speed-strip-detail"><span id="pip-speed-mach" hidden></span></div>
        </section>
      </footer>`;
    host.replaceChildren(this.root);
    // One coordinate system on every surface; narrow hosts scale the entire
    // panel instead of hiding fields or rearranging individual instruments.
    const fit = () => {
      const scale = Math.min(host.clientWidth / this.root.offsetWidth, host.clientHeight / this.root.offsetHeight);
      this.root.style.transform = `translate(-50%, -50%) scale(${scale})`;
    };
    this.#resize = new ResizeObserver(fit);
    this.#resize.observe(host);
    fit();
    const part = <T extends Element = HTMLElement>(selector: string) => instrumentElement<T>(this.root, selector);
    if (options.onCycleTarget) {
      const cycle = document.createElement("button");
      cycle.type = "button";
      cycle.className = "pip-cycle-target";
      cycle.textContent = "切换目标";
      cycle.title = "点击切换到下一个导航目标";
      cycle.dataset.actionIcon = "↻";
      cycle.addEventListener("click", options.onCycleTarget);
      part(".pip-actions").append(cycle);
    }
    if (options.trailingAction) part(".pip-actions").append(options.trailingAction);
    this.#heading = new PictureInPictureHeadingRenderer({ view: document.defaultView!, canvas: part<HTMLCanvasElement>("canvas"), guidance: options.guidance });
    this.#speed = new SpeedStripRenderer({ root: part("#pip-speed-strip"), state: part("#pip-speed-state"), value: part("#pip-speed-value"), mach: part("#pip-speed-mach"), track: part("#pip-speed-track"), fill: part("#pip-speed-fill"), markers: [part("#pip-speed-caution"), part("#pip-speed-warning"), part("#pip-speed-limit")] });
    this.#badges = new FlightStatusBadgeRenderer({ flight: part("#pip-flight-phase-badge"), gear: part("#pip-gear-status-badge") });
  }

  update(snapshot: EditionSnapshot, flightStatus: FlightStatusPresentation, extraTargets: readonly HeadingTapeTargetInput[] = []): void {
    const status = pictureInPictureStatus(snapshot);
    const set = (selector: string, value: string) => { instrumentElement(this.root, selector).textContent = value; };
    set("#pip-connection", status.connectionText);
    set("#pip-aircraft", status.aircraftText);
    set("#pip-aircraft-full", status.aircraftText);
    const connection = instrumentElement(this.root, "#pip-connection");
    connection.dataset.tone = snapshot.connected ? "connected" : "waiting";
    connection.title = snapshot.connected ? "已接收到游戏遥测数据" : "等待游戏遥测数据，请确认 Bridge 已运行";
    const aircraft = instrumentElement<HTMLDetailsElement>(this.root, "#pip-aircraft-info");
    aircraft.hidden = !snapshot.connected;
    if (!snapshot.connected) aircraft.open = false;
    instrumentElement(aircraft, "summary").title = snapshot.flight.aircraft ? `当前机型：${snapshot.flight.aircraft} · 点击查看全名` : "等待游戏提供机型信息";
    instrumentElement(this.root, "#pip-limit-status").hidden = !snapshot.connected || snapshot.flight.overspeed.matched;
    set("#pip-timer", status.timerText);
    set("#pip-heading-value", Math.round(snapshot.flight.headingDeg).toString().padStart(3, "0"));
    const target = instrumentElement(this.root, "#pip-target");
    target.textContent = landingPresentation(snapshot.landing).compact || status.targetText || "";
    target.title = target.textContent;
    target.hidden = !target.textContent;
    this.root.classList.toggle("is-landing", snapshot.landing?.settings.enabled === true);
    this.#heading.update(snapshot, extraTargets);
    this.#speed.update(snapshot);
    this.#badges.update(flightStatus);
  }

  close(): void { this.#resize.disconnect(); this.#heading.close(); }
}
