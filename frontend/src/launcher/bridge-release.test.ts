import { describe, expect, it, vi } from "vitest";
import { bridgeVersionState, fetchBridgeRelease } from "./bridge-release";

describe("Bridge release", () => {
  it("reads one bounded same-origin release fact", async () => {
    const fetcher = vi.fn(async () => Response.json({
      schema_version: 1,
      bridge_version: "1.2.8",
      bridge_sha256: "a".repeat(64),
    }));
    await expect(fetchBridgeRelease(
      new URL("https://bomana.example/downloads/bridge-release.json"),
      fetcher as typeof fetch,
    )).resolves.toEqual({
      schemaVersion: 1,
      bridgeVersion: "1.2.8",
      bridgeSha256: "a".repeat(64),
    });
    expect(fetcher).toHaveBeenCalledWith(
      new URL("https://bomana.example/downloads/bridge-release.json"),
      expect.objectContaining({ method: "GET", mode: "same-origin", redirect: "error" }),
    );
  });

  it("compares strict numeric versions without lexical ordering bugs", () => {
    expect(bridgeVersionState("1.2.7", "1.2.8")).toBe("outdated");
    expect(bridgeVersionState("1.2.10", "1.2.8")).toBe("newer");
    expect(bridgeVersionState("1.2.8", "1.2.8")).toBe("current");
    expect(bridgeVersionState("development", "1.2.8")).toBe("unknown");
  });

  it("rejects malformed or unbounded release documents", async () => {
    const malformed = (async () => Response.json({ schema_version: 1, bridge_version: "1.2", bridge_sha256: "x" })) as typeof fetch;
    await expect(fetchBridgeRelease(new URL("https://bomana.example/downloads/bridge-release.json"), malformed)).rejects.toThrow("invalid");
    const oversized = (async () => new Response("x".repeat(4_097))) as typeof fetch;
    await expect(fetchBridgeRelease(new URL("https://bomana.example/downloads/bridge-release.json"), oversized)).rejects.toThrow("size");
  });
});
