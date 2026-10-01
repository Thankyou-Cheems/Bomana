import { describe, expect, it, vi } from "vitest";
import { createAppMetricsReporter, readDailyActiveEnabled, reportDailyActive, setDailyActiveEnabled } from "./anonymous-daily-active";

class MemoryStorage {
  readonly values = new Map<string, string>();
  getItem(key: string): string | null { return this.values.get(key) ?? null; }
  setItem(key: string, value: string): void { this.values.set(key, value); }
  removeItem(key: string): void { this.values.delete(key); }
}

const knownSecret = btoa(String.fromCharCode(...Array.from({ length: 32 }, (_, index) => index)))
  .replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");

describe("anonymous daily active", () => {
  it("preserves daily HMAC identity on the versioned metrics contract", async () => {
    const storage = new MemoryStorage();
    storage.setItem("bomana:dau:install-secret:v1", knownSecret);
    const calls: Array<[RequestInfo | URL, RequestInit | undefined]> = [];
    const fetcher = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push([input, init]);
      return new Response(JSON.stringify({ accepted: true, duplicate: false }), { status: 202 });
    });
    expect(await reportDailyActive("Standard", {
      storage, fetcher: fetcher as typeof fetch, cryptoProvider: crypto,
      now: () => new Date("2026-08-03T12:00:00Z"), endpoint: "https://example.test/api/v2/metrics/events",
    })).toBe("reported");
    const [, init] = calls[0]!;
    expect(JSON.parse(String(init?.body))).toEqual({
      type: "dau", day: "2026-08-03",
      dailyToken: "25913f2a2d0a4ca138725fcae98c334b5754d9eb3543a4064e00303c9d627eb4",
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
    expect(await reportDailyActive("Calculator", { storage, fetcher: fetcher as typeof fetch })).toBe("disabled");
    expect(fetcher).not.toHaveBeenCalled();
    setDailyActiveEnabled(true, storage);
    expect(readDailyActiveEnabled(storage)).toBe(true);
  });

  it.each([["Standard", "Calculator"], ["Calculator", "Standard"]] as const)("tracks %s then %s with one shared daily identity", async (first, second) => {
    const storage = new MemoryStorage();
    const payloads: Array<{ channel: string; dailyToken: string }> = [];
    const fetcher = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      payloads.push(JSON.parse(String(init?.body)));
      return new Response(null, { status: 202 });
    });
    let day = "2026-09-27T23:59:00Z";
    const dependencies = { storage, fetcher: fetcher as typeof fetch, cryptoProvider: crypto, now: () => new Date(day) };
    expect(await reportDailyActive(first, dependencies)).toBe("reported");
    expect(await reportDailyActive(second, dependencies)).toBe("reported");
    expect(payloads[0]?.dailyToken).toBe(payloads[1]?.dailyToken);
    expect(await reportDailyActive("Calculator", dependencies)).toBe("already-reported");
    expect(fetcher).toHaveBeenCalledTimes(2);
    day = "2026-09-28T00:01:00Z";
    expect(await reportDailyActive("Calculator", dependencies)).toBe("reported");
    expect(payloads[2]?.dailyToken).not.toBe(payloads[0]?.dailyToken);
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

describe("successful App initialization", () => {
  it("counts three documents as three starts and a single daily identity", async () => {
    const storage = new MemoryStorage();
    const payloads: Array<{ type: string; eventId?: string }> = [];
    const fetcher = vi.fn(async (_: RequestInfo | URL, init?: RequestInit) => {
      payloads.push(JSON.parse(String(init?.body)));
      return new Response(null, { status: 202 });
    });
    for (let document = 0; document < 3; document += 1) {
      const report = createAppMetricsReporter({ storage, fetcher, cryptoProvider: crypto, origin: "https://bomana.ruikang.wang" });
      expect(await report("Standard")).toBe("reported");
      expect(await report("Standard")).toBe("already-reported");
    }
    await vi.waitFor(() => expect(payloads.filter((p) => p.type === "dau")).toHaveLength(1));
    const starts = payloads.filter((p) => p.type === "app_start");
    expect(starts).toHaveLength(3);
    expect(new Set(starts.map((p) => p.eventId)).size).toBe(3);
  });

  it("retries a lost acknowledgement with the same event identity", async () => {
    const storage = new MemoryStorage();
    storage.setItem("bomana:dau:reported-utc-day:v1", "2026-09-28");
    const bodies: string[] = [];
    const fetcher = vi.fn(async (_: RequestInfo | URL, init?: RequestInit) => {
      bodies.push(String(init?.body));
      if (bodies.length === 1) throw new Error("lost response");
      return new Response(null, { status: 202 });
    });
    const report = createAppMetricsReporter({ storage, fetcher, cryptoProvider: crypto, origin: "https://bomana.ruikang.wang", now: () => new Date("2026-09-28T23:59:59Z") });
    expect(await report("Enhanced", "mobile")).toBe("reported");
    expect(bodies).toHaveLength(2);
    expect(bodies[0]).toBe(bodies[1]);
    expect(JSON.parse(bodies[0]!)).toMatchObject({ type: "app_start", surface: "mobile", channel: "Enhanced" });
  });

  it("does not report local development or an opted-out App", async () => {
    const storage = new MemoryStorage();
    const fetcher = vi.fn();
    const local = createAppMetricsReporter({ storage, fetcher, origin: "http://localhost:5173" });
    expect(await local("Lite")).toBe("disabled");
    setDailyActiveEnabled(false, storage);
    const disabled = createAppMetricsReporter({ storage, fetcher, origin: "https://bomana.ruikang.wang" });
    expect(await disabled("Lite")).toBe("disabled");
    expect(fetcher).not.toHaveBeenCalled();
  });
});
