export const BROWSER_AUTHORIZATION_KEY = "bomana:cheemspay:authorization:v3";
export const ENHANCED_FEATURE = "bomana.super_bomber";

const LEASE_ISSUER = "https://pay.ruikang.wang/api/licenses";
const LEASE_AUDIENCE = "bomana:web";
const MAX_LEASE_SECONDS = 14 * 24 * 60 * 60;
const ED25519_SPKI_PREFIX = Uint8Array.from([0x30, 0x2a, 0x30, 0x05, 0x06, 0x03, 0x2b, 0x65, 0x70, 0x03, 0x21, 0x00]);
const PRODUCTION_LICENSE_KEYS: Readonly<Record<string, string>> = Object.freeze({
  "prod-2026-01": "MCowBQYDK2VwAyEAN30P0bd6DN_fP7iMf1qkzBBkssGMHj0b18B81TsW6n8",
});

export interface StoredBrowserAuthorization {
  readonly schemaVersion: 3;
  readonly accessToken: string;
  readonly accountLabel: string;
  readonly enhancedLease: string | null;
  readonly enhancedLeaseExpiresAt: number;
  readonly validatedAt: number;
}

export interface VerifiedEnhancedLease {
  readonly subject: string;
  readonly entitlementVersion: number;
  readonly expiresAt: number;
}

export interface VerifiedMobileEnhancedLease extends VerifiedEnhancedLease {
  readonly bridgePairingId: string;
}

type BrowserStorage = Pick<Storage, "getItem" | "setItem" | "removeItem">;

export function readBrowserAuthorization(storage: BrowserStorage = localStorage): StoredBrowserAuthorization | null {
  try {
    const raw = storage.getItem(BROWSER_AUTHORIZATION_KEY);
    if (!raw) return null;
    const value = JSON.parse(raw) as Partial<StoredBrowserAuthorization>;
    if (value.schemaVersion !== 3 || typeof value.accessToken !== "string" || !value.accessToken
      || typeof value.accountLabel !== "string" || !(value.enhancedLease === null || typeof value.enhancedLease === "string")
      || !Number.isFinite(value.enhancedLeaseExpiresAt) || !Number.isFinite(value.validatedAt)) throw new TypeError("invalid authorization");
    return value as StoredBrowserAuthorization;
  } catch {
    storage.removeItem(BROWSER_AUTHORIZATION_KEY);
    return null;
  }
}

export function saveBrowserAuthorization(value: StoredBrowserAuthorization, storage: BrowserStorage = localStorage): void {
  storage.setItem(BROWSER_AUTHORIZATION_KEY, JSON.stringify(value));
}

export function clearBrowserAuthorization(storage: BrowserStorage = localStorage): void {
  storage.removeItem(BROWSER_AUTHORIZATION_KEY);
}

export async function verifyEnhancedLease(
  token: string,
  options: {
    readonly now?: number;
    readonly issuer?: string;
    readonly audience?: string;
    readonly publicKeys?: Readonly<Record<string, string>>;
  } = {},
): Promise<VerifiedEnhancedLease> {
  if (token.length < 64 || token.length > 8_192) throw new Error("Enhanced Lease 长度无效");
  const segments = token.split(".");
  if (segments.length !== 3 || segments.some((segment) => !/^[A-Za-z0-9_-]+$/.test(segment))) throw new Error("Enhanced Lease 格式无效");
  const header = parseObject(decodeJson(segments[0]!), "Enhanced Lease 头无效");
  const claims = parseObject(decodeJson(segments[1]!), "Enhanced Lease 声明无效");
  const keyId = text(header.kid);
  const encodedKey = (options.publicKeys ?? PRODUCTION_LICENSE_KEYS)[keyId];
  if (header.alg !== "EdDSA" || header.typ !== "bomana-web-access+jwt" || !encodedKey) throw new Error("Enhanced Lease 签名密钥不受信任");
  const valid = await verifyEd25519Signature(
    decodeBase64Url(encodedKey),
    decodeBase64Url(segments[2]!),
    new TextEncoder().encode(`${segments[0]}.${segments[1]}`),
  );
  if (!valid) throw new Error("Enhanced Lease 签名无效");

  const now = options.now ?? Date.now();
  const issuedAt = integer(claims.iat);
  const expiresAtSeconds = integer(claims.exp);
  const serviceExpiresAt = claims.service_expires_at === null ? Number.POSITIVE_INFINITY : Date.parse(text(claims.service_expires_at));
  if (claims.iss !== (options.issuer ?? LEASE_ISSUER) || claims.aud !== (options.audience ?? LEASE_AUDIENCE)
    || claims.app_id !== "bomana" || claims.required_feature !== ENHANCED_FEATURE
    || !text(claims.sub) || !text(claims.jti) || (!Number.isFinite(serviceExpiresAt) && serviceExpiresAt !== Number.POSITIVE_INFINITY)
    || issuedAt <= 0 || expiresAtSeconds <= issuedAt || expiresAtSeconds - issuedAt > MAX_LEASE_SECONDS
    || now < (issuedAt - 300) * 1_000 || now >= expiresAtSeconds * 1_000 || expiresAtSeconds * 1_000 > serviceExpiresAt
    || integer(claims.entitlement_version) < 0) throw new Error("Enhanced Lease 已过期或声明无效");
  return Object.freeze({
    subject: text(claims.sub),
    entitlementVersion: integer(claims.entitlement_version),
    expiresAt: expiresAtSeconds * 1_000,
  });
}

export async function verifyMobileEnhancedLease(
  token: string,
  bridgePairingId: string,
  options: {
    readonly now?: number;
    readonly issuer?: string;
    readonly publicKeys?: Readonly<Record<string, string>>;
  } = {},
): Promise<VerifiedMobileEnhancedLease> {
  if (!/^[A-Za-z0-9_-]{16,96}$/.test(bridgePairingId)) throw new Error("手机 Bridge 配对标识无效");
  if (token.length < 64 || token.length > 8_192) throw new Error("手机 Enhanced Lease 长度无效");
  const segments = token.split(".");
  if (segments.length !== 3 || segments.some((segment) => !/^[A-Za-z0-9_-]+$/.test(segment))) {
    throw new Error("手机 Enhanced Lease 格式无效");
  }
  const header = parseObject(decodeJson(segments[0]!), "手机 Enhanced Lease 头无效");
  const claims = parseObject(decodeJson(segments[1]!), "手机 Enhanced Lease 声明无效");
  const keyId = text(header.kid);
  const encodedKey = (options.publicKeys ?? PRODUCTION_LICENSE_KEYS)[keyId];
  if (header.alg !== "EdDSA" || header.typ !== "bomana-mobile-access+jwt" || !encodedKey) {
    throw new Error("手机 Enhanced Lease 签名密钥不受信任");
  }
  const valid = await verifyEd25519Signature(
    decodeBase64Url(encodedKey),
    decodeBase64Url(segments[2]!),
    new TextEncoder().encode(`${segments[0]}.${segments[1]}`),
  );
  if (!valid) throw new Error("手机 Enhanced Lease 签名无效");

  const now = options.now ?? Date.now();
  const issuedAt = integer(claims.iat);
  const expiresAtSeconds = integer(claims.exp);
  const serviceExpiresAt = claims.service_expires_at === null
    ? Number.POSITIVE_INFINITY
    : Date.parse(text(claims.service_expires_at));
  if (
    claims.iss !== (options.issuer ?? LEASE_ISSUER) ||
    claims.aud !== "bomana:mobile-web" ||
    claims.app_id !== "bomana" ||
    claims.required_feature !== ENHANCED_FEATURE ||
    claims.bridge_pairing_id !== bridgePairingId ||
    !text(claims.sub) ||
    !text(claims.jti) ||
    !Number.isFinite(serviceExpiresAt) && serviceExpiresAt !== Number.POSITIVE_INFINITY ||
    issuedAt <= 0 ||
    expiresAtSeconds <= issuedAt ||
    expiresAtSeconds - issuedAt > 8 * 60 * 60 ||
    now < (issuedAt - 300) * 1_000 ||
    now >= expiresAtSeconds * 1_000 ||
    expiresAtSeconds * 1_000 > serviceExpiresAt ||
    integer(claims.entitlement_version) < 0
  ) throw new Error("手机 Enhanced Lease 已过期或声明无效");
  return Object.freeze({
    subject: text(claims.sub),
    entitlementVersion: integer(claims.entitlement_version),
    expiresAt: expiresAtSeconds * 1_000,
    bridgePairingId,
  });
}

async function verifyEd25519Signature(
  spki: ArrayBuffer,
  signature: ArrayBuffer,
  message: Uint8Array,
): Promise<boolean> {
  const subtle = globalThis.crypto?.subtle;
  if (subtle) {
    try {
      const publicKey = await subtle.importKey("spki", spki, { name: "Ed25519" }, false, ["verify"]);
      return await subtle.verify({ name: "Ed25519" }, publicKey, signature, Uint8Array.from(message));
    } catch {
      // RFC1918 HTTP pages are not secure contexts on iOS. The bundled verifier
      // keeps Mobile Enhanced Lease verification on the phone in that context.
    }
  }
  try {
    const [ed25519, hashes] = await Promise.all([
      import("@noble/ed25519"),
      import("@noble/hashes/sha2.js"),
    ]);
    ed25519.hashes.sha512 = hashes.sha512;
    return ed25519.verify(
      new Uint8Array(signature),
      message,
      extractEd25519PublicKey(new Uint8Array(spki)),
      { zip215: false },
    );
  } catch {
    return false;
  }
}

function extractEd25519PublicKey(spki: Uint8Array): Uint8Array {
  if (spki.length !== ED25519_SPKI_PREFIX.length + 32) throw new Error("invalid Ed25519 SPKI length");
  for (let index = 0; index < ED25519_SPKI_PREFIX.length; index += 1) {
    if (spki[index] !== ED25519_SPKI_PREFIX[index]) throw new Error("invalid Ed25519 SPKI prefix");
  }
  return spki.slice(ED25519_SPKI_PREFIX.length);
}

function decodeJson(segment: string): unknown {
  return JSON.parse(new TextDecoder().decode(decodeBase64Url(segment))) as unknown;
}

function decodeBase64Url(value: string): ArrayBuffer {
  const padded = value.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - value.length % 4) % 4);
  const binary = atob(padded);
  return Uint8Array.from(binary, (character) => character.charCodeAt(0)).buffer;
}

function parseObject(value: unknown, message: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error(message);
  return value as Record<string, unknown>;
}
function text(value: unknown): string { return typeof value === "string" ? value : ""; }
function integer(value: unknown): number { return typeof value === "number" && Number.isInteger(value) ? value : -1; }
