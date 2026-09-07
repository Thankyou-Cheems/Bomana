export interface GroundTrackEstimate {
  readonly valid: boolean;
  readonly worldX: number;
  readonly worldZ: number;
  readonly velocityX: number;
  readonly velocityZ: number;
  readonly groundSpeedMps: number;
  readonly headingDeg: number;
  readonly residualM: number;
  readonly sampleCount: number;
  readonly sampleSpanMs: number;
}

interface TrackSample {
  readonly atMs: number;
  readonly worldX: number;
  readonly worldZ: number;
}

const HISTORY_MS = 1_000;
const MAX_OBSERVATION_GAP_MS = 500;
const MAX_REPEATED_POSITION_MS = 350;
const FIT_WINDOW_MS = 280;
const MIN_SPAN_MS = 90;
const MIN_SAMPLES = 3;
const MAX_SAMPLES = 4;
const MIN_SPEED_MPS = 10;
const MAX_SPEED_MPS = 2_500;
const MAX_RESIDUAL_M = 100;

const EMPTY_ESTIMATE: GroundTrackEstimate = Object.freeze({
  valid: false,
  worldX: 0,
  worldZ: 0,
  velocityX: 0,
  velocityZ: 0,
  groundSpeedMps: 0,
  headingDeg: 0,
  residualM: 0,
  sampleCount: 0,
  sampleSpanMs: 0,
});

/** Causal ground-track fit bounded across the Web runtime's 10 Hz dynamic poll. */
export class GroundTrackEstimator {
  readonly #samples: TrackSample[] = [];
  #scale: readonly [number, number] | null = null;
  #firstObservedAtMs: number | null = null;

  get firstObservedAtMs(): number | null { return this.#firstObservedAtMs; }

  reset(): void {
    this.#samples.length = 0;
    this.#scale = null;
    this.#firstObservedAtMs = null;
  }

  update(input: {
    readonly atMs: number;
    readonly x: number;
    readonly y: number;
    readonly scale: readonly [number, number];
  }): GroundTrackEstimate {
    if (
      !Number.isFinite(input.atMs)
      || !Number.isFinite(input.x)
      || !Number.isFinite(input.y)
      || input.x < 0 || input.x > 1
      || input.y < 0 || input.y > 1
      || input.scale.some((value) => !Number.isFinite(value) || value <= 0)
    ) {
      this.reset();
      return EMPTY_ESTIMATE;
    }
    if (
      this.#scale
      && (this.#scale[0] !== input.scale[0] || this.#scale[1] !== input.scale[1])
    ) this.reset();
    this.#scale = input.scale;
    const latest = this.#samples.at(-1);
    if (
      latest
      && (input.atMs < latest.atMs || input.atMs - latest.atMs > MAX_OBSERVATION_GAP_MS)
    ) this.reset();
    const current = this.#samples.at(-1);
    if (current && input.atMs === current.atMs) return this.#estimate(input.atMs);
    // An unchanged map response is not a new zero-speed observation. Keep its
    // source time and only project the established track through a short gap.
    if (current && current.worldX === input.x * input.scale[0] && current.worldZ === -input.y * input.scale[1]) {
      return input.atMs - current.atMs <= MAX_REPEATED_POSITION_MS
        ? this.#estimate(input.atMs) : EMPTY_ESTIMATE;
    }
    if (this.#firstObservedAtMs === null) this.#firstObservedAtMs = input.atMs;
    this.#samples.push({
      atMs: input.atMs,
      worldX: input.x * input.scale[0],
      worldZ: -input.y * input.scale[1],
    });
    while (this.#samples.length && this.#samples[0]!.atMs < input.atMs - HISTORY_MS) {
      this.#samples.shift();
    }
    return this.#estimate(input.atMs);
  }

  #estimate(atMs: number): GroundTrackEstimate {
    const latest = this.#samples.at(-1);
    if (!latest) return EMPTY_ESTIMATE;
    let selected = this.#samples
      .filter((sample) => sample.atMs >= latest.atMs - FIT_WINDOW_MS)
      .slice(-MAX_SAMPLES);
    // Official 8111 normally supplies three observations inside the nominal
    // 10 Hz window. Keep a bounded three-sample fallback for older recordings
    // and repeated source-side positions; it never reaches beyond HISTORY_MS.
    if (selected.length < MIN_SAMPLES) selected = this.#samples.slice(-MIN_SAMPLES);
    const spanMs = selected.length > 1
      ? selected.at(-1)!.atMs - selected[0]!.atMs
      : 0;
    if (selected.length < MIN_SAMPLES || spanMs < MIN_SPAN_MS) {
      return Object.freeze({
        ...EMPTY_ESTIMATE,
        sampleCount: selected.length,
        sampleSpanMs: spanMs,
      });
    }
    const meanTime = selected.reduce((sum, sample) => sum + sample.atMs, 0) / selected.length;
    const meanX = selected.reduce((sum, sample) => sum + sample.worldX, 0) / selected.length;
    const meanZ = selected.reduce((sum, sample) => sum + sample.worldZ, 0) / selected.length;
    const varianceTime = selected.reduce(
      (sum, sample) => sum + ((sample.atMs - meanTime) / 1_000) ** 2,
      0,
    );
    if (varianceTime <= 1e-9) return EMPTY_ESTIMATE;
    const velocityX = selected.reduce(
      (sum, sample) => sum + (sample.atMs - meanTime) / 1_000 * (sample.worldX - meanX),
      0,
    ) / varianceTime;
    const velocityZ = selected.reduce(
      (sum, sample) => sum + (sample.atMs - meanTime) / 1_000 * (sample.worldZ - meanZ),
      0,
    ) / varianceTime;
    const fittedLatestX = meanX + velocityX * (atMs - meanTime) / 1_000;
    const fittedLatestZ = meanZ + velocityZ * (atMs - meanTime) / 1_000;
    const residualM = Math.sqrt(selected.reduce((sum, sample) => {
      const elapsed = (sample.atMs - meanTime) / 1_000;
      return sum
        + (sample.worldX - (meanX + velocityX * elapsed)) ** 2
        + (sample.worldZ - (meanZ + velocityZ * elapsed)) ** 2;
    }, 0) / selected.length);
    const groundSpeedMps = Math.hypot(velocityX, velocityZ);
    return Object.freeze({
      valid: groundSpeedMps >= MIN_SPEED_MPS
        && groundSpeedMps <= MAX_SPEED_MPS
        && residualM <= MAX_RESIDUAL_M,
      worldX: fittedLatestX,
      worldZ: fittedLatestZ,
      velocityX,
      velocityZ,
      groundSpeedMps,
      headingDeg: normalizeHeading(Math.atan2(velocityX, velocityZ) * 180 / Math.PI),
      residualM,
      sampleCount: selected.length,
      sampleSpanMs: spanMs,
    });
  }
}

export function targetGroundTrackGeometry(
  track: GroundTrackEstimate,
  target: { readonly x: number; readonly y: number },
  scale: readonly [number, number],
): {
  readonly distanceM: number;
  readonly alongTrackM: number;
  readonly crossTrackM: number;
  readonly relativeDeg: number;
} | null {
  if (!track.valid || track.groundSpeedMps < MIN_SPEED_MPS) return null;
  const directionX = track.velocityX / track.groundSpeedMps;
  const directionZ = track.velocityZ / track.groundSpeedMps;
  const deltaX = target.x * scale[0] - track.worldX;
  const deltaZ = -target.y * scale[1] - track.worldZ;
  const alongTrackM = deltaX * directionX + deltaZ * directionZ;
  const crossTrackM = directionX * deltaZ - directionZ * deltaX;
  return Object.freeze({
    distanceM: Math.hypot(deltaX, deltaZ),
    alongTrackM,
    crossTrackM,
    relativeDeg: normalizeSigned(Math.atan2(-crossTrackM, alongTrackM) * 180 / Math.PI),
  });
}

function normalizeHeading(value: number): number { return (value % 360 + 360) % 360; }
function normalizeSigned(value: number): number { return ((value + 180) % 360 + 360) % 360 - 180; }
