import type { GuidedEnvelope } from "./contracts";
import type { BombingWindow, OfficialMapGrid, OfficialChatMessage, MarkedZoneMarker } from "./extension-types";
import type { EditionPolicy } from "./edition-policy";
import type { FuelSnapshot } from "./fuel-management";
import type { SortieResetReason } from "./sortie-recovery";

export type RuntimePhase = "idle" | "hangar" | "arming" | "alive" | "loss-pending" | "wait-next";
export type StrikeTargetMode = "auto" | "zone" | "airfield-module" | "poi" | "hostile";
export type StrikeAirfieldModule = "airfield" | "storage" | "parking" | "dwelling";
export type NavigationSelectionMode = "auto" | "locked" | "paused";

export interface RuntimeSettings {
  readonly cycleMinutes: number;
  readonly checklistItems: readonly string[];
  readonly selectedNavigationId: string | null;
  readonly selectedWeaponId: string;
  readonly targetAltitudeM: number;
  readonly strikeTargetMode: StrikeTargetMode;
  readonly strikeAirfieldModule: StrikeAirfieldModule;
}

export interface RuntimeSettingsStore {
  load(): Partial<RuntimeSettings> | null;
  save(settings: RuntimeSettings): void;
}

export interface TimerCheckpoint {
  readonly lifeStartedAtMs: number;
  readonly savedAtMs: number;
  readonly cycleSeconds: number;
  readonly lifeIndex: number;
  readonly phase: "alive" | "loss-pending";
}

export interface TimerCheckpointStore {
  load(): unknown;
  save(checkpoint: TimerCheckpoint): void;
  clear(): void;
}

export interface RealtimeSolverPort {
  readonly terrainReady?: boolean;
  readonly terrainGeneration?: number;
  solveWeaponEnvelope(weaponId: string, state: {
    altitudeM: number;
    horizontalSpeedMps: number;
    verticalSpeedMps: number;
    targetAltitudeM: number;
    targetAltitudeSource?: "terrain" | "manual";
    atmosphereDatumM: number;
    seaLevelDensityKgM3: number;
    fighterMach?: number;
    aspectCosine?: number;
    initialAoaDeg?: number;
    terrainRay?: {
      readonly from: readonly [number, number];
      readonly to: readonly [number, number];
    };
  }): Promise<GuidedEnvelope>;
  terrainAltitudeAt?(x: number, y: number): Promise<{
    readonly altitudeM: number | null;
    readonly altitudeDatumM: number | null;
    readonly bombingAreaRadiusM?: number | null;
  }>;
}

export interface NavigationItem {
  readonly id: string;
  readonly kind: "zone" | "airfield" | "poi" | "traceback" | "hostile";
  readonly label: string;
  readonly x: number;
  readonly y: number;
  readonly distanceKm: number;
  readonly bearingDeg: number;
  readonly relativeDeg: number;
  readonly friendly: boolean;
  readonly hostile: boolean;
  readonly aircraft?: boolean;
  readonly officialIcon?: string;
  readonly selected: boolean;
  readonly dx?: number;
  readonly dy?: number;
  readonly runwayStart?: readonly [number, number];
  readonly runwayEnd?: readonly [number, number];
  readonly grid?: string;
}

export interface DestroyedZoneMarker {
  readonly id: string;
  readonly label: "战区已被摧毁";
  readonly x: number;
  readonly y: number;
  readonly expiresAtMs: number;
}

export interface EditionSnapshot {
  readonly edition: EditionPolicy;
  readonly revision: number;
  readonly sampledAtMs: number;
  readonly mapObjectsSampledAtMs?: number;
  readonly connected: boolean;
  readonly phase: RuntimePhase;
  readonly sortieContinuity: {
    readonly state: "live" | "partial-data" | "no-data-grace" | "reset-cancelled" | "reset-undo";
    readonly graceExpiresAtMs: number | null;
    readonly resetUndo: {
      readonly reason: SortieResetReason;
      readonly expiresAtMs: number;
    } | null;
  };
  readonly timer: {
    readonly remainingSec: number | null;
    readonly progress: number;
    readonly cycle: number | null;
    readonly lifeIndex: number | null;
    readonly cycleMinutes: number;
  };
  readonly flight: {
    readonly aircraft: string;
    readonly altitudeM: number;
    readonly iasKmh: number;
    readonly tasKmh: number;
    readonly tasObserved?: boolean;
    readonly verticalSpeedMps: number;
    readonly headingDeg: number;
    readonly mach: number | null;
    readonly gearPercent: number;
    readonly onGround: boolean;
    readonly overspeed: {
      readonly level: "none" | "caution" | "warning" | "critical";
      readonly ratio: number;
      readonly iasLimitKmh: number;
      readonly machLimit: number;
      readonly matched: boolean;
      readonly estimated?: boolean;
    };
  };
  readonly navigation: {
    readonly player: { readonly x: number; readonly y: number } | null;
    readonly mapScaleM: readonly [number, number] | null;
    readonly items: readonly NavigationItem[];
    readonly target: NavigationItem | null;
    readonly selectionMode: NavigationSelectionMode;
  } | null;
  readonly destroyedZones: readonly DestroyedZoneMarker[];
  readonly mapGrid: OfficialMapGrid | null;
  readonly markedZones: readonly MarkedZoneMarker[];
  readonly gameChat: readonly OfficialChatMessage[];
  readonly fuel: FuelSnapshot | null;
  readonly checklist: {
    readonly items: readonly string[];
    readonly checked: readonly boolean[];
  } | null;
  readonly strikeSelection: {
    readonly targetMode: StrikeTargetMode;
    readonly effectiveTargetMode?: Exclude<StrikeTargetMode, "auto">;
    readonly airfieldModule: StrikeAirfieldModule;
    readonly target: {
      readonly id: string;
      readonly kind: "zone" | "poi" | "airfield_module" | "hostile";
      readonly label: string;
      readonly x: number;
      readonly y: number;
      readonly distanceKm: number;
      readonly bearingDeg: number;
      readonly relativeDeg: number;
      readonly dx?: number;
      readonly dy?: number;
    } | null;
  } | null;
  readonly strike: {
    readonly weaponId: string;
    readonly targetAltitudeM: number;
    readonly envelope: GuidedEnvelope | null;
    readonly status: "ready" | "unavailable" | "disabled";
    readonly reason: string;
    readonly targetDistanceM: number;
    readonly timeToWindowS: number;
    readonly targetRelativeDeg?: number;
    readonly bombingWindow?: BombingWindow | null;
    readonly releaseStatus: "ready" | "approaching" | "too-far" | "passed" | "off-axis" | "reference-only" | "unavailable";
  } | null;
  readonly alerts: readonly string[];
}

export type EditionCommand =
  | { readonly type: "timer.reset" }
  | { readonly type: "timer.set-cycle"; readonly minutes: number }
  | { readonly type: "navigation.select"; readonly targetId: string | null }
  | { readonly type: "navigation.clear-selection" }
  | { readonly type: "navigation.resume-auto" }
  | { readonly type: "navigation.set-poi"; readonly x: number; readonly y: number }
  | { readonly type: "navigation.clear-poi" }
  | { readonly type: "checklist.set"; readonly items: readonly string[] }
  | { readonly type: "checklist.toggle"; readonly index: number }
  | { readonly type: "strike.select-weapon"; readonly weaponId: string }
  | { readonly type: "strike.set-target-mode"; readonly mode: StrikeTargetMode }
  | { readonly type: "strike.set-airfield-module"; readonly module: StrikeAirfieldModule }
  | { readonly type: "strike.set-target-altitude"; readonly altitudeM: number }
  | {
      readonly type: "strike.set-target-point";
      readonly x: number;
      readonly y: number;
      readonly label: string;
    }
  | { readonly type: "strike.clear-target-point" }
  | { readonly type: "sortie.undo-reset" };

export interface ParsedTelemetry {
  aircraft: string;
  indicatorsValid: boolean;
  stateValid: boolean;
  iasKmh: number;
  tasKmh: number;
  tasObserved: boolean;
  verticalSpeedMps: number;
  altitudeM: number;
  fuelKg: number;
  fuel0Kg: number;
  mach: number | null;
  gearPercent: number;
  aoaDeg: number | null;
  headingDeg: number | null;
  entityLike: boolean;
  onGround: boolean;
}

export interface ParsedMap {
  player: { x: number; y: number; dx: number; dy: number } | null;
  objects: Array<{
    id: string;
    kind: "zone" | "airfield" | "poi" | "traceback" | "hostile";
    label: string;
    x: number;
    y: number;
    friendly: boolean;
    hostile: boolean;
    aircraft?: boolean;
    officialIcon?: string;
    dx?: number;
    dy?: number;
    runwayStart?: readonly [number, number];
    runwayEnd?: readonly [number, number];
  }>;
  objectCount: number;
}

export interface PlayerFlightEvidence {
  readonly sampledAtMs: number;
  readonly iasKmh: number;
  readonly verticalSpeedMps: number;
  readonly gearPercent: number;
  readonly onGround: boolean;
}
