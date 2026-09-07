import {
  bridgeEndpointReachable,
  discoverBridgeEndpoint,
  fetchBridgeResource,
  forgetBridgeEndpoint,
  IncompatibleBridgeError,
  MobileBridgeError,
} from "./bridge-discovery";
import { normalizeOfficialMapInfo } from "./map-info";
import { abortableTask } from "./abortable-task";

export interface Observable8111State {
  readonly altitudeM: number;
  readonly horizontalSpeedMps: number;
  readonly verticalSpeedMps: number;
  readonly sampledAtMs: number;
}

export interface Official8111Frame {
  readonly sampledAtMs: number;
  readonly indicatorsSampledAtMs?: number | null;
  readonly stateSampledAtMs?: number | null;
  readonly mapObjectsSampledAtMs?: number | null;
  readonly bridgeReachable: boolean;
  readonly indicators: Readonly<Record<string, unknown>> | null;
  readonly state: Readonly<Record<string, unknown>> | null;
  readonly mapObjects: readonly unknown[] | Readonly<Record<string, unknown>> | null;
  readonly mapInfo: Readonly<Record<string, unknown>> | null;
  readonly gameChat?: readonly unknown[] | null;
  readonly availability: {
    readonly indicators: boolean;
    readonly state: boolean;
    readonly mapObjects: boolean;
    readonly mapInfo: boolean;
    readonly gameChat?: boolean;
  };
  readonly holdover?: {
    readonly indicators: boolean;
    readonly state: boolean;
    readonly mapObjects: boolean;
  };
}

export class TelemetryUnavailableError extends Error {}

export interface TelemetrySourceOptions {
  readonly includeGameChat?: boolean;
  readonly holdoverMs?: number;
}

export class TelemetrySource {
  readonly #configuredURL: string;
  readonly #fetch: typeof fetch;
  readonly #now: () => number;
  readonly #includeGameChat: boolean;
  readonly #holdoverMs: number;
  #mapInfo: Readonly<Record<string, unknown>> | null = null;
  #mapInfoFetchedAtMs = Number.NEGATIVE_INFINITY;
  #mapInfoPending = false;
  #gameChat: readonly unknown[] | null = null;
  #chatFetchedAtMs = Number.NEGATIVE_INFINITY;
  #chatPending = false;
  #auxiliaryController = new AbortController();
  #bridgeVerifiedAtMs = 0;
  #lastIndicators: CachedObservation<Readonly<Record<string, unknown>>> | null = null;
  #lastState: CachedObservation<Readonly<Record<string, unknown>>> | null = null;
  #lastMapObjects: CachedObservation<readonly unknown[] | Readonly<Record<string, unknown>>> | null = null;

  constructor(
    baseUrl = import.meta.env.VITE_BRIDGE_URL || "",
    fetchImplementation: typeof fetch = fetch,
    now: () => number = Date.now,
    options: TelemetrySourceOptions = {},
  ) {
    this.#configuredURL = baseUrl ? validateRelayBase(baseUrl).href : "";
    this.#fetch = fetchImplementation.bind(globalThis);
    this.#now = now;
    this.#includeGameChat = options.includeGameChat ?? true;
    this.#holdoverMs = boundedHoldover(options.holdoverMs);
  }

  async readState(signal?: AbortSignal): Promise<Observable8111State> {
    const observation = await this.#readTimedJson("api/v1/8111/state", 262_144, signal);
    const payload = observation.payload;
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
      throw new TelemetryUnavailableError("8111 state response is not an object");
    }
    const record = payload as Record<string, unknown>;
    const altitudeM = numberField(record, "H, m");
    const tasKmh = numberField(record, "TAS, km/h");
    const verticalSpeedMps = numberField(record, "Vy, m/s");
    const totalSpeedMps = tasKmh / 3.6;
    const horizontalSpeedMps = Math.sqrt(Math.max(0, totalSpeedMps ** 2 - verticalSpeedMps ** 2));
    if (horizontalSpeedMps < 10) throw new TelemetryUnavailableError("8111 speed is outside the solver domain");
    return Object.freeze({
      altitudeM,
      horizontalSpeedMps,
      verticalSpeedMps,
      sampledAtMs: observation.sampledAtMs,
    });
  }

  async readFrame(signal?: AbortSignal): Promise<Official8111Frame> {
    signal?.throwIfAborted();
    const attemptStartedAtMs = this.#now();
    let bridgeBase: URL;
    try {
      const discovery = discoverBridgeEndpoint(this.#fetch, this.#configuredURL, signal);
      bridgeBase = await (signal ? abortableTask(discovery, signal) : discovery);
      if (!this.#bridgeVerifiedAtMs) this.#bridgeVerifiedAtMs = attemptStartedAtMs;
    } catch (error) {
      signal?.throwIfAborted();
      if (error instanceof IncompatibleBridgeError || error instanceof MobileBridgeError && error.fatal) throw error;
      const failedAtMs = this.#now();
      return this.#applyHoldover(emptyFrame(failedAtMs, false, this.#mapInfo), failedAtMs);
    }
    this.#refreshAuxiliary(attemptStartedAtMs, this.#auxiliaryController.signal);
    const [indicatorObservation, stateObservation, mapObjectObservation] = await Promise.all([
      this.#readOptionalTimedObject("api/v1/8111/indicators", 262_144, signal),
      this.#readOptionalTimedObject("api/v1/8111/state", 262_144, signal),
      this.#readOptionalTimedJson("api/v1/8111/map-objects", 2_097_152, signal),
    ]);
    signal?.throwIfAborted();
    const indicators = indicatorObservation.payload;
    const state = stateObservation.payload;
    const mapObjects = mapObjectObservation.payload;
    const completedAtMs = this.#now();
    const chatMessages = completedAtMs - this.#chatFetchedAtMs <= 3_000 ? this.#gameChat : null;
    const sampledAtMs = indicatorObservation.sampledAtMs
      ?? stateObservation.sampledAtMs
      ?? mapObjectObservation.sampledAtMs
      ?? midpoint(attemptStartedAtMs, completedAtMs);
    const objectsValid = validMapObjectsPayload(mapObjects);
    const gameAvailable = indicators !== null || state !== null || objectsValid;
    let bridgeReachable = true;
    if (gameAvailable) {
      this.#bridgeVerifiedAtMs = completedAtMs;
    } else if (completedAtMs - this.#bridgeVerifiedAtMs >= 2_000) {
      bridgeReachable = await bridgeEndpointReachable(bridgeBase, this.#fetch, signal);
      this.#bridgeVerifiedAtMs = bridgeReachable ? completedAtMs : 0;
      if (!bridgeReachable) forgetBridgeEndpoint(bridgeBase);
    }
    signal?.throwIfAborted();
    return this.#applyHoldover(Object.freeze({
      sampledAtMs,
      indicatorsSampledAtMs: indicatorObservation.sampledAtMs,
      stateSampledAtMs: stateObservation.sampledAtMs,
      mapObjectsSampledAtMs: objectsValid ? mapObjectObservation.sampledAtMs : null,
      bridgeReachable,
      indicators,
      state,
      mapObjects: objectsValid
        ? mapObjects as readonly unknown[] | Readonly<Record<string, unknown>>
        : null,
      mapInfo: this.#mapInfo,
      gameChat: chatMessages,
      availability: Object.freeze({
        indicators: indicators !== null,
        state: state !== null,
        mapObjects: objectsValid,
        mapInfo: this.#mapInfo !== null,
        gameChat: chatMessages !== null,
      }),
      holdover: Object.freeze({ indicators: false, state: false, mapObjects: false }),
    }), completedAtMs);
  }

  cancelPending(): void {
    this.#auxiliaryController.abort();
    this.#auxiliaryController = new AbortController();
    this.#gameChat = null;
    this.#mapInfoFetchedAtMs = Number.NEGATIVE_INFINITY;
    this.#chatFetchedAtMs = Number.NEGATIVE_INFINITY;
  }

  #refreshAuxiliary(nowMs: number, signal?: AbortSignal): void {
    if (!this.#mapInfoPending && nowMs - this.#mapInfoFetchedAtMs >= (this.#mapInfo ? 30_000 : 1_000)) {
      this.#mapInfoPending = true;
      this.#mapInfoFetchedAtMs = nowMs;
      void this.#readOptionalObject("api/v1/8111/map-info", 262_144, signal).then(mapInfo => {
        if (!signal?.aborted && mapInfo && normalizeOfficialMapInfo(mapInfo)) this.#mapInfo = mapInfo;
      }).finally(() => { this.#mapInfoPending = false; });
    }
    if (this.#includeGameChat && !this.#chatPending && nowMs - this.#chatFetchedAtMs >= 1_000) {
      this.#chatPending = true;
      this.#chatFetchedAtMs = nowMs;
      void this.#readOptionalJson("api/v1/8111/gamechat", 262_144, signal).then(chat => {
        if (!signal?.aborted) this.#gameChat = Array.isArray(chat) ? chat : null;
      }).finally(() => { this.#chatPending = false; });
    }
  }

  #applyHoldover(frame: Official8111Frame, nowMs: number): Official8111Frame {
    const indicators = retainObservation(
      frame.indicators,
      frame.indicatorsSampledAtMs ?? null,
      this.#lastIndicators,
      nowMs,
      this.#holdoverMs,
    );
    const state = retainObservation(
      frame.state,
      frame.stateSampledAtMs ?? null,
      this.#lastState,
      nowMs,
      this.#holdoverMs,
    );
    const mapObjects = retainObservation(
      frame.mapObjects,
      frame.mapObjectsSampledAtMs ?? null,
      this.#lastMapObjects,
      nowMs,
      this.#holdoverMs,
    );
    this.#lastIndicators = indicators.cache;
    this.#lastState = state.cache;
    this.#lastMapObjects = mapObjects.cache;
    return Object.freeze({
      ...frame,
      indicators: indicators.payload,
      state: state.payload,
      mapObjects: mapObjects.payload,
      indicatorsSampledAtMs: indicators.sampledAtMs,
      stateSampledAtMs: state.sampledAtMs,
      mapObjectsSampledAtMs: mapObjects.sampledAtMs,
      availability: Object.freeze({
        ...frame.availability,
        indicators: indicators.payload !== null,
        state: state.payload !== null,
        mapObjects: mapObjects.payload !== null,
      }),
      holdover: Object.freeze({
        indicators: indicators.held,
        state: state.held,
        mapObjects: mapObjects.held,
      }),
    });
  }

  async #readOptionalObject(
    path: string,
    maxBytes: number,
    signal?: AbortSignal,
  ): Promise<Readonly<Record<string, unknown>> | null> {
    const payload = await this.#readOptionalJson(path, maxBytes, signal);
    return payload && typeof payload === "object" && !Array.isArray(payload) && Object.keys(payload).length > 0
      ? payload as Readonly<Record<string, unknown>>
      : null;
  }

  async #readOptionalTimedObject(
    path: string,
    maxBytes: number,
    signal?: AbortSignal,
  ): Promise<TimedObservation<Readonly<Record<string, unknown>>>> {
    const observation = await this.#readOptionalTimedJson(path, maxBytes, signal);
    const payload = observation.payload;
    return payload && typeof payload === "object" && !Array.isArray(payload) && Object.keys(payload).length > 0
      ? { payload: payload as Readonly<Record<string, unknown>>, sampledAtMs: observation.sampledAtMs }
      : { payload: null, sampledAtMs: null };
  }

  async #readOptionalJson(path: string, maxBytes: number, signal?: AbortSignal): Promise<unknown | null> {
    try {
      return await this.#readJson(path, maxBytes, signal);
    } catch {
      return null;
    }
  }

  async #readOptionalTimedJson(
    path: string,
    maxBytes: number,
    signal?: AbortSignal,
  ): Promise<TimedObservation<unknown>> {
    try {
      return await this.#readTimedJson(path, maxBytes, signal);
    } catch {
      return { payload: null, sampledAtMs: null };
    }
  }

  async #readTimedJson(
    path: string,
    maxBytes: number,
    signal?: AbortSignal,
  ): Promise<{ readonly payload: unknown; readonly sampledAtMs: number }> {
    const startedAtMs = this.#now();
    const payload = await this.#readJson(path, maxBytes, signal);
    return { payload, sampledAtMs: midpoint(startedAtMs, this.#now()) };
  }

  async #readJson(path: string, maxBytes: number, signal?: AbortSignal): Promise<unknown> {
    const startedAtMs = this.#now();
    const deadline = new AbortController();
    const abort = (): void => deadline.abort(signal?.reason);
    if (signal?.aborted) abort();
    else signal?.addEventListener("abort", abort, { once: true });
    const timer = globalThis.setTimeout(() => deadline.abort(new Error("8111 request timed out")), 1_500);
    try {
      const value = await abortableTask(this.#fetchJson(path, maxBytes, deadline.signal), deadline.signal);
      if (this.#now() - startedAtMs > 1_500) throw new TelemetryUnavailableError("8111 response expired while the page was suspended");
      return value;
    } finally {
      globalThis.clearTimeout(timer);
      signal?.removeEventListener("abort", abort);
    }
  }

  async #fetchJson(path: string, maxBytes: number, signal: AbortSignal): Promise<unknown> {
    const baseURL = await discoverBridgeEndpoint(this.#fetch, this.#configuredURL, signal);
    signal.throwIfAborted();
    const response = await fetchBridgeResource(this.#fetch, new URL(path, baseURL), {
      method: "GET",
      mode: "cors",
      cache: "no-store",
      credentials: "omit",
      redirect: "error",
      signal,
      headers: { Accept: "application/json" },
    });
    if (!response.ok) throw new TelemetryUnavailableError(`8111 relay returned ${response.status}`);
    const text = await response.text();
    signal.throwIfAborted();
    if (text.length > maxBytes) throw new TelemetryUnavailableError("8111 response is too large");
    try {
      return JSON.parse(text) as unknown;
    } catch {
      throw new TelemetryUnavailableError("8111 response is invalid JSON");
    }
  }
}

interface TimedObservation<T> {
  readonly payload: T | null;
  readonly sampledAtMs: number | null;
}

interface CachedObservation<T> {
  readonly payload: T;
  readonly sampledAtMs: number;
  readonly receivedAtMs: number;
}

function retainObservation<T>(
  payload: T | null,
  sampledAtMs: number | null,
  cache: CachedObservation<T> | null,
  nowMs: number,
  holdoverMs: number,
): { readonly payload: T | null; readonly sampledAtMs: number | null; readonly held: boolean; readonly cache: CachedObservation<T> | null } {
  if (payload !== null) {
    const next = Object.freeze({ payload, sampledAtMs: sampledAtMs ?? nowMs, receivedAtMs: nowMs });
    return { payload, sampledAtMs: next.sampledAtMs, held: false, cache: next };
  }
  const ageMs = cache ? nowMs - cache.receivedAtMs : Number.POSITIVE_INFINITY;
  if (cache && ageMs >= 0 && ageMs <= holdoverMs) {
    return { payload: cache.payload, sampledAtMs: cache.sampledAtMs, held: true, cache };
  }
  return { payload: null, sampledAtMs: null, held: false, cache: null };
}

function boundedHoldover(value: number | undefined): number {
  if (value === undefined) return 3_000;
  if (!Number.isFinite(value) || value < 0) throw new TypeError("8111 holdover must be a non-negative duration");
  return Math.min(3_000, value);
}

function emptyFrame(
  sampledAtMs: number,
  bridgeReachable: boolean,
  mapInfo: Readonly<Record<string, unknown>> | null,
): Official8111Frame {
  return Object.freeze({
    sampledAtMs,
    indicatorsSampledAtMs: null,
    stateSampledAtMs: null,
    mapObjectsSampledAtMs: null,
    bridgeReachable,
    indicators: null,
    state: null,
    mapObjects: null,
    mapInfo,
    gameChat: null,
    availability: Object.freeze({ indicators: false, state: false, mapObjects: false, mapInfo: mapInfo !== null, gameChat: false }),
    holdover: Object.freeze({ indicators: false, state: false, mapObjects: false }),
  });
}

function validateRelayBase(raw: string): URL {
  const url = new URL(raw);
  if (
    url.protocol !== "http:" ||
    !["127.0.0.1", "localhost", "[::1]"].includes(url.hostname) ||
    url.username ||
    url.password ||
    url.search ||
    url.hash
  ) {
    throw new TypeError("8111 relay must be an uncredentialed loopback HTTP origin");
  }
  url.pathname = "/";
  return url;
}

function numberField(record: Record<string, unknown>, key: string): number {
  const value = record[key];
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new TelemetryUnavailableError(`8111 field is unavailable: ${key}`);
  }
  return value;
}

function midpoint(startedAtMs: number, completedAtMs: number): number {
  return startedAtMs + Math.max(0, completedAtMs - startedAtMs) / 2;
}

function validMapObjectsPayload(value: unknown): boolean {
  if (Array.isArray(value)) return true;
  if (!value || typeof value !== "object") return false;
  const record = value as Readonly<Record<string, unknown>>;
  return ["objects", "map_objects", "items", "data"].some((key) => Array.isArray(record[key]));
}
