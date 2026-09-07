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

export interface BombingWindow {
  readonly halfAngleDeg: number;
  readonly relativeDeg: number;
  readonly radiusM: number;
  readonly crossTrackM: number;
  readonly impactMissM: number;
  readonly inside: boolean;
}
