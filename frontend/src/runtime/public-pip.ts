import type { EditionSnapshot } from "./runtime-types";
import { FlightInstruments } from "./flight-instruments";
import { createPipMapToggle, updatePipMapToggle } from "./pip-map-toggle";
import { PublicNavigationMap } from "./public-pip-mini-map";
import stylesheetURL from "../public-styles.css?url";
import { WindowClock } from "./window-clock";
import { readPipMapVisible, savePipMapVisible } from "./pip-map-preference";
import type { FlightStatusPresentation } from "./flight-status-badges";

interface PipApi { readonly window: Window | null; requestWindow(options: { width: number; height: number }): Promise<Window> }
export class PublicPictureInPicture {
  #view: Window | null = null;
  #instruments: FlightInstruments | null = null;
  #map: PublicNavigationMap | null = null;
  readonly #select: (id: string) => void;
  readonly #cycle: () => void;
  readonly #visibility: (visible: boolean) => void;
  readonly #basemap: PublicNavigationMap;
  readonly #clock = new WindowClock(() => this.#view && !this.#view.closed ? this.#view : window);
  #mapVisible = readPipMapVisible("Standard");
  #snapshot: EditionSnapshot | null = null;
  #latestFlightStatus: FlightStatusPresentation | null = null;
  constructor(select: (id: string) => void, cycle: () => void, visibility: (visible: boolean) => void, basemap: PublicNavigationMap) { this.#select = select; this.#cycle = cycle; this.#visibility = visibility; this.#basemap = basemap; }
  wait(milliseconds: number, signal?: AbortSignal): Promise<void> { return this.#clock.wait(milliseconds, signal); }
  setMapVisible(visible: boolean): void {
    this.#mapVisible = visible; savePipMapVisible("Standard", visible); this.#visibility(visible);
    const doc = this.#view?.document;
    doc?.querySelector(".pip-cockpit")?.classList.toggle("has-mini-map", visible);
    const map = doc?.querySelector<HTMLElement>(".pip-mini-map"); if (map) map.hidden = !visible;
    const toggle = doc?.querySelector<HTMLButtonElement>("#pip-map-toggle");
    if (toggle) updatePipMapToggle(toggle, visible);
    if (this.#snapshot && this.#latestFlightStatus) this.update(this.#snapshot, this.#latestFlightStatus);
  }
  async toggle(snapshot: EditionSnapshot, flightStatus: FlightStatusPresentation): Promise<void> {
    if (this.#view && !this.#view.closed) { this.#view.close(); return; }
    this.#snapshot = snapshot;
    this.#latestFlightStatus = flightStatus;
    const api = (window as Window & { documentPictureInPicture?: PipApi }).documentPictureInPicture;
    if (!window.isSecureContext || !api) throw new Error("此浏览器不支持置顶导航窗，请用桌面 Edge / Chrome 的 HTTPS 页面。");
    const view = await api.requestWindow({ width: this.#mapVisible ? 910 : 720, height: 188 });
    this.#view = view;
    view.addEventListener("pagehide", () => {
      if (this.#view !== view) return;
      this.#instruments?.close(); this.#map?.close(); this.#instruments = null; this.#map = null; this.#view = null; this.#clock.wake();
    }, { once: true });
    const doc = view.document;
    const css = doc.createElement("link"); css.rel = "stylesheet"; css.href = stylesheetURL;
    const stylesheetLoaded = new Promise<void>((resolve) => { css.onload = () => resolve(); css.onerror = () => resolve(); });
    doc.head.append(css);
    doc.title = "Bomana · 置顶导航窗"; doc.body.className = "public-pip";
    doc.documentElement.lang = "zh-CN";
    doc.body.innerHTML = `<main class="pip-cockpit"><div class="pip-instruments-slot"></div><section class="pip-mini-map"><canvas></canvas></section></main>`;
    this.#instruments = new FlightInstruments(doc.querySelector<HTMLElement>(".pip-instruments-slot")!, {
      onCycleTarget: this.#cycle,
      trailingAction: createPipMapToggle(doc, () => this.setMapVisible(!this.#mapVisible)),
    });
    await Promise.race([stylesheetLoaded, new Promise<void>((resolve) => window.setTimeout(resolve, 1500))]);
    if (view.closed || this.#view !== view) return;
    this.#map = new PublicNavigationMap(doc.querySelector<HTMLCanvasElement>(".pip-mini-map canvas")!, this.#select, this.#basemap);
    this.setMapVisible(this.#mapVisible);
    if (this.#snapshot && this.#latestFlightStatus) this.update(this.#snapshot, this.#latestFlightStatus);
    this.#clock.wake();
  }
  update(snapshot: EditionSnapshot, flightStatus: FlightStatusPresentation): void {
    this.#snapshot = snapshot;
    this.#latestFlightStatus = flightStatus;
    if (!this.#view || this.#view.closed) return;
    this.#instruments?.update(snapshot, flightStatus);
    if (this.#mapVisible) this.#map?.update(snapshot);
  }
}
