import type { OfflineAssetDescriptor, OfflineAssetKind } from "./persistent-asset-store";
import { sha256Digest, verifyEd25519Signature } from "./crypto-compat";

interface OfflineRootObject {
  readonly id: string;
  readonly kind: OfflineAssetKind;
  readonly sha256: string;
  readonly size_bytes: number;
}

export interface SignedOfflineRoot {
  readonly schema_version: 1;
  readonly scope: string;
  readonly revision: string;
  readonly objects: readonly OfflineRootObject[];
  readonly manifest_signature: {
    readonly algorithm: "ed25519";
    readonly key_id: string;
    readonly signature: string;
  };
}

const PINNED_KEYS: Readonly<Record<string, string>> = Object.freeze({
  "bomana-offline-2026-v1": "zSMo0z0dAKYP2j0pV68vJ0NvtonEV1CVyMWz/f5Rd6s=",
  "bomana-development-only": "1xSyz/1XoUPZfDCPlTA9GHkT6XJXIvMDtCHd+h11LOQ=",
});

export class VerifiedOfflineCatalog {
  readonly revision: string;
  readonly #objects: ReadonlyMap<string, OfflineRootObject>;
  readonly #urls: Readonly<Record<string, URL>>;
  constructor(root: SignedOfflineRoot, urls: Readonly<Record<string, URL>>) {
    this.revision = root.revision;
    this.#objects = new Map(root.objects.map((object) => [object.id, object]));
    this.#urls = urls;
  }
  asset(id: string): OfflineAssetDescriptor {
    const object = this.#objects.get(id);
    const url = this.#urls[id];
    if (!object || !url) throw new Error(`签名离线清单缺少对象：${id}`);
    return Object.freeze({ id: object.id, kind: object.kind, sha256: object.sha256, sizeBytes: object.size_bytes, url });
  }
}

export async function openVerifiedOfflineCatalog(
  rawRoot: unknown,
  urls: Readonly<Record<string, URL>>,
  options: { readonly expectedScope: string; readonly hostname?: string },
): Promise<VerifiedOfflineCatalog> {
  const root = parseRoot(rawRoot, options.expectedScope);
  const keyId = root.manifest_signature.key_id;
  const encodedKey = PINNED_KEYS[keyId];
  if (!encodedKey) throw new Error("离线根清单签名密钥不受信任");
  const hostname = options.hostname ?? globalThis.location?.hostname ?? "";
  if (keyId === "bomana-development-only" && !isLoopback(hostname)) {
    throw new Error("development-only 离线根清单只能在本机预览使用");
  }
  const unsigned = {
    schema_version: root.schema_version,
    scope: root.scope,
    objects: root.objects,
    revision: root.revision,
  };
  const revisionCore = { schema_version: root.schema_version, scope: root.scope, objects: root.objects };
  if (await sha256Hex(new TextEncoder().encode(canonicalJson(revisionCore)).buffer as ArrayBuffer) !== root.revision) {
    throw new Error("离线根清单 revision 不匹配");
  }
  const valid = await verifyEd25519Signature(
    decodeBase64(encodedKey),
    decodeBase64(root.manifest_signature.signature),
    new TextEncoder().encode(canonicalJson(unsigned)),
  );
  if (!valid) throw new Error("离线根清单签名校验失败");
  for (const object of root.objects) {
    if (!urls[object.id]) throw new Error(`离线根清单缺少受控 URL：${object.id}`);
  }
  return new VerifiedOfflineCatalog(root, urls);
}

function parseRoot(value: unknown, expectedScope: string): SignedOfflineRoot {
  const record = object(value);
  const objects = array(record.objects).map((value) => {
    const item = object(value);
    const parsed = {
      id: text(item.id), kind: text(item.kind), sha256: text(item.sha256), size_bytes: integer(item.size_bytes),
    };
    if (!/^[a-z][a-z0-9._-]{0,95}$/.test(parsed.id) || !["terrain", "weapon", "airfield", "reference", "wasm"].includes(parsed.kind)
      || !/^[a-f0-9]{64}$/.test(parsed.sha256) || parsed.size_bytes <= 0 || parsed.size_bytes > 256 * 1024 * 1024) {
      throw new Error("离线根清单对象无效");
    }
    return Object.freeze(parsed) as OfflineRootObject;
  });
  const signature = object(record.manifest_signature);
  const parsed = {
    schema_version: record.schema_version,
    scope: text(record.scope), revision: text(record.revision), objects: Object.freeze(objects),
    manifest_signature: Object.freeze({ algorithm: text(signature.algorithm), key_id: text(signature.key_id), signature: text(signature.signature) }),
  } as unknown as SignedOfflineRoot;
  if (parsed.schema_version !== 1 || parsed.scope !== expectedScope || !/^[a-f0-9]{64}$/.test(parsed.revision)
    || parsed.manifest_signature.algorithm !== "ed25519" || !parsed.objects.length
    || new Set(parsed.objects.map((object) => object.id)).size !== parsed.objects.length) {
    throw new Error("离线根清单结构无效");
  }
  return Object.freeze(parsed);
}

function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.entries(value as Record<string, unknown>).sort(([left], [right]) => left < right ? -1 : left > right ? 1 : 0).map(([key, item]) => `${JSON.stringify(key)}:${canonicalJson(item)}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

async function sha256Hex(bytes: ArrayBuffer): Promise<string> {
  return [...await sha256Digest(bytes)].map((value) => value.toString(16).padStart(2, "0")).join("");
}

function decodeBase64(value: string): ArrayBuffer {
  const binary = atob(value.replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from(binary, (character) => character.charCodeAt(0)).buffer;
}

function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("离线根清单无效");
  return value as Record<string, unknown>;
}
function array(value: unknown): unknown[] { if (!Array.isArray(value)) throw new Error("离线根清单数组无效"); return value; }
function text(value: unknown): string { return typeof value === "string" ? value : ""; }
function integer(value: unknown): number { return typeof value === "number" && Number.isInteger(value) ? value : 0; }
function isLoopback(hostname: string): boolean { return hostname === "127.0.0.1" || hostname === "localhost" || hostname === "::1"; }
