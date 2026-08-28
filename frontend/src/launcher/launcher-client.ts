import { discoverBridgeEndpoint, fetchBridgeResource } from "../runtime/bridge-discovery";
import {
  clearBrowserAuthorization,
  readBrowserAuthorization,
  saveBrowserAuthorization,
  verifyEnhancedLease,
} from "../runtime/enhanced-access";

export type Channel = "Lite" | "Standard" | "Enhanced";

export interface BridgeCapabilities {
  readonly schema_version: 1;
  readonly bridge_protocol: 1;
  readonly cache_protocol: 3;
  readonly bridge_version: string;
  readonly app_web_version?: string;
  readonly build_provenance: "github-actions-sigstore" | "local-unattested";
  readonly authenticode: false;
  readonly input: "official-8111-only";
  readonly write_commands: false;
  readonly routes: readonly string[];
}

export interface BrowserAccess {
  readonly state: "authorized" | "pending" | "signed_out" | "unavailable";
  readonly accountLabel: string;
  readonly enhanced: boolean;
  readonly userCode?: string;
  readonly verificationURL?: string;
  readonly offline?: boolean;
  readonly localValidUntil?: number;
}

export type BridgeProbe =
  | { readonly state: "connected"; readonly capabilities: BridgeCapabilities; readonly endpoint: string }
  | { readonly state: "blocked"; readonly message: string }
  | { readonly state: "disconnected"; readonly message: string };

type Fetcher = typeof fetch;
type BrowserStorage = Pick<Storage, "getItem" | "setItem" | "removeItem">;

const PENDING_KEY = "bomana:cheemspay:pending:v3";

export class BridgeClient {
  readonly #configuredURL: string;
  readonly #fetcher: Fetcher;
  constructor(baseURL = "", fetcher: Fetcher = fetch) {
    this.#configuredURL = baseURL;
    this.#fetcher = (input, init) => fetcher(input, init);
  }
  async capabilities(): Promise<BridgeCapabilities> {
    const baseURL = await discoverBridgeEndpoint(this.#fetcher, this.#configuredURL);
    const controller = new AbortController();
    const timeout = globalThis.setTimeout(() => controller.abort(), 3_500);
    let response: Response;
    try {
      response = await fetchBridgeResource(this.#fetcher, new URL("api/v1/capabilities", baseURL), {
        method: "GET", cache: "no-store", credentials: "omit", referrerPolicy: "no-referrer", signal: controller.signal,
      });
    } finally {
      globalThis.clearTimeout(timeout);
    }
    if (!response.ok) throw new Error(`Bridge HTTP ${response.status}`);
    const value = await response.json() as Partial<BridgeCapabilities>;
    if (value.schema_version !== 1 || value.bridge_protocol !== 1 || value.cache_protocol !== 3 || value.input !== "official-8111-only" || value.write_commands !== false
      || typeof value.bridge_version !== "string" || !value.bridge_version
      || value.authenticode !== false || !["github-actions-sigstore", "local-unattested"].includes(String(value.build_provenance))) {
      throw new Error("Bridge 协议不兼容");
    }
    return Object.freeze({ ...value }) as BridgeCapabilities;
  }

  async probe(): Promise<BridgeProbe> {
    try {
      const capabilities = await this.capabilities();
      const endpoint = await discoverBridgeEndpoint(this.#fetcher, this.#configuredURL);
      return { state: "connected", capabilities, endpoint: endpoint.origin };
    } catch {
      if (!this.#configuredURL) return { state: "disconnected", message: "未发现正在运行的 Bomana Bridge" };
      const controller = new AbortController();
      const timeout = globalThis.setTimeout(() => controller.abort(), 1_500);
      try {
        await this.#fetcher(new URL("healthz", this.#configuredURL), {
          method: "GET", mode: "no-cors", cache: "no-store", credentials: "omit", referrerPolicy: "no-referrer", signal: controller.signal,
        });
        return { state: "blocked", message: "配置端口上的服务不是当前 Bridge，或不允许 Bomana 网页访问" };
      } catch {
        return { state: "disconnected", message: "未发现正在运行的 Bomana Bridge" };
      } finally {
        globalThis.clearTimeout(timeout);
      }
    }
  }
}

export class BrowserAccessClient {
  readonly #baseURL: URL;
  readonly #fetcher: Fetcher;
  readonly #storage: BrowserStorage;
  readonly #verifyLease: typeof verifyEnhancedLease;
  constructor(
    baseURL: URL,
    fetcher: Fetcher = fetch,
    storage: BrowserStorage = localStorage,
    verifyLease: typeof verifyEnhancedLease = verifyEnhancedLease,
  ) {
    this.#baseURL = baseURL;
    this.#fetcher = (input, init) => fetcher(input, init);
    this.#storage = storage;
    this.#verifyLease = verifyLease;
  }
  async snapshot(): Promise<BrowserAccess> {
    const pending = this.#pending();
    if (pending) return { state: "pending", accountLabel: "等待 CheemsPay 确认", enhanced: false, userCode: pending.userCode, verificationURL: pending.verificationURL };
    const authorization = readBrowserAuthorization(this.#storage);
    if (!authorization) return { state: "signed_out", accountLabel: "未登录 CheemsPay", enhanced: false };
    let authoritativeFailure = false;
    try {
      const response = await this.#fetcher(new URL("/api/bomana/access", this.#baseURL), {
        method: "GET", cache: "no-store", credentials: "omit", referrerPolicy: "no-referrer",
        headers: { Authorization: `Bearer ${authorization.accessToken}` },
      });
      if (response.status === 401 || response.status === 403) {
        this.clearAuthorization();
        return { state: "signed_out", accountLabel: "CheemsPay 授权已过期", enhanced: false };
      }
      if (!response.ok) throw new Error(`CheemsPay HTTP ${response.status}`);
      const payload = await response.json() as { schemaVersion?: unknown; accountLabel?: unknown; enhanced?: unknown; enhancedLease?: unknown; enhancedLeaseExpiresAt?: unknown };
      if (payload.schemaVersion !== 2 || typeof payload.enhanced !== "boolean") {
        authoritativeFailure = true;
        throw new Error("CheemsPay access payload is invalid");
      }
      const now = Date.now();
      const accountLabel = typeof payload.accountLabel === "string" ? payload.accountLabel : "CheemsPay 用户";
      if (!payload.enhanced) {
        saveBrowserAuthorization({ ...authorization, accountLabel, enhancedLease: null, enhancedLeaseExpiresAt: 0, validatedAt: now }, this.#storage);
        return { state: "authorized", accountLabel, enhanced: false, offline: false };
      }
      if (typeof payload.enhancedLease !== "string" || typeof payload.enhancedLeaseExpiresAt !== "string") {
        authoritativeFailure = true;
        throw new Error("CheemsPay Enhanced Lease is missing");
      }
      let lease;
      try {
        lease = await this.#verifyLease(payload.enhancedLease, { now });
      } catch (error) {
        authoritativeFailure = true;
        throw error;
      }
      const declaredExpiry = Date.parse(payload.enhancedLeaseExpiresAt);
      if (!Number.isFinite(declaredExpiry) || Math.abs(declaredExpiry - lease.expiresAt) >= 1_000) {
        authoritativeFailure = true;
        throw new Error("CheemsPay Enhanced Lease expiry is invalid");
      }
      saveBrowserAuthorization({
        ...authorization, accountLabel, enhancedLease: payload.enhancedLease,
        enhancedLeaseExpiresAt: lease.expiresAt, validatedAt: now,
      }, this.#storage);
      return { state: "authorized", accountLabel, enhanced: true, offline: false, localValidUntil: lease.expiresAt };
    } catch {
      if (!authoritativeFailure && authorization.enhancedLease) {
        try {
          const offlineNow = Date.now();
          if (offlineNow + 5 * 60_000 < authorization.validatedAt) throw new Error("local clock rollback");
          const lease = await this.#verifyLease(authorization.enhancedLease, { now: offlineNow });
          return { state: "authorized", accountLabel: authorization.accountLabel || "CheemsPay 用户", enhanced: true, offline: true, localValidUntil: lease.expiresAt };
        } catch {
          return { state: "signed_out", accountLabel: "14 天本地授权已到期，请联网刷新", enhanced: false };
        }
      }
      return { state: "unavailable", accountLabel: "账户服务暂不可用", enhanced: false };
    }
  }

  async begin(): Promise<BrowserAccess> {
    const response = await this.#fetcher(new URL("/api/auth/device/code", this.#baseURL), {
      method: "POST", cache: "no-store", credentials: "omit", referrerPolicy: "no-referrer",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ client_id: "bomana-desktop", scope: "openid profile offline_access" }),
    });
    if (!response.ok) throw new Error(`CheemsPay device authorization HTTP ${response.status}`);
    const payload = await response.json() as Record<string, unknown>;
    const deviceCode = text(payload.device_code);
    const userCode = text(payload.user_code);
    const verificationURL = text(payload.verification_uri_complete) || text(payload.verification_uri);
    const expiresIn = Number(payload.expires_in);
    if (!deviceCode || !userCode || !verificationURL || !Number.isInteger(expiresIn) || expiresIn <= 0) throw new Error("CheemsPay device authorization is invalid");
    this.#storage.setItem(PENDING_KEY, JSON.stringify({ deviceCode, userCode, verificationURL, expiresAt: Date.now() + expiresIn * 1_000 }));
    return this.snapshot();
  }

  async poll(): Promise<BrowserAccess> {
    const pending = this.#pending();
    if (!pending) return this.snapshot();
    const response = await this.#fetcher(new URL("/api/auth/device/token", this.#baseURL), {
      method: "POST", cache: "no-store", credentials: "omit", referrerPolicy: "no-referrer",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ grant_type: "urn:ietf:params:oauth:grant-type:device_code", device_code: pending.deviceCode, client_id: "bomana-desktop" }),
    });
    const payload = await response.json().catch(() => ({})) as Record<string, unknown>;
    if (!response.ok) {
      const code = text(payload.error) || text((payload.error as Record<string, unknown> | undefined)?.code);
      if (["authorization_pending", "slow_down"].includes(code)) return this.snapshot();
      this.#storage.removeItem(PENDING_KEY);
      throw new Error(`CheemsPay authorization failed: ${code || response.status}`);
    }
    const token = text(payload.access_token);
    const expiresIn = Number(payload.expires_in);
    if (!token || !Number.isInteger(expiresIn) || expiresIn <= 0) throw new Error("CheemsPay access token is invalid");
    saveBrowserAuthorization({
      schemaVersion: 3, accessToken: token, accountLabel: "", enhancedLease: null,
      enhancedLeaseExpiresAt: 0, validatedAt: 0,
    }, this.#storage);
    this.#storage.removeItem(PENDING_KEY);
    return this.snapshot();
  }

  hasPending(): boolean { return this.#pending() !== null; }

  clearAuthorization(): void {
    clearBrowserAuthorization(this.#storage);
    this.#storage.removeItem(PENDING_KEY);
  }

  #pending(): { deviceCode: string; userCode: string; verificationURL: string; expiresAt: number } | null {
    try {
      const raw = this.#storage.getItem(PENDING_KEY);
      if (!raw) return null;
      const value = JSON.parse(raw) as Record<string, unknown>;
      const pending = { deviceCode: text(value.deviceCode), userCode: text(value.userCode), verificationURL: text(value.verificationURL), expiresAt: Number(value.expiresAt) };
      if (!pending.deviceCode || !pending.userCode || !pending.verificationURL || !Number.isFinite(pending.expiresAt) || pending.expiresAt <= Date.now()) {
        this.#storage.removeItem(PENDING_KEY);
        return null;
      }
      return pending;
    } catch {
      this.#storage.removeItem(PENDING_KEY);
      return null;
    }
  }
}

function text(value: unknown): string { return typeof value === "string" ? value : ""; }
