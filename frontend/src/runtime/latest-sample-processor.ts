export class LatestSampleProcessor<Sample> {
  readonly #process: (sample: Sample) => void | Promise<void>;
  readonly #onError: (error: unknown) => void;
  #active = false;
  #hasLatest = false;
  #latest: Sample | null = null;

  constructor(
    process: (sample: Sample) => void | Promise<void>,
    onError: (error: unknown) => void = () => undefined,
  ) {
    this.#process = process;
    this.#onError = onError;
  }

  push(sample: Sample): void {
    this.#latest = sample;
    this.#hasLatest = true;
    if (!this.#active) void this.#drain();
  }

  async #drain(): Promise<void> {
    this.#active = true;
    try {
      while (this.#hasLatest) {
        const sample = this.#latest as Sample;
        this.#latest = null;
        this.#hasLatest = false;
        try {
          await this.#process(sample);
        } catch (error) {
          this.#onError(error);
        }
      }
    } finally {
      this.#active = false;
      if (this.#hasLatest) void this.#drain();
    }
  }
}
