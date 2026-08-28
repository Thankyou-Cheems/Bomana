import { generateKeyPairSync, sign } from "node:crypto";
import { describe, expect, it } from "vitest";
import {
  BROWSER_AUTHORIZATION_KEY,
  readBrowserAuthorization,
  verifyEnhancedLease,
  verifyMobileEnhancedLease,
} from "./enhanced-access";

class MemoryStorage {
  readonly values = new Map<string, string>();
  getItem(key: string): string | null { return this.values.get(key) ?? null; }
  setItem(key: string, value: string): void { this.values.set(key, value); }
  removeItem(key: string): void { this.values.delete(key); }
}

function lease(options: { now: number; expiresInSec?: number; feature?: string }) {
  const { privateKey, publicKey } = generateKeyPairSync("ed25519");
  const header = encode({ alg: "EdDSA", kid: "test-key", typ: "bomana-web-access+jwt" });
  const issuedAt = Math.floor(options.now / 1_000);
  const payload = encode({
    iss: "https://cheemspay.test/api/licenses", aud: "bomana:web", sub: "user-1", jti: "lease-1",
    app_id: "bomana", required_feature: options.feature ?? "bomana.super_bomber",
    service_expires_at: "2027-01-01T00:00:00.000Z", entitlement_version: 4,
    iat: issuedAt, exp: issuedAt + (options.expiresInSec ?? 14 * 24 * 60 * 60),
  });
  const signingInput = `${header}.${payload}`;
  const signature = sign(null, Buffer.from(signingInput), privateKey).toString("base64url");
  return {
    token: `${signingInput}.${signature}`,
    publicKey: publicKey.export({ format: "der", type: "spki" }).toString("base64url"),
  };
}

function mobileLease(options: { now: number; bridgePairingId: string }) {
  const { privateKey, publicKey } = generateKeyPairSync("ed25519");
  const header = encode({ alg: "EdDSA", kid: "test-key", typ: "bomana-mobile-access+jwt" });
  const issuedAt = Math.floor(options.now / 1_000);
  const payload = encode({
    iss: "https://cheemspay.test/api/licenses", aud: "bomana:mobile-web", sub: "user-1", jti: "mobile-lease-1",
    app_id: "bomana", required_feature: "bomana.super_bomber", bridge_pairing_id: options.bridgePairingId,
    service_expires_at: "2027-01-01T00:00:00.000Z", entitlement_version: 5,
    iat: issuedAt, exp: issuedAt + 8 * 60 * 60,
  });
  const signingInput = `${header}.${payload}`;
  const signature = sign(null, Buffer.from(signingInput), privateKey).toString("base64url");
  return {
    token: `${signingInput}.${signature}`,
    publicKey: publicKey.export({ format: "der", type: "spki" }).toString("base64url"),
  };
}

describe("Enhanced access", () => {
  it("verifies a signed fourteen-day CheemsPay lease", async () => {
    const now = Date.parse("2026-08-25T00:00:00Z");
    const issued = lease({ now });
    await expect(verifyEnhancedLease(issued.token, {
      now,
      issuer: "https://cheemspay.test/api/licenses",
      publicKeys: { "test-key": issued.publicKey },
    })).resolves.toMatchObject({ subject: "user-1", entitlementVersion: 4 });
  });

  it("rejects tampering, wrong features, and expired leases", async () => {
    const now = Date.parse("2026-08-25T00:00:00Z");
    const issued = lease({ now });
    const parts = issued.token.split(".");
    const tampered = `${parts[0]}.${encode({ app_id: "bomana", required_feature: "bomana.super_bomber" })}.${parts[2]}`;
    await expect(verifyEnhancedLease(tampered, { now, issuer: "https://cheemspay.test/api/licenses", publicKeys: { "test-key": issued.publicKey } })).rejects.toThrow();
    const wrongFeature = lease({ now, feature: "bomana.other" });
    await expect(verifyEnhancedLease(wrongFeature.token, { now, issuer: "https://cheemspay.test/api/licenses", publicKeys: { "test-key": wrongFeature.publicKey } })).rejects.toThrow();
    await expect(verifyEnhancedLease(issued.token, { now: now + 14 * 24 * 60 * 60 * 1_000, issuer: "https://cheemspay.test/api/licenses", publicKeys: { "test-key": issued.publicKey } })).rejects.toThrow("已过期");
  });

  it("rejects the former editable v2 authorization record", () => {
    const storage = new MemoryStorage();
    storage.setItem(BROWSER_AUTHORIZATION_KEY, JSON.stringify({ schemaVersion: 2, accessToken: "token", cachedAccess: { enhanced: true } }));
    expect(readBrowserAuthorization(storage)).toBeNull();
  });

  it("verifies a phone-only Lease against the exact Bridge pairing", async () => {
    const now = Date.parse("2026-08-26T00:00:00Z");
    const bridgePairingId = "bridge_pairing_1234567890";
    const issued = mobileLease({ now, bridgePairingId });
    await expect(verifyMobileEnhancedLease(issued.token, bridgePairingId, {
      now,
      issuer: "https://cheemspay.test/api/licenses",
      publicKeys: { "test-key": issued.publicKey },
    })).resolves.toMatchObject({ subject: "user-1", entitlementVersion: 5, bridgePairingId });
    await expect(verifyEnhancedLease(issued.token, {
      now,
      issuer: "https://cheemspay.test/api/licenses",
      publicKeys: { "test-key": issued.publicKey },
    })).rejects.toThrow();
  });

  it("verifies a phone-only Lease without Web Crypto on an HTTP LAN page", async () => {
    const now = Date.parse("2026-08-26T00:00:00Z");
    const bridgePairingId = "bridge_pairing_1234567890";
    const issued = mobileLease({ now, bridgePairingId });
    const originalCrypto = Object.getOwnPropertyDescriptor(globalThis, "crypto");
    Object.defineProperty(globalThis, "crypto", { configurable: true, value: {} });
    try {
      await expect(verifyMobileEnhancedLease(issued.token, bridgePairingId, {
        now,
        issuer: "https://cheemspay.test/api/licenses",
        publicKeys: { "test-key": issued.publicKey },
      })).resolves.toMatchObject({ subject: "user-1", bridgePairingId });
      const parts = issued.token.split(".");
      const first = parts[2]![0] === "A" ? "B" : "A";
      const tampered = `${parts[0]}.${parts[1]}.${first}${parts[2]!.slice(1)}`;
      await expect(verifyMobileEnhancedLease(tampered, bridgePairingId, {
        now,
        issuer: "https://cheemspay.test/api/licenses",
        publicKeys: { "test-key": issued.publicKey },
      })).rejects.toThrow("签名无效");
    } finally {
      if (originalCrypto) Object.defineProperty(globalThis, "crypto", originalCrypto);
      else delete (globalThis as { crypto?: unknown }).crypto;
    }
  });
});

function encode(value: unknown): string {
  return Buffer.from(JSON.stringify(value)).toString("base64url");
}
