import { describe, expect, it } from "vitest";
import { overspeedDynamicProjection, speedStripProgress } from "./overspeed-scale";

describe("shared fixed overspeed scale", () => {
  it("allocates the bar to early warning and the approach to the source limit", () => {
    expect(overspeedDynamicProjection(0).fillRatio).toBe(0);
    expect(overspeedDynamicProjection(0.5).fillRatio).toBeCloseTo(0.09375, 8);
    expect(overspeedDynamicProjection(0.8).fillRatio).toBeCloseTo(0.15, 8);
    expect(overspeedDynamicProjection(0.9).fillRatio).toBeCloseTo(0.4, 8);
    expect(overspeedDynamicProjection(0.95).fillRatio).toBeCloseTo(0.65, 8);
    expect(overspeedDynamicProjection(1).fillRatio).toBeCloseTo(0.95, 8);
    expect(overspeedDynamicProjection(1.1).fillRatio).toBe(1);
  });

  it("joins the compressed and expanded regions without a jump in movement rate", () => {
    const step = 0.0000001;
    for (const join of [0.8, 0.9, 0.95, 1]) {
      const left = (speedStripProgress(join) - speedStripProgress(join - step)) / step;
      const right = (speedStripProgress(join + step) - speedStripProgress(join)) / step;
      expect(left).toBeGreaterThan(0);
      expect(Math.abs(right - left)).toBeLessThan(0.0001);
    }
  });

  it("expands warning detail before the limit without jumps or a moving scale", () => {
    let previousIncrement = 0;
    for (let percent = 80; percent < 100; percent++) {
      const increment = speedStripProgress((percent + 1) / 100) - speedStripProgress(percent / 100);
      expect(increment).toBeGreaterThanOrEqual(previousIncrement - 1e-12);
      previousIncrement = increment;
    }
    for (let percent = 95; percent < 100; percent++) {
      expect(speedStripProgress((percent + 1) / 100) - speedStripProgress(percent / 100)).toBeCloseTo(0.06, 10);
    }
    let previous = 0;
    for (let sample = 1; sample <= 1000; sample++) {
      const progress = speedStripProgress(sample / 1000);
      expect(progress).toBeGreaterThan(previous);
      expect(progress - previous).toBeLessThanOrEqual(0.006001);
      previous = progress;
    }
  });

  it("keeps threshold positions independent of current speed", () => {
    const projection = overspeedDynamicProjection(0.7);
    const before = overspeedDynamicProjection(0.699);
    const after = overspeedDynamicProjection(0.701);
    expect(Math.abs(after.fillRatio - before.fillRatio)).toBeLessThan(0.01);
    expect(after.markerRatios).toEqual(before.markerRatios);
    expect(projection.markerRatios[0]).toBeGreaterThan(projection.fillRatio);
    expect(projection.markerRatios).toHaveLength(3);
    for (const [index, expected] of [0.4, 0.65, 0.95].entries()) {
      expect(projection.markerRatios[index]).toBeCloseTo(expected, 10);
    }
  });

  it("keeps every overspeed value in the final five percent without overshoot", () => {
    let previous = speedStripProgress(1);
    for (let sample = 1001; sample <= 1200; sample++) {
      const progress = speedStripProgress(sample / 1000);
      expect(progress).toBeGreaterThanOrEqual(previous);
      expect(progress).toBeGreaterThanOrEqual(.95);
      expect(progress).toBeLessThanOrEqual(1);
      previous = progress;
    }
    expect(speedStripProgress(1.05)).toBeGreaterThan(.99);
    expect(speedStripProgress(1.1)).toBe(1);
    for (const invalid of [-1, NaN, Infinity]) expect(speedStripProgress(invalid)).toBe(0);
  });
});
