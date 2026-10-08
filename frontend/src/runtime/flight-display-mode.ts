/** A presentation preference, not a detected game mode or an entitlement. */
export type FlightDisplayMode = "simulator" | "air-realistic";
const key = "bomana:flight-display-mode:v1";
const listeners = new Set<(mode: FlightDisplayMode) => void>();
let current: FlightDisplayMode = "simulator";
try { if (localStorage.getItem(key) === "air-realistic") current = "air-realistic"; } catch { /* Session-only when storage is disabled. */ }
export function flightDisplayMode(): FlightDisplayMode { return current; }
export function setFlightDisplayMode(mode: FlightDisplayMode): void {
  if (current === mode) return;
  current = mode;
  try { localStorage.setItem(key, mode); } catch { /* Keep the local selection usable. */ }
  for (const listener of listeners) listener(mode);
}
export function observeFlightDisplayMode(listener: (mode: FlightDisplayMode) => void): () => void {
  listeners.add(listener);
  listener(current);
  return () => { listeners.delete(listener); };
}
if (typeof window !== "undefined") window.addEventListener("storage", event => {
  if (event.key === key) setFlightDisplayMode(event.newValue === "air-realistic" ? "air-realistic" : "simulator");
});
