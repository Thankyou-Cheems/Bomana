import { discoverBridgeEndpoint, fetchBridgeResource } from "./runtime/bridge-discovery";
import type { PublicFrame } from "./public-runtime";

export class PublicTelemetry {
  readonly #fetch: typeof fetch;
  readonly #configuredUrl: string;
  readonly #includeNavigation: boolean;
  #mapInfo: Readonly<Record<string, unknown>> | null = null;
  #mapInfoFetchedAtMs = 0;

  constructor(
    configuredUrl = import.meta.env.VITE_BRIDGE_URL || "",
    fetcher: typeof fetch = fetch,
    options: { readonly includeNavigation?: boolean } = {},
  ) {
    this.#configuredUrl = configuredUrl;
    this.#fetch = fetcher.bind(globalThis);
    this.#includeNavigation = options.includeNavigation ?? true;
  }

  async read(nowMs = Date.now()): Promise<PublicFrame> {
    try {
      const base = await discoverBridgeEndpoint(this.#fetch, this.#configuredUrl);
      const needsMapInfo = nowMs - this.#mapInfoFetchedAtMs >= 30_000;
      const [indicators, state, mapObjects, mapInfo] = await Promise.all([
        this.#json(new URL("api/v1/8111/indicators", base)),
        this.#json(new URL("api/v1/8111/state", base)),
        this.#includeNavigation ? this.#json(new URL("api/v1/8111/map-objects", base)) : Promise.resolve(null),
        this.#includeNavigation && needsMapInfo
          ? this.#json(new URL("api/v1/8111/map-info", base))
          : Promise.resolve(this.#mapInfo),
      ]);
      if (record(mapInfo)) {
        this.#mapInfo = record(mapInfo);
        this.#mapInfoFetchedAtMs = nowMs;
      }
      return Object.freeze({
        sampledAtMs: nowMs,
        connected: Boolean(record(indicators) || record(state) || Array.isArray(mapObjects)),
        indicators: record(indicators),
        state: record(state),
        mapObjects: Array.isArray(mapObjects) ? Object.freeze(mapObjects) : null,
        mapInfo: this.#mapInfo,
      });
    } catch {
      return Object.freeze({ sampledAtMs: nowMs, connected: false, indicators: null, state: null, mapObjects: null, mapInfo: this.#mapInfo });
    }
  }

  async #json(url: URL): Promise<unknown> {
    const response = await fetchBridgeResource(this.#fetch, url, {
      method: "GET", mode: "cors", cache: "no-store", credentials: "omit", redirect: "error",
      headers: { Accept: "application/json" },
    });
    if (!response.ok) return null;
    const text = await response.text();
    return text.length <= 2_097_152 ? JSON.parse(text) as unknown : null;
  }
}

function record(value: unknown): Readonly<Record<string, unknown>> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Readonly<Record<string, unknown>> : null;
}
