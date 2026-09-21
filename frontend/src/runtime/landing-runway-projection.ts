import type { LandingGeometry, LandingSnapshot } from "./landing-assist";

export interface LandingRunwayScene {
  readonly along: number;
  readonly across: number;
  readonly height: number;
  readonly length: number;
  readonly angle: number;
  readonly slope: number;
  readonly approach: boolean;
  readonly width?: number;
  readonly pitch?: number;
  readonly roll?: number;
  readonly speed?: number;
}
type Point2 = readonly [number, number];
export type ProjectedPoint = Point2;
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

/** Heading/attitude-referenced camera. Width is a definition reference or symbolic. */
export function landingRunwayScene(g: LandingGeometry | null | undefined, headingDeg: number, glideAngleDeg: number, attitude?: LandingSnapshot["attitude"]): LandingRunwayScene | null {
  if (!g || g.heightM === null || ![g.heightM, g.thresholdDistanceM, g.crossTrackM, g.lengthM, g.courseDeg, headingDeg, glideAngleDeg].every(Number.isFinite)
    || g.lengthM <= 0) return null;
  return { along: g.thresholdDistanceM, across: -g.crossTrackM, height: g.heightM, length: g.lengthM,
    angle: ((g.courseDeg - headingDeg + 540) % 360 - 180) * radians,
    slope: Math.tan(glideAngleDeg * radians), approach: g.thresholdDistanceM > 30 && g.stage !== "runway" && g.stage !== "past-runway",
    width: Number.isFinite(g.referenceWidthM) && g.referenceWidthM! > 0 ? g.referenceWidthM : 90,
    pitch: (attitude?.pitchDeg ?? 0) * radians, roll: (attitude?.rollDeg ?? 0) * radians, speed: attitude?.tasMps ?? 0 };
}

/** Clip in camera space before dividing, including a runway partly behind ownship. */
function segment(a: Point3, b: Point3): ProjectedSegment | null {
  if (a[2] < near && b[2] < near) return null;
  const start = a[2] < near ? intersectNear(a, b) : a;
  const end = b[2] < near ? intersectNear(b, a) : b;
  return [perspective(start), perspective(end)];
}

/** A heading-tangent geometric intercept, followed by an aligned final leg.
 * Coordinates are runway-forward, runway-right and height above its datum.
 * This is a visual route reference, not a turn-performance or clearance solution. */
export function landingApproachPath(scene: LandingRunwayScene) {
  const finalLength = Math.min(1500, scene.along * .25);
  const gate: Point2 = [scene.along - finalLength, scene.across];
  const reach = Math.hypot(gate[0], gate[1]);
  // Airspeed sets an eight-second visual lead, bounded by the actual intercept
  // distance. It changes route smoothness, never apparent perspective width.
  const handle = scene.speed && scene.speed > 0 ? Math.min(reach * .45, Math.max(reach * .15, scene.speed * 8)) : reach * .35;
  const controls: readonly [Point2, Point2, Point2, Point2] = [
    [0, 0],
    [Math.cos(scene.angle) * handle, -Math.sin(scene.angle) * handle],
    [gate[0] - handle, gate[1]],
    gate,
  ];
  const points: Point3[] = [];
  const normals: (readonly [number, number])[] = [];
  for (let i = 0; i <= 48; i++) {
    const t = i / 48, u = 1 - t;
    const [a, b, c, d] = controls;
    const coordinate = (axis: 0 | 1) => u ** 3 * a[axis] + 3 * u * u * t * b[axis]
      + 3 * u * t * t * c[axis] + t ** 3 * d[axis];
    points.push([coordinate(0), coordinate(1), 0]);
    const along = 3 * u * u * (b[0] - a[0]) + 6 * u * t * (c[0] - b[0]) + 3 * t * t * (d[0] - c[0]);
    const across = 3 * u * u * (b[1] - a[1]) + 6 * u * t * (c[1] - b[1]) + 3 * t * t * (d[1] - c[1]);
    const length = Math.hypot(along, across);
    normals.push(length > .001 ? [-across / length, along / length] : [0, 1]);
  }
  points.push([scene.along, scene.across, 15]); normals.push([0, 1]);
  // Reference height follows remaining route distance, not current altitude:
  // otherwise a high/low aircraft would bend the desired glide path onto itself.
  for (let i = points.length - 2; i >= 0; i--) {
    const p = points[i]!, next = points[i + 1]!;
    points[i] = [p[0], p[1], next[2] + Math.hypot(next[0] - p[0], next[1] - p[1]) * scene.slope];
  }
  return { controls, points, normals };
}

export function projectLandingRunway(scene: LandingRunwayScene, cameraPitch = -(scene.pitch ?? 0), cameraRoll = scene.roll ?? 0) {
  const runwayHalfWidth = (scene.width ?? 90) / 2;
  const sin = Math.sin(scene.angle), cos = Math.cos(scene.angle);
  const cp = Math.cos(cameraPitch), sp = Math.sin(cameraPitch);
  const point = (along: number, across: number, heightAboveRunway: number): Point3 => {
    const depth = along * cos - across * sin, down = scene.height - heightAboveRunway;
    const x = along * sin + across * cos, y = down * cp - depth * sp;
    // Positive right bank rotates the world counterclockwise in screen space.
    return [x * Math.cos(cameraRoll) + y * Math.sin(cameraRoll), -x * Math.sin(cameraRoll) + y * Math.cos(cameraRoll), depth * cp + down * sp];
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
  const markings: ProjectedSegment[] = [];
  for (const fraction of [-.7, -.4, .4, .7]) {
    const across = scene.across + fraction * runwayHalfWidth;
    const stripe = segment(point(scene.along + 25, across, 0), point(scene.along + Math.min(110, scene.length * .08), across, 0));
    if (stripe) markings.push(stripe);
  }
  const ground: ProjectedSegment[] = [];
  if (scene.height >= 0) {
    const span = Math.max(1000, (scene.width ?? 90) * 10);
    for (const along of [scene.along - 1500, scene.along + scene.length + 1500]) {
      const line = segment(point(along, scene.across - span, 0), point(along, scene.across + span, 0));
      if (line) ground.push(line);
    }
    for (const across of [scene.across - span, scene.across + span]) {
      const line = segment(point(scene.along - 6000, across, 0), point(scene.along + scene.length + 1500, across, 0));
      if (line) ground.push(line);
    }
  }
  const rails: ProjectedSegment[][] = [];
  const ribbon: ProjectedPoint[][] = [];
  const framing: ProjectedPoint[] = [...runwaySurface];
  if (scene.approach && start[2] >= 30) {
    const path = landingApproachPath(scene);
    const distances = [0];
    for (let i = 1; i < path.points.length; i++) {
      const a = path.points[i - 1]!, b = path.points[i]!;
      distances.push(distances[i - 1]! + Math.hypot(b[0] - a[0], b[1] - a[1]));
    }
    // Frame the route ahead, not the enormous near-plane cross-section beneath
    // the aircraft. Interpolate this cut so crossing a sample never steps the zoom.
    const routeLength = distances.at(-1)!;
    const lookAhead = Math.max(250, Math.min(routeLength * .35, Math.max(routeLength * .2, (scene.speed ?? 0) * 3)));
    // The reference centerline remains 15 m over the threshold. Draw the floor
    // 15 m below it: an eye exactly on the reference must not see a coplanar,
    // edge-on pair of lines. The floor joins the runway, with metric width.
    const edges: Point3[][] = [];
    for (const side of [-runwayHalfWidth, runwayHalfWidth]) {
      const samples = path.points.map((p, i) => point(p[0] + path.normals[i]![0] * side, p[1] + path.normals[i]![1] * side, p[2] - 15));
      edges.push(samples);
      const rail: ProjectedSegment[] = [];
      for (let i = 1; i < samples.length; i++) {
        const piece = segment(samples[i - 1]!, samples[i]!);
        if (piece) rail.push(piece);
        if (distances[i]! >= lookAhead) {
          const a = samples[i - 1]!, b = samples[i]!;
          const t = Math.max(0, (lookAhead - distances[i - 1]!) / (distances[i]! - distances[i - 1]!));
          const visible = segment([a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t], b);
          if (visible) framing.push(...visible);
        }
      }
      rails.push(rail);
    }
    for (let i = 1; i < path.points.length; i++) {
      const quad = surface([edges[0]![i - 1]!, edges[1]![i - 1]!, edges[1]![i]!, edges[0]![i]!]);
      if (quad.length >= 3) ribbon.push(quad);
    }
  }
  const bearing = Math.atan2((start[0] + end[0]) / 2, (start[2] + end[2]) / 2);
  const project = (p: Point3): ProjectedPoint | null => p[2] >= 30 ? [p[0] / p[2], p[1] / p[2]] : null;
  return { runway, entrance, surface: runwaySurface, markings, ground, rails, ribbon, framing, bearing,
    threshold: project(start), end: project(end) };
}

/** Keep aircraft pitch inside a usable viewing cone around the forward runway.
 * Zoom alone cannot recover ground behind a pitched-up camera's near plane. */
export function landingRunwayCamera(scene: LandingRunwayScene) {
  const aircraftPitch = -(scene.pitch ?? 0);
  const depth = (scene.along + scene.length / 2) * Math.cos(scene.angle) - scene.across * Math.sin(scene.angle);
  if (depth <= near) return aircraftPitch;
  const depression = Math.atan2(scene.height, depth), margin = 20 * radians;
  return Math.max(depression - margin, Math.min(depression + margin, aircraftPitch));
}

/** One perspective viewport shared by the target, corridor and other runways. */
export function landingRunwayFrame(scene: LandingRunwayScene, width: number, height: number) {
  const pitch = landingRunwayCamera(scene), roll = scene.roll ?? 0;
  const projected = projectLandingRunway(scene, pitch, roll);
  const base = { pitch, roll, projected, focal: width / (2 * Math.tan(Math.PI / 6)), x: width / 2, y: height / 2 };
  if (projected.surface.length < 3) return base;
  const bounds = (points: readonly ProjectedPoint[]) => ({
    left: Math.min(...points.map(p => p[0])), right: Math.max(...points.map(p => p[0])),
    top: Math.min(...points.map(p => p[1])), bottom: Math.max(...points.map(p => p[1])),
  });
  const runway = bounds(projected.surface), route = bounds(projected.framing);
  // A large lateral offset can leave a long route at the entrance boundary.
  // Ease its framing influence out before the ribbon is withdrawn at 30 m;
  // the runway view must not jump when that immediate guidance flag changes.
  const progress = Math.max(0, Math.min(1, (scene.along - near) / 250));
  const routeWeight = progress * progress * (3 - 2 * progress);
  for (const edge of ["left", "right", "top", "bottom"] as const) {
    route[edge] = runway[edge] + (route[edge] - runway[edge]) * routeWeight;
  }
  // Reserve the caption and a quiet margin. All axes, surfaces and neighboring
  // runways still share one focal length: never stretch or widen screen geometry.
  const left = 12, right = width - 12, top = 28, bottom = height - 14;
  const availableWidth = right - left, availableHeight = bottom - top;
  const fit = (b: ReturnType<typeof bounds>) => Math.min(availableWidth / Math.max(.000001, b.right - b.left), availableHeight / Math.max(.000001, b.bottom - b.top));
  const runwaySpan = Math.max(runway.right - runway.left, runway.bottom - runway.top);
  const readable = Math.min(32, Math.min(availableWidth, availableHeight) * .3) / Math.max(.000001, runwaySpan);
  // A long/high return can make the near route dominate the frame. Keep the
  // runway readable and let that route continue naturally beyond the lower edge.
  const focal = Math.min(fit(runway) * .85, Math.max(readable, Math.min(base.focal, fit(route))));
  const origin = (start: number, end: number, targetStart: number, targetEnd: number, routeStart: number, routeEnd: number) =>
    Math.max(start - targetStart * focal, Math.min(end - targetEnd * focal, (start + end - (routeStart + routeEnd) * focal) / 2));
  return { ...base, focal,
    x: origin(left, right, runway.left, runway.right, route.left, route.right),
    y: origin(top, bottom, runway.top, runway.bottom, route.top, route.bottom) };
}

/** Display-only critical damping. Preserves a coherent 3D scene instead of
 * independently drifting endpoint pixels. Lifecycle/validity resets are owned by the caller. */
export class RunwaySceneMotion {
  #value: LandingRunwayScene | null = null;
  #target: LandingRunwayScene | null = null;
  #velocity = { along: 0, across: 0, height: 0, angle: 0, pitch: 0, roll: 0, speed: 0 };
  #at = 0;
  observe(next: LandingRunwayScene | null, at: number, reset: boolean): void {
    this.step(at);
    if (reset || !next || !this.#value) {
      this.#value = next;
      this.#velocity = { along: 0, across: 0, height: 0, angle: 0, pitch: 0, roll: 0, speed: 0 };
    }
    this.#target = next;
    this.#at = at;
  }
  step(at: number): LandingRunwayScene | null {
    const dt = Math.max(0, at - this.#at) / 1000, omega = 18, decay = Math.exp(-omega * dt);
    this.#at = Math.max(at, this.#at);
    if (!this.#value || !this.#target) return this.#value;
    const value = { ...this.#target };
    for (const axis of ["along", "across", "height", "angle", "pitch", "roll", "speed"] as const) {
      if (this.#target[axis] === undefined) continue;
      let offset = (this.#value[axis] ?? 0) - this.#target[axis]!;
      if (axis === "angle" || axis === "roll") offset = Math.atan2(Math.sin(offset), Math.cos(offset));
      const c = this.#velocity[axis] + omega * offset;
      const delta = (offset + c * dt) * decay;
      const velocity = (this.#velocity[axis] - omega * c * dt) * decay;
      const epsilon = axis === "angle" ? .00001 : .01;
      if (delta * offset <= 0 || Math.abs(delta) < epsilon && Math.abs(velocity) < epsilon * 10) {
        value[axis] = this.#target[axis]; this.#velocity[axis] = 0;
      } else { value[axis] = this.#target[axis]! + delta; this.#velocity[axis] = velocity; }
    }
    this.#value = value;
    return value;
  }
  isMoving(at: number): boolean {
    const value = this.step(at);
    return value !== null && this.#target !== null
      && (["along", "across", "height", "angle", "pitch", "roll", "speed"] as const).some(axis => value[axis] !== this.#target![axis]);
  }
}
