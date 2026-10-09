import type { Official8111Frame } from "./telemetry-source";
import type { EditionSnapshot } from "./runtime-types";
import { extractObjects, selectPlayerObject } from "./public-runtime";

export const FLIGHT_RECORDING_SCHEMA = "bomana-flight-recording/v1";
export const RECORDING_MAX_BYTES = 32 * 1024 * 1024;
export const RECORDING_MAX_AGE_MS = 3 * 60 * 60 * 1000;
export const RECORDING_CHUNK_MS = 10_000;
export const RECORDING_CHUNK_BYTES = 1024 * 1024;
export type RecordingContext = Readonly<Record<string, string | number | boolean | null>>;
export function retainedRecordingChunks<T extends { session: string; fromMs: number; bytes: number }>(
  chunks: readonly T[], incoming: { session: string; toMs: number; bytes: number },
): readonly T[] {
  let bytes = incoming.bytes;
  const keep: T[] = [];
  for (const chunk of chunks.toReversed()) {
    if (chunk.session !== incoming.session || chunk.fromMs < incoming.toMs - RECORDING_MAX_AGE_MS || bytes + chunk.bytes > RECORDING_MAX_BYTES) break;
    bytes += chunk.bytes; keep.push(chunk);
  }
  return keep.reverse();
}
type Payload = Record<string, unknown>;
const contextKeys = new Set(["edition", "version", "phase", "battleMode", "terrainMapId", "weaponId", "targetId", "targetMode", "y66Status", "y66Reason", "y66Points", "y66Airports",
  "contextSampledAtMs", "timerRemainingSec", "timerCycle", "lifeIndex", "navigationSelectionMode", "releaseTimeS", "strikeReason", "targetAltitudeM", "targetX", "targetY"]);

export function flightRecordingContext(snapshot: EditionSnapshot | null): RecordingContext {
  if (!snapshot) return {};
  const target = snapshot.strikeSelection?.target ?? snapshot.navigation?.target;
  return { contextSampledAtMs: snapshot.sampledAtMs, phase: snapshot.phase,
    timerRemainingSec: snapshot.timer.remainingSec, timerCycle: snapshot.timer.cycle, lifeIndex: snapshot.timer.lifeIndex,
    navigationSelectionMode: snapshot.navigation?.selectionMode ?? null, weaponId: snapshot.strike?.weaponId ?? null,
    targetMode: snapshot.strikeSelection?.targetMode ?? null, targetId: target?.id ?? null, targetX: target?.x ?? null, targetY: target?.y ?? null,
    targetAltitudeM: snapshot.strike?.targetAltitudeM ?? null, releaseTimeS: snapshot.strike?.referenceTimeToReleaseS ?? null,
    strikeReason: snapshot.strike?.reason ?? null };
}

/** Only official telemetry and selected app state, never chat or access material. */
export function recordingFrame(frame: Official8111Frame, context: RecordingContext): Payload {
  const cleanContext: Payload = {};
  for (const [key, value] of Object.entries(context)) if (contextKeys.has(key)) {
    if (value === null || typeof value === "boolean" || typeof value === "number" && Number.isFinite(value)) cleanContext[key] = value;
    else if (typeof value === "string") cleanContext[key] = value.slice(0, 128);
  }
  const numeric = (value: unknown, allowType = false): Payload | null => {
    if (!value || typeof value !== "object" || Array.isArray(value)) return null;
    const result: Payload = {};
    for (const [key, item] of Object.entries(value).slice(0, 160)) {
      if (key.length > 80 || /token|password|secret|cookie|auth/i.test(key)) continue;
      if (typeof item === "number" && Number.isFinite(item) || typeof item === "boolean") result[key] = item;
      else if (allowType && key === "type" && typeof item === "string") result[key] = item.slice(0, 128);
    }
    return result;
  };
  const rawObjects = extractObjects(frame.mapObjects);
  const player = selectPlayerObject(rawObjects);
  const retainedObjects = rawObjects.slice(0, 2000);
  if (player && !retainedObjects.includes(player)) retainedObjects[1999] = player;
  const objects = frame.mapObjects ? retainedObjects.map(raw => {
    const item = raw && typeof raw === "object" ? raw as Payload : {};
    const result: Payload = {};
    if (raw === player) result.is_player = true;
    for (const key of ["x", "y", "dx", "dy", "sx", "sy", "ex", "ey", "blink"]) if (typeof item[key] === "number" && Number.isFinite(item[key])) result[key] = item[key];
    for (const key of ["type", "icon", "icon_bg", "color"]) if (typeof item[key] === "string") result[key] = item[key].slice(0, 80);
    if (Array.isArray(item["color[]"])) result["color[]"] = item["color[]"].slice(0, 3).map(value => typeof value === "number" && Number.isFinite(value) ? value : 0);
    return result;
  }) : null;
  const mapInfo: Payload = numeric(frame.mapInfo) ?? {};
  for (const key of ["map_min", "map_max", "grid_size", "grid_steps", "grid_zero"]) {
    const value = frame.mapInfo?.[key];
    if (Array.isArray(value) && value.length === 2 && value.every(n => typeof n === "number" && Number.isFinite(n))) mapInfo[key] = value;
  }
  return {
    sampledAtMs: frame.sampledAtMs, receivedAtMs: frame.receivedAtMs ?? frame.sampledAtMs,
    indicatorsSampledAtMs: frame.indicatorsSampledAtMs ?? null, stateSampledAtMs: frame.stateSampledAtMs ?? null,
    mapObjectsSampledAtMs: frame.mapObjectsSampledAtMs ?? null, bridgeReachable: frame.bridgeReachable,
    indicators: numeric(frame.indicators, true), state: numeric(frame.state), mapObjects: objects,
    mapObjectsTruncated: rawObjects.length > 2000,
    mapInfo, availability: numeric(frame.availability), holdover: numeric(frame.holdover), context: cleanContext,
  };
}

/** Chunks are independent keyframes followed by changed top-level fields. */
export class FlightRecordingEncoder {
  #previous = new Map<string, string>();
  #lines: string[] = [];
  bytes = 0;
  fromMs = 0;
  toMs = 0;
  frames = 0;
  add(frame: Payload, droppedBefore = 0): void {
    const atMs = Number(frame.sampledAtMs);
    if (!Number.isFinite(atMs)) return;
    const set: Payload = {};
    for (const [key, value] of Object.entries(frame)) {
      const encoded = JSON.stringify(value);
      if (this.#previous.get(key) !== encoded) { set[key] = value; this.#previous.set(key, encoded); }
    }
    const line = JSON.stringify({ atMs, set, ...(droppedBefore ? { droppedBefore } : {}) }) + "\n";
    this.#lines.push(line); this.bytes += new TextEncoder().encode(line).length;
    if (this.frames++ === 0) this.fromMs = atMs;
    this.toMs = atMs;
  }
  take(): { text: string; fromMs: number; toMs: number; frames: number } | null {
    if (!this.frames) return null;
    const result = { text: this.#lines.join(""), fromMs: this.fromMs, toMs: this.toMs, frames: this.frames };
    this.#lines = []; this.#previous.clear(); this.bytes = this.frames = 0;
    return result;
  }
}

/** Hangar ends a match; temporary disconnects and an aircraft respawn do not. */
export class RecordingMatchBoundary {
  #key = "";
  #hangarSince: number | null = null;
  #ended = false;
  #lastPlayerAt: number | null = null;
  get ended(): boolean { return this.#ended; }
  get mapKey(): string { return this.#key; }
  update(frame: Payload): "idle" | "continue" | "new" {
    const objects = frame.mapObjects as Payload[] | null;
    const hasPlayer = objects?.some(p => p.is_player === true) === true;
    const info = frame.mapInfo as Payload;
    const at = Number(frame.sampledAtMs);
    const state = frame.state as Payload | null;
    const availability = frame.availability as Payload | null;
    const holdover = frame.holdover as Payload | null;
    if (!hasPlayer) {
      if (frame.bridgeReachable && state?.valid === false && availability?.state === true
        && holdover?.state !== true && availability?.mapObjects === false) {
        this.#hangarSince ??= at;
        if (at - this.#hangarSince >= 10_000) this.#ended = true;
      } else this.#hangarSince = null;
      return this.#key && !this.#ended && this.#lastPlayerAt !== null && at - this.#lastPlayerAt < 60_000 ? "continue" : "idle";
    }
    this.#hangarSince = null;
    this.#lastPlayerAt = at;
    // Map info arrives independently of the first ownship frame after a reload.
    // Do not replace a saved sortie with an unknown identity.
    if (!Array.isArray(info.map_min) || !Array.isArray(info.map_max)) return this.#key && !this.#ended ? "continue" : "idle";
    const key = JSON.stringify([info.map_min, info.map_max, info.map_generation]);
    const changed = this.#ended || key !== this.#key;
    this.#key = key; this.#ended = false;
    return changed ? "new" : "continue";
  }
}
