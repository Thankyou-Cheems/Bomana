import { readBrowserAuthorization } from "./enhanced-access";

let pendingMutation: Promise<void> = Promise.resolve();
let generation = 0;
let lastInstalledLease: string | null = null;
let latestRequestedLease: string | null = null;

function serialize(operation: () => Promise<void>, requireLock = false): Promise<void> {
  const result = pendingMutation.then(async () => {
    if (typeof navigator !== "undefined" && navigator.locks) return navigator.locks.request("bomana:enhanced-resource-access", operation);
    if (requireLock) throw new Error("请更新浏览器后重新授权 Enhanced。");
    return operation();
  });
  pendingMutation = result.catch(() => {});
  return result;
}

function resourceEndpoint(): URL | null {
  if (typeof location === "undefined" || location.protocol !== "https:" || !(location.pathname.startsWith("/app/") || location.pathname.startsWith("/launcher/"))) return null;
  return new URL("/app/Enhanced/resource-access", location.origin);
}

export function clearEnhancedResourceAccess(expectedLease: string | null = lastInstalledLease, isCurrent: () => boolean = () => true): void {
  if (!isCurrent()) return;
  const previousSubject = leaseSubjectHint(expectedLease);
  const installedSubject = leaseSubjectHint(latestRequestedLease);
  // Cleanup for an older account must not invalidate a different account's bind.
  if (!previousSubject || !installedSubject || previousSubject === installedSubject) generation += 1;
  const endpoint = resourceEndpoint();
  if (!endpoint || !expectedLease) return;
  void serialize(async () => {
    if (!isCurrent()) return;
    await fetch(endpoint, { method: "DELETE", cache: "no-store", credentials: "same-origin", redirect: "error", referrerPolicy: "no-referrer", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ lease: expectedLease }) });
  }).catch(() => {});
}

export async function installEnhancedResourceAccess(lease: string, offline: boolean, isCurrent: () => boolean = () => true): Promise<void> {
  const endpoint = resourceEndpoint();
  if (!endpoint) return;
  if (!isCurrent()) throw new Error("Enhanced 账号授权已变化，请刷新页面。");
  latestRequestedLease = lease;
  const installation = generation;
  return serialize(async () => {
    if (installation !== generation || !isCurrent()) throw new Error("Enhanced 账号授权已变化，请刷新页面。");
    lastInstalledLease = lease;
    let response: Response;
    try {
      response = await fetch(endpoint, { method: "POST", cache: "no-store", credentials: "same-origin", redirect: "error", referrerPolicy: "no-referrer", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ lease }) });
    } catch (error) {
      // Allows an attempt using the existing cookie/private HTTP cache, not a promise of full offline boot.
      if (offline && installation === generation && isCurrent()) return;
      throw error;
    }
    if (!response.ok) throw new Error(`Enhanced 资源授权失败（HTTP ${response.status}），请联网刷新授权。`);
    if (installation !== generation || !isCurrent()) throw new Error("Enhanced 账号授权已变化，请刷新页面。");
  }, true);
}

if (typeof window !== "undefined") window.addEventListener("storage", (event) => {
  if (event.key !== "bomana:cheemspay:authorization:v3") return;
  try {
    const previous = JSON.parse(event.oldValue ?? "null") as { accessToken?: string; enhancedLease?: string | null } | null;
    const current = JSON.parse(event.newValue ?? "null") as { accessToken?: string; enhancedLease?: string | null } | null;
    if (!current || !current.enhancedLease || previous?.accessToken !== current.accessToken) {
      const previousLease = previous?.enhancedLease ?? null;
      clearEnhancedResourceAccess(previousLease, () => canClearEnhancedResourceAccess(previousLease));
    }
  } catch { clearEnhancedResourceAccess(lastInstalledLease, () => canClearEnhancedResourceAccess(lastInstalledLease)); }
});
// Subject hints only coordinate cleanup; the server verifies both signed selectors.
function leaseSubjectHint(lease: string | null): string | null {
  try {
    const value = JSON.parse(atob((lease ?? "").split(".")[1]!.replace(/-/g, "+").replace(/_/g, "/"))) as { sub?: unknown };
    return typeof value.sub === "string" && value.sub ? value.sub : null;
  } catch { return null; }
}

export function canClearEnhancedResourceAccess(previousLease: string | null, storage?: Pick<Storage, "getItem" | "setItem" | "removeItem">): boolean {
  const currentLease = readBrowserAuthorization(storage)?.enhancedLease;
  if (!currentLease) return true;
  const previousSubject = leaseSubjectHint(previousLease);
  const currentSubject = leaseSubjectHint(currentLease);
  return previousSubject !== null && currentSubject !== null && previousSubject !== currentSubject;
}
