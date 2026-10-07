/** Private Enhanced sampling data; public transports only describe the contract. */
export interface TerrainPreviewRequest {
  readonly x: number;
  readonly y: number;
  readonly headingDeg: number;
  readonly trackDeg: number;
  readonly rangeM: number;
}
export interface TerrainPreviewMesh {
  readonly mapId: string;
  readonly rangeM: number;
  readonly groundM: number | null;
  /** 17 depth rows × 17 lateral columns, in the 8111 altitude datum. */
  readonly altitudesM: readonly (number | null)[];
  /** Full-resolution grid crossings on ground track, independent of the display. */
  readonly profile: readonly (readonly [number, number])[] | null;
}
export interface TerrainAwarenessSnapshot {
  readonly state: "checking" | "ready" | "partial" | "unavailable";
  readonly mesh: TerrainPreviewMesh | null;
  readonly altitudeM: number;
  readonly clearanceM: number | null;
  readonly warning: "caution" | "danger" | null;
  readonly conflictTimeS: number | null;
}

export interface OfficialChatMessage {
  readonly id: number;
  readonly msg: string;
  readonly sender: string;
  readonly enemy: boolean;
  readonly channel: "team" | "all";
  readonly channelLabel: string;
}

export interface MarkedZoneMarker {
  readonly zoneId: string;
  readonly player: string;
  readonly grid: string;
  readonly x: number;
  readonly y: number;
  readonly expiresAtMs: number;
  readonly label: string;
}

export interface OfficialMapGrid {
  readonly minimum: readonly [number, number];
  readonly maximum: readonly [number, number];
  readonly zero: readonly [number, number];
  readonly steps: readonly [number, number];
}

export type AngularRange = readonly [number, number];

export type TargetAreaSource = "mission-area" | "airfield-module";

/**
 * A mission-area match resolved against the active offline terrain/map pair.
 * The sphere fields describe mission matching only. Display and release cues
 * share the oriented building-layout footprint, not that mission radius.
 */
export interface MatchedMissionArea {
  readonly mapId: string;
  readonly id: string;
  readonly centerNormalized: readonly [number, number];
  readonly cornersNormalized: readonly (readonly [number, number])[];
  readonly radiusM: number;
  readonly crossSectionRadiusM: number;
  readonly effectiveRadiusM: number;
  readonly offsetM: number;
}

/** Geometry accepted by the presentation-only target silhouette projection. */
export type TargetAreaShape =
  | { readonly kind: "circle"; readonly center: readonly [number, number]; readonly radiusM: number }
  | { readonly kind: "polygon"; readonly center: readonly [number, number]; readonly corners: readonly (readonly [number, number])[] };

/**
 * Target silhouette in the same signed relative-heading coordinate used by
 * the heading tape. This is reference geometry; release eligibility remains
 * owned by BombingWindow and the strike trust gates.
 */
export interface TargetAreaProjection {
  readonly targetId: string;
  readonly source: TargetAreaSource;
  /** Signed bearing of the authoritative target centre from the reference heading. */
  readonly relativeDeg: number;
  readonly centerRelativeDeg: number;
  /** Unwrapped contiguous interval centred on relativeDeg. */
  readonly rangeDeg: AngularRange;
  /** Canonical [-180, 180] pieces when rangeDeg crosses the heading branch. */
  readonly rangesDeg: readonly AngularRange[];
  readonly referenceHeadingDeg: number;
  readonly shape: "circle" | "polygon";
  readonly quality: "offline-reference" | "calibrated-reference";
}

/** Normalized map coordinates of the static module rectangle, not a 3D hitbox. */
export interface AirfieldModuleArea {
  readonly corners: readonly (readonly [number, number])[];
  readonly uncertaintyM: number;
}

export interface BombingWindow {
  readonly source: "mission-area" | "airfield-module";
  readonly relativeDeg: number;
  readonly approachRangeDeg: AngularRange;
  readonly impactRangesDeg: readonly AngularRange[];
  readonly alongTrackRangeM: readonly [number, number] | null;
  readonly inside: boolean;
}
