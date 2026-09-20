import type { LandingGeometry } from "./landing-assist";

export interface LandingRunwayScene {
  readonly along: number;
  readonly across: number;
  readonly height: number;
  readonly length: number;
  readonly angle: number;
  readonly slope: number;
  readonly approach: boolean;
  readonly width?: number;
}
export type ProjectedPoint = readonly [number, number];
type Point3 = readonly [number, number, number];
export type ProjectedSegment = readonly [ProjectedPoint, ProjectedPoint];
const radians = Math.PI / 180;
const near = 30;
function intersectNear(p: Point3, q: Point3): Point3 {
  const t = (near - p[2]) / (q[2] - p[2]);
  return [p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t, near];
}
const perspective = (p: Point3): ProjectedPoint => [p[0] / p[2], p[1] / p[2]];

/** A runway may straddle the camera plane during a pass; clip its surface too. */
function surface(corners: readonly Point3[]): ProjectedPoint[] {
  const clipped: Point3[] = [];
  for (let i = 0; i < corners.length; i++) {
    const a = corners[i]!, b = corners[(i + 1) % corners.length]!;
    if (a[2] >= near) clipped.push(a);
    if ((a[2] >= near) !== (b[2] >= near)) clipped.push(intersectNear(a, b));
  }
  return clipped.map(perspective);
}

/** Level, heading-referenced camera. Width is a definition reference or symbolic. */
export function landingRunwayScene(g: LandingGeometry | null | undefined, headingDeg: number, glideAngleDeg: number): LandingRunwayScene | null {
  if (!g || g.heightM === null || ![g.heightM, g.thresholdDistanceM, g.crossTrackM, g.lengthM, g.courseDeg, headingDeg, glideAngleDeg].every(Number.isFinite)
    || g.lengthM <= 0) return null;
  return { along: g.thresholdDistanceM, across: -g.crossTrackM, height: g.heightM, length: g.lengthM,
    angle: ((g.courseDeg - headingDeg + 540) % 360 - 180) * radians,
    slope: Math.tan(glideAngleDeg * radians), approach: g.thresholdDistanceM > 30 && g.stage !== "runway" && g.stage !== "past-runway",
    width: Number.isFinite(g.referenceWidthM) && g.referenceWidthM! > 0 ? g.referenceWidthM : 90 };
}

/** Clip in camera space before dividing, including a runway partly behind ownship. */
function segment(a: Point3, b: Point3): ProjectedSegment | null {
  if (a[2] < near && b[2] < near) return null;
  const start = a[2] < near ? intersectNear(a, b) : a;
  const end = b[2] < near ? intersectNear(b, a) : b;
  return [perspective(start), perspective(end)];
}

export function projectLandingRunway(scene: LandingRunwayScene, cameraPitch = 0) {
  const runwayHalfWidth = (scene.width ?? 90) / 2;
  const sin = Math.sin(scene.angle), cos = Math.cos(scene.angle);
  const cp = Math.cos(cameraPitch), sp = Math.sin(cameraPitch);
  const point = (along: number, across: number, heightAboveRunway: number): Point3 => {
    const depth = along * cos - across * sin, down = scene.height - heightAboveRunway;
    return [along * sin + across * cos, down * cp - depth * sp, depth * cp + down * sp];
  };
  const start = point(scene.along, scene.across, 0);
  const end = point(scene.along + scene.length, scene.across, 0);
  // These are the official ordered endpoints, using the one known runway datum.
  const runway = segment(start, end);
  const entrance = segment(point(scene.along, scene.across - runwayHalfWidth, 0), point(scene.along, scene.across + runwayHalfWidth, 0));
  const runwaySurface = surface([
    point(scene.along, scene.across - runwayHalfWidth, 0), point(scene.along, scene.across + runwayHalfWidth, 0),
    point(scene.along + scene.length, scene.across + runwayHalfWidth, 0), point(scene.along + scene.length, scene.across - runwayHalfWidth, 0),
  ]);
  const rails: ProjectedSegment[] = [];
  if (scene.approach && start[2] >= 30) {
    const extent = Math.max(6000, scene.along * 1.2);
    // The corridor shares the displayed reference width, not a safety envelope.
    for (const side of [-runwayHalfWidth, runwayHalfWidth]) {
      const rail = segment(point(scene.along, scene.across + side, 15),
        point(scene.along - extent, scene.across + side, 15 + extent * scene.slope));
      if (rail) rails.push(rail);
    }
  }
  const bearing = Math.atan2((start[0] + end[0]) / 2, (start[2] + end[2]) / 2);
  const project = (p: Point3): ProjectedPoint | null => p[2] >= 30 ? [p[0] / p[2], p[1] / p[2]] : null;
  return { runway, entrance, surface: runwaySurface, rails, bearing, threshold: project(start), end: project(end) };
}

/** Inspection camera tilts toward the runway, not a measured aircraft attitude.
 * Keep yaw heading-referenced; zoom/tilt never distort the runway itself. */
export function landingRunwayCamera(scene: LandingRunwayScene) {
  const depth = (scene.along + scene.length / 2) * Math.cos(scene.angle) - scene.across * Math.sin(scene.angle);
  return depth > 30 ? Math.max(-Math.PI / 3, Math.min(Math.PI / 3, Math.atan2(scene.height, depth))) : 0;
}

/** Display-only critical damping. Preserves a coherent 3D scene instead of
 * independently drifting endpoint pixels. Lifecycle/validity resets are owned by the caller. */
export class RunwaySceneMotion {
  #value: LandingRunwayScene | null = null;
  #target: LandingRunwayScene | null = null;
  #velocity = { along: 0, across: 0, height: 0, angle: 0 };
  #at = 0;
  observe(next: LandingRunwayScene | null, at: number, reset: boolean): void {
    this.step(at);
    if (reset || !next || !this.#value) {
      this.#value = next;
      this.#velocity = { along: 0, across: 0, height: 0, angle: 0 };
    }
    this.#target = next;
    this.#at = at;
  }
  step(at: number): LandingRunwayScene | null {
    const dt = Math.max(0, at - this.#at) / 1000, omega = 18, decay = Math.exp(-omega * dt);
    this.#at = Math.max(at, this.#at);
    if (!this.#value || !this.#target) return this.#value;
    const value = { ...this.#target };
    for (const axis of ["along", "across", "height", "angle"] as const) {
      let offset = this.#value[axis] - this.#target[axis];
      if (axis === "angle") offset = Math.atan2(Math.sin(offset), Math.cos(offset));
      const c = this.#velocity[axis] + omega * offset;
      const delta = (offset + c * dt) * decay;
      const velocity = (this.#velocity[axis] - omega * c * dt) * decay;
      const epsilon = axis === "angle" ? .00001 : .01;
      if (delta * offset <= 0 || Math.abs(delta) < epsilon && Math.abs(velocity) < epsilon * 10) {
        value[axis] = this.#target[axis]; this.#velocity[axis] = 0;
      } else { value[axis] += delta; this.#velocity[axis] = velocity; }
    }
    this.#value = value;
    return value;
  }
  isMoving(at: number): boolean {
    const value = this.step(at);
    return value !== null && this.#target !== null
      && (["along", "across", "height", "angle"] as const).some(axis => value[axis] !== this.#target![axis]);
  }
}
