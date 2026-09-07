import { describe, expect, it, vi } from "vitest";
import { AutoConnectionLoop } from "./auto-connection-loop";

class ManualWaiter {
  readonly requests: Array<{ milliseconds: number; release: () => void }> = [];

  readonly wait = (milliseconds: number, signal: AbortSignal): Promise<void> => new Promise((resolve) => {
    const release = (): void => {
      signal.removeEventListener("abort", release);
      resolve();
    };
    signal.addEventListener("abort", release, { once: true });
    this.requests.push({ milliseconds, release });
  });
}

describe("AutoConnectionLoop", () => {
  it("cancels an in-flight read on retry and never publishes the abandoned sample", async () => {
    const signals: AbortSignal[] = [];
    const complete: Array<(value: number) => void> = [];
    const published: number[] = [];
    const loop = new AutoConnectionLoop({
      attempt: (signal: AbortSignal) => { signals.push(signal); return new Promise<number>(resolve => complete.push(resolve)); },
      isConnected: () => true, onSample: value => { published.push(value); }, onState: () => undefined,
    });
    loop.start();
    loop.retryNow();
    await vi.waitFor(() => expect(complete).toHaveLength(2));
    expect(signals[0]?.aborted).toBe(true);
    complete[0]!(1);
    loop.stop();
    expect(signals[1]?.aborted).toBe(true);
    complete[1]!(2);
    await Promise.resolve();
    expect(published).toEqual([]);
  });

  it("starts immediately, backs off exponentially, and returns to the active cadence", async () => {
    const waiter = new ManualWaiter();
    const samples = [{ connected: false }, { connected: false }, { connected: true }];
    const attempt = vi.fn(async () => samples.shift() ?? { connected: true });
    const states: string[] = [];
    const loop = new AutoConnectionLoop({
      attempt,
      isConnected: (sample) => sample.connected,
      onSample: () => undefined,
      onState: (state) => states.push(`${state.phase}:${state.retryDelayMs}`),
      wait: waiter.wait,
      random: () => 0.5,
      now: () => 0,
    });

    loop.start();
    await vi.waitFor(() => expect(waiter.requests).toHaveLength(1));
    expect(waiter.requests[0]?.milliseconds).toBe(500);
    waiter.requests[0]?.release();
    await vi.waitFor(() => expect(waiter.requests).toHaveLength(2));
    expect(waiter.requests[1]?.milliseconds).toBe(1_000);
    waiter.requests[1]?.release();
    await vi.waitFor(() => expect(waiter.requests).toHaveLength(3));
    expect(waiter.requests[2]?.milliseconds).toBe(100);
    expect(states).toContain("waiting:500");
    expect(states).toContain("waiting:1000");
    expect(states).toContain("connected:100");
    loop.stop();
  });

  it("lets a manual retry interrupt the current backoff wait", async () => {
    const waiter = new ManualWaiter();
    const attempt = vi.fn(async () => ({ connected: false }));
    const loop = new AutoConnectionLoop({
      attempt,
      isConnected: (sample) => sample.connected,
      onSample: () => undefined,
      onState: () => undefined,
      wait: waiter.wait,
      random: () => 0.5,
      now: () => 0,
    });

    loop.start();
    await vi.waitFor(() => expect(waiter.requests).toHaveLength(1));
    loop.retryNow();
    await vi.waitFor(() => expect(attempt).toHaveBeenCalledTimes(2));
    loop.stop();
  });

  it("keeps the 10 Hz acquisition clock independent from a slow presentation consumer", async () => {
    const waiter = new ManualWaiter();
    let releasePresentation!: () => void;
    const onSample = vi.fn(() => new Promise<void>((resolve) => { releasePresentation = resolve; }));
    const loop = new AutoConnectionLoop({
      attempt: async () => ({ bridgeReachable: true }),
      isConnected: (sample) => sample.bridgeReachable,
      onSample,
      onState: () => undefined,
      wait: waiter.wait,
      random: () => 0.5,
      now: () => 0,
    });

    loop.start();
    await vi.waitFor(() => expect(onSample).toHaveBeenCalledTimes(1));
    await vi.waitFor(() => expect(waiter.requests).toHaveLength(1));
    expect(waiter.requests[0]?.milliseconds).toBe(100);
    releasePresentation();
    loop.stop();
  });

  it("does not back off when Bridge is reachable but the game frame is unavailable", async () => {
    const waiter = new ManualWaiter();
    const states: object[] = [];
    const loop = new AutoConnectionLoop({
      attempt: async () => ({ bridgeReachable: true, frameAvailable: false }),
      isConnected: (sample) => sample.bridgeReachable,
      onSample: () => undefined,
      onState: (state) => states.push(state),
      wait: waiter.wait,
      random: () => 0.5,
      now: () => 0,
    });

    loop.start();
    await vi.waitFor(() => expect(waiter.requests).toHaveLength(1));
    expect(waiter.requests[0]?.milliseconds).toBe(100);
    expect(states).toContainEqual(expect.objectContaining({ phase: "connected", retryDelayMs: 100 }));
    expect(states).not.toContainEqual(expect.objectContaining({ phase: "waiting" }));
    loop.stop();
  });

  it("publishes the retry deadline so Web can show a live countdown", async () => {
    const waiter = new ManualWaiter();
    const states: object[] = [];
    const before = Date.now();
    const loop = new AutoConnectionLoop({
      attempt: async () => ({ connected: false }),
      isConnected: (sample) => sample.connected,
      onSample: () => undefined,
      onState: (state) => states.push(state),
      wait: waiter.wait,
      random: () => 0.5,
    });

    loop.start();
    await vi.waitFor(() => expect(waiter.requests).toHaveLength(1));
    expect(states).toContainEqual(expect.objectContaining({
      phase: "waiting",
      retryAtMs: expect.any(Number),
    }));
    const waiting = states.find((state) => (state as { phase?: string }).phase === "waiting") as { retryAtMs: number };
    expect(waiting.retryAtMs).toBeGreaterThanOrEqual(before + 500);
    loop.stop();
  });

  it("subtracts request time from the connected cadence", async () => {
    const waiter = new ManualWaiter();
    let nowMs = 1_000;
    const loop = new AutoConnectionLoop({
      attempt: async () => { nowMs += 35; return { connected: true }; },
      isConnected: (sample) => sample.connected,
      onSample: () => undefined,
      onState: () => undefined,
      wait: waiter.wait,
      now: () => nowMs,
    });

    loop.start();
    await vi.waitFor(() => expect(waiter.requests).toHaveLength(1));
    expect(waiter.requests[0]?.milliseconds).toBe(65);
    loop.stop();
  });
});
