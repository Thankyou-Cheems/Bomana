import type { EditionSnapshot } from "./runtime-types";
import { landingPresentation } from "./landing-presentation";
import { PictureInPictureHeadingRenderer } from "./pip-heading-renderer";
import { PublicNavigationMap } from "./public-pip-mini-map";
import { SpeedStripRenderer } from "./speed-strip-renderer";
import stylesheetURL from "../public-styles.css?url";
import { WindowClock } from "./window-clock";
import { readPipMapVisible, savePipMapVisible } from "./pip-map-preference";
import { FlightStatusBadgeRenderer, type FlightStatusPresentation } from "./flight-status-badges";

interface PipApi { readonly window: Window | null; requestWindow(options: { width: number; height: number }): Promise<Window> }
export class PublicPictureInPicture {
  #view: Window | null = null;
  #heading: PictureInPictureHeadingRenderer | null = null;
  #map: PublicNavigationMap | null = null;
  #speed: SpeedStripRenderer | null = null;
  #badges: FlightStatusBadgeRenderer | null = null;
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
    doc?.querySelector("#pip-map-toggle")?.setAttribute("aria-pressed", String(visible));
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
      this.#heading?.close(); this.#map?.close(); this.#heading = null; this.#map = null; this.#speed = null; this.#badges = null; this.#view = null; this.#clock.wake();
    }, { once: true });
    const doc = view.document;
    const css = doc.createElement("link"); css.rel = "stylesheet"; css.href = stylesheetURL;
    const stylesheetLoaded = new Promise<void>((resolve) => { css.onload = () => resolve(); css.onerror = () => resolve(); });
    doc.head.append(css);
    doc.title = "Bomana · 置顶导航窗"; doc.body.className = "public-pip";
    const shell = doc.createElement("main"); shell.className = "pip-cockpit";
    const primary = doc.createElement("section"); primary.className = "pip-primary";
    const headingPanel = doc.createElement("section"); headingPanel.className = "pip-heading";
    const heading = doc.createElement("canvas");
    const headingValue = doc.createElement("strong"); headingValue.id = "pip-heading-value"; headingValue.className = "public-heading-value";
    headingPanel.append(heading, headingValue);
    const summary = doc.createElement("div"); summary.className = "pip-header";
    const brand = doc.createElement("strong"); brand.textContent = "BOMANA";
    const flight = doc.createElement("small"), gear = doc.createElement("small");
    this.#badges = new FlightStatusBadgeRenderer({ flight, gear });
    const status = doc.createElement("span"); status.dataset.status = "true";
    const cycle = doc.createElement("button"); cycle.className = "pip-cycle-target"; cycle.textContent = "切换目标"; cycle.onclick = this.#cycle;
    const toggle = doc.createElement("button"); toggle.id = "pip-map-toggle"; toggle.textContent = "小地图";
    toggle.onclick = () => this.setMapVisible(!this.#mapVisible);
    summary.append(brand, status, flight, gear, cycle, toggle);
    const landing = doc.createElement("span"); landing.className = "public-landing-compact"; landing.dataset.landing = "true"; summary.append(landing);
    const strip = document.getElementById("speed-strip")!.cloneNode(true) as HTMLElement;
    const part = (id: string) => strip.querySelector<HTMLElement>(`#${id}`)!;
    this.#speed = new SpeedStripRenderer({ root: strip, state: part("overspeed"), value: part("speed-limit-value"), mach: part("speed-limit-mach"), track: part("speed-track"), fill: part("speed-fill"), markers: [part("speed-caution-mark"), part("speed-warning-mark"), part("speed-critical-mark")] });
    const mapPanel = doc.createElement("section"); mapPanel.className = "pip-mini-map";
    const map = doc.createElement("canvas"); mapPanel.append(map);
    primary.append(summary, headingPanel, strip); shell.append(primary, mapPanel); doc.body.append(shell);
    await Promise.race([stylesheetLoaded, new Promise<void>((resolve) => window.setTimeout(resolve, 1500))]);
    if (view.closed || this.#view !== view) return;
    this.#heading = new PictureInPictureHeadingRenderer({ view, canvas: heading });
    this.#map = new PublicNavigationMap(map, this.#select, this.#basemap);
    this.setMapVisible(this.#mapVisible);
    if (this.#snapshot && this.#latestFlightStatus) this.update(this.#snapshot, this.#latestFlightStatus);
    this.#clock.wake();
  }
  update(snapshot: EditionSnapshot, flightStatus: FlightStatusPresentation): void {
    this.#snapshot = snapshot;
    this.#latestFlightStatus = flightStatus;
    if (!this.#view || this.#view.closed) return;
    this.#view.document.querySelector(".pip-cockpit")?.classList.toggle("is-landing", snapshot.landing?.settings.enabled === true);
    this.#heading?.update(snapshot); if (this.#mapVisible) this.#map?.update(snapshot);
    this.#badges?.update(flightStatus);
    const headingValue = this.#view.document.getElementById("pip-heading-value");
    if (headingValue) headingValue.textContent = `HDG ${Math.round(snapshot.flight.headingDeg).toString().padStart(3, "0")}°`;
    const status = this.#view.document.querySelector<HTMLElement>("[data-status]");
    const seconds = snapshot.timer.remainingSec === null ? null : Math.max(0, Math.ceil(snapshot.timer.remainingSec));
    if (status) status.textContent = seconds === null ? "--:--" : `${Math.floor(seconds / 60).toString().padStart(2, "0")}:${(seconds % 60).toString().padStart(2, "0")}`;
    this.#speed?.update(snapshot);
    const landing = this.#view.document.querySelector<HTMLElement>("[data-landing]");
    if (landing) { landing.textContent = landingPresentation(snapshot.landing).compact; landing.title = landing.textContent; landing.hidden = !landing.textContent; }
  }
}
