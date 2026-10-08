import { discoverBridgeEndpoint, fetchBridgeResource } from "./bridge-discovery";
import type { EditionCommand, EditionSnapshot, TimerPresentationState } from "./runtime-types";
import type { PublicRuntime } from "./public-runtime";

interface TimerResponse {
  accepted?: boolean;
  schema_version: number; epoch: string; revision: number; server_now_ms: number;
  anchor_at_ms: number; desktop_present: boolean; timer: TimerPresentationState | null;
  readers_present?: boolean;
}
interface Anchor { timer: TimerPresentationState; at: number; identity: string }
export type TimerCommand = Extract<EditionCommand, { type: "timer.reset" | "timer.set-cycle" }>;

/** Shared presentation uses Bridge uptime and browser monotonic time, never
 * cross-device wall clocks. Lifecycle remains in App; Bridge only sequences it. */
export class SharedTimerSession {
  readonly #runtime: PublicRuntime;
  readonly #mobile: boolean;
  readonly #fetcher: typeof fetch;
  readonly #endpoint: () => Promise<URL>;
  readonly #now: () => number;
  readonly #status: (message: string) => void;
  #state: TimerResponse | null = null;
  #anchor: Anchor | null = null;
  #localAnchor: Anchor | null = null;
  #localKey = "";
  #awaitingLocalSpawn = false;
  #busy = false;
  #commands: Promise<unknown> = Promise.resolve();
  #lastRefreshAt = Number.NEGATIVE_INFINITY;
  #lastAcceptedAt = Number.NEGATIVE_INFINITY;

  constructor(options: { runtime: PublicRuntime; mobile: boolean; fetcher?: typeof fetch;
    endpoint?: () => Promise<URL>; now?: () => number; onStatus?: (message: string) => void }) {
    this.#runtime = options.runtime; this.#mobile = options.mobile;
    this.#fetcher = options.fetcher ?? fetch;
    this.#endpoint = options.endpoint ?? (() => discoverBridgeEndpoint(this.#fetcher));
    this.#now = options.now ?? (() => performance.now());
    this.#status = options.onStatus ?? (() => {});
  }

  project(snapshot: EditionSnapshot): EditionSnapshot {
    const key = this.#runtime.timerPresentationKey();
    if (this.#localAnchor?.identity !== key) {
      this.#localAnchor = { timer: this.#runtime.timerPresentation(), at: this.#now(), identity: key };
    }
    const followsDesktop = this.#mobile && this.#state?.desktop_present && this.#now() - this.#lastAcceptedAt < 5000;
    const unpublishedLifecycle = this.#localKey !== key && !followsDesktop && !this.#awaitingLocalSpawn;
    const locallyConfirmed = snapshot.phase === "alive" || snapshot.phase === "loss-pending";
    const anchor = (unpublishedLifecycle || !locallyConfirmed && !followsDesktop ? null : this.#anchor) ?? this.#localAnchor;
    const timer = elapsedTimer(anchor, this.#now());
    const elapsed = timer.elapsed_sec, period = timer.cycle_seconds;
    return { ...snapshot, timer: {
      remainingSec: timer.active ? period - elapsed % period : null,
      progress: timer.active ? elapsed % period / period : 0,
      cycle: timer.active ? Math.floor(elapsed / period) + 1 : null,
      lifeIndex: timer.active ? timer.life_index : null, cycleMinutes: period / 60,
      cueIdentity: anchor.identity,
    } };
  }

  /** Called by the presentation clock; at most one network task at a time. */
  async refresh(force = false): Promise<void> {
    if (this.#busy || !force && this.#now() - this.#lastRefreshAt < 500) return;
    this.#busy = true; this.#lastRefreshAt = this.#now();
    try { await this.#synchronize(); }
    catch (error) {
      this.#status(error instanceof Error ? error.message : "计时同步等待 Bridge");
    } finally { this.#busy = false; }
  }

  command(command: TimerCommand): Promise<EditionSnapshot> {
    const task = this.#commands.then(async () => {
      // A command waits for the current refresh rather than racing an old PUT.
      while (this.#busy) await new Promise(resolve => setTimeout(resolve, 10));
      this.#busy = true;
      try {
        let remote: TimerResponse;
        try { remote = await this.#request("GET"); }
        catch (error) {
          if (this.#mobile) throw error;
          return this.#runtime.command(command); // Ordinary Web on an older Bridge.
        }
        const continuing = this.#state?.epoch === remote.epoch || remote.readers_present === true
          || this.#mobile && remote.desktop_present;
        this.#accept(remote, continuing);
        const prior = this.#anchor ? elapsedTimer(this.#anchor, this.#now()) : this.#runtime.timerPresentation();
        const snapshot = await this.#runtime.command(command);
        const local = this.#runtime.timerPresentation();
        let commandKey = this.#runtime.timerPresentationKey();
        let desired = command.type === "timer.reset" ? { ...local, elapsed_sec: 0 }
          : { ...prior, cycle_seconds: command.minutes * 60 };
        for (let attempt = 0; attempt < 3; attempt++) {
          const result = await this.#request("PUT", remote, desired);
          if (commandKey !== this.#runtime.timerPresentationKey()) {
            this.#accept(result, false);
            this.#localKey = commandKey;
            return this.project(this.#runtime.snapshot());
          }
          this.#accept(result);
          commandKey = this.#runtime.timerPresentationKey();
          if (result.accepted) {
            this.#localKey = this.#runtime.timerPresentationKey();
            return this.project(snapshot);
          }
          remote = result;
          if (command.type === "timer.set-cycle" && this.#anchor) {
            desired = { ...elapsedTimer(this.#anchor, this.#now()), cycle_seconds: command.minutes * 60 };
          }
        }
        throw new Error("计时状态同时发生变化，请重试");
      } finally { this.#busy = false; }
    });
    this.#commands = task.catch(() => undefined);
    return task;
  }

  async #synchronize(): Promise<void> {
    if (this.#runtime.timerRecoveryPending()) return;
    const remote = await this.#request("GET");
    const local = this.#runtime.timerPresentation(), key = this.#runtime.timerPresentationKey();
    const first = !this.#state || this.#state.epoch !== remote.epoch;
    const mayPublish = !this.#mobile || !remote.desktop_present;
    // Older Bridges cannot prove another page is still observing this timer.
    // A paired phone can still follow their actively polling desktop owner.
    const continuing = remote.readers_present === true || this.#mobile && remote.desktop_present;
    const snapshot = this.#runtime.snapshot();
    const observedInactive = !local.active && snapshot.connected && snapshot.mapObjectsFresh === true && snapshot.phase !== "arming";
    let changed = this.#localKey !== key || this.#mobile && !remote.desktop_present
      && this.#state?.desktop_present === true && local.active !== remote.timer?.active;
    if (remote.timer?.active && observedInactive) {
      changed = true;
      this.#awaitingLocalSpawn = false;
    }
    if (this.#awaitingLocalSpawn && local.active && remote.timer?.active) {
      changed = false; this.#awaitingLocalSpawn = false;
    }
    if (first && continuing && !observedInactive && remote.timer?.active && !local.active) this.#awaitingLocalSpawn = true;
    // A previous page may have left Bridge idle before this page observed spawn.
    // The local lifecycle owner must publish that spawn even on its first read.
    const result = (!remote.timer || first && (!continuing || observedInactive || local.active && !remote.timer.active) || !first && changed) && mayPublish
      ? await this.#request("PUT", remote, local) : remote;
    // Telemetry keeps running during PUT. A response for the pre-spawn/death
    // state must neither rebase the new life nor mark its change as published.
    const changedDuringRequest = key !== this.#runtime.timerPresentationKey();
    this.#accept(result, !changedDuringRequest);
    this.#localKey = changedDuringRequest ? key : this.#runtime.timerPresentationKey();
    this.#status("");
  }

  #accept(value: TimerResponse, applyTimer = true): void {
    if (this.#state?.epoch === value.epoch && value.revision < this.#state.revision) return;
    this.#state = value;
    this.#lastAcceptedAt = this.#now();
    if (!value.timer || !applyTimer) { this.#anchor = null; return; }
    // #request rebases elapsed to the receive instant using midpoint RTT.
    this.#anchor = { timer: value.timer, at: this.#now(), identity: `${value.epoch}:${value.revision}` };
    this.#runtime.rebaseTimerPresentation(value.timer);
  }

  async #request(method: "GET" | "PUT", expected?: TimerResponse, timer?: TimerPresentationState): Promise<TimerResponse> {
    const base = await this.#endpoint(), started = this.#now();
    const response = await fetchBridgeResource(this.#fetcher, new URL("api/v1/presentation/timer", base), {
      method, mode: "cors", cache: "no-store", credentials: "omit", referrerPolicy: "no-referrer",
      signal: AbortSignal.timeout(1500),
      headers: method === "PUT" ? { Accept: "application/json", "Content-Type": "application/json" } : { Accept: "application/json" },
      ...(method === "PUT" ? { body: JSON.stringify({ schema_version: 1, epoch: expected!.epoch,
        expected_revision: expected!.revision, timer }) } : {}),
    });
    if (response.status === 404) throw new Error("手机同步计时需要更新 Bridge，请到启动器下载新版");
    if (!response.ok && response.status !== 409) throw new Error(`计时同步暂不可用（${response.status}）`);
    const value: unknown = await response.json();
    if (!validResponse(value)) throw new Error("Bridge 计时响应无效");
    const received = this.#now();
    return { ...value, accepted: response.ok, timer: value.timer ? { ...value.timer,
      elapsed_sec: value.timer.elapsed_sec + (value.timer.active
        ? (value.server_now_ms - value.anchor_at_ms + Math.min(1500, received - started) / 2) / 1000 : 0) } : null };
  }
}

function elapsedTimer(anchor: Anchor, now: number): TimerPresentationState {
  return { ...anchor.timer, elapsed_sec: anchor.timer.elapsed_sec
    + (anchor.timer.active ? Math.max(0, now - anchor.at) / 1000 : 0) };
}
function validResponse(value: unknown): value is TimerResponse {
  if (!value || typeof value !== "object") return false;
  const v = value as TimerResponse, t = v.timer;
  return v.schema_version === 1 && typeof v.epoch === "string" && /^[A-Za-z0-9_-]{16,64}$/.test(v.epoch)
    && Number.isSafeInteger(v.revision) && v.revision >= 0 && typeof v.desktop_present === "boolean"
    && (v.readers_present === undefined || typeof v.readers_present === "boolean")
    && Number.isFinite(v.server_now_ms) && Number.isFinite(v.anchor_at_ms)
    && v.server_now_ms >= v.anchor_at_ms && v.anchor_at_ms >= 0
    && (t === null || !!t && typeof t.active === "boolean" && Number.isFinite(t.elapsed_sec)
      && t.elapsed_sec >= 0 && t.elapsed_sec <= 604800 && Number.isInteger(t.cycle_seconds)
      && t.cycle_seconds >= 60 && t.cycle_seconds <= 10800 && t.cycle_seconds % 60 === 0
      && Number.isInteger(t.life_index) && t.life_index >= (t.active ? 1 : 0) && t.life_index <= 1000000);
}
