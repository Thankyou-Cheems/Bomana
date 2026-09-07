import { describe, expect, it } from "vitest";
import { GroundTrackEstimator, targetGroundTrackGeometry } from "./ground-track";

describe("GroundTrackEstimator", () => {
  it("expires unchanged source positions instead of projecting a frozen map indefinitely", () => {
    const estimator = new GroundTrackEstimator();
    const scale = [100000, 100000] as const;
    for (const atMs of [0, 100, 200]) estimator.update({ atMs, x: .5, y: .5-atMs*.000002, scale });
    expect(estimator.update({ atMs: 300, x: .5, y: .4996, scale }).valid).toBe(true);
    expect(estimator.update({ atMs: 600, x: .5, y: .4996, scale }).valid).toBe(false);
  });

  it("establishes a causal track from nominal 10 Hz 8111 map frames", () => {
    const estimator = new GroundTrackEstimator();
    let track = estimator.update({ atMs: 0, x: 0.5, y: 0.5, scale: [100_000, 100_000] });
    track = estimator.update({ atMs: 105, x: 0.5001, y: 0.4998, scale: [100_000, 100_000] });
    track = estimator.update({ atMs: 210, x: 0.5002, y: 0.4996, scale: [100_000, 100_000] });
    track = estimator.update({ atMs: 315, x: 0.5003, y: 0.4994, scale: [100_000, 100_000] });

    expect(track.valid).toBe(true);
    expect(track.sampleCount).toBe(3);
    expect(track.groundSpeedMps).toBeCloseTo(Math.hypot(10, 20) / 0.105, 5);
    expect(track.headingDeg).toBeCloseTo(26.565, 3);
  });

  it("keeps a bounded three-sample fit when official map frames temporarily remain at 5 Hz", () => {
    const estimator = new GroundTrackEstimator();
    estimator.update({ atMs: 0, x: 0.5, y: 0.5, scale: [100_000, 100_000] });
    estimator.update({ atMs: 200, x: 0.5002, y: 0.4996, scale: [100_000, 100_000] });
    const track = estimator.update({ atMs: 400, x: 0.5004, y: 0.4992, scale: [100_000, 100_000] });

    expect(track.valid).toBe(true);
    expect(track.sampleCount).toBe(3);
    expect(track.sampleSpanMs).toBe(400);
  });

  it("fails closed for stationary or high-residual transition frames", () => {
    const stationary = new GroundTrackEstimator();
    for (const atMs of [0, 100, 200]) {
      stationary.update({ atMs, x: 0.5, y: 0.5, scale: [100_000, 100_000] });
    }
    expect(stationary.update({ atMs: 300, x: 0.5, y: 0.5, scale: [100_000, 100_000] }).valid).toBe(false);

    const turning = new GroundTrackEstimator();
    turning.update({ atMs: 0, x: 0.5, y: 0.5, scale: [100_000, 100_000] });
    turning.update({ atMs: 100, x: 0.501, y: 0.499, scale: [100_000, 100_000] });
    const track = turning.update({ atMs: 200, x: 0.498, y: 0.501, scale: [100_000, 100_000] });
    expect(track.valid).toBe(false);
  });

  it("projects target distance and cross-track error from the fitted track", () => {
    const estimator = new GroundTrackEstimator();
    estimator.update({ atMs: 0, x: 0.5, y: 0.5, scale: [10_000, 10_000] });
    estimator.update({ atMs: 100, x: 0.5, y: 0.498, scale: [10_000, 10_000] });
    const track = estimator.update({ atMs: 200, x: 0.5, y: 0.496, scale: [10_000, 10_000] });
    const target = targetGroundTrackGeometry(track, { x: 0.505, y: 0.396 }, [10_000, 10_000]);

    expect(target).not.toBeNull();
    expect(target?.alongTrackM).toBeCloseTo(1_000, 5);
    expect(target?.crossTrackM).toBeCloseTo(-50, 5);
    expect(target?.relativeDeg).toBeGreaterThan(0);
  });
});
