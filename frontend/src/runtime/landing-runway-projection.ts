import type { LandingGeometry, LandingSnapshot } from "./landing-assist";
import { aircraftCamera, aircraftCameraFrame, projectCameraSegment as segment, projectCameraSurface as surface } from "./aircraft-perspective";

export interface LandingRunwayScene {
  readonly terrainCorridor?: import("./landing-terrain-types").LandingTerrainCorridor | null;
  readonly along: number;
  readonly across: number;
  readonly height: number;
  readonly heightKnown?: boolean;
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
type RunwayDetailLod = "outline" | "sparse" | "full";
interface RunwayPatternMark {
  readonly kind: "threshold" | "centerline" | "aiming" | "touchdown" | "edge" | "rubber";
  /** Forward fractions [0,1] and lateral fractions [-1,1], never measured paint dimensions. */
  readonly rect: readonly [number, number, number, number];
}

// War Thunder paved-runway references are recorded in landing-assist.md.
// Counts and spacing are deliberately schematic; no airport-instance identity,
// designation number or real-world marking standard is inferred from them.
function runwayPattern(sparse: boolean): readonly RunwayPatternMark[] {
  const marks: RunwayPatternMark[] = [];
  const add = (kind: RunwayPatternMark["kind"], from: number, to: number, cross: number, half: number) => {
    marks.push(Object.freeze({ kind, rect: Object.freeze([from, cross - half, to, cross + half]) as RunwayPatternMark["rect"] }));
  };
  for (const end of [0, 1]) {
    const pair = (kind: RunwayPatternMark["kind"], from: number, to: number, cross: number, half: number) => {
      for (const side of [-1, 1]) add(kind, end ? 1 - to : from, end ? 1 - from : to, side * cross, half);
    };
    for (const cross of sparse ? [.35, .7] : [.25, .45, .65, .85]) pair("threshold", .014, .042, cross, .035);
    for (const from of sparse ? [.13] : [.13, .37]) pair("aiming", from, from + .025, .35, .075);
    if (!sparse) {
      for (const from of [.075, .21, .28]) pair("touchdown", from, from + .014, .65, .028);
      pair("rubber", .065, .24, .11, .035);
    }
  }
  const count = sparse ? 8 : 18;
  for (let i = 0; i < count; i++) {
    const from = .055 + (i + .225) * .89 / count;
    add("centerline", from, from + .89 / count * .55, 0, .018);
  }
  for (const side of [-1, 1]) add("edge", .005, .995, side * .96, .012);
  return Object.freeze(marks);
}
// Only two tiny immutable vector layouts are built; telemetry never rebuilds
// a texture or an unbounded collection keyed by runway position or dimensions.
const runwayPatterns = { full: runwayPattern(false), sparse: runwayPattern(true), outline: Object.freeze([]) };
export function landingRunwayPattern(lod: RunwayDetailLod): readonly RunwayPatternMark[] { return runwayPatterns[lod]; }
const radians = Math.PI / 180;

const viewLimit = 2.4;
/** Drop the part of a stroke that a near-plane clip would fling across the strip. */
function clipProjected(piece: ProjectedSegment | null): ProjectedSegment | null {
  if (!piece) return null;
  const [a, b] = piece;
  const dx = b[0] - a[0], dy = b[1] - a[1];
  let t0 = 0, t1 = 1;
  const bound = (limit: number, value: number, delta: number) => {
    if (Math.abs(delta) < 1e-8) return value <= limit;
    const t = (limit - value) / delta;
    if (delta > 0) {
      if (t < t0) return false;
      if (t < t1) t1 = t;
    } else if (t > t1) return false;
    else if (t > t0) t0 = t;
    return true;
  };
  if (!bound(viewLimit, a[0], dx) || !bound(viewLimit, -a[0], -dx) || !bound(viewLimit, a[1], dy) || !bound(viewLimit, -a[1], -dy) || t1 < t0) return null;
  return [[a[0] + dx * t0, a[1] + dy * t0], [a[0] + dx * t1, a[1] + dy * t1]];
}

/** Heading/attitude-referenced camera. Width is a definition reference or symbolic. */
export function landingRunwayScene(g: LandingGeometry | null | undefined, headingDeg: number, glideAngleDeg: number, attitude?: LandingSnapshot["attitude"]): LandingRunwayScene | null {
  if (!g || ![g.heightM ?? 0, g.thresholdDistanceM, g.crossTrackM, g.lengthM, g.courseDeg, headingDeg, glideAngleDeg].every(Number.isFinite)
    || g.lengthM <= 0) return null;
  return { along: g.thresholdDistanceM, across: -g.crossTrackM, height: g.heightM ?? 0, heightKnown: g.heightM !== null, length: g.lengthM,
    angle: ((g.courseDeg - headingDeg + 540) % 360 - 180) * radians,
    slope: g.heightM === null ? 0 : Math.tan(glideAngleDeg * radians), approach: g.heightM === null ? Math.hypot(g.thresholdDistanceM, g.crossTrackM) > 30 : g.heightM > 40 || g.thresholdDistanceM > 30 && g.stage !== "runway" && g.stage !== "past-runway",
    width: Number.isFinite(g.referenceWidthM) && g.referenceWidthM! > 0 ? g.referenceWidthM : 90,
    pitch: g.heightM === null ? 0 : (attitude?.pitchDeg ?? 0) * radians, roll: g.heightM === null ? 0 : (attitude?.rollDeg ?? 0) * radians, speed: attitude?.tasMps ?? 0 };
}

/** A heading-tangent geometric intercept, followed by an aligned final leg.
 * Coordinates are runway-forward, runway-right and height above its datum.
 * This is a visual route reference, not a turn-performance or clearance solution. */
export function landingApproachPath(scene: LandingRunwayScene) {
  const finalLength = Math.min(1500, scene.along > 30 ? scene.along * .25 : Math.max(300, Math.hypot(scene.along, scene.across) * .25));
  const gate: Point2 = [scene.along - finalLength, scene.across];
  const reach = Math.hypot(gate[0], gate[1]);
  // Airspeed sets an eight-second visual lead, bounded by the actual intercept
  // distance. It changes route smoothness, never apparent perspective width.
  const lead = scene.speed && scene.speed > 0 ? Math.min(reach * .45, Math.max(reach * .15, scene.speed * 8)) : reach * .35;
  const pitch = scene.pitch ?? -Math.atan(scene.slope);
  const handle = lead * Math.cos(pitch);
  const controls: readonly [Point2, Point2, Point2, Point2] = [
    [0, 0],
    [Math.cos(scene.angle) * handle, -Math.sin(scene.angle) * handle],
    [gate[0] - lead, gate[1]],
    gate,
  ];
  const points: Point3[] = [];
  const normals: (readonly [number, number])[] = [];
  // Collinear, opposite-facing cubic handles otherwise produce a cusp (fly
  // backwards, then reverse instantly). A smooth lateral lobe preserves both
  // endpoint tangents and provides a deterministic right-hand return reference.
  const opposition = Math.max(0, (-Math.cos(scene.angle) - .2) / .8);
  const turnOffset = reach * .45 * opposition * opposition * Math.exp(-((scene.across / Math.max(1, reach) / .35) ** 2));
  for (let i = 0; i <= 48; i++) {
    // More samples near the player keep the wing-to-world transition smooth.
    const t = (i / 48) ** 2, u = 1 - t;
    const [a, b, c, d] = controls;
    const coordinate = (axis: 0 | 1) => u ** 3 * a[axis] + 3 * u * u * t * b[axis]
      + 3 * u * t * t * c[axis] + t ** 3 * d[axis];
    points.push([coordinate(0), coordinate(1) + turnOffset * 16 * t * t * u * u, 0]);
    const along = 3 * u * u * (b[0] - a[0]) + 6 * u * t * (c[0] - b[0]) + 3 * t * t * (d[0] - c[0]);
    const across = 3 * u * u * (b[1] - a[1]) + 6 * u * t * (c[1] - b[1]) + 3 * t * t * (d[1] - c[1])
      + turnOffset * 32 * t * u * (1 - 2 * t);
    const length = Math.hypot(along, across);
    normals.push(length > .001 ? [-across / length, along / length] : [0, 1]);
  }
  points.push([scene.along, scene.across, scene.heightKnown === false ? 0 : 15]); normals.push([0, 1]);
  // Keep the final leg on the selected glide reference; the intercept is a
  // visual connection from the aircraft, not a replacement for glide deviation.
  for (let i = points.length - 2; i >= 0; i--) {
    const p = points[i]!, next = points[i + 1]!;
    points[i] = [p[0], p[1], next[2] + Math.hypot(next[0] - p[0], next[1] - p[1]) * scene.slope];
  }
  const startOffset = scene.height - points[0]![2];
  // Resolve the bounded spatial lead into horizontal/vertical components.
  // Unlike tan(pitch), this remains finite through vertical flight attitudes.
  const tangentOffset = 3 * lead * (Math.sin(pitch) + Math.cos(pitch) * scene.slope);
  for (let i = 0; i < 48; i++) {
    const t = (i / 48) ** 2, u = 1 - t, p = points[i]!;
    points[i] = [p[0], p[1], p[2] + u * u * (1 + 2 * t) * startOffset + t * u * u * tangentOffset];
  }
  return { controls, points, normals };
}

/** Keep the verified horizontal footprint fixed in the world. Only its vertical
 * intercept follows the same smoothed height/pitch as the camera; never blend a
 * new terrain floor downward or move rails onto unmeasured ground. */
export function landingTerrainPath(scene: LandingRunwayScene) {
  const terrain = scene.terrainCorridor!;
  const live = landingApproachPath({ ...terrain.referenceScene, along:scene.along, across:scene.across,
    height: scene.height, pitch: scene.pitch, speed:scene.speed });
  return { normals: terrain.normals, points: terrain.points.map((p, i): Point3 => {
    const x = p[0] + scene.along - terrain.along, y = p[1] + scene.across - terrain.across;
    let nearest = Infinity, height = scene.height;
    // Sample the live vertical curve at this retained world position. Matching
    // old array indices would anchor the intercept behind a moving aircraft and
    // still jump every batch. Only height is taken from the live curve.
    for (let j=1;j<live.points.length;j++) {
      const a=live.points[j-1]!, b=live.points[j]!, dx=b[0]-a[0], dy=b[1]-a[1];
      const t=Math.max(0,Math.min(1,((x-a[0])*dx+(y-a[1])*dy)/Math.max(1e-9,dx*dx+dy*dy)));
      const distance=(x-a[0]-dx*t)**2+(y-a[1]-dy*t)**2;
      if (distance<nearest) {nearest=distance;height=a[2]+(b[2]-a[2])*t;}
    }
    return [x,y,Math.max(terrain.floorsM[i]!,height)];
  }) };
}

export function projectLandingRunway(scene: LandingRunwayScene, cameraPitch = -(scene.pitch ?? 0), cameraRoll = scene.roll ?? 0, retreat = 0, yaw = 0,
  options: { simplified?: boolean; floorDrop?: number; pixelScale?: number; path?: ReturnType<typeof landingApproachPath> } = {}) {
  const runwayHalfWidth = (scene.width ?? 90) / 2;
  const sin = Math.sin(scene.angle + yaw), cos = Math.cos(scene.angle + yaw);
  const camera = aircraftCamera(cameraPitch, cameraRoll);
  // A one-metre altitude twitch at field elevation otherwise flips the pavement
  // between a surface and an edge-on line. The displayed height is unchanged.
  const eye = scene.heightKnown === false ? 0 : Math.max(scene.height, 12);
  const point = (along: number, across: number, heightAboveRunway: number): Point3 => {
    const depth = along * cos - across * sin + retreat, down = eye - heightAboveRunway;
    return camera(along * sin + across * cos, down, depth);
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
  const scale = options.pixelScale ?? 0;
  const projectedWidthPx = runwaySurface.length ? (Math.max(...runwaySurface.map(p => p[0])) - Math.min(...runwaySurface.map(p => p[0]))) * scale : 0;
  const detailLod: RunwayDetailLod = scene.heightKnown === false || projectedWidthPx < 8 ? "outline"
    : options.simplified || projectedWidthPx < 24 ? "sparse" : "full";
  const details: { readonly kind: RunwayPatternMark["kind"]; readonly points: readonly ProjectedPoint[] }[] = [];
  for (const mark of landingRunwayPattern(detailLod)) {
    const [from, left, to, right] = mark.rect;
    const corners = surface([
      point(scene.along + from * scene.length, scene.across + left * runwayHalfWidth, 0),
      point(scene.along + from * scene.length, scene.across + right * runwayHalfWidth, 0),
      point(scene.along + to * scene.length, scene.across + right * runwayHalfWidth, 0),
      point(scene.along + to * scene.length, scene.across + left * runwayHalfWidth, 0),
    ]);
    let twiceArea = 0;
    for (let i = 0; i < corners.length; i++) {
      const a = corners[i]!, b = corners[(i + 1) % corners.length]!;
      twiceArea += a[0] * b[1] - a[1] * b[0];
    }
    // Cull sub-pixel marks instead of fattening their geometry or strobing dots.
    if (corners.length >= 3 && Math.abs(twiceArea) * scale * scale >= 1) details.push({ kind: mark.kind, points: corners });
  }
  const ground: ProjectedSegment[] = [];
  let groundSurface: ProjectedPoint[] = [];
  if (scene.terrainCorridor === undefined && scene.heightKnown !== false && scene.height >= 0 && !options.simplified) {
    const ahead = Math.max(120, Math.min(scene.along * .2, 1800));
    const half = Math.min(Math.max(1600, (scene.width ?? 90) * 18), 4500);
    for (const along of [ahead, scene.along + scene.length + 1200]) {
      const line = segment(point(along, -half, 0), point(along, half, 0));
      if (line) ground.push(line);
    }
    for (const across of [-half, half]) {
      const line = segment(point(ahead, across, 0), point(scene.along + scene.length + 1200, across, 0));
      if (line) ground.push(line);
    }
    // Only the ground ahead of the aircraft. Points beside the camera wrap
    // around the view and paint over the sky.
    groundSurface = surface([
      point(ahead, -half, 0), point(ahead, half, 0),
      point(scene.along + scene.length + 1200, half, 0), point(scene.along + scene.length + 1200, -half, 0),
    ]);
  }
  const rails: ProjectedSegment[][] = [];
  const ribbon: ProjectedPoint[][] = [];
  if (scene.approach && scene.terrainCorridor !== null) {
    const terrain = scene.terrainCorridor;
    const path = terrain ? landingTerrainPath(scene)
      : options.path ?? landingApproachPath(scene);
    const distances = [0];
    for (let i = 1; i < path.points.length; i++) {
      const a = path.points[i - 1]!, b = path.points[i]!;
      distances.push(distances[i - 1]! + Math.hypot(b[0] - a[0], b[1] - a[1]));
    }
    const routeLength = distances.at(-1)!;
    const handoff = Math.min(routeLength, Math.max(300, (scene.speed ?? 0) * 8));
    // The near cross-section follows the player's wings, including during a
    // bank. It blends into the world-aligned runway corridor ahead. Only this
    // display floor changes; the reference path and glide deviation do not.
    const edges: Point3[][] = [];
    for (const side of [-runwayHalfWidth, runwayHalfWidth]) {
      const samples = path.points.map((p, i) => {
        const nearDrop = terrain ? Math.min(15, options.floorDrop ?? 15) : options.floorDrop ?? 15;
        const farDrop = scene.heightKnown === false ? nearDrop : 15;
        const world = point(p[0] + path.normals[i]![0] * side, p[1] + path.normals[i]![1] * side, p[2] - farDrop);
        if (options.floorDrop === undefined) return world;
        const center = point(...p), wing = [center[0] + side, center[1] + nearDrop, center[2]];
        const t = Math.min(1, distances[i]! / Math.max(1, handoff)), weight = t * t * (3 - 2 * t);
        const blend = (axis: 0 | 1 | 2) => wing[axis]! + (world[axis] - wing[axis]!) * weight;
        const blended: [number,number,number] = [blend(0), blend(1), blend(2)];
        if (terrain) {
          // Preserve wing-following motion without allowing bank or a tall
          // window's display drop to lower either rail beneath the terrain floor.
          const up = camera(0,-1,0);
          const below = Math.min(0, (blended[0]-world[0])*up[0] + (blended[1]-world[1])*up[1] + (blended[2]-world[2])*up[2]);
          for (const axis of [0,1,2] as const) blended[axis] -= below * up[axis];
        }
        return blended;
      });
      edges.push(samples);
      const rail: ProjectedSegment[] = [];
      for (let i = 1; i < samples.length; i++) {
        const piece = clipProjected(segment(samples[i - 1]!, samples[i]!));
        if (piece) rail.push(piece);
      }
      rails.push(rail);
    }
    for (let i = 1; !options.simplified && i < path.points.length; i++) {
      const quad = surface([edges[0]![i - 1]!, edges[1]![i - 1]!, edges[1]![i]!, edges[0]![i]!]);
      if (quad.length >= 3) ribbon.push(quad);
    }
  }
  const bearing = Math.atan2((start[0] + end[0]) / 2, (start[2] + end[2]) / 2);
  const project = (p: Point3): ProjectedPoint | null => p[2] >= 30 ? [p[0] / p[2], p[1] / p[2]] : null;
  return { runway, entrance, surface: runwaySurface, markings, details, detailLod, projectedWidthPx, ground, groundSurface, rails, ribbon, bearing,
    threshold: project(start), end: project(end) };
}

/** The player is the camera; the runway must not rotate or zoom it. */
export function landingRunwayCamera(scene: LandingRunwayScene) {
  return scene.heightKnown === false ? 0 : -(scene.pitch ?? 0);
}

/** Shared central perspective viewport, excluding IAS and fuel columns. */
export function landingPerspectiveViewport(width: number) {
  const left = Math.max(54, Math.min(125, width * .18)) + Math.max(8, Math.min(20, width * .025));
  return { left, width: width - left * 2 };
}

/** A fixed forward perspective: the window sides are the near wing-tip anchors.
 * The ribbon floor is a display surface below the reference path, not a second
 * glide instruction. Unknown elevation has only horizontal bearing/depth. */
export function landingRunwayFrame(scene: LandingRunwayScene, width: number, height: number, simplified = false) {
  const pitch = landingRunwayCamera(scene), roll = scene.heightKnown === false ? 0 : scene.roll ?? 0;
  const { focal, x, y } = aircraftCameraFrame(width, height);
  // At the near edge, half the corridor occupies half the window. One focal
  // length then makes every farther cross-section smaller with actual depth.
  const floorDrop = Math.max(1, (height - 6 - y) * (scene.width ?? 90) / width);
  const projected = projectLandingRunway(scene, pitch, roll, 0, 0, { simplified, floorDrop, pixelScale: focal });
  return { pitch, roll, retreat: 0, yaw: 0, projected, routeWeight: scene.approach ? 1 : 0,
    focal, x, y };
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
    const dt = Math.max(0, at - this.#at) / 1000;
    // Pitch and roll follow the flight path, whose vertical speed jitters between
    // 8111 samples. A slower response keeps the runway from strobing in the strip.
    const omegaFor = (axis: string) => axis === "pitch" || axis === "roll" ? 2.2 : 18;
    this.#at = Math.max(at, this.#at);
    if (!this.#value || !this.#target) return this.#value;
    const value = { ...this.#target };
    for (const axis of ["along", "across", "height", "angle", "pitch", "roll", "speed"] as const) {
      if (this.#target[axis] === undefined) continue;
      let offset = (this.#value[axis] ?? 0) - this.#target[axis]!;
      if (axis === "angle" || axis === "roll") offset = Math.atan2(Math.sin(offset), Math.cos(offset));
      const omega = omegaFor(axis), decay = Math.exp(-omega * dt);
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
