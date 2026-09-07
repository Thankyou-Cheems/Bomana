import type { EditionSnapshot } from "./runtime-types";

export type SoundCuePreset = "classic" | "chime" | "low";

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
type CueKind = "timer" | "zone-destroyed";

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
  #lastOverspeedAtMs = 0;
  #knownDestroyedZones = new Set<string>();

  constructor(preferences: Partial<SoundCuePreferences> | null = null) {
    this.#preferences = normalizeSoundCuePreferences(preferences);
  }

  get enabled(): boolean { return this.#preferences.masterEnabled; }
  get preferences(): SoundCuePreferences { return this.#preferences; }

  async enable(): Promise<void> {
    if (!this.#context) this.#context = new AudioContext();
    if (this.#context.state === "suspended") await this.#context.resume();
  }

  configure(preferences: SoundCuePreferences): SoundCuePreferences {
    this.#preferences = normalizeSoundCuePreferences(preferences);
    return this.#preferences;
  }

  toggle(): boolean {
    this.#preferences = Object.freeze({ ...this.#preferences, masterEnabled: !this.#preferences.masterEnabled });
    if (this.#preferences.masterEnabled) this.#tone(988, 40, 0.05);
    return this.#preferences.masterEnabled;
  }

  preview(kind: CueKind, preset: SoundCuePreset): void { this.#playCue(kind, preset, 5); }

  update(snapshot: EditionSnapshot): void {
    const remaining = snapshot.timer.remainingSec === null ? null : Math.ceil(snapshot.timer.remainingSec);
    const destroyedZoneIds = new Set(snapshot.destroyedZones.map((zone) => zone.id));
    const newlyDestroyed = [...destroyedZoneIds].some((id) => !this.#knownDestroyedZones.has(id));
    if (this.#preferences.masterEnabled && this.#context) {
      if (
        this.#preferences.timerEnabled
        && remaining !== null
        && remaining !== this.#lastTimerSecond
        && [30, 20, 10, 5, 4, 3, 2, 1].includes(remaining)
      ) this.#playCue("timer", this.#preferences.timerPreset, remaining);
      const level = snapshot.flight.overspeed.level;
      const interval = level === "critical" ? 550 : level === "warning" ? 1100 : 0;
      if (interval && snapshot.sampledAtMs - this.#lastOverspeedAtMs >= interval) {
        this.#lastOverspeedAtMs = snapshot.sampledAtMs;
        this.#tone(level === "critical" ? 760 : 620, 45, 0.035);
      }
      if (this.#preferences.zoneDestroyedEnabled && newlyDestroyed) {
        this.#playCue("zone-destroyed", this.#preferences.zoneDestroyedPreset, 0);
      }
    }
    this.#lastTimerSecond = remaining;
    this.#knownDestroyedZones = destroyedZoneIds;
  }

  #playCue(kind: CueKind, preset: SoundCuePreset, remaining: number): void {
    const urgent = remaining < 10;
    if (preset === "chime") {
      const first = kind === "timer" ? urgent ? 1046 : 880 : 659;
      this.#tone(first, 70, 0.045);
      this.#tone(kind === "timer" ? first * 1.25 : 784, 90, 0.04, 85);
      return;
    }
    if (preset === "low") {
      this.#tone(kind === "timer" ? urgent ? 523 : 440 : 294, kind === "timer" ? 90 : 170, 0.05);
      return;
    }
    this.#tone(
      kind === "timer" ? remaining >= 10 ? 784 : 988 : 440,
      kind === "timer" ? remaining >= 10 ? 55 : 35 : 100,
      kind === "timer" ? 0.045 : 0.05,
    );
  }

  #tone(frequency: number, durationMs: number, gainValue: number, delayMs = 0): void {
    const context = this.#context;
    if (!context) return;
    const oscillator = context.createOscillator();
    const gain = context.createGain();
    const startsAt = context.currentTime + delayMs / 1000;
    oscillator.frequency.value = frequency;
    gain.gain.value = gainValue;
    oscillator.connect(gain).connect(context.destination);
    oscillator.start(startsAt);
    oscillator.stop(startsAt + durationMs / 1000);
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
