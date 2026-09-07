export type DailyActiveEdition = "Lite" | "Standard" | "Enhanced";
export type DailyActiveResult = "reported" | "already-reported" | "disabled" | "failed";

const ENDPOINT = "https://bomanaupdate.ruikang.wang/api/v1/telemetry/dau";
const INSTALL_SECRET_KEY = "bomana:dau:install-secret:v1";
const REPORTED_UTC_DAY_KEY = "bomana:dau:reported-utc-day:v1";
const DISABLED_KEY = "bomana:dau:disabled:v1";
const INSTALL_SECRET_BYTES = 32;
const REQUEST_TIMEOUT_MS = 1_500;

type DailyActiveStorage = Pick<Storage, "getItem" | "setItem" | "removeItem">;

export function readDailyActiveEnabled(storage: DailyActiveStorage = localStorage): boolean {
  try { return storage.getItem(DISABLED_KEY) !== "1"; } catch { return false; }
}

export function setDailyActiveEnabled(enabled: boolean, storage: DailyActiveStorage = localStorage): void {
  if (enabled) storage.removeItem(DISABLED_KEY);
  else storage.setItem(DISABLED_KEY, "1");
}

export async function reportDailyActive(
  edition: DailyActiveEdition,
  dependencies: {
    readonly storage?: DailyActiveStorage;
    readonly fetcher?: typeof fetch;
    readonly cryptoProvider?: Crypto;
    readonly now?: () => Date;
    readonly endpoint?: string;
    readonly timeoutMs?: number;
  } = {},
): Promise<DailyActiveResult> {
  try {
    if (!new Set<DailyActiveEdition>(["Lite", "Standard", "Enhanced"]).has(edition)) return "failed";
    const storage = dependencies.storage ?? localStorage;
    if (!readDailyActiveEnabled(storage)) return "disabled";
    const utcDay = (dependencies.now?.() ?? new Date()).toISOString().slice(0, 10);
    if (storage.getItem(REPORTED_UTC_DAY_KEY) === utcDay) return "already-reported";
    const cryptoProvider = dependencies.cryptoProvider ?? crypto;
    const secret = loadOrCreateSecret(storage, cryptoProvider);
    storage.setItem(REPORTED_UTC_DAY_KEY, utcDay);
    const installDayToken = await deriveInstallDayToken(secret, utcDay, cryptoProvider);
    const controller = new AbortController();
    const timeout = globalThis.setTimeout(() => controller.abort(), dependencies.timeoutMs ?? REQUEST_TIMEOUT_MS);
    try {
      const response = await (dependencies.fetcher ?? fetch)(dependencies.endpoint ?? ENDPOINT, {
        method: "POST",
        mode: "cors",
        cache: "no-store",
        credentials: "omit",
        referrerPolicy: "no-referrer",
        keepalive: true,
        signal: controller.signal,
        headers: { Accept: "application/json", "Content-Type": "application/json" },
        body: JSON.stringify({ schema_version: 1, install_day_token: installDayToken, channel: edition }),
      });
      return response.ok ? "reported" : "failed";
    } finally {
      globalThis.clearTimeout(timeout);
    }
  } catch {
    return "failed";
  }
}

function loadOrCreateSecret(storage: DailyActiveStorage, cryptoProvider: Crypto): Uint8Array<ArrayBuffer> {
  const existing = decodeSecret(storage.getItem(INSTALL_SECRET_KEY));
  if (existing) return existing;
  const secret = new Uint8Array(INSTALL_SECRET_BYTES);
  cryptoProvider.getRandomValues(secret);
  storage.setItem(INSTALL_SECRET_KEY, encodeBase64Url(secret));
  return secret;
}

async function deriveInstallDayToken(secret: Uint8Array<ArrayBuffer>, utcDay: string, cryptoProvider: Crypto): Promise<string> {
  const key = await cryptoProvider.subtle.importKey("raw", secret, { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const signature = await cryptoProvider.subtle.sign("HMAC", key, new TextEncoder().encode(utcDay));
  return [...new Uint8Array(signature)].map((value) => value.toString(16).padStart(2, "0")).join("");
}

function decodeSecret(raw: string | null): Uint8Array<ArrayBuffer> | null {
  if (!raw || !/^[A-Za-z0-9_-]{43}$/.test(raw)) return null;
  try {
    const padded = raw.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - raw.length % 4) % 4);
    const binary = atob(padded);
    if (binary.length !== INSTALL_SECRET_BYTES) return null;
    return Uint8Array.from(binary, (character) => character.charCodeAt(0));
  } catch { return null; }
}

function encodeBase64Url(value: Uint8Array): string {
  let binary = "";
  for (const byte of value) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}
