import { afterEach, describe, expect, it, vi } from "vitest";
import { BridgeClient, BrowserAccessClient } from "./launcher-client";

class MemoryStorage {
  readonly values = new Map<string, string>();
  getItem(key: string): string | null { return this.values.get(key) ?? null; }
  setItem(key: string, value: string): void { this.values.set(key, value); }
  removeItem(key: string): void { this.values.delete(key); }
}

afterEach(() => vi.useRealTimers());

describe("Launcher clients", () => {
  it("reads only the stable Bridge capability endpoint", async () => {
    const calls: string[] = [];
    const fetcher = async (input: RequestInfo | URL) => {
      calls.push(String(input));
      return new Response(JSON.stringify({ schema_version: 1, bridge_protocol: 1, cache_protocol: 3, bridge_version: "1.0.0", build_provenance: "github-actions-sigstore", authenticode: false, input: "official-8111-only", write_commands: false, routes: [] }));
    };
    const bridge = new BridgeClient("http://127.0.0.1:8878", fetcher as typeof fetch);
    const capabilities = await bridge.capabilities();
    expect(capabilities.bridge_version).toBe("1.0.0");
    expect(capabilities).not.toHaveProperty("app_web_version");
    expect(calls).toEqual([
      "http://127.0.0.1:8878/api/v1/capabilities",
      "http://127.0.0.1:8878/api/v1/capabilities",
    ]);
  });

  it("rejects a Bridge that predates manual terrain selection", async () => {
    const bridge = new BridgeClient("http://127.0.0.1:8878", (async () => new Response(JSON.stringify({
      schema_version: 1,
      bridge_protocol: 1,
      cache_protocol: 1,
      bridge_version: "1.2.4",
      build_provenance: "github-actions-sigstore",
      authenticode: false,
      input: "official-8111-only",
      write_commands: false,
    }))) as typeof fetch);
    await expect(bridge.capabilities()).rejects.toThrow();
  });

  it("completes device authorization and reads only the Bomana access projection", async () => {
    const storage = new MemoryStorage();
    const calls: Array<{ url: string; authorization: string | null }> = [];
    const fetcher = async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      calls.push({ url, authorization: new Headers(init?.headers).get("Authorization") });
      if (url.endsWith("/api/auth/device/code")) return new Response(JSON.stringify({ device_code: "device", user_code: "ABCD-1234", verification_uri_complete: "https://pay.example.test/device?code=ABCD-1234", expires_in: 600 }));
      if (url.endsWith("/api/auth/device/token")) return new Response(JSON.stringify({ access_token: "access-token", expires_in: 2_592_000 }));
      const expiresAt = Date.now() + 14 * 24 * 60 * 60 * 1_000;
      return new Response(JSON.stringify({ schemaVersion: 2, accountLabel: "pilot", enhanced: true, enhancedLease: String(expiresAt), enhancedLeaseExpiresAt: new Date(expiresAt).toISOString() }));
    };
    const access = new BrowserAccessClient(new URL("https://pay.example.test"), fetcher as typeof fetch, storage, fakeLeaseVerifier);
    expect((await access.begin()).state).toBe("pending");
    expect(await access.poll()).toMatchObject({ state: "authorized", accountLabel: "pilot", enhanced: true, offline: false });
    expect(calls.at(-1)).toEqual({ url: "https://pay.example.test/api/bomana/access", authorization: "Bearer access-token" });
  });

  it("fails closed when account state is unavailable", async () => {
    const storage = new MemoryStorage();
    storage.setItem("bomana:cheemspay:authorization:v3", JSON.stringify({ schemaVersion: 3, accessToken: "token", accountLabel: "", enhancedLease: null, enhancedLeaseExpiresAt: 0, validatedAt: 0 }));
    const access = new BrowserAccessClient(new URL("https://pay.example.test"), (async () => { throw new Error("offline"); }) as typeof fetch, storage, fakeLeaseVerifier);
    expect((await access.snapshot()).enhanced).toBe(false);
  });

  it("bounds a missing Bridge probe so the Launcher can still render", async () => {
    const bridge = new BridgeClient("http://127.0.0.1:8878", ((_input: RequestInfo | URL, init?: RequestInit) => new Promise((_resolve, reject) => {
      init?.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
    })) as typeof fetch);
    await expect(bridge.capabilities()).rejects.toThrow("aborted");
  }, 5_000);

  it("distinguishes a service occupying the Bridge port from a missing Bridge", async () => {
    let calls = 0;
    const bridge = new BridgeClient("http://127.0.0.1:8878", (async () => {
      calls += 1;
      if (calls === 1) throw new TypeError("CORS blocked");
      return new Response(null, { status: 200 });
    }) as typeof fetch);
    await expect(bridge.probe()).resolves.toMatchObject({ state: "blocked" });
  });

  it("keeps an authorized projection for 14 days and refreshes that window online", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-08-01T00:00:00Z"));
    const storage = new MemoryStorage();
    let online = true;
    const fetcher = async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/auth/device/code")) return new Response(JSON.stringify({ device_code: "device", user_code: "ABCD-1234", verification_uri_complete: "https://pay.example.test/device?code=ABCD-1234", expires_in: 600 }));
      if (url.endsWith("/api/auth/device/token")) return new Response(JSON.stringify({ access_token: "access-token", expires_in: 2_592_000 }));
      if (!online) throw new TypeError("offline");
      const expiresAt = Date.now() + 14 * 24 * 60 * 60 * 1_000;
      return new Response(JSON.stringify({ schemaVersion: 2, accountLabel: "pilot", enhanced: true, enhancedLease: String(expiresAt), enhancedLeaseExpiresAt: new Date(expiresAt).toISOString() }));
    };

    const initial = new BrowserAccessClient(new URL("https://pay.example.test"), fetcher as typeof fetch, storage, fakeLeaseVerifier);
    await initial.begin();
    expect((await initial.poll()).state).toBe("authorized");

    vi.setSystemTime(new Date("2026-08-14T00:00:00Z"));
    const refreshed = new BrowserAccessClient(new URL("https://pay.example.test"), fetcher as typeof fetch, storage, fakeLeaseVerifier);
    expect((await refreshed.snapshot()).state).toBe("authorized");

    vi.setSystemTime(new Date("2026-08-27T00:00:00Z"));
    online = false;
    const offline = await new BrowserAccessClient(new URL("https://pay.example.test"), fetcher as typeof fetch, storage, fakeLeaseVerifier).snapshot();
    expect(offline).toMatchObject({ state: "authorized", enhanced: true, offline: true });

    vi.setSystemTime(new Date("2026-08-29T00:00:01Z"));
    expect((await new BrowserAccessClient(new URL("https://pay.example.test"), fetcher as typeof fetch, storage, fakeLeaseVerifier).snapshot()).state).toBe("signed_out");
  });

  it("revokes a cached Lease when the online entitlement is no longer Enhanced", async () => {
    const storage = new MemoryStorage();
    const expiresAt = Date.now() + 86_400_000;
    storage.setItem("bomana:cheemspay:authorization:v3", JSON.stringify({
      schemaVersion: 3, accessToken: "token", accountLabel: "pilot",
      enhancedLease: String(expiresAt), enhancedLeaseExpiresAt: expiresAt, validatedAt: Date.now(),
    }));
    const fetcher = (async () => new Response(JSON.stringify({ schemaVersion: 2, accountLabel: "pilot", enhanced: false, enhancedLease: null, enhancedLeaseExpiresAt: null }))) as typeof fetch;
    const access = await new BrowserAccessClient(new URL("https://pay.example.test"), fetcher, storage, fakeLeaseVerifier).snapshot();
    expect(access).toMatchObject({ state: "authorized", enhanced: false, offline: false });
    expect(JSON.parse(storage.getItem("bomana:cheemspay:authorization:v3")!).enhancedLease).toBeNull();
  });

  it("does not fall back to an old Lease after a malformed authoritative response", async () => {
    const storage = new MemoryStorage();
    const expiresAt = Date.now() + 86_400_000;
    storage.setItem("bomana:cheemspay:authorization:v3", JSON.stringify({
      schemaVersion: 3, accessToken: "token", accountLabel: "pilot",
      enhancedLease: String(expiresAt), enhancedLeaseExpiresAt: expiresAt, validatedAt: Date.now(),
    }));
    const fetcher = (async () => new Response(JSON.stringify({ schemaVersion: 2, accountLabel: "pilot", enhanced: true, enhancedLease: "invalid", enhancedLeaseExpiresAt: new Date(expiresAt).toISOString() }))) as typeof fetch;
    const access = await new BrowserAccessClient(new URL("https://pay.example.test"), fetcher, storage, fakeLeaseVerifier).snapshot();
    expect(access).toMatchObject({ state: "unavailable", enhanced: false });
  });

  it("rejects offline access when the clock moves before the last online validation", async () => {
    vi.useFakeTimers();
    const validatedAt = Date.parse("2026-08-25T12:00:00Z");
    vi.setSystemTime(new Date("2026-08-25T10:00:00Z"));
    const storage = new MemoryStorage();
    const expiresAt = Date.parse("2026-09-01T00:00:00Z");
    storage.setItem("bomana:cheemspay:authorization:v3", JSON.stringify({
      schemaVersion: 3, accessToken: "token", accountLabel: "pilot",
      enhancedLease: String(expiresAt), enhancedLeaseExpiresAt: expiresAt, validatedAt,
    }));
    const offlineFetcher = (async () => { throw new TypeError("offline"); }) as typeof fetch;
    const access = await new BrowserAccessClient(new URL("https://pay.example.test"), offlineFetcher, storage, fakeLeaseVerifier).snapshot();
    expect(access).toMatchObject({ state: "signed_out", enhanced: false });
  });
});

async function fakeLeaseVerifier(token: string, options: { readonly now?: number } = {}) {
  const expiresAt = Number(token);
  if (!Number.isFinite(expiresAt) || (options.now ?? Date.now()) >= expiresAt) throw new Error("expired");
  return { subject: "user-1", entitlementVersion: 1, expiresAt };
}
