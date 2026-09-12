/** Display-only target bearing filter. It never changes area edges or release membership. */
export class TargetCenterMotion {
  #id = "";
  #raw = 0;
  #display = 0;
  #lastAt = Number.NaN;

  observe(id: string, relativeDeg: number): void {
    if (!Number.isFinite(relativeDeg)) return;
    this.#raw = relativeDeg;
    if (id !== this.#id) {
      this.#id = id;
      this.#display = relativeDeg;
      this.#lastAt = Number.NaN;
    }
  }

  step(nowMs: number): number {
    const elapsed = Number.isFinite(this.#lastAt) ? Math.max(0, Math.min(50, nowMs - this.#lastAt)) : 0;
    this.#lastAt = nowMs;
    const error = signedAngle(this.#raw - this.#display);
    // Limit visual lag during real turns; no velocity extrapolation of noisy map samples.
    const bounded = Math.max(-.1, Math.min(.1, error));
    this.#display = this.#raw - bounded * Math.exp(-elapsed / 90);
    return this.#display;
  }
}

function signedAngle(value: number): number { return ((value + 180) % 360 + 360) % 360 - 180; }
