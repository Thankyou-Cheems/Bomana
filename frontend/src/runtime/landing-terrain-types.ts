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
  readonly normals: readonly (readonly [number,number])[];
  /** Separate the sampled footprint/floor from the live vertical intercept. */
  readonly referenceScene: LandingRunwayScene;
  readonly floorsM: readonly number[];
  readonly raised: boolean;
}
