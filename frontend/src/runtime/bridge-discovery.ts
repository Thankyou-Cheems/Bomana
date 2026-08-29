export const BRIDGE_PORT_START = 8878;
export const BRIDGE_PORT_END = 8897;

type Fetcher = typeof fetch;

export type MobileBridgeFailureReason =
  | "mixed-content"
  | "local-network-permission"
  | "cors"
  | "unauthorized"
  | "unreachable"
  | "official-route";

export class MobileBridgeError extends Error {
  readonly reason: MobileBridgeFailureReason;
  readonly fatal: boolean;

  constructor(reason: MobileBridgeFailureReason, message: string, fatal: boolean) {
    super(message);
    this.name = "MobileBridgeError";
    this.reason = reason;
    this.fatal = fatal;
  }
}

const OFFICIAL_PAIRING_ROUTES = Object.freeze([
  "api/v1/8111/state",
  "api/v1/8111/indicators",
  "api/v1/8111/map-objects",
]);

let selectedBridge: URL | null = null;
let discovery: Promise<URL> | null = null;
let mobileBridge: { readonly endpoints: readonly URL[]; readonly pairingToken: string } | null = null;

export function configureMobileBridge(input: {
  readonly endpoints: readonly string[];
  readonly pairingToken: string;
} | null): void {
  mobileBridge = input
    ? Object.freeze({
        endpoints: Object.freeze(input.endpoints.map((endpoint) => validatePrivateBridgeBase(new URL(endpoint)))),
        pairingToken: input.pairingToken,
      })
    : null;
  selectedBridge = null;
  discovery = null;
}

export async function discoverBridgeEndpoint(fetcher: Fetcher = fetch, configuredURL = ""): Promise<URL> {
  if (mobileBridge) {
    if (selectedBridge && mobileBridge.endpoints.some((candidate) => candidate.origin === selectedBridge?.origin)) {
      return new URL(selectedBridge);
    }
    discovery ??= scanMobileBridgeEndpoints(fetcher).finally(() => { discovery = null; });
    selectedBridge = await discovery;
    return new URL(selectedBridge);
  }
  if (configuredURL) {
    const candidate = validateLoopbackBase(new URL(configuredURL));
    if (selectedBridge?.origin === candidate.origin) return new URL(selectedBridge);
    discovery ??= probeConfigured(candidate, fetcher).finally(() => { discovery = null; });
    selectedBridge = await discovery;
    return new URL(selectedBridge);
  }
  if (selectedBridge) return new URL(selectedBridge);
  discovery ??= scanBridgePorts(fetcher).finally(() => { discovery = null; });
  selectedBridge = await discovery;
  return new URL(selectedBridge);
}

export function fetchBridgeResource(
  fetcher: Fetcher,
  input: URL | RequestInfo,
  init: RequestInit = {},
): Promise<Response> {
  if (!mobileBridge) {
    const loopbackInit: RequestInit & { readonly targetAddressSpace: "loopback" } = {
      ...init,
      targetAddressSpace: "loopback",
    };
    return fetcher(input, loopbackInit);
  }
  const headers = new Headers(init.headers);
  headers.set("X-Bomana-Mobile-Pairing", mobileBridge.pairingToken);
  const localInit: RequestInit & { readonly targetAddressSpace: "local" } = {
    ...init,
    headers,
    targetAddressSpace: "local",
  };
  return fetcher(input, localInit);
}

export function clearBridgeDiscoveryForTest(): void {
  selectedBridge = null;
  discovery = null;
  mobileBridge = null;
}

export async function bridgeEndpointReachable(baseURL: URL, fetcher: Fetcher = fetch): Promise<boolean> {
  return probe(baseURL, fetcher);
}

export function forgetBridgeEndpoint(baseURL?: URL): void {
  if (!baseURL || selectedBridge?.origin === baseURL.origin) selectedBridge = null;
  discovery = null;
}

export async function provePairedOfficialRoutes(baseURL: URL, fetcher: Fetcher = fetch): Promise<void> {
  for (const path of OFFICIAL_PAIRING_ROUTES) {
    const controller = new AbortController();
    const timeout = globalThis.setTimeout(() => controller.abort(), 1_200);
    try {
      const response = await fetchBridgeResource(fetcher, new URL(path, baseURL), {
        method: "GET",
        mode: "cors",
        cache: "no-store",
        credentials: "omit",
        referrerPolicy: "no-referrer",
        signal: controller.signal,
        headers: { Accept: "application/json" },
      });
      if (response.status === 401 || response.status === 403) {
        throw new MobileBridgeError("unauthorized", "局域网配对口令已失效。请回到电脑重新生成二维码。", true);
      }
      if (response.status === 502 || response.status === 503 || response.status === 504) continue;
      if (!response.ok) {
        throw new MobileBridgeError("official-route", "已找到局域网 Bridge，但官方 8111 数据通道被拒绝。请用 Android Chrome 重试。", true);
      }
    } catch (error) {
      if (error instanceof MobileBridgeError) throw error;
      throw classifyBrowserNetworkError(error, "official-route");
    } finally {
      globalThis.clearTimeout(timeout);
    }
  }
}

async function scanMobileBridgeEndpoints(fetcher: Fetcher): Promise<URL> {
  if (!mobileBridge) throw new Error("手机 Bridge 配对不可用");
  let unauthorized = 0;
  let lastRetryable: MobileBridgeError | null = null;
  for (const candidate of mobileBridge.endpoints) {
    try {
      const result = await probeResult(candidate, fetcher);
      if (result === "match") return candidate;
      if (result === "unauthorized") unauthorized += 1;
    } catch (error) {
      if (error instanceof MobileBridgeError && error.fatal) throw error;
      lastRetryable = error instanceof MobileBridgeError ? error : classifyBrowserNetworkError(error);
    }
  }
  if (unauthorized > 0 && unauthorized === mobileBridge.endpoints.length) {
    throw new MobileBridgeError("unauthorized", "局域网配对口令已失效。请回到电脑重新生成二维码。", true);
  }
  throw lastRetryable ?? new MobileBridgeError(
    "unreachable",
    "找不到二维码中的局域网 Bridge。请确认同一 Wi-Fi，关闭 VPN，并检查电脑防火墙是否拦截了临时端口。",
    false,
  );
}

async function scanBridgePorts(fetcher: Fetcher): Promise<URL> {
  const candidates = Array.from({ length: BRIDGE_PORT_END - BRIDGE_PORT_START + 1 }, (_, index) => new URL(`http://127.0.0.1:${BRIDGE_PORT_START + index}/`));
  const results = await Promise.all(candidates.map(async (candidate) => await probe(candidate, fetcher) ? candidate : null));
  const selected = results.find((candidate): candidate is URL => candidate !== null);
  if (!selected) throw new Error("未发现 Bomana Bridge");
  return selected;
}

async function probeConfigured(candidate: URL, fetcher: Fetcher): Promise<URL> {
  if (!await probe(candidate, fetcher)) throw new Error("配置的 Bomana Bridge 不可用");
  selectedBridge = candidate;
  return new URL(candidate);
}

async function probe(candidate: URL, fetcher: Fetcher): Promise<boolean> {
  try {
    return await probeResult(candidate, fetcher) === "match";
  } catch (error) {
    if (error instanceof MobileBridgeError && error.fatal && mobileBridge) throw error;
    return false;
  }
}

async function probeResult(candidate: URL, fetcher: Fetcher): Promise<"match" | "mismatch" | "unauthorized"> {
  const controller = new AbortController();
  const timeout = globalThis.setTimeout(() => controller.abort(), 1_200);
  try {
    const response = await fetchBridgeResource(fetcher, new URL("api/v1/capabilities", candidate), {
      method: "GET", mode: "cors", cache: "no-store", credentials: "omit", referrerPolicy: "no-referrer", signal: controller.signal,
    });
    if (response.status === 401 || response.status === 403) return "unauthorized";
    if (!response.ok) return "mismatch";
    const value = await response.json() as Record<string, unknown>;
    return value.schema_version === 1 && value.bridge_protocol === 1 && value.cache_protocol === 4
      && value.input === "official-8111-only" && value.write_commands === false
      ? "match"
      : "mismatch";
  } catch (error) {
    throw classifyBrowserNetworkError(error);
  } finally {
    globalThis.clearTimeout(timeout);
  }
}

function classifyBrowserNetworkError(error: unknown, fallback: MobileBridgeFailureReason = "unreachable"): MobileBridgeError {
  if (error instanceof MobileBridgeError) return error;
  const message = error instanceof Error ? error.message : String(error);
  if (/mixed content/i.test(message)) {
    return new MobileBridgeError("mixed-content", "当前浏览器阻止 HTTPS 网页访问局域网 HTTP。请用 Android Chrome 独立打开二维码。", true);
  }
  if (/address space|local network|private network|permission was denied/i.test(message)) {
    return new MobileBridgeError("local-network-permission", "浏览器未允许访问本地网络。请点击允许，或在站点设置中打开本地网络权限。", true);
  }
  if (/cors|access-control/i.test(message)) {
    return new MobileBridgeError("cors", "当前网页来源未被 Bridge 允许。请使用官方站点，并用 Chrome 独立打开。", true);
  }
  if (fallback === "official-route") {
    return new MobileBridgeError("official-route", "已找到局域网 Bridge，但官方 8111 数据通道被拦截。请关闭 VPN，并用 Android Chrome 重试。", true);
  }
  return new MobileBridgeError(
    "unreachable",
    "找不到二维码中的局域网 Bridge。请确认同一 Wi-Fi，关闭 VPN，并检查电脑防火墙是否拦截了临时端口。",
    false,
  );
}

function validatePrivateBridgeBase(url: URL): URL {
  const octets = url.hostname.split(".").map(Number);
  const privateIPv4 = octets.length === 4 && octets.every((value) => Number.isInteger(value) && value >= 0 && value <= 255) && (
    octets[0] === 10 ||
    octets[0] === 172 && octets[1]! >= 16 && octets[1]! <= 31 ||
    octets[0] === 192 && octets[1] === 168
  );
  if (
    (url.protocol !== "http:" && url.protocol !== "https:") ||
    !privateIPv4 ||
    !url.port ||
    url.username ||
    url.password ||
    url.search ||
    url.hash ||
    url.pathname !== "/"
  ) throw new TypeError("手机 Bridge 地址必须是无凭据的私有 IPv4 HTTP(S) 地址");
  return url;
}

function validateLoopbackBase(url: URL): URL {
  if (url.protocol !== "http:" || !["127.0.0.1", "localhost", "[::1]"].includes(url.hostname)
    || url.username || url.password || url.search || url.hash) throw new TypeError("Bridge 地址必须是本机 HTTP 地址");
  url.pathname = "/";
  return url;
}
