import type { EditionSnapshot } from "./runtime-types";
import { scheduleSoundCue, soundCueNotes, type SoundCueKind, type SoundCuePreset } from "./sound-cue-design";

export type { SoundCuePreset } from "./sound-cue-design";

export interface SoundCuePreferences {
  readonly masterEnabled: boolean;
  readonly timerEnabled: boolean;
  readonly timerPreset: SoundCuePreset;
  readonly zoneDestroyedEnabled: boolean;
  readonly zoneDestroyedPreset: SoundCuePreset;
}

export const DEFAULT_SOUND_CUE_PREFERENCES: SoundCuePreferences = Object.freeze({
  masterEnabled: true,
  timerEnabled: true,
  timerPreset: "classic",
  zoneDestroyedEnabled: true,
  zoneDestroyedPreset: "classic",
});

type SoundCueStorage = Pick<Storage, "getItem" | "setItem" | "removeItem">;

const SOUND_CUE_KEY = "bomana:sound-cues:v1";
const PRESET_CODES: Readonly<Record<SoundCuePreset, string>> = Object.freeze({ classic: "c", chime: "h", low: "l" });
const CODE_PRESETS: Readonly<Record<string, SoundCuePreset>> = Object.freeze({ c: "classic", h: "chime", l: "low" });

export class SoundCuePreferencesStore {
  readonly #storage: SoundCueStorage;

  constructor(storage: SoundCueStorage = localStorage) { this.#storage = storage; }

  load(): SoundCuePreferences {
    try {
      const raw = this.#storage.getItem(SOUND_CUE_KEY);
      return normalizeSoundCuePreferences(raw ? JSON.parse(raw) : null);
    } catch {
      return DEFAULT_SOUND_CUE_PREFERENCES;
    }
  }

  save(preferences: SoundCuePreferences): void {
    try {
      this.#storage.setItem(SOUND_CUE_KEY, JSON.stringify(normalizeSoundCuePreferences(preferences)));
    } catch {
      // Sound remains available for this page even when browser storage is unavailable.
    }
  }
}

export function encodeSoundCuePreferences(preferences: SoundCuePreferences): string {
  const value = normalizeSoundCuePreferences(preferences);
  return [
    "1",
    value.masterEnabled ? "1" : "0",
    value.timerEnabled ? "1" : "0",
    PRESET_CODES[value.timerPreset],
    value.zoneDestroyedEnabled ? "1" : "0",
    PRESET_CODES[value.zoneDestroyedPreset],
  ].join(".");
}

export function decodeSoundCuePreferences(value: string): SoundCuePreferences | null {
  const match = /^1\.([01])\.([01])\.([chl])\.([01])\.([chl])$/.exec(value);
  if (!match) return null;
  return Object.freeze({
    masterEnabled: match[1] === "1",
    timerEnabled: match[2] === "1",
    timerPreset: CODE_PRESETS[match[3]!]!,
    zoneDestroyedEnabled: match[4] === "1",
    zoneDestroyedPreset: CODE_PRESETS[match[5]!]!,
  });
}

export class SoundCues {
  #context: AudioContext | null = null;
  #preferences: SoundCuePreferences;
  #lastTimerSecond: number | null = null;
  #timerIdentity = "";
  #playedThresholds = new Set<number>();
  readonly #statusListeners = new Set<() => void>();
  #lastOverspeedAtMs = 0;
  #knownDestroyedZones = new Set<string>();
  #airRealistic = false;
  readonly #voices = new Map<OscillatorNode, SoundCueKind>();

  constructor(preferences: Partial<SoundCuePreferences> | null = null) {
    this.#preferences = normalizeSoundCuePreferences(preferences);
  }

  get enabled(): boolean { return this.#preferences.masterEnabled; }
  get preferences(): SoundCuePreferences { return this.#preferences; }
  get ready(): boolean { return this.#context?.state === "running"; }
  observeStatus(listener: () => void): () => void {
    this.#statusListeners.add(listener); listener();
    return () => { this.#statusListeners.delete(listener); };
  }
  #notifyStatus(): void { for (const listener of this.#statusListeners) listener(); }

  async enable(): Promise<void> {
    if (!this.#context || this.#context.state === "closed") {
      this.#context = new AudioContext();
      this.#context.onstatechange = () => {
        if (!this.ready) this.#stopVoices(() => true);
        this.#notifyStatus();
      };
    }
    try {
      if (!this.ready) await this.#context.resume();
    } finally { this.#notifyStatus(); }
  }
  async recover(): Promise<void> { if (this.#context) await this.enable(); }

  configure(preferences: SoundCuePreferences): SoundCuePreferences {
    this.#preferences = normalizeSoundCuePreferences(preferences);
    this.#stopVoices(kind => !this.enabled || kind === "timer" && !this.#preferences.timerEnabled
      || kind === "zone-destroyed" && !this.#preferences.zoneDestroyedEnabled);
    this.#notifyStatus();
    return this.#preferences;
  }

  toggle(): boolean {
    this.#preferences = Object.freeze({ ...this.#preferences, masterEnabled: !this.#preferences.masterEnabled });
    this.#notifyStatus();
    if (!this.enabled) this.#stopVoices(() => true);
    return this.#preferences.masterEnabled;
  }

  preview(kind: SoundCueKind, preset: SoundCuePreset): void {
    if (!this.enabled) return;
    this.#stopVoices(() => true);
    this.#playCue(kind, preset, true);
  }

  setAirRealistic(enabled: boolean): void {
    this.#airRealistic = enabled;
    if (enabled) {
      this.#stopVoices(kind => kind === "timer" || kind === "zone-destroyed");
    }
  }

  update(snapshot: EditionSnapshot, airRealistic = this.#airRealistic): void {
    this.setAirRealistic(airRealistic);
    const remaining = snapshot.timer.remainingSec === null ? null : Math.ceil(snapshot.timer.remainingSec);
    const identity = `${snapshot.timer.cueIdentity ?? snapshot.timer.lifeIndex ?? ""}:${snapshot.timer.cycle ?? ""}`;
    if (identity !== this.#timerIdentity) {
      this.#timerIdentity = identity; this.#lastTimerSecond = null; this.#playedThresholds.clear();
    }
    const thresholds = [30, 20, 10, 5, 4, 3, 2, 1];
    const crossed = remaining === null ? [] : thresholds.filter(threshold => !this.#playedThresholds.has(threshold)
      && (remaining === threshold || this.#lastTimerSecond !== null
        && this.#lastTimerSecond > threshold && remaining < threshold));
    // Coalesce skipped thresholds into one current warning; never replay a burst
    // after background suspension, or consume the same threshold twice.
    const warn = crossed.length > 0 && remaining !== null && remaining > 0
      && (this.#lastTimerSecond === null || this.#lastTimerSecond - remaining <= 3);
    for (const threshold of crossed) this.#playedThresholds.add(threshold);
    const destroyedZoneIds = new Set(snapshot.destroyedZones.map((zone) => zone.id));
    const newlyDestroyed = [...destroyedZoneIds].some((id) => !this.#knownDestroyedZones.has(id));
    if (this.#preferences.masterEnabled && this.ready) {
      const level = snapshot.flight.overspeed.level;
      const critical = level === "critical";
      if (critical) this.#stopVoices(kind => kind !== "overspeed");
      if (
        !critical && !airRealistic && this.#preferences.timerEnabled
        && remaining !== null
        && remaining !== this.#lastTimerSecond && warn
      ) this.#playCue("timer", this.#preferences.timerPreset, remaining < 10);
      const interval = critical ? 1100 : level === "warning" ? 2200 : 0;
      if (interval && snapshot.sampledAtMs - this.#lastOverspeedAtMs >= interval) {
        this.#lastOverspeedAtMs = snapshot.sampledAtMs;
        this.#playCue("overspeed", "classic", critical);
      }
      if (!critical && !airRealistic && this.#preferences.zoneDestroyedEnabled && newlyDestroyed) {
        this.#playCue("zone-destroyed", this.#preferences.zoneDestroyedPreset);
      }
    }
    this.#lastTimerSecond = remaining;
    this.#knownDestroyedZones = destroyedZoneIds;
  }

  #playCue(kind: SoundCueKind, preset: SoundCuePreset, urgent = false): void {
    if (kind !== "overspeed" && this.#airRealistic) return;
    const context = this.#context;
    if (!context || !this.ready) return;
    for (const voice of scheduleSoundCue(context, soundCueNotes(kind, preset, urgent), voice => this.#voices.delete(voice))) {
      this.#voices.set(voice, kind);
    }
  }

  #stopVoices(matches: (kind: SoundCueKind) => boolean): void {
    for (const [voice, kind] of this.#voices) {
      if (!matches(kind)) continue;
      voice.stop(); voice.disconnect(); this.#voices.delete(voice);
    }
  }
}

function normalizeSoundCuePreferences(value: Partial<SoundCuePreferences> | null): SoundCuePreferences {
  return Object.freeze({
    masterEnabled: typeof value?.masterEnabled === "boolean" ? value.masterEnabled : true,
    timerEnabled: typeof value?.timerEnabled === "boolean" ? value.timerEnabled : true,
    timerPreset: isPreset(value?.timerPreset) ? value.timerPreset : "classic",
    zoneDestroyedEnabled: typeof value?.zoneDestroyedEnabled === "boolean" ? value.zoneDestroyedEnabled : true,
    zoneDestroyedPreset: isPreset(value?.zoneDestroyedPreset) ? value.zoneDestroyedPreset : "classic",
  });
}

function isPreset(value: unknown): value is SoundCuePreset {
  return value === "classic" || value === "chime" || value === "low";
}
