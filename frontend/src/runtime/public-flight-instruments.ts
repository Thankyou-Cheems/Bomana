import type { EditionSnapshot } from "./runtime-types";
import type { FlightStatusPresentation } from "./flight-status-badges";
import type { BasemapPainter } from "./basemap-painter";
import { FlightInstruments } from "./flight-instruments";
import { AirRealisticInstruments } from "./air-realistic-instruments";
import { flightDisplayMode, observeFlightDisplayMode } from "./flight-display-mode";
import { flightModeSwitch } from "./flight-mode-switch";

/** Standard composes public instruments directly, without the Enhanced shell. */
export class PublicFlightInstruments {
  readonly #panel: FlightInstruments;
  readonly #air: AirRealisticInstruments;
  readonly #stopMode: () => void;
  #latest: { snapshot: EditionSnapshot; status: FlightStatusPresentation } | null = null;
  constructor(host: HTMLElement, options: { onCycleTarget: () => void; paintBasemap: BasemapPainter; trailingAction?: HTMLElement; airHost?: HTMLElement }) {
    this.#panel = new FlightInstruments(host, options);
    const switcher = flightModeSwitch(host.ownerDocument, "simulator");
    this.#panel.root.querySelector(".pip-header")!.prepend(switcher);
    const airHost = options.airHost ?? host;
    this.#air = new AirRealisticInstruments(airHost, options.paintBasemap);
    this.#stopMode = observeFlightDisplayMode(mode => {
      airHost.classList.toggle("is-air-realistic", mode === "air-realistic");
      host.ownerDocument.body.classList.toggle("air-realistic-mode", mode === "air-realistic");
      // The main page retains its heading tape above the central Air Realistic map.
      for (const button of switcher.querySelectorAll<HTMLButtonElement>("button")) {
        const selected = button.dataset.mode === mode;
        button.setAttribute("aria-pressed", String(selected));
        button.title = `${selected ? "当前：" : "切换到"}${button.textContent}`;
      }
      if (this.#latest) this.update(this.#latest.snapshot, this.#latest.status);
    });
  }
  update(snapshot: EditionSnapshot, status: FlightStatusPresentation): void {
    this.#latest = { snapshot, status };
    if (flightDisplayMode() === "air-realistic") this.#air.update(snapshot);
    if (this.#panel.root.getClientRects().length) this.#panel.update(snapshot, status);
  }
  close(): void { this.#stopMode(); this.#air.close(); this.#panel.close(); }
}
