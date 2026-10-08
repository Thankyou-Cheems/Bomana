const key = "bomana:air-velocity-vector:v1";
const listeners = new Set<(enabled: boolean) => void>();
let enabled = true;
try { enabled = localStorage.getItem(key) !== "off"; } catch { /* Keep the default without storage. */ }

export function setAirVelocityVectorEnabled(value: boolean): void {
  if (enabled === value) return;
  enabled = value;
  try { localStorage.setItem(key, value ? "on" : "off"); } catch { /* Session-only preference. */ }
  for (const listener of listeners) listener(value);
}

export function observeAirVelocityVectorEnabled(listener: (enabled: boolean) => void): () => void {
  listeners.add(listener); listener(enabled);
  return () => { listeners.delete(listener); };
}

if (typeof window !== "undefined") window.addEventListener("storage", event => {
  if (event.key === key || event.key === null) setAirVelocityVectorEnabled(event.newValue !== "off");
});
