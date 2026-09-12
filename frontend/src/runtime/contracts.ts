import type { MatchedMissionArea } from "./extension-types";

export interface ReleaseState {
  readonly altitudeM: number;
  readonly horizontalSpeedMps: number;
  readonly verticalSpeedMps: number;
  readonly targetAltitudeM: number;
  readonly targetAltitudeSource?: "terrain" | "manual";
  readonly atmosphereDatumM: number;
  readonly seaLevelDensityKgM3: number;
  readonly initialAoaDeg?: number;
  readonly terrainRay?: {
    readonly from: readonly [number, number];
    readonly to: readonly [number, number];
  };
}

export interface GuidedEnvelopeSample {
  readonly rangeM: number;
  readonly durationS: number;
}

export interface GuidedEnvelope {
  readonly weaponId: string;
  readonly role?: "bomb" | "aam" | "agm";
  readonly modelId: string;
  readonly quality: string;
  readonly minRangeM: number;
  readonly maxRangeM: number;
  readonly minDurationS: number;
  readonly maxDurationS: number;
  readonly hardLimited: boolean;
  readonly tailChaseMaxRangeM?: number;
  readonly headOnMaxRangeM?: number;
  readonly maxTimeS?: number;
  readonly samples: readonly GuidedEnvelopeSample[];
}

export interface GuidedWeaponSummary {
  readonly id: string;
  readonly displayName: string;
  readonly displayNameZh: string;
  readonly guidanceKind: string;
  readonly planform: string;
  readonly role?: "bomb" | "aam" | "agm";
  readonly compatibleAircraft: readonly string[];
}

export interface SolverCatalogSummary {
  readonly schemaVersion: 1;
  readonly modelId: string;
  readonly quality: string;
  readonly sourceVersion: string;
  readonly sourceCommit: string;
  readonly weapons: readonly GuidedWeaponSummary[];
}

export type SolverWorkerRequest =
  | { readonly type: "catalog"; readonly requestId: number }
  | {
      readonly type: "terrain-load";
      readonly requestId: number;
      readonly container: ArrayBuffer;
      readonly mapInfo: {
        readonly minimum: readonly [number, number];
        readonly maximum: readonly [number, number];
      };
    }
  | {
      readonly type: "terrain-sample";
      readonly requestId: number;
      readonly x: number;
      readonly y: number;
    }
  | { readonly type: "terrain-clear"; readonly requestId: number }
  | {
      readonly type: "solve-guided";
      readonly requestId: number;
      readonly weaponId: string;
      readonly state: ReleaseState;
    }
  | {
      readonly type: "solve-weapon";
      readonly requestId: number;
      readonly weaponId: string;
      readonly state: ReleaseState & {
        readonly fighterMach?: number;
        readonly aspectCosine?: number;
      };
    };

export type SolverWorkerResponse =
  | { readonly type: "terrain-clear-result"; readonly requestId: number }
  | {
      readonly type: "terrain-load-result";
      readonly requestId: number;
      readonly mapId: string;
    }
  | {
      readonly type: "terrain-sample-result";
      readonly requestId: number;
      readonly altitudeM: number | null;
      readonly altitudeDatumM: number | null;
      readonly bombingAreaRadiusM?: number | null;
      readonly bombingArea?: MatchedMissionArea | null;
    }
  | {
      readonly type: "catalog-result";
      readonly requestId: number;
      readonly catalog: SolverCatalogSummary;
    }
  | {
      readonly type: "solve-result";
      readonly requestId: number;
      readonly envelope: GuidedEnvelope;
    }
  | {
      readonly type: "error";
      readonly requestId: number;
      readonly code: string;
      readonly message: string;
    };
