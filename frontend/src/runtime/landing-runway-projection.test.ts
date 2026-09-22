import { expect, it } from "vitest";
import { landingGeometry } from "./landing-assist";
import { landingApproachPath, landingRunwayScene, landingRunwayCamera, landingRunwayFrame, projectLandingRunway, RunwaySceneMotion } from "./landing-runway-projection";

const input = { player: { x: .53, y: .53 }, scale: [10000, 100000] as const,
  start: [.5, .5] as const, end: [.5, .48] as const, altitudeM: 400, elevationM: 100, glideAngleDeg: 3, velocity: [0, -100] as const };
const geometry = landingGeometry(input);
const scene = landingRunwayScene(geometry, 0, 3)!;

it.each([-90, 90])("uses a finite spatial lead at %d degrees of pitch", pitch => {
  const current = { ...scene, height: 2500, pitch: pitch * Math.PI / 180 };
  const path = landingApproachPath(current);
  expect(path.points[0]![2]).toBeCloseTo(2500);
  expect(path.points.at(-1)![2]).toBe(15);
  expect(Math.max(...path.points.map(p => Math.abs(p[2])))).toBeLessThan(5500);
});

it.each([2000, 2500, 3000])("keeps a %dm high approach readable and enlarges the runway as distance closes", altitude => {
  const sizes: number[] = [];
  for (const along of [30000, 12000, 6000, 3000]) {
    const frame = landingRunwayFrame({ ...scene, across: 500, along, height: altitude, pitch: 0, roll: 0 }, 1200, 150);
    const pixel = ([x, y]: readonly number[]) => [frame.x + x! * frame.focal, frame.y + y! * frame.focal];
    const corners = frame.projected.surface.map(pixel);
    const runwayWidth = Math.hypot(corners[1]![0]! - corners[0]![0]!, corners[1]![1]! - corners[0]![1]!);
    const visibleRailPoints = frame.projected.rails.flat(2).map(pixel)
      .filter(([x, y]) => x! >= 8 && x! <= 1192 && y! >= 25 && y! <= 142);
    const railHeight = visibleRailPoints.length ? Math.max(...visibleRailPoints.map(p => p[1]!)) - Math.min(...visibleRailPoints.map(p => p[1]!)) : 0;
    sizes.push(runwayWidth);
    expect.soft(runwayWidth).toBeGreaterThanOrEqual(8);
    expect.soft(railHeight).toBeGreaterThan(40);
    for (const [x, y] of frame.projected.framing.map(pixel)) {
      expect(x).toBeGreaterThanOrEqual(8); expect(x).toBeLessThanOrEqual(1192);
      expect(y).toBeGreaterThanOrEqual(25); expect(y).toBeLessThanOrEqual(142);
    }
  }
  expect(sizes[3]!).toBeGreaterThan(sizes[0]! * 1.5);
});

it.each([
  [1200, 150, 3000, 3000, 0, 0],
  [1200, 150, 3000, 800, 25, 40],
  [220, 210, 800, 1400, 35, 65],
  [1200, 150, 30000, 2500, 0, 0],
  [220, 140, 500, 20, -35, -70],
  [1200, 150, 1500, -40, 15, -20],
  [1200, 150, 80000, 10000, 45, 80],
])("fits the runway into %dx%d at distance %dm / height %dm / pitch %d / bank %d", (width, height, along, altitude, pitch, roll) => {
  const frame = landingRunwayFrame({ ...scene, across: 0, along, height: altitude, pitch: pitch * Math.PI / 180, roll: roll * Math.PI / 180 }, width, height);
  expect(frame.projected.surface.length).toBeGreaterThanOrEqual(3);
  const pixels = frame.projected.surface.map(([x, y]) => [frame.x + x * frame.focal, frame.y + y * frame.focal]);
  for (const [x, y] of pixels) {
    expect(x).toBeGreaterThanOrEqual(8); expect(x).toBeLessThanOrEqual(width - 8);
    expect(y).toBeGreaterThanOrEqual(25); expect(y).toBeLessThanOrEqual(height - 8);
  }
  expect(Math.max(...pixels.map(p => p[1]!)) - Math.min(...pixels.map(p => p[1]!))
    + Math.max(...pixels.map(p => p[0]!)) - Math.min(...pixels.map(p => p[0]!))).toBeGreaterThan(20);
});

it("retains aircraft pitch inside the forward viewing cone and uses definition width", () => {
  const s = landingRunwayScene({ ...geometry, crossTrackM: 0, referenceWidthM: 140 }, 0, 3)!;
  const pitch = landingRunwayCamera(s), result = projectLandingRunway(s, pitch);
  expect(pitch).toBeCloseTo(0);
  expect(result.threshold![1]).toBeGreaterThan(0);
  expect(result.end![1]).toBeGreaterThan(0);
  expect(result.surface[1]![0] - result.surface[0]![0]).toBeGreaterThan(result.surface[2]![0] - result.surface[3]![0]);
  expect(projectLandingRunway(s).surface[1]![0]).toBeCloseTo(70 / 3000);
  expect(landingRunwayCamera({ ...s, angle: Math.PI })).toBeCloseTo(0);
  expect(landingRunwayCamera({ ...s, height: 3000, pitch: .5 })).toBeGreaterThan(0);
});

it("fits with one uniform perspective scale and keeps the corridor joined to the runway", () => {
  const frame = landingRunwayFrame({ ...scene, across: 0, height: 1400, pitch: .3, roll: .5 }, 1200, 150);
  const pixel = ([x, y]: readonly number[]) => [frame.x + x! * frame.focal, frame.y + y! * frame.focal];
  const distance = (a: readonly number[], b: readonly number[]) => Math.hypot(a[0]! - b[0]!, a[1]! - b[1]!);
  const surface = frame.projected.surface;
  const nearWidth = distance(surface[0]!, surface[1]!), farWidth = distance(surface[2]!, surface[3]!);
  expect(nearWidth).toBeGreaterThan(farWidth);
  expect(distance(pixel(surface[0]!), pixel(surface[1]!)) / distance(pixel(surface[2]!), pixel(surface[3]!))).toBeCloseTo(nearWidth / farWidth);
  expect(frame.projected.rails[0]!.at(-1)![1]).toEqual(surface[0]);
  expect(frame.projected.rails[1]!.at(-1)![1]).toEqual(surface[1]);
});

it("keeps adaptive framing continuous as the aircraft moves through route samples", () => {
  const initial = { ...scene, across: 700, speed: 120, height: 1600, pitch: .25, roll: .4 };
  let previous = landingRunwayFrame(initial, 1200, 150);
  for (let i = 1; i <= 200; i++) {
    const next = landingRunwayFrame({ ...initial, along: initial.along - i, height: initial.height - i * .1 }, 1200, 150);
    for (let j = 0; j < 4; j++) {
      const a = previous.projected.surface[j]!, b = next.projected.surface[j]!;
      expect(Math.hypot(previous.x + a[0] * previous.focal - next.x - b[0] * next.focal,
        previous.y + a[1] * previous.focal - next.y - b[1] * next.focal)).toBeLessThan(1);
    }
    previous = next;
  }
});

it("keeps a rearward runway behind the view and a passed entrance finite", () => {
  const rear = landingRunwayFrame({ ...scene, angle: Math.PI }, 1200, 150);
  expect(rear.projected.surface).toHaveLength(0);
  expect(rear.projected.rails).toHaveLength(0);
  const past = landingRunwayFrame({ ...scene, along: -200, height: 5, approach: false }, 220, 150);
  expect(past.projected.rails).toHaveLength(0);
  expect([past.focal, past.x, past.y, ...past.projected.surface.flat()].every(Number.isFinite)).toBe(true);
});

it("does not jump when the approach ribbon withdraws at the entrance boundary during an oblique pass", () => {
  const pass = { ...scene, across: 1000, angle: -Math.PI / 4, height: 300 };
  const before = landingRunwayFrame({ ...pass, along: 30.01, approach: true }, 1200, 150);
  const after = landingRunwayFrame({ ...pass, along: 29.99, approach: false }, 1200, 150);
  expect(Math.abs(before.focal - after.focal)).toBeLessThan(1);
  expect(Math.hypot(before.x - after.x, before.y - after.y)).toBeLessThan(1);
});

it("shows a runway plane with a wider near edge and narrower far edge", () => {
  const result = projectLandingRunway({ ...scene, across: 0, height: 230 });
  expect(result).toMatchObject({ surface: [
    [expect.closeTo(-45 / 3000, 6), expect.closeTo(230 / 3000, 6)],
    [expect.closeTo(45 / 3000, 6), expect.closeTo(230 / 3000, 6)],
    [expect.closeTo(45 / 5000, 6), expect.closeTo(230 / 5000, 6)],
    [expect.closeTo(-45 / 5000, 6), expect.closeTo(230 / 5000, 6)],
  ] });
});

it("projects both endpoints from metric position and height without enlarging the runway", () => {
  const result = projectLandingRunway(scene);
  expect(result.threshold![0]).toBeCloseTo(-.1);
  expect(result.threshold![1]).toBeCloseTo(.1);
  expect(result.end![0]).toBeCloseTo(-.06);
  expect(result.end![1]).toBeCloseTo(.06);
  expect(projectLandingRunway({ ...scene, height: 600 }).threshold![1]).toBeCloseTo(.2);
  expect(projectLandingRunway({ ...scene, along: 30000 }).threshold![1]).toBeCloseTo(.01);
  const mirrored = projectLandingRunway({ ...scene, across: -scene.across });
  expect(mirrored.threshold![0]).toBeCloseTo(.1);
  expect(mirrored.threshold![1]).toBeCloseTo(.1);
});

it("swaps the selected entrance without changing the endpoints' physical projection", () => {
  const reversed = landingRunwayScene(landingGeometry({ ...input, start: input.end, end: input.start }), 0, 3)!;
  const before = projectLandingRunway(scene), after = projectLandingRunway(reversed);
  expect(after.threshold![0]).toBeCloseTo(before.end![0]);
  expect(after.threshold![1]).toBeCloseTo(before.end![1]);
  expect(after.end![0]).toBeCloseTo(before.threshold![0]);
  expect(after.end![1]).toBeCloseTo(before.threshold![1]);
  expect(after.rails).toHaveLength(0);
});

it("draws two perspective floor edges 15 m below the reference, joining the runway", () => {
  const projection = projectLandingRunway(scene);
  expect(projection.rails).toHaveLength(2);
  const left = projection.rails[0]!.at(-1)!, right = projection.rails[1]!.at(-1)!;
  expect(left[1][1]).toBeCloseTo(scene.height / scene.along);
  expect(left[1][0]).toBeLessThan(projection.threshold![0]);
  expect(right[1][0]).toBeGreaterThan(projection.threshold![0]);
  const steeper = projectLandingRunway({ ...scene, slope: Math.tan(6 * Math.PI / 180) });
  expect(steeper.rails[0]!.at(-1)![0][1]).toBeLessThan(left[0][1]);
});

it("retains visible near-wide far-narrow perspective even exactly on the glide reference", () => {
  const current = { ...scene, across: 0, angle: 0, height: 15 + scene.along * scene.slope, pitch: -Math.atan(scene.slope) };
  const result = projectLandingRunway(current);
  const left = result.rails[0]!, right = result.rails[1]!;
  const nearLeft = left[0]![0], nearRight = right[0]![0];
  const farLeft = left.at(-1)![1], farRight = right.at(-1)![1];
  expect(nearRight[0] - nearLeft[0]).toBeGreaterThan(20 * (farRight[0] - farLeft[0]));
  expect(nearLeft[1]).toBeGreaterThan(farLeft[1] + .2);
  expect(result.ribbon.length).toBeGreaterThan(1);
  const banked = projectLandingRunway({ ...current, roll: Math.PI / 4 });
  expect(banked.entrance![1][1]).toBeLessThan(banked.entrance![0][1]);
  const norm = (p: readonly number[]) => Math.hypot(...p);
  expect(norm(banked.threshold!)).toBeCloseTo(norm(result.threshold!));
  expect(landingRunwayCamera({ ...current, along: 80000, height: 10000 })).toBe(landingRunwayCamera(current));
  expect(landingApproachPath({ ...current, speed: 80 }).controls[1][0])
    .toBeLessThan(landingApproachPath({ ...current, speed: 250 }).controls[1][0]);
});

it("starts along the current heading, curves to the runway axis and joins the chosen final slope tangentially", () => {
  for (const angle of [-75, -30, 0, 30, 75]) {
    const current = { ...scene, angle: angle * Math.PI / 180 };
    const { controls: [a, b, c, gate], points } = landingApproachPath(current);
    expect(a).toEqual([0, 0]);
    expect(Math.atan2(-(b[1] - a[1]), b[0] - a[0])).toBeCloseTo(current.angle);
    expect(gate[1] - c[1]).toBe(0);
    expect(points.at(-1)).toEqual([scene.along, scene.across, 15]);
    expect(points[0]![2]).toBeCloseTo(scene.height);
    const before = points.at(-2)!, after = points.at(-1)!;
    expect((before[2] - after[2]) / Math.hypot(after[0] - before[0], after[1] - before[1])).toBeCloseTo(scene.slope);
    expect(points.flat().every(Number.isFinite)).toBe(true);
  }
  const left = landingApproachPath({ ...scene, angle: -.6 }).points[15]!;
  const right = landingApproachPath({ ...scene, angle: .6 }).points[15]!;
  expect(left[1]).toBeGreaterThan(right[1]);
  const aligned = landingApproachPath({ ...scene, angle: 0, across: 0 });
  expect(aligned.points.every(point => point[1] === 0)).toBe(true);
  const high = landingApproachPath({ ...scene, height: 2500 }).points;
  expect(high[0]![2]).toBeCloseTo(2500);
  expect(high[15]![2]).toBeGreaterThan(landingApproachPath(scene).points[15]![2]);
  expect(high.at(-2)).toEqual(landingApproachPath(scene).points.at(-2));
  const onGlide = { ...scene, angle: 0, across: 0, height: 15 + scene.along * scene.slope, pitch: -Math.atan(scene.slope) };
  for (const point of landingApproachPath(onGlide).points) {
    expect(point[2]).toBeCloseTo(15 + (scene.along - point[0]) * scene.slope);
  }
});

it("keeps subtle ground references and runway markings on the same perspective datum at steep viewing angles", () => {
  for (const camera of [0, .2, Math.PI / 3]) {
    const result = projectLandingRunway(scene, camera);
    const horizon = -Math.tan(camera);
    expect(result.surface.every(point => point[1] > horizon)).toBe(true);
    expect(result.ground.length).toBeGreaterThan(0);
    expect(result.ground.flat().every(point => point[1] > horizon)).toBe(true);
    expect(result.markings).toHaveLength(4);
    expect(result.markings.flat(2).every(Number.isFinite)).toBe(true);
    expect(result.rails.flat(3).every(Number.isFinite)).toBe(true);
  }
  expect(projectLandingRunway({ ...scene, height: -10 }).ground).toHaveLength(0);
});

it("clips before perspective division and removes guidance beyond the entrance or behind the camera", () => {
  const past = projectLandingRunway({ ...scene, along: -300, approach: false });
  expect(past.threshold).toBeNull();
  expect(past.runway).not.toBeNull();
  expect(past.rails).toHaveLength(0);
  expect(past.runway!.flat().every(Number.isFinite)).toBe(true);
  expect(past.surface.length).toBeGreaterThanOrEqual(3);
  expect(past.surface.flat().every(Number.isFinite)).toBe(true);
  const behind = projectLandingRunway({ ...scene, angle: Math.PI });
  expect(behind.runway).toBeNull();
  expect(behind.surface).toHaveLength(0);
  expect(behind.rails).toHaveLength(0);
  expect(landingRunwayScene({ ...geometry, heightM: null }, 0, 3)).toBeNull();
  expect(landingRunwayScene({ ...geometry, lengthM: 0 }, 0, 3)).toBeNull();
});

it("smooths heading across north on the shortest arc and resets unknown geometry immediately", () => {
  const motion = new RunwaySceneMotion();
  motion.observe({ ...scene, angle: 179 * Math.PI / 180 }, 0, true);
  motion.observe({ ...scene, angle: -179 * Math.PI / 180 }, 100, false);
  expect(Math.abs(motion.step(200)!.angle)).toBeGreaterThan(170 * Math.PI / 180);
  expect(motion.step(1500)!.angle).toBeCloseTo(-179 * Math.PI / 180);
  expect(motion.isMoving(1500)).toBe(false);
  motion.observe(null, 1501, false);
  expect(motion.step(1501)).toBeNull();
});
