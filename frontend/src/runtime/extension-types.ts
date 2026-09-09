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
