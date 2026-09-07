import { createHash } from "node:crypto";
import { describe, expect, it, vi } from "vitest";
import { BridgeAssetObjectStorage, MemoryAssetObjectStorage, PersistentAssetStore, type AssetObjectStorage, type OfflineAssetDescriptor } from "./persistent-asset-store";

function descriptor(bytes: Uint8Array): OfflineAssetDescriptor {
  return {
    id: "weapon-catalog",
    kind: "weapon",
    sha256: createHash("sha256").update(bytes).digest("hex"),
    sizeBytes: bytes.byteLength,
    url: new URL("https://cdn.example.test/objects/weapon-catalog"),
  };
}

describe("PersistentAssetStore", () => {
  it("downloads once and reuses a content-addressed object across store instances", async () => {
    const bytes = new TextEncoder().encode("stable offline catalog");
    const storage = new MemoryAssetObjectStorage();
    const fetcher = vi.fn(async () => new Response(bytes, { status: 200, headers: { "Content-Length": String(bytes.byteLength) } }));
    const first = new PersistentAssetStore(storage, fetcher as typeof fetch);
    expect(new TextDecoder().decode(await first.load(descriptor(bytes)))).toBe("stable offline catalog");
    const afterReload = new PersistentAssetStore(storage, fetcher as typeof fetch);
    expect(new TextDecoder().decode(await afterReload.load(descriptor(bytes)))).toBe("stable offline catalog");
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("removes a corrupt cached object and repairs it from the CDN", async () => {
    const valid = new TextEncoder().encode("valid catalog bytes");
    const storage = new MemoryAssetObjectStorage();
    storage.objects.set(descriptor(valid).sha256, new TextEncoder().encode("same-size-corrupt!").buffer);
    const fetcher = vi.fn(async () => new Response(valid, { status: 200 }));
    const store = new PersistentAssetStore(storage, fetcher as typeof fetch);
    expect(new Uint8Array(await store.load(descriptor(valid)))).toEqual(valid);
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("does not persist a download whose digest differs from the manifest", async () => {
    const expected = new TextEncoder().encode("expected");
    const wrong = new TextEncoder().encode("tampered");
    const storage = new MemoryAssetObjectStorage();
    const store = new PersistentAssetStore(storage, (async () => new Response(wrong)) as typeof fetch);
    await expect(store.load(descriptor(expected))).rejects.toThrow("校验失败");
    expect(storage.objects.size).toBe(0);
  });

  it("deduplicates concurrent requests for the same content hash", async () => {
    const bytes = new TextEncoder().encode("one request");
    const storage = new MemoryAssetObjectStorage();
    const fetcher = vi.fn(async () => new Response(bytes));
    const store = new PersistentAssetStore(storage, fetcher as typeof fetch);
    await Promise.all([store.load(descriptor(bytes)), store.load(descriptor(bytes))]);
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("validates decoded bytes instead of compressed transfer length", async () => {
    const bytes = new TextEncoder().encode("decoded offline bytes");
    const response = new Response(bytes, { headers: { "Content-Encoding": "gzip", "Content-Length": "7" } });
    const store = new PersistentAssetStore(new MemoryAssetObjectStorage(), (async () => response) as typeof fetch);
    expect(new Uint8Array(await store.load(descriptor(bytes)))).toEqual(bytes);
  });

  it("validates offline objects without Web Crypto on an HTTP LAN page", async () => {
    const bytes = new TextEncoder().encode("iPhone HTTP offline bytes");
    const originalCrypto = Object.getOwnPropertyDescriptor(globalThis, "crypto");
    Object.defineProperty(globalThis, "crypto", { configurable: true, value: {} });
    try {
      const store = new PersistentAssetStore(
        new MemoryAssetObjectStorage(),
        (async () => new Response(bytes)) as typeof fetch,
      );
      await expect(store.load(descriptor(bytes))).resolves.toEqual(bytes.buffer);
    } finally {
      if (originalCrypto) Object.defineProperty(globalThis, "crypto", originalCrypto);
      else delete (globalThis as { crypto?: unknown }).crypto;
    }
  });

  it("loads signed objects from the exact paired Bridge HTTP origin only", async () => {
    const bytes = new TextEncoder().encode("paired Bridge asset");
    const pairedDescriptor = {
      ...descriptor(bytes),
      url: new URL("http://192.168.1.20:43123/mobile/Enhanced/assets/catalog.json"),
    };
    const fetcher = vi.fn(async () => new Response(bytes));
    const store = new PersistentAssetStore(
      new MemoryAssetObjectStorage(),
      fetcher as typeof fetch,
      { documentOrigin: "http://192.168.1.20:43123" },
    );
    await expect(store.load(pairedDescriptor)).resolves.toEqual(bytes.buffer);
    expect(() => store.load({
      ...pairedDescriptor,
      id: "wrong-bridge",
      url: new URL("http://192.168.1.21:43123/mobile/Enhanced/assets/catalog.json"),
    })).toThrow("offline asset URL must use HTTPS");
  });

  it("uses the trusted module origin when an iPhone Worker serializes its origin as null", async () => {
    const bytes = new TextEncoder().encode("worker solver asset");
    const workerDescriptor = {
      ...descriptor(bytes),
      url: new URL("http://192.168.1.20:43123/mobile/Enhanced/assets/solver-kernel.wasm"),
    };
    const store = new PersistentAssetStore(
      new MemoryAssetObjectStorage(),
      (async () => new Response(bytes)) as typeof fetch,
      {
        documentOrigin: "null",
        moduleUrl: "http://192.168.1.20:43123/mobile/Enhanced/assets/solver.worker.js",
      },
    );
    await expect(store.load(workerDescriptor)).resolves.toEqual(bytes.buffer);
  });

  it("uses Bridge as the durable object store and projects every map status", async () => {
    const payload = new TextEncoder().encode("bridge object");
    const digest = createHash("sha256").update(payload).digest("hex");
    const calls: Array<{ url: string; method: string }> = [];
    const fetcher = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      calls.push({ url, method });
      if (url.endsWith("/api/v1/capabilities")) return new Response(JSON.stringify({ schema_version: 1, bridge_protocol: 1, cache_protocol: 4, input: "official-8111-only", write_commands: false }));
      if (url.endsWith("/api/v1/cache/status")) return new Response(JSON.stringify({
        schema_version: 1, state: "syncing", map_count: 2, cached_map_count: 1,
        selected_map_count: 1, selected_cached_map_count: 1,
        object_count: 3, cached_object_count: 2, total_bytes: 100, cached_bytes: 60,
        maps: [
          { id: "air_alpha", state: "cached", selected: true, cached_bytes: 50, total_bytes: 50 },
          { id: "air_bravo", state: "not-selected", selected: false, cached_bytes: 0, total_bytes: 50 },
        ],
      }));
      if (method === "GET") return new Response(payload);
      return new Response(null, { status: 204 });
    });
    const storage = new BridgeAssetObjectStorage(new URL("http://127.0.0.1:8878"), fetcher as typeof fetch);
    expect(new Uint8Array((await storage.read(digest))!)).toEqual(payload);
    await storage.write(digest, payload.buffer);
    await storage.remove(digest);
    await storage.selectTerrainMaps(["air_alpha"]);
    const stats = await storage.stats();
    expect(stats).toMatchObject({ count: 2, bytes: 60, cache: { state: "syncing", mapCount: 2, cachedMapCount: 1 } });
    expect(stats.cache?.maps).toHaveLength(2);
    expect(calls.map((call) => call.method)).toEqual(["GET", "GET", "PUT", "DELETE", "PUT", "GET"]);
  });

  it("waits for Bridge-owned terrain sync instead of downloading a missing object in Web", async () => {
    const bytes = new TextEncoder().encode("bridge owns this object");
    const storage: AssetObjectStorage = {
      kind: "bridge",
      read: async () => null,
      write: async () => { throw new Error("Web must not upload a CDN terrain object"); },
      remove: async () => undefined,
      stats: async () => ({ count: 0, bytes: 0 }),
    };
    const fetcher = vi.fn(async () => new Response(bytes));
    const store = new PersistentAssetStore(storage, fetcher as typeof fetch);

    await expect(store.load(descriptor(bytes))).rejects.toThrow("Bridge 正在下载");
    expect(fetcher).not.toHaveBeenCalled();
  });
});
