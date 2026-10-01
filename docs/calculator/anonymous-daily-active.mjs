// Generated from frontend/src/runtime/anonymous-daily-active.ts.




const ENDPOINT = "https://bomanaupdate.ruikang.wang/api/v2/metrics/events";
const INSTALL_SECRET_KEY = "bomana:dau:install-secret:v1";
const REPORTED_UTC_DAY_KEY = "bomana:dau:reported-utc-day:v1";
const DISABLED_KEY = "bomana:dau:disabled:v1";
const INSTALL_SECRET_BYTES = 32;
const REQUEST_TIMEOUT_MS = 1_500;












export function readDailyActiveEnabled(storage                     = localStorage)          {
  try { return storage.getItem(DISABLED_KEY) !== "1"; } catch { return false; }
}

export function setDailyActiveEnabled(enabled         , storage                     = localStorage)       {
  if (enabled) storage.removeItem(DISABLED_KEY);
  else storage.setItem(DISABLED_KEY, "1");
}

export async function reportDailyActive(
  edition                    ,
  dependencies                      = {},
)                             {
  try {
    if (!new Set                    (["Lite", "Standard", "Enhanced", "Calculator"]).has(edition)) return "failed";
    const storage = dependencies.storage ?? localStorage;
    if (!readDailyActiveEnabled(storage)) return "disabled";
    const utcDay = (dependencies.now?.() ?? new Date()).toISOString().slice(0, 10);
    const reportedDayKey = edition === "Calculator" ? `${REPORTED_UTC_DAY_KEY}:calculator` : REPORTED_UTC_DAY_KEY;
    if (storage.getItem(reportedDayKey) === utcDay) return "already-reported";
    const cryptoProvider = dependencies.cryptoProvider ?? crypto;
    const secret = loadOrCreateSecret(storage, cryptoProvider);
    storage.setItem(reportedDayKey, utcDay);
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
        body: JSON.stringify({ type: "dau", day: utcDay, dailyToken: installDayToken, channel: edition }),
      });
      return response.ok ? "reported" : "failed";
    } finally {
      globalThis.clearTimeout(timeout);
    }
  } catch {
    return "failed";
  }
}

// Created once per document. Only successful App bootstrap calls this reporter;
// component mounts, Launcher, Calculator and Bridge reconnects do not call it.
export function createAppMetricsReporter(
  dependencies                                                     = {},
)                                                                                          {
  let attempted = false;
  return async (edition, surface = "web") => {
    try {
      const origin = dependencies.origin ?? location.origin;
      const url = new URL(origin);
      const parts = url.hostname.split(".").map(Number);
      const privateIPv4 = parts.length === 4 && parts.every((part) => Number.isInteger(part) && part >= 0 && part <= 255)
        && (parts[0] === 10 || (parts[0] === 172 && parts[1]  >= 16 && parts[1]  <= 31) || (parts[0] === 192 && parts[1] === 168));
      if (origin !== "https://bomana.ruikang.wang" && !(url.protocol === "http:" && privateIPv4)) return "disabled";
      const storage = dependencies.storage ?? localStorage;
      if (!readDailyActiveEnabled(storage)) return "disabled";
      if (attempted) return "already-reported";
      if (!["Lite", "Standard", "Enhanced"].includes(edition)) return "failed";
      attempted = true;
      void reportDailyActive(edition, dependencies);
      const random = new Uint8Array(16);
      (dependencies.cryptoProvider ?? crypto).getRandomValues(random);
      const payload = JSON.stringify({
        type: "app_start",
        eventId: [...random].map((byte) => byte.toString(16).padStart(2, "0")).join(""),
        occurredAt: (dependencies.now?.() ?? new Date()).toISOString(), channel: edition, surface,
      });
      // One bounded retry reuses the same event ID, including across UTC midnight.
      for (let attempt = 0; attempt < 2; attempt += 1) {
        const controller = new AbortController();
        const timeout = globalThis.setTimeout(() => controller.abort(), dependencies.timeoutMs ?? REQUEST_TIMEOUT_MS);
        try {
          const response = await (dependencies.fetcher ?? fetch)(dependencies.endpoint ?? ENDPOINT, {
            method: "POST", mode: "cors", cache: "no-store", credentials: "omit", referrerPolicy: "no-referrer",
            keepalive: true, signal: controller.signal,
            headers: { Accept: "application/json", "Content-Type": "application/json" }, body: payload,
          });
          if (response.ok) return "reported";
          if (response.status < 500 && response.status !== 429) return "failed";
        } catch { /* Best effort; a lost acknowledgement is safe to retry. */ }
        finally { globalThis.clearTimeout(timeout); }
        if (attempt === 0) await new Promise((resolve) => globalThis.setTimeout(resolve, 250));
      }
      return "failed";
    } catch { return "failed"; }
  };
}

export const reportAppInitialized = createAppMetricsReporter();

function loadOrCreateSecret(storage                    , cryptoProvider        )                          {
  const existing = decodeSecret(storage.getItem(INSTALL_SECRET_KEY));
  if (existing) return existing;
  const secret = new Uint8Array(INSTALL_SECRET_BYTES);
  cryptoProvider.getRandomValues(secret);
  storage.setItem(INSTALL_SECRET_KEY, encodeBase64Url(secret));
  return secret;
}

async function deriveInstallDayToken(secret                         , utcDay        , cryptoProvider        )                  {
  const key = await cryptoProvider.subtle.importKey("raw", secret, { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const signature = await cryptoProvider.subtle.sign("HMAC", key, new TextEncoder().encode(utcDay));
  return [...new Uint8Array(signature)].map((value) => value.toString(16).padStart(2, "0")).join("");
}

function decodeSecret(raw               )                                 {
  if (!raw || !/^[A-Za-z0-9_-]{43}$/.test(raw)) return null;
  try {
    const padded = raw.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - raw.length % 4) % 4);
    const binary = atob(padded);
    if (binary.length !== INSTALL_SECRET_BYTES) return null;
    return Uint8Array.from(binary, (character) => character.charCodeAt(0));
  } catch { return null; }
}

function encodeBase64Url(value            )         {
  let binary = "";
  for (const byte of value) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}
