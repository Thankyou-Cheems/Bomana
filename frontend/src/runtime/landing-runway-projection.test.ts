import { expect, it } from "vitest";
import { landingGeometry } from "./landing-assist";
import { landingRunwayScene, landingRunwayCamera, projectLandingRunway, RunwaySceneMotion } from "./landing-runway-projection";

const input = { player: { x: .53, y: .53 }, scale: [10000, 100000] as const,
  start: [.5, .5] as const, end: [.5, .48] as const, altitudeM: 400, elevationM: 100, glideAngleDeg: 3, velocity: [0, -100] as const };
const geometry = landingGeometry(input);
const scene = landingRunwayScene(geometry, 0, 3)!;

it("tilts the inspection camera as one perspective transform and uses definition width", () => {
  const s = landingRunwayScene({ ...geometry, crossTrackM: 0, referenceWidthM: 140 }, 0, 3)!;
  const pitch = landingRunwayCamera(s), result = projectLandingRunway(s, pitch);
  expect(pitch).toBeCloseTo(Math.atan2(300, 4000));
  expect(result.threshold![1]).toBeGreaterThan(0);
  expect(result.end![1]).toBeLessThan(0);
  expect(result.surface[1]![0] - result.surface[0]![0]).toBeGreaterThan(result.surface[2]![0] - result.surface[3]![0]);
  expect(projectLandingRunway(s).surface[1]![0]).toBeCloseTo(70 / 3000);
  expect(landingRunwayCamera({ ...s, angle: Math.PI })).toBe(0);
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

it("uses the selected angle and 15 m threshold reference for exactly two rails", () => {
  const projection = projectLandingRunway(scene);
  expect(projection.rails).toHaveLength(2);
  expect(projection.rails[0]![0][1]).toBeCloseTo((scene.height - 15) / scene.along);
  expect(projection.rails[0]![0][0]).toBeLessThan(projection.threshold![0]);
  expect(projection.rails[1]![0][0]).toBeGreaterThan(projection.threshold![0]);
  const steeper = projectLandingRunway({ ...scene, slope: Math.tan(6 * Math.PI / 180) });
  expect(steeper.rails[0]![1][1]).toBeLessThan(projection.rails[0]![1][1]);
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
