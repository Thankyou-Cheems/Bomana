import { BROWSER_AUTHORIZATION_KEY, readBrowserAuthorization, verifyEnhancedLease } from "./enhanced-access";

/** Re-enter bootstrap on local session loss; cached bytes never establish eligibility. */
export function watchDesktopEnhancedSession(options: {
  accessToken: string;
  expiresAt: number;
  readAuthorization?: typeof readBrowserAuthorization;
  verifyLease?: typeof verifyEnhancedLease;
  restart?: () => void;
}): (() => void) | null {
  const read = options.readAuthorization ?? readBrowserAuthorization;
  const verify = options.verifyLease ?? verifyEnhancedLease;
  const restart = options.restart ?? (() => location.replace(location.href));
  const page = typeof document === "undefined" ? null : document;
  let stopped = false; let revision = 0; let timer: ReturnType<typeof setTimeout>;
  const dispose = () => {
    stopped = true; revision += 1; clearTimeout(timer);
    window.removeEventListener("storage", onStorage); window.removeEventListener("pageshow", check);
    page?.removeEventListener("visibilitychange", onVisibility);
  };
  const invalidate = () => { if (stopped) return; dispose(); restart(); };
  const current = () => { const value = read(); return value?.accessToken === options.accessToken && value.enhancedLease ? value : null; };
  const schedule = (expiresAt: number) => { clearTimeout(timer); timer = setTimeout(check, Math.max(0, expiresAt - Date.now())); };
  async function check() {
    const attempt = ++revision; const authorization = current();
    if (!authorization) { invalidate(); return; }
    try {
      if (Date.now() + 5 * 60_000 < authorization.validatedAt) throw new Error("clock rollback");
      const lease = await verify(authorization.enhancedLease!);
      if (stopped || attempt !== revision) return;
      const latest = current();
      if (!latest) { invalidate(); return; }
      if (latest.enhancedLease !== authorization.enhancedLease) { void check(); return; }
      if (lease.expiresAt <= Date.now()) { invalidate(); return; }
      schedule(lease.expiresAt);
    } catch { if (!stopped && attempt === revision) invalidate(); }
  }
  function onStorage(event: Event) { if ((event as StorageEvent).key === BROWSER_AUTHORIZATION_KEY) void check(); }
  function onVisibility() { if (page?.visibilityState === "visible") void check(); }
  if (!current() || !Number.isFinite(options.expiresAt) || options.expiresAt <= Date.now()) { invalidate(); return null; }
  window.addEventListener("storage", onStorage); window.addEventListener("pageshow", check);
  page?.addEventListener("visibilitychange", onVisibility);
  schedule(options.expiresAt);
  return dispose;
}
