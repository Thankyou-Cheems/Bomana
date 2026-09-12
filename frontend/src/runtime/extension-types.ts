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
 * The marker may be offset from the source sphere; effectiveRadiusM is the
 * conservative horizontal cross-section available around the observed marker.
 */
export interface MatchedMissionArea {
  readonly mapId: string;
  readonly id: string;
  readonly centerNormalized: readonly [number, number];
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
