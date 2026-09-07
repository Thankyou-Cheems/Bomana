const MAX_EXTRAPOLATION_MS = 240;
const MAX_ANGULAR_SPEED_DEG_MS = .3;
const SNAP_DELTA_DEG = 90;
const TIME_CONSTANT_MS = 105;

export class SampledAngleMotion {
  #sample = Number.NaN;
  #sampleAtMs = 0;
  #velocityDegMs = 0;
  #display = Number.NaN;
  #lastStepMs = Number.NaN;

  observe(valueDeg: number, atMs: number): void {
    if (!Number.isFinite(valueDeg) || !Number.isFinite(atMs)) return;
    if (!Number.isFinite(this.#sample)) {
      this.#sample = valueDeg;
      this.#sampleAtMs = atMs;
      this.#display = valueDeg;
      return;
    }
    const elapsed = atMs - this.#sampleAtMs;
    const delta = normalizeSigned(valueDeg - this.#sample);
    if (elapsed <= 0 || elapsed > 1_000 || Math.abs(delta) >= SNAP_DELTA_DEG) {
      this.#sample = valueDeg;
      this.#sampleAtMs = atMs;
      this.#velocityDegMs = 0;
      this.#display = valueDeg;
      this.#lastStepMs = atMs;
      return;
    }
    this.#sample += delta;
    this.#sampleAtMs = atMs;
    this.#velocityDegMs = clamp(delta / elapsed, -MAX_ANGULAR_SPEED_DEG_MS, MAX_ANGULAR_SPEED_DEG_MS);
  }

  step(nowMs: number): number {
    if (!Number.isFinite(this.#sample)) return 0;
    if (!Number.isFinite(this.#display)) this.#display = this.#sample;
    if (!Number.isFinite(this.#lastStepMs)) {
      this.#lastStepMs = nowMs;
      return this.#display;
    }
    const elapsed = Math.max(0, Math.min(50, nowMs - this.#lastStepMs));
    this.#lastStepMs = nowMs;
    const sampleAge = clamp(nowMs - this.#sampleAtMs, 0, MAX_EXTRAPOLATION_MS);
    const predicted = this.#sample + this.#velocityDegMs * sampleAge;
    const delta = normalizeSigned(predicted - this.#display);
    this.#display += delta * (1 - Math.exp(-elapsed / TIME_CONSTANT_MS));
    return this.#display;
  }

  reset(valueDeg = Number.NaN): void {
    this.#sample = valueDeg;
    this.#sampleAtMs = 0;
    this.#velocityDegMs = 0;
    this.#display = valueDeg;
    this.#lastStepMs = Number.NaN;
  }
}

export function sampledAtPerformanceTime(
  sampledAtEpochMs: number,
  epochNowMs = Date.now(),
  performanceNowMs = performance.now(),
): number {
  if (!Number.isFinite(sampledAtEpochMs)) return performanceNowMs;
  const ageMs = Math.max(0, epochNowMs - sampledAtEpochMs);
  return performanceNowMs - ageMs;
}

function normalizeSigned(value: number): number { return ((value + 180) % 360 + 360) % 360 - 180; }
function clamp(value: number, minimum: number, maximum: number): number { return Math.min(maximum, Math.max(minimum, value)); }
