import { describe, expect, it, vi } from "vitest";
import { readDailyActiveEnabled, reportDailyActive, setDailyActiveEnabled } from "./anonymous-daily-active";

class MemoryStorage {
  readonly values = new Map<string, string>();
  getItem(key: string): string | null { return this.values.get(key) ?? null; }
  setItem(key: string, value: string): void { this.values.set(key, value); }
  removeItem(key: string): void { this.values.delete(key); }
}

const knownSecret = btoa(String.fromCharCode(...Array.from({ length: 32 }, (_, index) => index)))
  .replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");

describe("anonymous daily active", () => {
  it("preserves the legacy three-field HMAC contract", async () => {
    const storage = new MemoryStorage();
    storage.setItem("bomana:dau:install-secret:v1", knownSecret);
    const calls: Array<[RequestInfo | URL, RequestInit | undefined]> = [];
    const fetcher = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push([input, init]);
      return new Response(JSON.stringify({ accepted: true, duplicate: false }), { status: 202 });
    });
    expect(await reportDailyActive("Standard", {
      storage, fetcher: fetcher as typeof fetch, cryptoProvider: crypto,
      now: () => new Date("2026-08-03T12:00:00Z"), endpoint: "https://example.test/api/v1/telemetry/dau",
    })).toBe("reported");
    const [, init] = calls[0]!;
    expect(JSON.parse(String(init?.body))).toEqual({
      schema_version: 1,
      install_day_token: "25913f2a2d0a4ca138725fcae98c334b5754d9eb3543a4064e00303c9d627eb4",
      channel: "Standard",
    });
    expect(new Headers(init?.headers).get("Authorization")).toBeNull();
    expect(init?.credentials).toBe("omit");
  });

  it("counts one browser installation only once across Editions per UTC day", async () => {
    const storage = new MemoryStorage();
    const fetcher = vi.fn(async () => new Response(null, { status: 202 }));
    const dependencies = { storage, fetcher: fetcher as typeof fetch, cryptoProvider: crypto, now: () => new Date("2026-08-03T23:59:00Z") };
    expect(await reportDailyActive("Lite", dependencies)).toBe("reported");
    expect(await reportDailyActive("Enhanced", dependencies)).toBe("already-reported");
    expect(fetcher).toHaveBeenCalledOnce();
  });

  it("offers a browser-local opt-out without contacting the collector", async () => {
    const storage = new MemoryStorage();
    const fetcher = vi.fn();
    setDailyActiveEnabled(false, storage);
    expect(readDailyActiveEnabled(storage)).toBe(false);
    expect(await reportDailyActive("Lite", { storage, fetcher: fetcher as typeof fetch })).toBe("disabled");
    expect(fetcher).not.toHaveBeenCalled();
    setDailyActiveEnabled(true, storage);
    expect(readDailyActiveEnabled(storage)).toBe(true);
  });

  it("fails silently and still bounds transport attempts to once per day", async () => {
    const storage = new MemoryStorage();
    const fetcher = vi.fn(async () => { throw new Error("offline"); });
    const dependencies = { storage, fetcher: fetcher as typeof fetch, cryptoProvider: crypto, now: () => new Date("2026-08-03T12:00:00Z") };
    expect(await reportDailyActive("Enhanced", dependencies)).toBe("failed");
    expect(await reportDailyActive("Enhanced", dependencies)).toBe("already-reported");
    expect(fetcher).toHaveBeenCalledOnce();
  });
});
