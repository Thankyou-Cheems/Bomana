/** Keep the shared Web frame below the header as its content changes size. */
export function initializeWebShellLayout(header: HTMLElement, flightPanel: HTMLElement): void {
  const update = () => {
    const bottom = Math.ceil(header.getBoundingClientRect().bottom + 6);
    document.documentElement.style.setProperty("--portrait-flight-top", `${bottom}px`);
    document.documentElement.style.setProperty("--portrait-map-top", `${flightPanel.getBoundingClientRect().bottom}px`);
    document.documentElement.style.setProperty("--hud-top-bottom", `${bottom}px`);
  };
  update();
  window.addEventListener("resize", update);
  const observer = new ResizeObserver(update);
  observer.observe(header);
  observer.observe(flightPanel);
  window.addEventListener("pagehide", event => {
    if (event.persisted) return;
    observer.disconnect();
    window.removeEventListener("resize", update);
  });
}
