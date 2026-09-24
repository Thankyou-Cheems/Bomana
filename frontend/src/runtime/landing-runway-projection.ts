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
    const t = i / 48, u = 1 - t, p = points[i]!;
    points[i] = [p[0], p[1], p[2] + u * u * (1 + 2 * t) * startOffset + t * u * u * tangentOffset];
  }
  return { controls, points, normals };
}

export function projectLandingRunway(scene: LandingRunwayScene, cameraPitch = -(scene.pitch ?? 0), cameraRoll = scene.roll ?? 0, retreat = 0, yaw = 0) {
  const runwayHalfWidth = (scene.width ?? 90) / 2;
  const sin = Math.sin(scene.angle + yaw), cos = Math.cos(scene.angle + yaw);
  const cp = Math.cos(cameraPitch), sp = Math.sin(cameraPitch);
  // A one-metre altitude twitch at field elevation otherwise flips the pavement
  // between a surface and an edge-on line. The displayed height is unchanged.
  const eye = scene.height >= 0 ? Math.max(scene.height, 12) : scene.height;
  const point = (along: number, across: number, heightAboveRunway: number): Point3 => {
    const depth = along * cos - across * sin + retreat, down = eye - heightAboveRunway;
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
  let groundSurface: ProjectedPoint[] = [];
  if (scene.height >= 0) {
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
    const lookAhead = Math.max(routeLength * .6, routeLength - Math.max(3000, scene.length * 2));
    // The reference centerline remains 15 m over the threshold. Draw the floor
    // 15 m below it: an eye exactly on the reference must not see a coplanar,
    // edge-on pair of lines. The floor joins the runway, with metric width.
    const edges: Point3[][] = [];
    for (const side of [-runwayHalfWidth, runwayHalfWidth]) {
      const samples = path.points.map((p, i) => point(p[0] + path.normals[i]![0] * side, p[1] + path.normals[i]![1] * side, p[2] - 15));
      edges.push(samples);
      const rail: ProjectedSegment[] = [];
      for (let i = 1; i < samples.length; i++) {
        const piece = clipProjected(segment(samples[i - 1]!, samples[i]!));
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
  return { runway, entrance, surface: runwaySurface, markings, ground, groundSurface, rails, ribbon, framing, bearing,
    threshold: project(start), end: project(end) };
}

/** Keep aircraft pitch inside a usable viewing cone around the forward runway.
 * Zoom alone cannot recover ground behind a pitched-up camera's near plane. */
export function landingRunwayCamera(scene: LandingRunwayScene, retreat = 0) {
  const aircraftPitch = -(scene.pitch ?? 0);
  const depth = (scene.along + scene.length / 2) * Math.cos(scene.angle) - scene.across * Math.sin(scene.angle);
  if (depth + retreat <= near) return aircraftPitch;
  const depression = Math.atan2(scene.height, depth + retreat), margin = 20 * radians;
  return Math.max(depression - margin, Math.min(depression + margin, aircraftPitch));
}

/** One perspective viewport shared by the target, corridor and other runways. */
export function landingRunwayFrame(scene: LandingRunwayScene, width: number, height: number) {
  const forward = (scene.along + scene.length / 2) * Math.cos(scene.angle) - scene.across * Math.sin(scene.angle);
  const high = Math.max(0, Math.min(1, (scene.height / Math.max(scene.length, Math.hypot(scene.along, scene.across)) - .08) / .25));
  const forwardFraction = Math.max(0, Math.min(1, (forward - near) / Math.max(500, scene.length)));
  const forwardWeight = forwardFraction * forwardFraction * (3 - 2 * forwardFraction);
  const range = Math.hypot(scene.along, scene.across);
  const steep = Math.max(0, Math.min(1, (Math.abs(scene.height) / Math.max(800, range) - .12) / .35));
  const aspect = Math.max(0, Math.min(1, (width / height - 1) / 2));
  // Far returns stay nearly behind the aircraft. A steep, close return may
  // look slightly aside and aft so the pavement is a surface, not a vertical hairline.
  const yaw = (10 + 22 * steep) * radians * high * aspect * forwardWeight;
  const cameraScene = { ...scene, angle: scene.angle + yaw };
  const depth = (scene.along + scene.length / 2) * Math.cos(cameraScene.angle) - scene.across * Math.sin(cameraScene.angle);
  const retreat = Math.min(Math.max(0, Math.abs(scene.height) / Math.tan((14 + 10 * steep) * radians) - depth),
    range * (.2 + steep * 1.6)) * forwardWeight;
  const pitch = landingRunwayCamera(cameraScene, retreat), roll = scene.roll ?? 0;
  const projected = projectLandingRunway(scene, pitch, roll, retreat, yaw);
  const base = { pitch, roll, retreat, yaw, projected, focal: width / (2 * Math.tan(Math.PI / 6)), x: width / 2, y: height / 2 };
  if (projected.surface.length < 3) return base;
  const bounds = (points: readonly ProjectedPoint[]) => ({
    left: Math.min(...points.map(p => p[0])), right: Math.max(...points.map(p => p[0])),
    top: Math.min(...points.map(p => p[1])), bottom: Math.max(...points.map(p => p[1])),
  });
  const runway = bounds(projected.surface);
  const runwaySpan = Math.max(.000001, runway.bottom - runway.top);
  const widthSpan = Math.max(.000001, runway.right - runway.left);
  // Rails run from the aircraft to the threshold. The joining curve is the suffix.
  // Ignore a vertex the near plane has thrown far outside the view; it must not set the zoom.
  const joined: ProjectedPoint[] = [];
  for (const rail of projected.rails) for (const piece of rail.slice(-16)) {
    if ([piece[0], piece[1]].some((point) => Math.abs(point[0]) > 1.2 || Math.abs(point[1]) > 1.2)) continue;
    joined.push(piece[0], piece[1]);
  }
  const picture = bounds(joined.length ? [...projected.surface, ...joined] : projected.surface);
  // Ease the path out of the frame before the ribbon disappears at 30 m.
  const progress = Math.max(0, Math.min(1, (scene.along - near) / 250));
  const routeWeight = progress * progress * (3 - 2 * progress);
  for (const edge of ["left", "right", "top", "bottom"] as const) {
    picture[edge] = runway[edge] + (picture[edge] - runway[edge]) * routeWeight;
  }
  // Reserve the caption and a quiet margin. All axes, surfaces and neighboring
  // runways still share one focal length: never stretch or widen screen geometry.
  const left = 12, right = width - 12, top = 28, bottom = height - 14;
  const availableWidth = right - left, availableHeight = bottom - top;
  const fit = (b: ReturnType<typeof bounds>) => Math.min(availableWidth / Math.max(.000001, b.right - b.left), availableHeight / Math.max(.000001, b.bottom - b.top));
  const naturalFocal = width / (2 * Math.tan(Math.PI / 6));
  const handoff = 1800;
  // Magnification grows almost in proportion to distance past 1.8 km, so the
  // far pavement stays recognizable and still gets smaller as it gets farther.
  // At and inside the handoff the focal is cockpit perspective.
  const gain = range <= handoff ? 1 : Math.pow(range / handoff, .9);
  const contained = Math.min(fit(runway) * .92, availableHeight * .86 / runwaySpan, availableWidth * .78 / widthSpan);
  const boosted = Math.min(contained, naturalFocal * gain);
  const together = fit(picture) * .92;
  const pathFocal = Math.min(boosted, Math.max(together, boosted * .58));
  let focal = boosted + (pathFocal - boosted) * routeWeight;
  const shortNdc = Math.min(widthSpan, runwaySpan);
  const aligned = Math.abs(scene.angle) < 25 * radians && Math.abs(scene.roll ?? 0) < 12 * radians;
  if (aligned && range > handoff && shortNdc > 0.000001) {
    const readableFocal = Math.min(contained, 26 / shortNdc);
    const blend = Math.min(1, (range - handoff) / 1600);
    if (readableFocal > focal) focal += (readableFocal - focal) * blend;
  }
  const origin = (start: number, end: number, targetStart: number, targetEnd: number, routeStart: number, routeEnd: number) =>
    Math.max(start - targetStart * focal, Math.min(end - targetEnd * focal, (start + end - (routeStart + routeEnd) * focal) / 2));
  return { ...base, focal,
    x: origin(left, right, runway.left, runway.right, picture.left, picture.right),
    y: origin(top, bottom, runway.top, runway.bottom, picture.top, picture.bottom) };
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
