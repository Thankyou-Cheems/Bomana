import {
  configureMobileBridge,
  discoverBridgeEndpoint,
  provePairedOfficialRoutes,
} from "./bridge-discovery";
import { queryLocalNetworkPermission as queryBrowserLocalNetworkPermission } from "./local-network-permission";
import {
  SoundCuePreferencesStore,
  decodeSoundCuePreferences,
  encodeSoundCuePreferences,
  type SoundCuePreferences,
} from "./sound-cues";

const MOBILE_SESSION_KEY = "bomana:mobile-pairing:v1";
const MOBILE_HANDOFF_ORIGIN = "https://bomana.ruikang.wang";
const MOBILE_REOPEN_WINDOW_MS = 15 * 60_000;

export type MobileEdition = "Standard" | "Enhanced";
export type MobileLeaseVerifier = (
  lease: string,
  bridgePairingId: string,
  options: { readonly now: number },
) => Promise<{ readonly expiresAt: number }>;

export type MobileLanBrowserKind = "supported" | "embedded-webview" | "ios";

export interface MobileNetworkCandidate {
  readonly interface: string;
  readonly address: string;
  readonly endpoint: string;
  readonly tlsEndpoint?: string;
}

export interface DesktopMobilePairingOffer {
  readonly edition: MobileEdition;
  readonly bridgePairingId: string;
  readonly pairingCode: string;
  readonly expiresAt: number;
  readonly networks: readonly MobileNetworkCandidate[];
  pairingURL(endpoint: string): string;
}

export interface StoredMobilePairingSession {
  readonly schemaVersion: 3;
  readonly edition: MobileEdition;
  readonly bridgePairingId: string;
  readonly pairingToken: string;
  readonly endpoints: readonly string[];
  readonly mobileLease?: string;
  readonly expiresAt: number;
  readonly reopenUntil: number;
}

export interface IssuedMobilePairingLease {
  readonly bridgePairingId: string;
  readonly mobileLease: string;
  readonly expiresAt: number;
}

export interface TrayMobilePairingHandoff {
  readonly edition: "Enhanced";
  readonly bridgePairingId: string;
  readonly pairingToken: string;
  readonly localPage: URL;
  readonly pairingExpiresAt: number;
  readonly soundPreferences: SoundCuePreferences | null;
}

export interface MobilePairingStartContext {
  readonly bridgeBase: URL;
  readonly bridgePairingId: string;
  readonly pairingToken: string;
  readonly pairingExpiresAt: number;
}

interface MobilePairingNavigationTarget {
  readonly location: {
    readonly hash: string;
    reload(): void;
  };
  addEventListener(type: "hashchange", listener: EventListener): void;
}

type Fetcher = typeof fetch;
type SessionStorage = Pick<Storage, "getItem" | "setItem" | "removeItem">;

export async function beginDesktopMobilePairing(input: {
  readonly edition: MobileEdition;
  readonly fetcher?: Fetcher;
  readonly forceNew?: boolean;
  readonly soundPreferences?: SoundCuePreferences;
  readonly prepareEnhanced?: (context: MobilePairingStartContext) => Promise<IssuedMobilePairingLease>;
}): Promise<DesktopMobilePairingOffer> {
  const fetcher = input.fetcher ?? fetch;
  const bridgeBase = await discoverBridgeEndpoint(fetcher);
  const bridgeResponse = await fetcher(new URL(
    input.forceNew ? "api/v1/mobile/pairing/rotate" : "api/v1/mobile/pairing/start",
    bridgeBase,
  ), {
    method: "POST",
    mode: "cors",
    cache: "no-store",
    credentials: "omit",
    referrerPolicy: "no-referrer",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ schema_version: 1, edition: input.edition }),
  });
  if (!bridgeResponse.ok) throw new Error(`Bridge 手机配对 HTTP ${bridgeResponse.status}`);
  const bridge = await bridgeResponse.json() as {
    schema_version?: unknown;
    mobile_pairing_protocol?: unknown;
    edition?: unknown;
    bridge_pairing_id?: unknown;
    pairing_token?: unknown;
    pairing_code?: unknown;
    pairing_expires_at?: unknown;
    expires_at?: unknown;
    networks?: unknown;
  };
  const bridgePairingId = text(bridge.bridge_pairing_id);
  const pairingToken = text(bridge.pairing_token);
  const bridgePairingCode = text(bridge.pairing_code);
  const bridgePairingExpiresAt = Date.parse(text(bridge.pairing_expires_at));
  const expiresAt = Date.parse(text(bridge.expires_at));
  const networks = normalizeNetworks(bridge.networks);
  if (bridge.mobile_pairing_protocol !== 7) {
    throw new Error("Bridge 手机配对协议过旧，请退出并重启 Bomana Bridge 后重试");
  }
  if (
    bridge.schema_version !== 1 ||
    bridge.edition !== input.edition ||
    !/^[A-Za-z0-9_-]{16,96}$/.test(bridgePairingId) ||
    !/^[A-Za-z0-9_-]{43}$/.test(pairingToken) ||
    !/^[A-Z2-9]{4}-[A-Z2-9]{4}$/.test(bridgePairingCode) ||
    !Number.isFinite(bridgePairingExpiresAt) ||
    !Number.isFinite(expiresAt) ||
    expiresAt <= Date.now() ||
    networks.length === 0
  ) throw new Error("Bridge 手机配对响应无效");

  let effectiveExpiry = bridgePairingExpiresAt;
  let enhancedPrepared = false;
  if (input.edition === "Enhanced" && input.prepareEnhanced) {
    const issued = await input.prepareEnhanced({ bridgeBase, bridgePairingId, pairingToken, pairingExpiresAt: bridgePairingExpiresAt });
    effectiveExpiry = Math.min(bridgePairingExpiresAt, issued.expiresAt);
    const prepareResponse = await fetcher(new URL("api/v1/mobile/pairing/prepare", bridgeBase), {
      method: "POST",
      mode: "cors",
      cache: "no-store",
      credentials: "omit",
      referrerPolicy: "no-referrer",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        schema_version: 1,
        bridge_pairing_id: bridgePairingId,
        pairing_token: pairingToken,
        mobile_lease: issued.mobileLease,
        mobile_lease_expires_at: new Date(issued.expiresAt).toISOString(),
        pairing_expires_at: new Date(effectiveExpiry).toISOString(),
      }),
    });
    if (!prepareResponse.ok) throw new Error(`Bridge 手机配对准备 HTTP ${prepareResponse.status}`);
    enhancedPrepared = true;
  }
  return Object.freeze({
    edition: input.edition,
    bridgePairingId,
    pairingCode: bridgePairingCode,
    expiresAt: effectiveExpiry,
    networks,
    pairingURL: (endpoint: string) => {
      const pageOrigin = normalizePrivateEndpoint(endpoint, "http:") ?? normalizePrivateEndpoint(endpoint, "https:");
      if (!pageOrigin) throw new Error("请选择手机当前连接的局域网");
      const mobilePath = `/mobile/${input.edition}/`;
      const localPage = new URL(mobilePath, pageOrigin);
      const handoffParameters = new URLSearchParams({
        "mobile-lan": localPage.toString(),
        "mobile-pairing": pairingToken,
        "mobile-edition": input.edition,
      });
      if (input.soundPreferences) {
        handoffParameters.set("mobile-sound", encodeSoundCuePreferences(input.soundPreferences));
      }
      if (input.edition === "Standard") {
        localPage.hash = new URLSearchParams({
          "mobile-edition": input.edition,
          "mobile-pairing": pairingToken,
          ...(input.soundPreferences ? { "mobile-sound": encodeSoundCuePreferences(input.soundPreferences) } : {}),
        }).toString();
        return localPage.toString();
      }
      const handoff = new URL(mobilePath, MOBILE_HANDOFF_ORIGIN);
      if (!enhancedPrepared) {
        handoff.searchParams.set("handoff", "bridge-tray");
        handoffParameters.set("mobile-tray", "1");
        handoffParameters.set("bridge-pairing", bridgePairingId);
        handoffParameters.set("pairing-expires", new Date(bridgePairingExpiresAt).toISOString());
      }
      handoff.hash = handoffParameters.toString();
      return handoff.toString();
    },
  });
}

export function mobilePairingHandoffTarget(hash = globalThis.location?.hash ?? ""): URL | null {
  const parameters = new URLSearchParams(hash.startsWith("#") ? hash.slice(1) : hash);
  if (parameters.has("mobile-tray")) return null;
  const localRaw = parameters.getAll("mobile-lan");
  const claims = parameters.getAll("mobile-pairing");
  const editions = parameters.getAll("mobile-edition");
  const sounds = parameters.getAll("mobile-sound");
  if (
    localRaw.length !== 1
    || claims.length !== 1
    || editions.length !== 1 || editions[0] !== "Enhanced"
    || sounds.length > 1
    || !/^[A-Za-z0-9_-]{43}$/.test(claims[0]!)
    || sounds.length === 1 && !decodeSoundCuePreferences(sounds[0]!)
  ) return null;
  try {
    const local = new URL(localRaw[0]!);
    const protocol = local.protocol === "https:" ? "https:" : "http:";
    const origin = normalizePrivateEndpoint(`${local.origin}/`, protocol);
    if (!origin || local.pathname !== "/mobile/Enhanced/" || local.search || local.hash) return null;
    const target = new URL("/mobile/Enhanced/", origin);
    const targetParameters = new URLSearchParams({
      "mobile-edition": "Enhanced",
      "mobile-pairing": claims[0]!,
    });
    if (sounds[0]) targetParameters.set("mobile-sound", sounds[0]);
    target.hash = targetParameters.toString();
    return target;
  } catch {
    return null;
  }
}

export function trayMobilePairingHandoff(hash = globalThis.location?.hash ?? ""): TrayMobilePairingHandoff | null {
  const parameters = new URLSearchParams(hash.startsWith("#") ? hash.slice(1) : hash);
  const tray = parameters.getAll("mobile-tray");
  const localRaw = parameters.getAll("mobile-lan");
  const claims = parameters.getAll("mobile-pairing");
  const bridgePairings = parameters.getAll("bridge-pairing");
  const pairingExpiries = parameters.getAll("pairing-expires");
  const editions = parameters.getAll("mobile-edition");
  const sounds = parameters.getAll("mobile-sound");
  if (
    tray.length !== 1 || tray[0] !== "1"
    || localRaw.length !== 1
    || claims.length !== 1
    || bridgePairings.length !== 1
    || pairingExpiries.length !== 1
    || editions.length !== 1 || editions[0] !== "Enhanced"
    || sounds.length > 1
    || !/^[A-Za-z0-9_-]{43}$/.test(claims[0]!)
    || !/^[A-Za-z0-9_-]{16,96}$/.test(bridgePairings[0]!)
    || sounds.length === 1 && !decodeSoundCuePreferences(sounds[0]!)
  ) return null;
  try {
    const localPage = new URL(localRaw[0]!);
    const protocol = localPage.protocol === "https:" ? "https:" : "http:";
    const origin = normalizePrivateEndpoint(`${localPage.origin}/`, protocol);
    const pairingExpiresAt = Date.parse(pairingExpiries[0]!);
    if (
      !origin || localPage.pathname !== "/mobile/Enhanced/" || localPage.search || localPage.hash
      || !Number.isFinite(pairingExpiresAt) || pairingExpiresAt <= Date.now()
    ) return null;
    return Object.freeze({
      edition: "Enhanced",
      bridgePairingId: bridgePairings[0]!,
      pairingToken: claims[0]!,
      localPage: new URL("/mobile/Enhanced/", origin),
      pairingExpiresAt,
      soundPreferences: sounds[0] ? decodeSoundCuePreferences(sounds[0]!) : null,
    });
  } catch {
    return null;
  }
}

export function reloadOnTrayMobilePairingHashChange(
  target: MobilePairingNavigationTarget = window,
): void {
  target.addEventListener("hashchange", () => {
    if (trayMobilePairingHandoff(target.location.hash)) target.location.reload();
  });
}

export function reloadOnMobilePairingHashChange(
  target: MobilePairingNavigationTarget = window,
): void {
  target.addEventListener("hashchange", () => {
    const parameters = new URLSearchParams(target.location.hash.replace(/^#/, ""));
    if (parameters.has("mobile-pairing")) target.location.reload();
  });
}

export function authorizedTrayMobilePairingTarget(
  handoff: TrayMobilePairingHandoff,
  issued: IssuedMobilePairingLease,
): URL {
  if (issued.bridgePairingId !== handoff.bridgePairingId || issued.expiresAt <= Date.now()) {
    throw new Error("手机 Enhanced Lease 与 Bridge 配对不匹配");
  }
  const target = new URL(handoff.localPage);
  const parameters = new URLSearchParams({
    "mobile-edition": handoff.edition,
    "mobile-pairing": handoff.pairingToken,
    "mobile-tray-prepare": "1",
    "bridge-pairing": handoff.bridgePairingId,
    "pairing-expires": new Date(handoff.pairingExpiresAt).toISOString(),
    "mobile-lease": issued.mobileLease,
    "mobile-lease-expires": new Date(issued.expiresAt).toISOString(),
  });
  if (handoff.soundPreferences) parameters.set("mobile-sound", encodeSoundCuePreferences(handoff.soundPreferences));
  target.hash = parameters.toString();
  return target;
}

interface MobilePairingCompletionOptions {
  readonly edition: MobileEdition;
  readonly origin?: string;
  readonly fetcher?: Fetcher;
  readonly storage?: SessionStorage;
  readonly now?: number;
  readonly verifyLease?: MobileLeaseVerifier;
  readonly preferencesStorage?: SessionStorage;
}

interface MobilePairingLocationOptions extends MobilePairingCompletionOptions {
  readonly hash?: string;
  readonly replaceHistory?: (url: string) => void;
}

export async function claimOrRestoreMobilePairingSession(
  input: MobilePairingLocationOptions,
): Promise<"authorized" | "absent"> {
  const claimed = await completeMobilePairingFromLocation(input);
  if (claimed === "authorized") return claimed;
  const restored = await restoreMobilePairingSession(input.storage, input.now, input.edition, input.verifyLease);
  return restored ? "authorized" : "absent";
}

export async function completeMobilePairingFromLocation(input: MobilePairingLocationOptions): Promise<"authorized" | "absent"> {
  const hash = input.hash ?? globalThis.location?.hash ?? "";
  const parameters = new URLSearchParams(hash.startsWith("#") ? hash.slice(1) : hash);
  const claims = parameters.getAll("mobile-pairing");
  const editions = parameters.getAll("mobile-edition");
  const soundValues = parameters.getAll("mobile-sound");
  if (claims.length === 0) return "absent";
  const replacement = `${globalThis.location?.pathname ?? `/mobile/${input.edition}/`}${globalThis.location?.search ?? ""}`;
  if (input.replaceHistory) input.replaceHistory(replacement);
  else if (typeof globalThis.history?.replaceState === "function") globalThis.history.replaceState(null, "", replacement);
  const pairingToken = claims.length === 1 ? claims[0]! : "";
  if (!/^[A-Za-z0-9_-]{43}$/.test(pairingToken)) throw new Error("二维码配对凭据无效，请回到电脑重新生成并扫描");
  if (editions.length !== 1 || editions[0] !== input.edition) throw new Error("二维码手机版本不匹配，请回到电脑重新选择并扫描");
  if (soundValues.length > 1) throw new Error("二维码提示音设置无效，请回到电脑重新生成并扫描");
  const soundPreferences = soundValues.length === 1 ? decodeSoundCuePreferences(soundValues[0]!) : null;
  if (soundValues.length === 1 && !soundPreferences) throw new Error("二维码提示音设置无效，请回到电脑重新生成并扫描");
  const trayPreparation = readTrayPreparation(parameters);
  const saved = readMobilePairingSession(input.storage, input.now, input.edition);
  const sameClaim = saved?.pairingToken === pairingToken
    && saved.endpoints.includes(`${input.origin ?? globalThis.location?.origin ?? ""}/`)
    && (!trayPreparation || input.edition === "Enhanced"
      && saved.bridgePairingId === trayPreparation.bridgePairingId
      && saved.mobileLease === trayPreparation.mobileLease);
  const restored = sameClaim
    ? await restoreMobilePairingSession(input.storage, input.now, input.edition, input.verifyLease)
    : null;
  const result = restored ? "authorized" : await completeMobilePairing(
    input,
    { schema_version: 1, pairing_token: pairingToken },
    "claim",
    trayPreparation,
  );
  if (soundPreferences) new SoundCuePreferencesStore(input.preferencesStorage ?? localStorage).save(soundPreferences);
  return result;
}

export async function completeMobilePairingWithCode(input: {
  readonly edition: MobileEdition;
  readonly pairingCode: string;
  readonly origin?: string;
  readonly fetcher?: Fetcher;
  readonly storage?: SessionStorage;
  readonly now?: number;
  readonly verifyLease?: MobileLeaseVerifier;
}): Promise<"authorized"> {
  const pairingCode = input.pairingCode.trim().toUpperCase();
  if (!/^[A-Z2-9]{4}-?[A-Z2-9]{4}$/.test(pairingCode)) throw new Error("请输入电脑上显示的 8 位配对码");
  return completeMobilePairing(input, { schema_version: 1, pairing_code: pairingCode }, "code");
}

async function completeMobilePairing(
  input: MobilePairingCompletionOptions,
  body: { readonly schema_version: 1; readonly pairing_code: string } | { readonly schema_version: 1; readonly pairing_token: string },
  credential: "code" | "claim",
  trayPreparation: TrayPreparation | null = null,
): Promise<"authorized"> {
  const rawOrigin = input.origin ?? globalThis.location?.origin ?? "";
  let protocol: "http:" | "https:";
  try {
    protocol = new URL(rawOrigin).protocol === "https:" ? "https:" : "http:";
  } catch {
    throw new Error("请从二维码打开电脑上的局域网页面");
  }
  const endpoint = normalizePrivateEndpoint(`${rawOrigin}/`, protocol);
  if (!endpoint) throw new Error("请从二维码打开电脑上的局域网页面");
  if (trayPreparation) {
    if (input.edition !== "Enhanced" || !input.verifyLease) throw new Error("Bridge 手机授权参数与版本不匹配");
    if (!("pairing_token" in body)) throw new Error("Bridge 托盘二维码不支持手动配对码");
    const now = input.now ?? Date.now();
    const verified = await input.verifyLease(
      trayPreparation.mobileLease,
      trayPreparation.bridgePairingId,
      { now },
    );
    if (Math.abs(verified.expiresAt - trayPreparation.mobileLeaseExpiresAt) >= 1_000) {
      throw new Error("手机 Enhanced Lease 到期时间无效");
    }
    const prepareResponse = await (input.fetcher ?? fetch)(new URL("api/v1/mobile/pairing/prepare", endpoint), {
      method: "POST",
      mode: "same-origin",
      cache: "no-store",
      credentials: "omit",
      referrerPolicy: "no-referrer",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        schema_version: 1,
        bridge_pairing_id: trayPreparation.bridgePairingId,
        pairing_token: body.pairing_token,
        mobile_lease: trayPreparation.mobileLease,
        mobile_lease_expires_at: new Date(trayPreparation.mobileLeaseExpiresAt).toISOString(),
        pairing_expires_at: new Date(trayPreparation.pairingExpiresAt).toISOString(),
      }),
    });
    if (!prepareResponse.ok) throw new Error(`Bridge 手机配对准备 HTTP ${prepareResponse.status}`);
  }
  const response = await (input.fetcher ?? fetch)(new URL("api/v1/mobile/pairing/complete", endpoint), {
    method: "POST",
    mode: "same-origin",
    cache: "no-store",
    credentials: "omit",
    referrerPolicy: "no-referrer",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const rejection = response.ok ? "" : await response.text().catch(() => "");
  if (response.status === 429) throw new Error("配对尝试过多，请稍后再试");
  if (response.status === 410 && credential === "claim") throw new Error("二维码已使用，请回到电脑重新生成并扫描");
  if (response.status === 410) throw new Error("配对码已使用，请在电脑上重新生成");
  if (response.status === 403 && rejection.includes("invalid pairing code")) throw new Error("配对码不正确");
  if (response.status === 403 && credential === "claim") throw new Error("二维码配对凭据无效或已过期，请回到电脑重新生成并扫描");
  if (response.status === 403) throw new Error("局域网页面校验失败，请回到电脑重新生成并扫描二维码");
  if (!response.ok) throw new Error(`Bridge 手机配对 HTTP ${response.status}`);
  const value = await response.json() as {
    schema_version?: unknown;
    edition?: unknown;
    bridge_pairing_id?: unknown;
    pairing_token?: unknown;
    mobile_lease?: unknown;
    mobile_lease_expires_at?: unknown;
    expires_at?: unknown;
  };
  const bridgePairingId = text(value.bridge_pairing_id);
  const pairingToken = text(value.pairing_token);
  const mobileLease = text(value.mobile_lease);
  const mobileLeaseExpiresAt = Date.parse(text(value.mobile_lease_expires_at));
  const bridgeExpiresAt = Date.parse(text(value.expires_at));
  if (
    value.schema_version !== 1 ||
    value.edition !== input.edition ||
    !/^[A-Za-z0-9_-]{16,96}$/.test(bridgePairingId) ||
    !/^[A-Za-z0-9_-]{43}$/.test(pairingToken) ||
    !Number.isFinite(bridgeExpiresAt)
  ) throw new Error("Bridge 手机配对响应无效");
  const now = input.now ?? Date.now();
  let expiresAt = bridgeExpiresAt;
  if (input.edition === "Enhanced") {
    if (!mobileLease || !Number.isFinite(mobileLeaseExpiresAt) || !input.verifyLease) {
      throw new Error("Bridge 手机 Enhanced Lease 响应无效");
    }
    const verified = await input.verifyLease(mobileLease, bridgePairingId, { now });
    if (Math.abs(verified.expiresAt - mobileLeaseExpiresAt) >= 1_000) throw new Error("手机 Enhanced Lease 到期时间无效");
    expiresAt = Math.min(bridgeExpiresAt, mobileLeaseExpiresAt);
  } else if (mobileLease || text(value.mobile_lease_expires_at)) {
    throw new Error("Bridge 普通版手机配对响应无效");
  }
  if (expiresAt <= now) throw new Error("手机配对已过期");
  const session: StoredMobilePairingSession = Object.freeze({
    schemaVersion: 3,
    edition: input.edition,
    bridgePairingId,
    pairingToken,
    endpoints: [endpoint],
    ...(mobileLease ? { mobileLease } : {}),
    expiresAt,
    reopenUntil: Math.min(expiresAt, now + MOBILE_REOPEN_WINDOW_MS),
  });
  (input.storage ?? localStorage).setItem(MOBILE_SESSION_KEY, JSON.stringify(session));
  configureMobileBridge({ endpoints: session.endpoints, pairingToken: session.pairingToken });
  return "authorized";
}

interface TrayPreparation {
  readonly bridgePairingId: string;
  readonly pairingExpiresAt: number;
  readonly mobileLease: string;
  readonly mobileLeaseExpiresAt: number;
}

function readTrayPreparation(parameters: URLSearchParams): TrayPreparation | null {
  if (parameters.get("mobile-tray-prepare") !== "1") return null;
  const bridgePairingId = parameters.get("bridge-pairing") ?? "";
  const mobileLease = parameters.get("mobile-lease") ?? "";
  const pairingExpiresAt = Date.parse(parameters.get("pairing-expires") ?? "");
  const mobileLeaseExpiresAt = Date.parse(parameters.get("mobile-lease-expires") ?? "");
  if (
    !/^[A-Za-z0-9_-]{16,96}$/.test(bridgePairingId)
    || !mobileLease || mobileLease.length > 8192
    || !Number.isFinite(pairingExpiresAt)
    || !Number.isFinite(mobileLeaseExpiresAt)
  ) throw new Error("Bridge 手机授权参数无效，请重新扫描二维码");
  return { bridgePairingId, pairingExpiresAt, mobileLease, mobileLeaseExpiresAt };
}

export function isPrivateLanOrigin(origin = globalThis.location?.origin ?? ""): boolean {
  return Boolean(normalizePrivateEndpoint(`${origin}/`, "https:") || normalizePrivateEndpoint(`${origin}/`, "http:"));
}

export function inspectMobileLanBrowser(userAgent = globalThis.navigator?.userAgent ?? ""): MobileLanBrowserKind {
  if (/MicroMessenger|QQ\/|MQQBrowser|AlipayClient|UCBrowser|DingTalk|miniProgram|; wv\)/i.test(userAgent)) {
    return "embedded-webview";
  }
  if (/iPhone|iPad|iPod/i.test(userAgent)) return "ios";
  return "supported";
}

export function mobileLanBrowserMessage(kind: MobileLanBrowserKind): string {
  if (kind === "ios") {
    return "请用系统相机打开二维码，进入电脑上的局域网页面。请只勾选与手机同一 Wi-Fi 的地址。";
  }
  if (kind === "embedded-webview") {
    return "请用系统相机或 Chrome / Safari 独立打开此二维码。微信、QQ 等内置浏览器无法打开电脑上的局域网页面。";
  }
  return "请使用最新版 Android Chrome 独立打开。";
}

export async function queryLocalNetworkPermission(): Promise<"granted" | "prompt" | "denied" | "unsupported"> {
  return queryBrowserLocalNetworkPermission("local");
}

export async function connectMobileBridge(fetcher: Fetcher = fetch): Promise<URL> {
  const base = await discoverBridgeEndpoint(fetcher);
  await provePairedOfficialRoutes(base, fetcher);
  return base;
}

export function readMobilePairingSession(
  storage: SessionStorage = localStorage,
  now = Date.now(),
  expectedEdition?: MobileEdition,
): StoredMobilePairingSession | null {
  try {
    const raw = storage.getItem(MOBILE_SESSION_KEY);
    if (!raw) return null;
    const rawValue = JSON.parse(raw) as Omit<Partial<StoredMobilePairingSession>, "schemaVersion"> & { readonly schemaVersion?: number };
    const value = rawValue.schemaVersion === 1 || rawValue.schemaVersion === 2
      ? {
          ...rawValue,
          schemaVersion: 3 as const,
          edition: rawValue.schemaVersion === 1 ? "Enhanced" as const : rawValue.edition,
          reopenUntil: Math.min(Number(rawValue.expiresAt) || 0, now + MOBILE_REOPEN_WINDOW_MS),
        }
      : rawValue;
    const endpoints = uniqueEndpoints([
      ...normalizeEndpoints(value.endpoints, "http:"),
      ...normalizeEndpoints(value.endpoints, "https:"),
    ]);
    if (
      value.schemaVersion !== 3 ||
      (value.edition !== "Standard" && value.edition !== "Enhanced") ||
      (expectedEdition !== undefined && value.edition !== expectedEdition) ||
      !/^[A-Za-z0-9_-]{16,96}$/.test(value.bridgePairingId ?? "") ||
      !/^[A-Za-z0-9_-]{43}$/.test(value.pairingToken ?? "") ||
      (value.edition === "Enhanced" && !value.mobileLease) ||
      !Number.isFinite(value.expiresAt) ||
      value.expiresAt! <= now ||
      !Number.isFinite(value.reopenUntil) ||
      value.reopenUntil! <= now ||
      value.reopenUntil! > value.expiresAt! ||
      endpoints.length === 0
    ) throw new Error("invalid mobile pairing session");
    const session = value as StoredMobilePairingSession;
    configureMobileBridge({ endpoints, pairingToken: session.pairingToken });
    return Object.freeze({ ...session, endpoints });
  } catch {
    storage.removeItem(MOBILE_SESSION_KEY);
    configureMobileBridge(null);
    return null;
  }
}

export async function restoreMobilePairingSession(
  storage: SessionStorage = localStorage,
  now = Date.now(),
  edition: MobileEdition = "Enhanced",
  verifyLease?: MobileLeaseVerifier,
): Promise<StoredMobilePairingSession | null> {
  const session = readMobilePairingSession(storage, now, edition);
  if (!session) return null;
  if (session.edition === "Standard") return session;
  try {
    if (!verifyLease || !session.mobileLease) throw new Error("mobile lease verifier unavailable");
    const verified = await verifyLease(
      session.mobileLease,
      session.bridgePairingId,
      { now },
    );
    if (verified.expiresAt + 1_000 < session.expiresAt) throw new Error("mobile lease expiry mismatch");
    return session;
  } catch {
    storage.removeItem(MOBILE_SESSION_KEY);
    configureMobileBridge(null);
    return null;
  }
}

export function refreshMobilePairingReopenWindow(
  storage: SessionStorage = localStorage,
  now = Date.now(),
  expectedEdition?: MobileEdition,
  activeSession?: StoredMobilePairingSession | null,
): StoredMobilePairingSession | null {
  const session = activeSession && activeSession.expiresAt > now
    && (expectedEdition === undefined || activeSession.edition === expectedEdition)
    ? activeSession
    : readMobilePairingSession(storage, now, expectedEdition);
  if (!session) return null;
  const refreshed = Object.freeze({
    ...session,
    reopenUntil: Math.min(session.expiresAt, now + MOBILE_REOPEN_WINDOW_MS),
  });
  storage.setItem(MOBILE_SESSION_KEY, JSON.stringify(refreshed));
  return refreshed;
}

function normalizeNetworks(value: unknown): readonly MobileNetworkCandidate[] {
  if (!Array.isArray(value)) return [];
  return Object.freeze(value.slice(0, 8).flatMap((item) => {
    if (!item || typeof item !== "object" || Array.isArray(item)) return [];
    const record = item as Record<string, unknown>;
    const endpoint = normalizePrivateEndpoint(text(record.endpoint), "http:");
    const tlsEndpoint = normalizePrivateEndpoint(text(record.tls_endpoint), "https:") ?? undefined;
    return endpoint ? [{
      interface: text(record.interface) || text(record.address),
      address: text(record.address),
      endpoint,
      ...(tlsEndpoint ? { tlsEndpoint } : {}),
    }] : [];
  }));
}

function normalizeEndpoints(value: unknown, protocol: "http:" | "https:" = "http:"): readonly string[] {
  if (!Array.isArray(value)) return [];
  const endpoints = value.slice(0, 8).map((item) => normalizePrivateEndpoint(text(item), protocol)).filter((item): item is string => Boolean(item));
  return uniqueEndpoints(endpoints);
}

function uniqueEndpoints(value: readonly string[]): readonly string[] {
  return Object.freeze([...new Set(value)]);
}

function normalizePrivateEndpoint(raw: string, protocol: "http:" | "https:" = "http:"): string | null {
  try {
    const url = new URL(raw);
    const octets = url.hostname.split(".").map(Number);
    const privateIPv4 = octets.length === 4 && octets.every((value) => Number.isInteger(value) && value >= 0 && value <= 255) && (
      octets[0] === 10 ||
      octets[0] === 172 && octets[1]! >= 16 && octets[1]! <= 31 ||
      octets[0] === 192 && octets[1] === 168
    );
    if (
      url.protocol !== protocol || !privateIPv4 || !url.port ||
      url.username || url.password || url.search || url.hash || url.pathname !== "/"
    ) return null;
    return url.toString();
  } catch {
    return null;
  }
}

function text(value: unknown): string { return typeof value === "string" ? value : ""; }
