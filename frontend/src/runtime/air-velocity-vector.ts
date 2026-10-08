import type { EditionSnapshot } from "./runtime-types";
import { GroundTrackEstimator } from "./ground-track";
import { speedObservationCurrent } from "./speed-strip-renderer";

export interface AirVelocityVector {
  readonly headingDeg: number;
  readonly relativeDeg: number;
  readonly groundSpeedMps: number;
}

/** Horizontal ownship motion from fresh 8111 positions, independent of nose direction. */
export class AirVelocityVectorEstimator {
  readonly #track = new GroundTrackEstimator();
  #key = "";

  reset(): void { this.#track.reset(); this.#key = ""; }

  observe(snapshot: EditionSnapshot, nowMs: number): AirVelocityVector | null {
    const player = snapshot.navigation?.player, scale = snapshot.navigation?.mapScaleM;
    const at = snapshot.mapObjectsSampledAtMs;
    if (!snapshot.connected || snapshot.mapObjectsFresh !== true || snapshot.phase !== "alive"
      || !speedObservationCurrent(snapshot, nowMs)
      || snapshot.flight.onGround || !Number.isFinite(snapshot.flight.headingDeg)
      || !player || !scale || at == null || !Number.isFinite(at) || nowMs < at || nowMs - at > 500) {
      this.reset(); return null;
    }
    const key = `${snapshot.flight.aircraft}\0${snapshot.timer.lifeIndex ?? ""}\0${snapshot.mapGrid?.minimum}\0${snapshot.mapGrid?.maximum}`;
    if (key !== this.#key) this.#track.reset();
    this.#key = key;
    const track = this.#track.update({ atMs: at, x: player.x, y: player.y, scale });
    if (!track.valid) return null;
    return { headingDeg: track.headingDeg, groundSpeedMps: track.groundSpeedMps,
      relativeDeg: ((track.headingDeg - snapshot.flight.headingDeg + 180) % 360 + 360) % 360 - 180 };
  }
}
