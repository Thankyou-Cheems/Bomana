import { abortableTask } from "./abortable-task";

export type AutoConnectionPhase = "connecting" | "connected" | "waiting";

export interface AutoConnectionState {
  readonly phase: AutoConnectionPhase;
  readonly retryAttempt: number;
  readonly retryDelayMs: number;
  readonly retryAtMs: number;
  readonly error?: Error;
}

export interface AutoConnectionLoopOptions<Sample> {
  readonly attempt: (signal: AbortSignal) => Promise<Sample>;
  readonly isConnected: (sample: Sample) => boolean;
  readonly onSample: (sample: Sample) => void | Promise<void>;
  readonly onState: (state: AutoConnectionState) => void;
  readonly onInterrupt?: () => void;
  readonly wait?: (milliseconds: number, signal: AbortSignal) => Promise<void>;
  readonly random?: () => number;
  readonly now?: () => number;
  readonly activeIntervalMs?: number;
  readonly baseRetryMs?: number;
  readonly maxRetryMs?: number;
}

export class AutoConnectionLoop<Sample> {
  readonly #options: Required<Omit<AutoConnectionLoopOptions<Sample>, "wait" | "random" | "now">> & {
    readonly wait: NonNullable<AutoConnectionLoopOptions<Sample>["wait"]>;
    readonly random: NonNullable<AutoConnectionLoopOptions<Sample>["random"]>;
    readonly now: NonNullable<AutoConnectionLoopOptions<Sample>["now"]>;
  };
  #running = false;
  #generation = 0;
  #attemptController: AbortController | null = null;
  #waitController: AbortController | null = null;
  #lastState = "";

  constructor(options: AutoConnectionLoopOptions<Sample>) {
    this.#options = {
      ...options,
      onInterrupt: options.onInterrupt ?? (() => undefined),
      wait: options.wait ?? waitWithAbort,
      random: options.random ?? Math.random,
      now: options.now ?? Date.now,
      activeIntervalMs: options.activeIntervalMs ?? 100,
      baseRetryMs: options.baseRetryMs ?? 500,
      maxRetryMs: options.maxRetryMs ?? 8_000,
    };
  }

  start(): void {
    if (this.#running) return;
    this.#running = true;
    void this.#run(++this.#generation);
  }

  retryNow(): void {
    this.#options.onInterrupt();
    if (!this.#running) {
      this.start();
      return;
    }
    this.#attemptController?.abort();
    this.#waitController?.abort();
  }

  stop(): void {
    this.#options.onInterrupt();
    this.#running = false;
    this.#generation += 1;
    this.#attemptController?.abort();
    this.#waitController?.abort();
    this.#waitController = null;
  }

  async #run(generation: number): Promise<void> {
    let failures = 0;
    this.#emit({ phase: "connecting", retryAttempt: 0, retryDelayMs: 0, retryAtMs: 0 });
    while (this.#running && generation === this.#generation) {
      const attemptStartedAtMs = this.#options.now();
      const controller = new AbortController();
      this.#attemptController = controller;
      let sample: Sample | null = null;
      let failure: Error | undefined;
      try {
        sample = await abortableTask(this.#options.attempt(controller.signal), controller.signal);
      } catch (error) {
        failure = error instanceof Error ? error : new Error(String(error));
        sample = null;
      }
      if (!this.#running || generation !== this.#generation) return;
      this.#attemptController = null;
      if (controller.signal.aborted) { failures = 0; continue; }
      if (sample !== null) {
        void Promise.resolve(this.#options.onSample(sample)).catch(() => undefined);
      }
      const connected = sample !== null && this.#options.isConnected(sample);
      const delay = connected
        ? Math.max(0, this.#options.activeIntervalMs - Math.max(0, this.#options.now() - attemptStartedAtMs))
        : retryDelay(++failures, this.#options.baseRetryMs, this.#options.maxRetryMs, this.#options.random());
      if (connected) {
        failures = 0;
        this.#emit({ phase: "connected", retryAttempt: 0, retryDelayMs: delay, retryAtMs: 0 });
      } else {
        this.#emit({ phase: "waiting", retryAttempt: failures, retryDelayMs: delay, retryAtMs: this.#options.now() + delay, ...(failure ? { error: failure } : {}) });
      }
      this.#waitController = new AbortController();
      await this.#options.wait(delay, this.#waitController.signal);
      if (generation !== this.#generation) return;
      this.#waitController = null;
      if (this.#running && failures > 0) {
        this.#emit({ phase: "connecting", retryAttempt: failures, retryDelayMs: 0, retryAtMs: 0 });
      }
    }
  }

  #emit(state: AutoConnectionState): void {
    const signature = `${state.phase}:${state.retryAttempt}:${state.retryDelayMs}:${state.retryAtMs}:${state.error?.message ?? ""}`;
    if (signature === this.#lastState) return;
    this.#lastState = signature;
    this.#options.onState(Object.freeze(state));
  }
}

function retryDelay(attempt: number, baseMs: number, maxMs: number, random: number): number {
  const exponential = Math.min(maxMs, baseMs * 2 ** Math.max(0, attempt - 1));
  const jitter = 0.8 + Math.min(1, Math.max(0, random)) * 0.4;
  return Math.min(maxMs, Math.round(exponential * jitter));
}

function waitWithAbort(milliseconds: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    if (signal.aborted) { resolve(); return; }
    const timer = globalThis.setTimeout(finish, milliseconds);
    signal.addEventListener("abort", finish, { once: true });
    function finish(): void {
      globalThis.clearTimeout(timer);
      signal.removeEventListener("abort", finish);
      resolve();
    }
  });
}
