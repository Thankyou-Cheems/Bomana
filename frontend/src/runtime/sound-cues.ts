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
  #timerIdentity = "";
  #playedThresholds = new Set<number>();
  readonly #statusListeners = new Set<() => void>();
  #lastOverspeedAtMs = 0;
  #knownDestroyedZones = new Set<string>();
  #airRealistic = false;
  readonly #timerTones = new Set<OscillatorNode>();

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
      this.#context.onstatechange = () => this.#notifyStatus();
    }
    try {
      if (!this.ready) await this.#context.resume();
    } finally { this.#notifyStatus(); }
  }
  async recover(): Promise<void> { if (this.#context) await this.enable(); }

  configure(preferences: SoundCuePreferences): SoundCuePreferences {
    this.#preferences = normalizeSoundCuePreferences(preferences);
    this.#notifyStatus();
    return this.#preferences;
  }

  toggle(): boolean {
    this.#preferences = Object.freeze({ ...this.#preferences, masterEnabled: !this.#preferences.masterEnabled });
    this.#notifyStatus();
    if (this.#preferences.masterEnabled) this.#tone(988, 40, 0.05);
    return this.#preferences.masterEnabled;
  }

  preview(kind: CueKind, preset: SoundCuePreset): void { this.#playCue(kind, preset, 5); }

  setAirRealistic(enabled: boolean): void {
    this.#airRealistic = enabled;
    if (enabled) {
      for (const oscillator of this.#timerTones) {
        oscillator.stop();
        oscillator.disconnect();
      }
      this.#timerTones.clear();
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
      if (
        !airRealistic && this.#preferences.timerEnabled
        && remaining !== null
        && remaining !== this.#lastTimerSecond && warn
      ) this.#playCue("timer", this.#preferences.timerPreset, remaining);
      const level = snapshot.flight.overspeed.level;
      const interval = level === "critical" ? 550 : level === "warning" ? 1100 : 0;
      if (interval && snapshot.sampledAtMs - this.#lastOverspeedAtMs >= interval) {
        this.#lastOverspeedAtMs = snapshot.sampledAtMs;
        this.#tone(level === "critical" ? 760 : 620, 45, 0.035);
      }
      if (!airRealistic && this.#preferences.zoneDestroyedEnabled && newlyDestroyed) {
        this.#playCue("zone-destroyed", this.#preferences.zoneDestroyedPreset, 0);
      }
    }
    this.#lastTimerSecond = remaining;
    this.#knownDestroyedZones = destroyedZoneIds;
  }

  #playCue(kind: CueKind, preset: SoundCuePreset, remaining: number): void {
    if (kind === "timer" && this.#airRealistic) return;
    const urgent = remaining < 10;
    if (preset === "chime") {
      const first = kind === "timer" ? urgent ? 1046 : 880 : 659;
      this.#tone(first, 70, 0.045, 0, kind);
      this.#tone(kind === "timer" ? first * 1.25 : 784, 90, 0.04, 85, kind);
      return;
    }
    if (preset === "low") {
      this.#tone(kind === "timer" ? urgent ? 523 : 440 : 294, kind === "timer" ? 90 : 170, 0.05, 0, kind);
      return;
    }
    this.#tone(
      kind === "timer" ? remaining >= 10 ? 784 : 988 : 440,
      kind === "timer" ? remaining >= 10 ? 55 : 35 : 100,
      kind === "timer" ? 0.045 : 0.05,
      0, kind,
    );
  }

  #tone(frequency: number, durationMs: number, gainValue: number, delayMs = 0, kind?: CueKind): void {
    const context = this.#context;
    if (!context || !this.ready) return;
    const oscillator = context.createOscillator();
    const gain = context.createGain();
    const startsAt = context.currentTime + delayMs / 1000;
    oscillator.frequency.value = frequency;
    gain.gain.value = gainValue;
    oscillator.connect(gain).connect(context.destination);
    if (kind === "timer") this.#timerTones.add(oscillator);
    oscillator.onended = () => { this.#timerTones.delete(oscillator); oscillator.disconnect(); gain.disconnect(); };
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
