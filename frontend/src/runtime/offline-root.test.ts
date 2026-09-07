import { describe, expect, it } from "vitest";
import { PUBLIC_OFFLINE_ROOT, PUBLIC_OFFLINE_URLS } from "../generated/public-offline-assets";
import { openVerifiedOfflineCatalog } from "./offline-root";

describe("Offline Root trust", () => {
  it("accepts development roots only on loopback and production roots remotely", async () => {
    const catalog = await openVerifiedOfflineCatalog(PUBLIC_OFFLINE_ROOT, PUBLIC_OFFLINE_URLS, { expectedScope: "public", hostname: "127.0.0.1" });
    expect(catalog.asset("aircraft-parameters").sha256).toMatch(/^[a-f0-9]{64}$/);
    const remote = openVerifiedOfflineCatalog(PUBLIC_OFFLINE_ROOT, PUBLIC_OFFLINE_URLS, { expectedScope: "public", hostname: "bomana.example" });
    if (PUBLIC_OFFLINE_ROOT.manifest_signature.key_id === "bomana-development-only") {
      await expect(remote).rejects.toThrow("只能在本机预览");
    } else {
      await expect(remote).resolves.toBeInstanceOf(Object);
    }
  });

  it("rejects a tampered object even when the old signature is retained", async () => {
    const tampered = structuredClone(PUBLIC_OFFLINE_ROOT) as unknown as { objects: Array<{ size_bytes: number }> };
    tampered.objects[0]!.size_bytes += 1;
    await expect(openVerifiedOfflineCatalog(tampered, PUBLIC_OFFLINE_URLS, { expectedScope: "public", hostname: "127.0.0.1" }))
      .rejects.toThrow(/revision|签名/);
  });

  it("opens the signed offline root without Web Crypto on an iPhone HTTP LAN page", async () => {
    const originalCrypto = Object.getOwnPropertyDescriptor(globalThis, "crypto");
    Object.defineProperty(globalThis, "crypto", { configurable: true, value: {} });
    try {
      await expect(openVerifiedOfflineCatalog(PUBLIC_OFFLINE_ROOT, PUBLIC_OFFLINE_URLS, {
        expectedScope: "public",
        hostname: "127.0.0.1",
      })).resolves.toBeInstanceOf(Object);
    } finally {
      if (originalCrypto) Object.defineProperty(globalThis, "crypto", originalCrypto);
      else delete (globalThis as { crypto?: unknown }).crypto;
    }
  });
});
