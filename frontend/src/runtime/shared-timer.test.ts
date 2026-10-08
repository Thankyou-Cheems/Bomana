import { describe, expect, it } from "vitest";
import { PublicRuntime } from "./public-runtime";
import { editionPolicy } from "./edition-policy";
import { publicFlight } from "./public-runtime-fixture";
import { SharedTimerSession } from "./shared-timer";
import type { TimerPresentationState } from "./runtime-types";

class Relay {
  now = 0; epoch = "bridge_epoch_123456"; revision = 0; anchor = 0;
  timer: TimerPresentationState | null = null;
  desktopSeen = Number.NEGATIVE_INFINITY;
  conflictNext = false;
  response() { return { schema_version: 1, epoch: this.epoch, revision: this.revision,
    server_now_ms: this.now, anchor_at_ms: this.anchor, desktop_present: this.now - this.desktopSeen < 5000,
    timer: this.timer }; }
  fetcher(mobile: boolean): typeof fetch {
    return (async (_url, options) => {
      if (!mobile) this.desktopSeen = this.now;
      if (options?.method === "PUT") {
        const payload = JSON.parse(String(options.body));
        if (this.conflictNext) {
          this.conflictNext = false; this.revision++;
          return Response.json(this.response(), { status: 409 });
        }
        if (payload.epoch !== this.epoch || payload.expected_revision !== this.revision) {
          return Response.json(this.response(), { status: 409 });
        }
        this.timer = payload.timer; this.anchor = this.now; this.revision++;
      }
      return Response.json(this.response());
    }) as typeof fetch;
  }
}
const frame = (at: number) => ({ ...publicFlight(1000), sampledAtMs: at });
async function spawn(runtime: PublicRuntime, at: number) {
  await runtime.ingest(frame(at)); await runtime.ingest(frame(at + 1000));
}
function client(relay: Relay, runtime: PublicRuntime, mobile: boolean) {
  return new SharedTimerSession({ runtime, mobile, fetcher: relay.fetcher(mobile),
    endpoint: async () => new URL("http://127.0.0.1:8878/"), now: () => relay.now });
}

describe("shared cycle timer presentation", () => {
  it.each([false, true])("does not lose a Standard spawn during PUT (previous life: %s)", async previousLife => {
    const relay = new Relay(); let now = 0;
    const runtime = new PublicRuntime({ edition: editionPolicy("Standard"), now: () => now });
    if (previousLife) { now = relay.now = 2000; await spawn(runtime, 1000); }
    const requestAt = now;
    const fetcher = relay.fetcher(false);
    let release!: () => void;
    let pending!: () => void;
    const enteredPut = new Promise<void>(resolve => { pending = resolve; });
    const resumePut = new Promise<void>(resolve => { release = resolve; });
    let delay = true;
    const session = new SharedTimerSession({ runtime, mobile: false, now: () => relay.now,
      endpoint: async () => new URL("http://127.0.0.1:8878/"), fetcher: async (...args) => {
        const response = await fetcher(...args);
        if (args[1]?.method === "PUT" && delay) { delay = false; pending(); await resumePut; }
        return response;
      } });
    const synchronizing = session.refresh(true);
    await enteredPut;
    if (previousLife) {
      now = relay.now = requestAt + 100;
      await runtime.ingest({ ...frame(now), mapObjects: [] });
      expect(runtime.snapshot().phase).toBe("wait-next");
    }
    // Complete the transition within the real 1500ms request deadline.
    now = relay.now = requestAt + 1200;
    await spawn(runtime, requestAt + 200);
    release(); await synchronizing;
    expect(session.project(runtime.snapshot()).timer.remainingSec).toBe(899);
    await session.refresh(true);
    expect(session.project(runtime.snapshot()).timer.remainingSec).toBe(899);
    expect(runtime.timerPresentation().life_index).toBe(previousLife ? 2 : 1);
    expect(relay.timer?.active).toBe(true);
  });

  it.each(["Lite", "Standard"] as const)("starts a fresh %s spawn when Bridge holds a previous inactive timer", async edition => {
    const relay = new Relay(); relay.revision = 1;
    relay.timer = { active: false, elapsed_sec: 0, cycle_seconds: 900, life_index: 0 };
    const runtime = new PublicRuntime({ edition: editionPolicy(edition), now: () => 2000 });
    await spawn(runtime, 1000);
    const session = client(relay, runtime, false);
    await session.refresh(true);
    await session.refresh(true);
    expect(runtime.snapshot().phase).toBe("alive");
    expect(session.project(runtime.snapshot()).timer.remainingSec).toBe(899);
    expect(relay.timer?.active).toBe(true);
  });

  it.each([false, true])("only lets the phone publish its spawn without a desktop owner (desktop present: %s)", async desktopPresent => {
    const relay = new Relay(); relay.revision = 1;
    relay.timer = { active: false, elapsed_sec: 0, cycle_seconds: 900, life_index: 0 };
    if (desktopPresent) relay.desktopSeen = relay.now;
    const runtime = new PublicRuntime({ edition: editionPolicy("Standard"), now: () => 2000 });
    await spawn(runtime, 1000);
    const session = client(relay, runtime, true);
    await session.refresh(true);
    expect(session.project(runtime.snapshot()).timer.remainingSec).toBe(desktopPresent ? null : 899);
    expect(relay.timer?.active).toBe(!desktopPresent);
  });

  it("automatically starts the Standard timer after entering before spawn, without manual reset", async () => {
    const relay = new Relay(); let now = 0;
    const runtime = new PublicRuntime({ edition: editionPolicy("Standard"), now: () => now });
    const session = client(relay, runtime, false);
    await session.refresh(true);
    expect(session.project(runtime.snapshot()).timer.remainingSec).toBeNull();
    for (const at of [1000, 1500, 2000, 2500, 3000]) {
      now = relay.now = at;
      await runtime.ingest(frame(at));
      await session.refresh(true);
    }
    expect(runtime.snapshot().phase).toBe("alive");
    expect(session.project(runtime.snapshot()).timer.remainingSec).toBe(898);
    expect(relay.timer?.active).toBe(true);
  });

  it("Standard late phone shares actual cycle boundaries despite a 120s wall-clock offset", async () => {
    const relay = new Relay(); let desktopNow = 2000, phoneNow = 242000;
    const make = (now: () => number) => new PublicRuntime({ edition: editionPolicy("Standard"), now });
    const desktop = make(() => desktopNow), phone = make(() => phoneNow);
    await spawn(desktop, 1000);
    const desk = client(relay, desktop, false), mobile = client(relay, phone, true);
    await desk.refresh(true);
    relay.now = 120000; desktopNow = 122000; await desk.refresh(true);
    await spawn(phone, 241000); await mobile.refresh(true);
    expect(desk.project(desktop.snapshot()).timer.remainingSec).toBe(779);
    expect(mobile.project(phone.snapshot()).timer.remainingSec).toBe(779);
    relay.now = 899000; desktopNow = 901000; phoneNow = 1021000;
    expect(desk.project(desktop.snapshot()).timer).toMatchObject({ cycle: 2, remainingSec: 900 });
    expect(mobile.project(phone.snapshot()).timer).toMatchObject({ cycle: 2, remainingSec: 900 });
    phoneNow += 60000; // In-session wall-clock change does not alter shared display.
    expect(mobile.project(phone.snapshot()).timer.remainingSec).toBe(900);
  });

  it("propagates reset in both directions and changes period without losing elapsed time", async () => {
    const relay = new Relay(); let now = 2000;
    const desktop = new PublicRuntime({ edition: editionPolicy("Standard"), now: () => now });
    const phone = new PublicRuntime({ edition: editionPolicy("Standard"), now: () => now });
    await spawn(desktop, 1000); await spawn(phone, 1000);
    const desk = client(relay, desktop, false), mobile = client(relay, phone, true);
    await desk.refresh(true); await mobile.refresh(true);
    relay.now = 20000; now = 22000;
    await mobile.command({ type: "timer.reset" }); await desk.refresh(true);
    expect(desk.project(desktop.snapshot()).timer.remainingSec).toBe(900);
    relay.now += 30000; now += 30000;
    await mobile.command({ type: "timer.set-cycle", minutes: 10 }); await desk.refresh(true);
    expect(desk.project(desktop.snapshot()).timer).toMatchObject({ remainingSec: 570, cycleMinutes: 10 });
    await desk.command({ type: "timer.reset" }); await mobile.refresh(true);
    expect(mobile.project(phone.snapshot()).timer.remainingSec).toBe(600);
    expect(phone.timerPresentation().cycle_seconds).toBe(600);
  });

  it("an early phone cannot seed independent spawn over a present desktop; tray-only phone can seed", async () => {
    const relay = new Relay(); let now = 2000;
    const desktop = new PublicRuntime({ edition: editionPolicy("Standard"), now: () => now });
    const phone = new PublicRuntime({ edition: editionPolicy("Standard"), now: () => now });
    const desk = client(relay, desktop, false), mobile = client(relay, phone, true);
    await desk.refresh(true); await spawn(phone, 1000); await mobile.refresh(true);
    expect(mobile.project(phone.snapshot()).timer.remainingSec).toBeNull();
    relay.now = 6000; now = 8000; await mobile.refresh(true);
    // No desktop heartbeat for 5s: the phone can now own standalone lifecycle.
    // A local lifecycle transition supplies the next authoritative projection.
    await phone.command({ type: "timer.reset" }); await mobile.refresh(true);
    expect(mobile.project(phone.snapshot()).timer.remainingSec).toBe(900);
  });

  it("retries compare-and-swap conflicts instead of acknowledging another writer's update as its command", async () => {
    const relay = new Relay();
    const runtime = new PublicRuntime({ edition: editionPolicy("Standard"), now: () => 2000 });
    await spawn(runtime, 1000); const session = client(relay, runtime, false); await session.refresh(true);
    const revision = relay.revision; relay.conflictNext = true;
    await session.command({ type: "timer.reset" });
    expect(relay.revision).toBe(revision + 2);
    expect(session.project(runtime.snapshot()).timer.remainingSec).toBe(900);
  });

  it("ignores lower revisions on reconnect and accepts a new Bridge epoch", async () => {
    const relay = new Relay();
    const runtime = new PublicRuntime({ edition: editionPolicy("Standard"), now: () => 2000 });
    await spawn(runtime, 1000); const session = client(relay, runtime, false); await session.refresh(true);
    await session.command({ type: "timer.reset" });
    relay.revision = 1; relay.timer = { active: true, elapsed_sec: 70, cycle_seconds: 900, life_index: 1 };
    await session.refresh(true);
    expect(session.project(runtime.snapshot()).timer.remainingSec).toBe(900);
    relay.epoch = "new_bridge_epoch_123"; relay.revision = 0; relay.timer = null;
    await session.refresh(true);
    expect(relay.revision).toBe(1);
    expect(session.project(runtime.snapshot()).timer.cueIdentity).toBe("new_bridge_epoch_123:1");
  });

  it("keeps the monotonic timer during disconnection and obtains the latest reset after visibility recovery", async () => {
    const relay = new Relay(); let wall = 2000, offline = false;
    const desktop = new PublicRuntime({ edition: editionPolicy("Standard"), now: () => wall });
    const phone = new PublicRuntime({ edition: editionPolicy("Standard"), now: () => wall });
    await spawn(desktop, 1000); await spawn(phone, 1000);
    const desk = client(relay, desktop, false), fetcher = relay.fetcher(true), messages: string[] = [];
    const mobile = new SharedTimerSession({ runtime: phone, mobile: true,
      fetcher: async (...args) => { if (offline) throw new Error("Bridge offline"); return fetcher(...args); },
      endpoint: async () => new URL("http://127.0.0.1:8878/"), now: () => relay.now,
      onStatus: message => messages.push(message) });
    await desk.refresh(true); await mobile.refresh(true);
    offline = true; relay.now = 10000; wall += 70000;
    await mobile.refresh(true);
    expect(messages.at(-1)).toBe("Bridge offline");
    expect(mobile.project(phone.snapshot()).timer.remainingSec).toBe(889);
    await desk.command({ type: "timer.reset" });
    offline = false; await mobile.refresh(true);
    expect(mobile.project(phone.snapshot()).timer.remainingSec).toBe(900);
    expect(messages.at(-1)).toBe("");
  });

  it("serializes rapid reset and period commands without losing either update", async () => {
    const relay = new Relay();
    const runtime = new PublicRuntime({ edition: editionPolicy("Standard"), now: () => 2000 });
    await spawn(runtime, 1000); const session = client(relay, runtime, true); await session.refresh(true);
    const revision = relay.revision;
    await Promise.all([session.command({ type: "timer.reset" }), session.command({ type: "timer.set-cycle", minutes: 1 })]);
    expect(relay.revision).toBe(revision + 2);
    expect(session.project(runtime.snapshot()).timer).toMatchObject({ remainingSec: 60, cycleMinutes: 1 });
  });
});
