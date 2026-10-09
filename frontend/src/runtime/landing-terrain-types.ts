import type { LandingRunwayScene } from "./landing-runway-projection";

export interface LandingCorridorRequest {
  readonly scene: LandingRunwayScene;
  readonly x: number;
  readonly y: number;
  readonly courseDeg: number;
  readonly elevationM: number;
}
export interface LandingTerrainCorridor {
  /** Anchor in runway-relative coordinates, retained while the camera moves. */
  readonly along: number;
  readonly across: number;
  readonly points: readonly (readonly [number,number,number])[];
  /** Terrain floors are independent of the live geometric intercept. */
  readonly floorsM: readonly number[];
  /** Half-width covered by the five sampled longitudinal profiles. */
  readonly halfWidthM: number;
  readonly raised: boolean;
}
