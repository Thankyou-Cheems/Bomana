import type { EditionSnapshot } from "./runtime-types";
import { speedObservationCurrent } from "./speed-strip-renderer";

export type AirEnergyCue = "up" | "down";

const GRAVITY = 9.80665;
const WINDOW_MS = 2500;
const MIN_SPAN_MS = 1200;
const SHOW_MPS = 18;
const HIDE_MPS = 8;

/** Ownship specific-energy trend from TAS and altitude. Blank unless the
 * change is obvious; a zoom climb that trades speed for height can stay blank. */
export class AirEnergyTrend {
  #key = "";
  #samples: { at: number; es: number }[] = [];
  #shown: AirEnergyCue | null = null;

  reset(): void { this.#samples = []; this.#shown = null; this.#key = ""; }

  observe(snapshot: EditionSnapshot, nowMs: number): AirEnergyCue | null {
    const flight = snapshot.flight;
    const tasKmh = flight.tasKmh;
    const at = snapshot.speedSampledAtMs;
    const live = speedObservationCurrent(snapshot, nowMs)
      && flight.tasObserved !== false
      && !flight.onGround
      && at != null
      && Number.isFinite(at)
      && Number.isFinite(flight.altitudeM)
      && Number.isFinite(tasKmh)
      && tasKmh >= 36;
    if (!live || at == null) { this.reset(); return null; }
    const es = flight.altitudeM + (tasKmh / 3.6) ** 2 / (2 * GRAVITY);
    const key = `${flight.aircraft}\0${snapshot.timer.lifeIndex ?? ""}`;
    const previous = this.#samples[this.#samples.length - 1];
    const broken = key !== this.#key || !previous || at < previous.at || at - previous.at > 1500
      || (Math.abs(es - previous.es) > 250 && at - previous.at < 1000);
    if (broken) { this.#samples = []; this.#shown = null; }
    this.#key = key;
    if (!broken && previous!.at === at) return this.#shown;
    this.#samples.push({ at, es });
    this.#samples = this.#samples.filter(row => at - row.at <= WINDOW_MS);
    const span = at - this.#samples[0]!.at;
    if (this.#samples.length < 3 || span < MIN_SPAN_MS) return this.#shown;
    const rate = energyRate(this.#samples);
    if (rate >= SHOW_MPS) this.#shown = "up";
    else if (rate <= -SHOW_MPS) this.#shown = "down";
    else if (Math.abs(rate) < HIDE_MPS) this.#shown = null;
    return this.#shown;
  }
}

function energyRate(samples: readonly { at: number; es: number }[]): number {
  const meanAt = samples.reduce((sum, row) => sum + row.at, 0) / samples.length;
  const meanEs = samples.reduce((sum, row) => sum + row.es, 0) / samples.length;
  let variance = 0, covariance = 0;
  for (const row of samples) {
    const seconds = (row.at - meanAt) / 1000;
    variance += seconds ** 2;
    covariance += seconds * (row.es - meanEs);
  }
  return variance > 0 ? covariance / variance : 0;
}
