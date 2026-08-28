import { discoverBridgeEndpoint, fetchBridgeResource } from "./bridge-discovery";

export type OfflineAssetKind = "terrain" | "weapon" | "airfield" | "reference" | "wasm";

export interface OfflineAssetDescriptor {
  readonly id: string;
  readonly kind: OfflineAssetKind;
  readonly sha256: string;
  readonly sizeBytes: number;
  readonly url: URL;
}

export interface OfflineCacheStatus {
  readonly objectCount: number;
  readonly objectBytes: number;
  readonly persistent: boolean | null;
  readonly quotaBytes: number | null;
  readonly usageBytes: number | null;
  readonly storageKind: "bridge" | "memory";
  readonly state?: "checking" | "syncing" | "ready" | "degraded";
  readonly mapCount?: number;
  readonly cachedMapCount?: number;
  readonly selectedMapCount?: number;
  readonly selectedCachedMapCount?: number;
  readonly totalBytes?: number;
  readonly cachedBytes?: number;
  readonly maps?: readonly OfflineMapCacheStatus[];
  readonly error?: string;
}

export interface OfflineMapCacheStatus {
  readonly id: string;
  readonly state: "not-selected" | "pending" | "downloading" | "cached" | "error";
  readonly selected: boolean;
  readonly cachedBytes: number;
  readonly totalBytes: number;
  readonly error?: string;
}

interface StorageStats {
  readonly count: number;
  readonly bytes: number;
  readonly cache?: Omit<OfflineCacheStatus, "objectCount" | "objectBytes" | "persistent" | "quotaBytes" | "usageBytes" | "storageKind">;
}

export interface AssetObjectStorage {
  readonly kind: OfflineCacheStatus["storageKind"];
  read(sha256: string): Promise<ArrayBuffer | null>;
  write(sha256: string, bytes: ArrayBuffer): Promise<void>;
  remove(sha256: string): Promise<void>;
  stats(): Promise<StorageStats>;
  selectTerrainMaps?(mapIds: readonly string[]): Promise<void>;
  readTerrainCatalog?(): Promise<ArrayBuffer | null>;
}

type Fetcher = typeof fetch;
type ProgressCallback = (receivedBytes: number, totalBytes: number) => void;

const MAX_OBJECT_BYTES = 256 * 1024 * 1024;

export class PersistentAssetStore {
  readonly #storage: AssetObjectStorage;
  readonly #fetcher: Fetcher;
  readonly #inFlight = new Map<string, Promise<ArrayBuffer>>();
  readonly #verified = new Set<string>();

  constructor(storage: AssetObjectStorage, fetcher: Fetcher = fetch) {
    this.#storage = storage;
    this.#fetcher = (input, init) => fetcher(input, init);
  }

  static async openBridge(): Promise<PersistentAssetStore> {
    return new PersistentAssetStore(new BridgeAssetObjectStorage(import.meta.env.VITE_BRIDGE_URL || ""));
  }

  static async openSession(): Promise<PersistentAssetStore> {
    return new PersistentAssetStore(new MemoryAssetObjectStorage());
  }

  load(descriptor: OfflineAssetDescriptor, onProgress?: ProgressCallback): Promise<ArrayBuffer> {
    validateDescriptor(descriptor);
    const pending = this.#inFlight.get(descriptor.sha256);
    if (pending) return pending.then(cloneBuffer);
    const request = this.#load(descriptor, onProgress).finally(() => this.#inFlight.delete(descriptor.sha256));
    this.#inFlight.set(descriptor.sha256, request);
    return request.then(cloneBuffer);
  }

  async status(): Promise<OfflineCacheStatus> {
    const objects = await this.#storage.stats();
    return Object.freeze({
      objectCount: objects.count,
      objectBytes: objects.bytes,
      persistent: this.#storage.kind === "bridge" ? true : null,
      quotaBytes: null,
      usageBytes: null,
      storageKind: this.#storage.kind,
      ...objects.cache,
    });
  }

  async selectTerrainMaps(mapIds: readonly string[]): Promise<void> {
    if (!this.#storage.selectTerrainMaps) throw new Error("当前存储不支持地形选择");
    await this.#storage.selectTerrainMaps(mapIds);
  }

  async terrainCatalog(): Promise<ArrayBuffer | null> {
    return this.#storage.readTerrainCatalog?.() ?? null;
  }

  async terrainMapSelected(mapId: string): Promise<boolean | null> {
    if (this.#storage.kind !== "bridge") return null;
    const map = (await this.status()).maps?.find((item) => item.id === mapId);
    return map?.selected ?? false;
  }

  async #load(descriptor: OfflineAssetDescriptor, onProgress?: ProgressCallback): Promise<ArrayBuffer> {
    const cached = await this.#storage.read(descriptor.sha256);
    if (cached) {
      if (cached.byteLength === descriptor.sizeBytes && (
        this.#verified.has(descriptor.sha256)
        || await sha256Hex(cached) === descriptor.sha256
      )) {
        this.#verified.add(descriptor.sha256);
        onProgress?.(descriptor.sizeBytes, descriptor.sizeBytes);
        return cached;
      }
      await this.#storage.remove(descriptor.sha256);
      this.#verified.delete(descriptor.sha256);
    }
    if (this.#storage.kind === "bridge") {
      throw new Error(`Bridge 正在下载离线资源：${descriptor.id}`);
    }
    const bytes = await downloadExact(this.#fetcher, descriptor, onProgress);
    if (await sha256Hex(bytes) !== descriptor.sha256) {
      throw new Error(`离线资源校验失败：${descriptor.id}`);
    }
    await this.#storage.write(descriptor.sha256, bytes);
    this.#verified.add(descriptor.sha256);
    return bytes;
  }
}

export class BridgeAssetObjectStorage implements AssetObjectStorage {
  readonly kind = "bridge" as const;
  readonly #configuredURL: string;
  readonly #fetcher: Fetcher;
  constructor(configuredURL: string | URL = "", fetcher: Fetcher = fetch) {
    this.#configuredURL = String(configuredURL);
    this.#fetcher = (input, init) => fetcher(input, init);
  }
  async read(sha256: string): Promise<ArrayBuffer | null> {
    const response = await fetchBridgeResource(this.#fetcher, await this.#objectURL(sha256), { method: "GET", cache: "no-store", credentials: "omit", referrerPolicy: "no-referrer" });
    if (response.status === 404) return null;
    if (!response.ok) throw new Error(`Bridge 缓存读取失败 (${response.status})`);
    return response.arrayBuffer();
  }
  async write(sha256: string, bytes: ArrayBuffer): Promise<void> {
    const response = await fetchBridgeResource(this.#fetcher, await this.#objectURL(sha256), {
      method: "PUT", cache: "no-store", credentials: "omit", referrerPolicy: "no-referrer",
      headers: { "Content-Type": "application/octet-stream" }, body: bytes,
    });
    if (!response.ok) throw new Error(`Bridge 缓存写入失败 (${response.status})`);
  }
  async remove(sha256: string): Promise<void> {
    const response = await fetchBridgeResource(this.#fetcher, await this.#objectURL(sha256), { method: "DELETE", cache: "no-store", credentials: "omit", referrerPolicy: "no-referrer" });
    if (!response.ok && response.status !== 404) throw new Error(`Bridge 缓存清理失败 (${response.status})`);
  }
  async stats(): Promise<StorageStats> {
    const baseURL = await discoverBridgeEndpoint(this.#fetcher, this.#configuredURL);
    const response = await fetchBridgeResource(this.#fetcher, new URL("api/v1/cache/status", baseURL), { method: "GET", cache: "no-store", credentials: "omit", referrerPolicy: "no-referrer" });
    if (!response.ok) throw new Error(`Bridge 缓存状态不可用 (${response.status})`);
    const status = parseBridgeCacheStatus(await response.json());
    return {
      count: status.cachedObjectCount,
      bytes: status.cachedBytes,
      cache: {
        state: status.state, mapCount: status.mapCount, cachedMapCount: status.cachedMapCount,
        selectedMapCount: status.selectedMapCount, selectedCachedMapCount: status.selectedCachedMapCount,
        totalBytes: status.totalBytes, cachedBytes: status.cachedBytes, maps: status.maps, error: status.error,
      },
    };
  }
  async selectTerrainMaps(mapIds: readonly string[]): Promise<void> {
    const baseURL = await discoverBridgeEndpoint(this.#fetcher, this.#configuredURL);
    const response = await fetchBridgeResource(this.#fetcher, new URL("api/v1/cache/selection", baseURL), {
      method: "PUT", cache: "no-store", credentials: "omit", referrerPolicy: "no-referrer",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify({ map_ids: mapIds }),
    });
    if (!response.ok) throw new Error(`Bridge 地形选择失败 (${response.status})`);
  }
  async readTerrainCatalog(): Promise<ArrayBuffer | null> {
    const baseURL = await discoverBridgeEndpoint(this.#fetcher, this.#configuredURL);
    const response = await fetchBridgeResource(this.#fetcher, new URL("api/v1/cache/catalog", baseURL), {
      method: "GET", cache: "no-store", credentials: "omit", referrerPolicy: "no-referrer",
    });
    if (response.status === 404 || response.status === 503) return null;
    if (!response.ok) throw new Error(`Bridge 地形目录不可用 (${response.status})`);
    const bytes = await response.arrayBuffer();
    if (bytes.byteLength <= 0 || bytes.byteLength > 4 * 1024 * 1024) throw new Error("Bridge 地形目录大小无效");
    return bytes;
  }
  async #objectURL(sha256: string): Promise<URL> {
    return new URL(`api/v1/cache/objects/${sha256}`, await discoverBridgeEndpoint(this.#fetcher, this.#configuredURL));
  }
}

let sharedBridgeStore: Promise<PersistentAssetStore> | null = null;
let sharedSessionStore: Promise<PersistentAssetStore> | null = null;
export function openBridgeAssetStore(): Promise<PersistentAssetStore> {
  sharedBridgeStore ??= PersistentAssetStore.openBridge();
  return sharedBridgeStore;
}
export function openSessionAssetStore(): Promise<PersistentAssetStore> {
  sharedSessionStore ??= PersistentAssetStore.openSession();
  return sharedSessionStore;
}

export class MemoryAssetObjectStorage implements AssetObjectStorage {
  readonly kind = "memory" as const;
  readonly objects = new Map<string, ArrayBuffer>();

  async read(sha256: string): Promise<ArrayBuffer | null> {
    const value = this.objects.get(sha256);
    return value ? cloneBuffer(value) : null;
  }
  async write(sha256: string, bytes: ArrayBuffer): Promise<void> {
    this.objects.set(sha256, cloneBuffer(bytes));
  }
  async remove(sha256: string): Promise<void> { this.objects.delete(sha256); }
  async stats(): Promise<{ count: number; bytes: number }> {
    return { count: this.objects.size, bytes: [...this.objects.values()].reduce((sum, value) => sum + value.byteLength, 0) };
  }
}

function parseBridgeCacheStatus(value: unknown): {
  state: "checking" | "syncing" | "ready" | "degraded";
  mapCount: number; cachedMapCount: number; selectedMapCount: number; selectedCachedMapCount: number;
  cachedObjectCount: number; totalBytes: number; cachedBytes: number;
  maps: readonly OfflineMapCacheStatus[]; error?: string;
} {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Bridge 缓存状态无效");
  const record = value as Record<string, unknown>;
  const state = String(record.state);
  const maps = Array.isArray(record.maps) ? record.maps.map((item) => {
    if (!item || typeof item !== "object" || Array.isArray(item)) throw new Error("Bridge 地图缓存状态无效");
    const map = item as Record<string, unknown>;
    const parsed = { id: String(map.id), state: String(map.state), selected: map.selected === true, cachedBytes: Number(map.cached_bytes), totalBytes: Number(map.total_bytes), ...(typeof map.error === "string" && map.error ? { error: map.error } : {}) };
    if (!/^[A-Za-z0-9_.-]+$/.test(parsed.id) || !["not-selected", "pending", "downloading", "cached", "error"].includes(parsed.state)
      || !Number.isFinite(parsed.cachedBytes) || !Number.isFinite(parsed.totalBytes)) throw new Error("Bridge 地图缓存状态无效");
    return parsed as OfflineMapCacheStatus;
  }) : [];
  if (record.schema_version !== 1 || !["checking", "syncing", "ready", "degraded"].includes(state)) throw new Error("Bridge 缓存状态无效");
  return {
    state: state as "checking" | "syncing" | "ready" | "degraded",
    mapCount: Number(record.map_count), cachedMapCount: Number(record.cached_map_count),
    selectedMapCount: Number(record.selected_map_count), selectedCachedMapCount: Number(record.selected_cached_map_count),
    cachedObjectCount: Number(record.cached_object_count),
    totalBytes: Number(record.total_bytes), cachedBytes: Number(record.cached_bytes), maps,
    ...(typeof record.error === "string" && record.error ? { error: record.error } : {}),
  };
}

async function downloadExact(fetcher: Fetcher, descriptor: OfflineAssetDescriptor, onProgress?: ProgressCallback): Promise<ArrayBuffer> {
  const response = await fetcher(descriptor.url, { cache: "force-cache", credentials: "same-origin", referrerPolicy: "no-referrer" });
  if (!response.ok) throw new Error(`离线资源下载失败 (${response.status})：${descriptor.id}`);
  const declared = Number(response.headers.get("Content-Length"));
  const contentEncoding = response.headers.get("Content-Encoding");
  if (!contentEncoding && Number.isFinite(declared) && declared > 0 && declared !== descriptor.sizeBytes) {
    throw new Error(`离线资源大小不匹配：${descriptor.id}`);
  }
  const output = new Uint8Array(descriptor.sizeBytes);
  let received = 0;
  if (response.body) {
    const reader = response.body.getReader();
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      if (received + value.byteLength > output.byteLength) {
        await reader.cancel();
        throw new Error(`离线资源超过清单大小：${descriptor.id}`);
      }
      output.set(value, received);
      received += value.byteLength;
      onProgress?.(received, descriptor.sizeBytes);
    }
  } else {
    const bytes = new Uint8Array(await response.arrayBuffer());
    if (bytes.byteLength <= output.byteLength) output.set(bytes);
    received = bytes.byteLength;
    onProgress?.(received, descriptor.sizeBytes);
  }
  if (received !== descriptor.sizeBytes) throw new Error(`离线资源下载不完整：${descriptor.id}`);
  return output.buffer;
}

function validateDescriptor(descriptor: OfflineAssetDescriptor): void {
  if (!/^[a-z][a-z0-9._-]{0,95}$/.test(descriptor.id)) throw new TypeError("offline asset id is invalid");
  if (!/^[a-f0-9]{64}$/.test(descriptor.sha256)) throw new TypeError("offline asset digest is invalid");
  if (!Number.isInteger(descriptor.sizeBytes) || descriptor.sizeBytes <= 0 || descriptor.sizeBytes > MAX_OBJECT_BYTES) {
    throw new TypeError("offline asset size is invalid");
  }
  if (descriptor.url.protocol !== "https:" && !(descriptor.url.protocol === "http:" && isLoopback(descriptor.url.hostname))) {
    throw new TypeError("offline asset URL must use HTTPS");
  }
}

async function sha256Hex(bytes: ArrayBuffer): Promise<string> {
  const digest = await globalThis.crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)].map((value) => value.toString(16).padStart(2, "0")).join("");
}

function cloneBuffer(value: ArrayBuffer): ArrayBuffer { return value.slice(0); }
function isLoopback(host: string): boolean { return host === "127.0.0.1" || host === "localhost" || host === "[::1]"; }
