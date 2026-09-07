import type { EditionChannel } from "./edition-policy";

type PipMapStorage = Pick<Storage, "getItem" | "setItem">;
const STORAGE_KEY = "bomana:web:pip-map-visible:v1";

export function readPipMapVisible(edition: EditionChannel, storage?: PipMapStorage): boolean {
  try { return (storage ?? localStorage).getItem(`${STORAGE_KEY}:${edition}`) !== "false"; }
  catch { return true; }
}

export function savePipMapVisible(edition: EditionChannel, visible: boolean, storage?: PipMapStorage): void {
  try { (storage ?? localStorage).setItem(`${STORAGE_KEY}:${edition}`, String(visible)); }
  catch { /* Keep the current window usable when browser storage is unavailable. */ }
}
