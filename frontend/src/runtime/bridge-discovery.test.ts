import { afterEach, describe, expect, it, vi } from "vitest";
import {
  clearBridgeDiscoveryForTest,
  discoverBridgeEndpoint,
  fetchBridgeResource,
} from "./bridge-discovery";

afterEach(clearBridgeDiscoveryForTest);

describe("public Bridge discovery", () => {
  it("selects the first loopback port with the complete public protocol", async () => {
    const fetcher = vi.fn<typeof fetch>(async (input) => {
      const url = new URL(String(input));
      if (url.port !== "8880") return new Response("not Bridge", { status: 404 });
      return Response.json({
        schema_version: 1,
        bridge_protocol: 1,
        cache_protocol: 4,
        input: "official-8111-only",
        write_commands: false,
      });
    });
    await expect(discoverBridgeEndpoint(fetcher)).resolves.toEqual(new URL("http://127.0.0.1:8880/"));
  });

  it("marks public Web requests as loopback network access", async () => {
    const fetcher = vi.fn(async () => Response.json({ ok: true }));
    await fetchBridgeResource(fetcher as typeof fetch, "http://127.0.0.1:8878/api/v1/capabilities");
    expect(fetcher).toHaveBeenCalledWith(
      "http://127.0.0.1:8878/api/v1/capabilities",
      expect.objectContaining({ targetAddressSpace: "loopback" }),
    );
  });

  it("rejects non-loopback configured endpoints", async () => {
    await expect(discoverBridgeEndpoint(vi.fn<typeof fetch>(), "http://192.168.1.10:8878/"))
      .rejects.toThrow(/本机/);
  });
});
