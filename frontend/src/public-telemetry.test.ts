import { afterEach, describe, expect, it, vi } from "vitest";
import { clearBridgeDiscoveryForTest } from "./runtime/bridge-discovery";
import { PublicTelemetry } from "./public-telemetry";

afterEach(clearBridgeDiscoveryForTest);

describe("public telemetry", () => {
  it("requests no gamechat, terrain, or Enhanced route", async () => {
    const requests: string[] = [];
    const fetcher = vi.fn<typeof fetch>(async (input) => {
      const url = String(input); requests.push(url);
      if (url.endsWith("/api/v1/capabilities")) return Response.json({ schema_version: 1, bridge_protocol: 1, cache_protocol: 4, input: "official-8111-only", write_commands: false });
      if (url.endsWith("/api/v1/8111/map-objects")) return Response.json([]);
      return Response.json({ valid: true, map_min: [0, 0], map_max: [1, 1] });
    });
    const source = new PublicTelemetry("http://127.0.0.1:8878/", fetcher);
    await expect(source.read(1_000)).resolves.toMatchObject({ connected: true });
    expect(requests.some((url) => /gamechat|terrain|mobile|pairing/i.test(url))).toBe(false);
  });

  it("keeps Lite telemetry free of map requests", async () => {
    const requests: string[] = [];
    const fetcher = vi.fn<typeof fetch>(async (input) => {
      const url = String(input); requests.push(url);
      if (url.endsWith("/api/v1/capabilities")) return Response.json({ schema_version: 1, bridge_protocol: 1, cache_protocol: 4, input: "official-8111-only", write_commands: false });
      return Response.json({ valid: true, compass1: 0, "IAS, km/h": 500, "H, m": 3000 });
    });
    const source = new PublicTelemetry("http://127.0.0.1:8878/", fetcher, { includeNavigation: false });
    const frame = await source.read(1_000);
    expect(frame.mapObjects).toBeNull();
    expect(frame.mapInfo).toBeNull();
    expect(requests.some((url) => /map-objects|map-info/.test(url))).toBe(false);
  });
});
