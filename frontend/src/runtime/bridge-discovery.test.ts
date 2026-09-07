import { afterEach, describe, expect, it, vi } from "vitest";
import {
  BRIDGE_PORT_START,
  clearBridgeDiscoveryForTest,
  configureMobileBridge,
  discoverBridgeEndpoint,
  fetchBridgeResource,
  provePairedOfficialRoutes,
} from "./bridge-discovery";
import { connectMobileBridge } from "./mobile-pairing";

afterEach(clearBridgeDiscoveryForTest);

const BRIDGE_IDENTITY = Object.freeze({
  schema_version: 1, bridge_protocol: 1, cache_protocol: 4,
  input: "official-8111-only", write_commands: false,
});

function createHttpsPhoneLanFetch(input: {
  permission: { current: "prompt" | "granted" | "denied" };
  userGesture: { current: boolean };
  bridges: Readonly<Record<string, {
    token: string;
    corsOrigin?: string;
    capabilities?: Record<string, unknown>;
    official?: Readonly<Record<string, { status: number; body?: unknown; blocked?: boolean }>>;
  }>>;
  documentOrigin?: string;
}): typeof fetch {
  const documentOrigin = input.documentOrigin ?? "https://bomana.ruikang.wang";
  return (async (requestInfo: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(requestInfo));
    const targetAddressSpace = (init as RequestInit & { targetAddressSpace?: string })?.targetAddressSpace;
    if (url.protocol === "http:" && documentOrigin.startsWith("https:")) {
      if (targetAddressSpace !== "local" && input.permission.current !== "granted") {
        throw new TypeError(`Mixed Content: The page at '${documentOrigin}' was loaded over HTTPS, but requested an insecure resource '${url.href}'.`);
      }
      if (input.permission.current === "denied") {
        throw new TypeError("Permission was denied for this request to access the local address space.");
      }
      if (input.permission.current === "prompt") {
        if (!input.userGesture.current) {
          throw new TypeError("Permission was denied for this request to access the local address space.");
        }
        input.permission.current = "granted";
      }
    }
    const bridge = input.bridges[url.origin];
    if (!bridge) throw new TypeError("Failed to fetch");
    if (bridge.corsOrigin && bridge.corsOrigin !== documentOrigin) throw new TypeError("Failed to fetch");
    const pairing = new Headers(init?.headers).get("X-Bomana-Mobile-Pairing");
    if (pairing !== bridge.token) return new Response("mobile pairing unavailable", { status: 401 });
    if (url.pathname === "/api/v1/capabilities") {
      return Response.json(bridge.capabilities ?? BRIDGE_IDENTITY);
    }
    const official = bridge.official?.[url.pathname];
    if (!official) return new Response("not found", { status: 404 });
    if (official.blocked) throw new TypeError("Failed to fetch");
    return new Response(JSON.stringify(official.body ?? { ok: true }), {
      status: official.status,
      headers: { "Content-Type": "application/json" },
    });
  }) as typeof fetch;
}

describe("Bridge endpoint discovery", () => {
  it("cancels every port probe and does not cache an abandoned discovery", async () => {
    const signals: AbortSignal[] = [];
    const fetcher = vi.fn((_input: RequestInfo | URL, init?: RequestInit) => {
      signals.push(init!.signal!);
      return new Promise<Response>(() => {});
    });
    const controller = new AbortController();
    const rejected = expect(discoverBridgeEndpoint(fetcher as typeof fetch, "", controller.signal)).rejects.toThrow();
    controller.abort();
    await rejected;
    expect(signals).toHaveLength(20);
    expect(signals.every(signal => signal.aborted)).toBe(true);
    const retry = vi.fn(async () => Response.json(BRIDGE_IDENTITY));
    await discoverBridgeEndpoint(retry as typeof fetch);
    expect(retry).toHaveBeenCalledTimes(20);
  });

  it("expires a capabilities body that ignores network cancellation", async () => {
    vi.useFakeTimers();
    try {
      const fetcher = vi.fn(async () => ({ ok: true, json: () => new Promise(() => {}) }) as Response);
      const rejected = expect(discoverBridgeEndpoint(fetcher as typeof fetch, "http://127.0.0.1:8878/")).rejects.toThrow();
      await vi.advanceTimersByTimeAsync(1_201);
      await rejected;
    } finally { vi.useRealTimers(); }
  });

  it("marks desktop Bridge requests as loopback network access", async () => {
    const fetcher = vi.fn(async () => Response.json(BRIDGE_IDENTITY));
    await fetchBridgeResource(fetcher as typeof fetch, "http://127.0.0.1:8878/api/v1/capabilities");
    expect(fetcher).toHaveBeenCalledWith(
      "http://127.0.0.1:8878/api/v1/capabilities",
      expect.objectContaining({ targetAddressSpace: "loopback" }),
    );
  });

  it("selects the first port that proves the complete Bridge protocol", async () => {
    const acceptedPort = BRIDGE_PORT_START + 3;
    const fetcher = vi.fn(async (input: RequestInfo | URL) => {
      const port = Number(new URL(String(input)).port);
      if (port !== acceptedPort) return new Response(JSON.stringify({ service: "not-bomana" }), { status: port === BRIDGE_PORT_START ? 200 : 404 });
      return new Response(JSON.stringify({ schema_version: 1, bridge_protocol: 1, cache_protocol: 4, input: "official-8111-only", write_commands: false }));
    });
    expect((await discoverBridgeEndpoint(fetcher as typeof fetch)).port).toBe(String(acceptedPort));
    expect(fetcher).toHaveBeenCalledTimes(20);
  });

  it("rejects an occupied port whose service is not Bomana Bridge", async () => {
    const fetcher = vi.fn(async () => new Response(JSON.stringify({ schema_version: 1, bridge_protocol: 99 })));
    await expect(discoverBridgeEndpoint(fetcher as typeof fetch)).rejects.toThrow("未发现");
  });

  it("probes every QR candidate and authenticates phone requests to the reachable Bridge", async () => {
    configureMobileBridge({
      endpoints: ["http://192.168.1.20:41000/", "http://172.20.10.2:41000/"],
      pairingToken: "mobile-pairing-token",
    });
    const fetcher = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      expect(new Headers(init?.headers).get("X-Bomana-Mobile-Pairing")).toBe("mobile-pairing-token");
      expect((init as RequestInit & { targetAddressSpace?: string })?.targetAddressSpace).toBe("local");
      if (new URL(String(input)).hostname !== "172.20.10.2") return new Response(null, { status: 401 });
      return Response.json({
        schema_version: 1, bridge_protocol: 1, cache_protocol: 4,
        input: "official-8111-only", write_commands: false,
      });
    });

    expect((await discoverBridgeEndpoint(fetcher as typeof fetch)).hostname).toBe("172.20.10.2");
    await fetchBridgeResource(fetcher as typeof fetch, "http://172.20.10.2:41000/api/v1/8111/state");
    expect(fetcher).toHaveBeenCalledTimes(3);
  });

  it("does not swallow Local Network Access or mixed-content failures as a missing Bridge", async () => {
    configureMobileBridge({
      endpoints: ["http://192.168.1.20:41000/", "http://10.0.0.8:41000/"],
      pairingToken: "a".repeat(43),
    });
    const fetcher = createHttpsPhoneLanFetch({
      permission: { current: "prompt" },
      userGesture: { current: false },
      bridges: {
        "http://192.168.1.20:41000": { token: "a".repeat(43) },
        "http://10.0.0.8:41000": { token: "a".repeat(43) },
      },
    });
    await expect(discoverBridgeEndpoint(fetcher)).rejects.toThrow(/本地网络|Chrome/);
    await expect(discoverBridgeEndpoint(fetcher)).rejects.not.toThrow("未发现二维码对应的 Bomana Bridge");
  });

  it("keeps probing later QR candidates after one private address is unreachable", async () => {
    configureMobileBridge({
      endpoints: ["http://192.168.56.1:41000/", "http://192.168.1.20:41000/"],
      pairingToken: "a".repeat(43),
    });
    const fetcher = createHttpsPhoneLanFetch({
      permission: { current: "granted" },
      userGesture: { current: true },
      bridges: {
        "http://192.168.1.20:41000": { token: "a".repeat(43) },
      },
    });
    expect((await discoverBridgeEndpoint(fetcher)).hostname).toBe("192.168.1.20");
  });

  it("treats capabilities success plus blocked official 8111 routes as an incomplete pairing", async () => {
    configureMobileBridge({
      endpoints: ["http://192.168.1.20:41000/"],
      pairingToken: "a".repeat(43),
    });
    const fetcher = createHttpsPhoneLanFetch({
      permission: { current: "granted" },
      userGesture: { current: true },
      bridges: {
        "http://192.168.1.20:41000": {
          token: "a".repeat(43),
          official: {
            "/api/v1/8111/state": { status: 200, blocked: true },
            "/api/v1/8111/indicators": { status: 200, body: { valid: true } },
            "/api/v1/8111/map-objects": { status: 200, body: [] },
          },
        },
      },
    });
    const base = await discoverBridgeEndpoint(fetcher);
    expect(base.hostname).toBe("192.168.1.20");
    await expect(provePairedOfficialRoutes(base, fetcher)).rejects.toThrow(/8111|官方/);
    await expect(connectMobileBridge(fetcher)).rejects.toThrow(/8111|官方/);
  });

  it("accepts official 8111 502 as Bridge-reachable when the game is not running", async () => {
    configureMobileBridge({
      endpoints: ["http://192.168.1.20:41000/"],
      pairingToken: "a".repeat(43),
    });
    const fetcher = createHttpsPhoneLanFetch({
      permission: { current: "granted" },
      userGesture: { current: true },
      bridges: {
        "http://192.168.1.20:41000": {
          token: "a".repeat(43),
          official: {
            "/api/v1/8111/state": { status: 502, body: { error: "8111 unavailable" } },
            "/api/v1/8111/indicators": { status: 502 },
            "/api/v1/8111/map-objects": { status: 502 },
          },
        },
      },
    });
    const fetcherSpy = vi.fn(fetcher);
    await expect(connectMobileBridge(fetcherSpy)).resolves.toMatchObject({ hostname: "192.168.1.20" });
    const paths = fetcherSpy.mock.calls.map(([request]) => new URL(String(request)).pathname);
    expect(paths).toContain("/api/v1/capabilities");
    expect(paths).toContain("/api/v1/8111/state");
    expect(paths).toContain("/api/v1/8111/indicators");
    expect(paths).toContain("/api/v1/8111/map-objects");
  });

  it("names an expired pairing token instead of a missing Bridge", async () => {
    configureMobileBridge({
      endpoints: ["http://192.168.1.20:41000/", "http://10.8.0.2:41000/"],
      pairingToken: "a".repeat(43),
    });
    const fetcher = createHttpsPhoneLanFetch({
      permission: { current: "granted" },
      userGesture: { current: true },
      bridges: {
        "http://192.168.1.20:41000": { token: "other-token" },
        "http://10.8.0.2:41000": { token: "other-token" },
      },
    });
    await expect(discoverBridgeEndpoint(fetcher)).rejects.toThrow(/口令|重新生成/);
  });
});
