/** A launcher entry/back navigation cannot establish continuity with a closed flight. */
export function isPageReload(): boolean {
  return (performance.getEntriesByType("navigation")[0] as PerformanceNavigationTiming | undefined)?.type === "reload";
}

// A hidden page may still drive PiP. Only an actual freeze stops acquisition.
export function bindPageSession(options: {
  document: EventTarget & { readonly visibilityState: string };
  window: EventTarget;
  save: () => void;
  suspend: () => void;
  reconnect: () => void;
  reconcileTimer?: (historyRestore: boolean) => void;
}): () => void {
  const hidden = (): void => {
    if (options.document.visibilityState === "hidden") options.save();
    else { options.reconcileTimer?.(false); options.reconnect(); }
  };
  const freeze = (): void => { options.save(); options.suspend(); };
  const resume = (): void => { options.reconcileTimer?.(false); options.reconnect(); };
  const show = (event: Event): void => {
    if ((event as PageTransitionEvent).persisted) { options.reconcileTimer?.(true); options.reconnect(); }
  };
  options.document.addEventListener("visibilitychange", hidden);
  options.document.addEventListener("freeze", freeze);
  options.document.addEventListener("resume", resume);
  options.window.addEventListener("pagehide", freeze);
  options.window.addEventListener("pageshow", show);
  return () => {
    options.document.removeEventListener("visibilitychange", hidden);
    options.document.removeEventListener("freeze", freeze);
    options.document.removeEventListener("resume", resume);
    options.window.removeEventListener("pagehide", freeze);
    options.window.removeEventListener("pageshow", show);
  };
}
