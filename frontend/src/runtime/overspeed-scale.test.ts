import { describe, expect, it } from "vitest";
import { overspeedDynamicProjection, speedStripProgress } from "./overspeed-scale";

describe("shared fixed overspeed scale", () => {
  it("marks the source limit and reserves visible room beyond it", () => {
    expect(overspeedDynamicProjection(0).fillRatio).toBe(0);
    expect(overspeedDynamicProjection(0.5).fillRatio).toBeLessThan(0.06);
    expect(overspeedDynamicProjection(0.8).fillRatio).toBeLessThan(0.10);
    expect(overspeedDynamicProjection(0.9).fillRatio).toBeCloseTo(0.25, 8);
    expect(overspeedDynamicProjection(1).fillRatio).toBeCloseTo(0.625, 8);
    expect(overspeedDynamicProjection(1.1).fillRatio).toBe(1);
  });

  it("joins the compressed and expanded regions without a jump in movement rate", () => {
    const step = 0.0001;
    for (const join of [0.8, 0.9]) {
      const left = (speedStripProgress(join) - speedStripProgress(join - step)) / step;
      const right = (speedStripProgress(join + step) - speedStripProgress(join)) / step;
      expect(left).toBeGreaterThan(0);
      expect(Math.abs(right - left)).toBeLessThan(0.00001);
    }
  });

  it("gives equal speed increments equal distances throughout the approach to overspeed", () => {
    for (let percent = 90; percent < 110; percent++) {
      expect(speedStripProgress((percent + 1) / 100) - speedStripProgress(percent / 100)).toBeCloseTo(0.0375, 10);
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
    for (const [index, expected] of [0.25, 0.4375, 0.625].entries()) {
      expect(projection.markerRatios[index]).toBeCloseTo(expected, 10);
    }
  });

  it("caps the display at 110 percent without inventing another damage node", () => {
    expect(speedStripProgress(1.05)).toBeCloseTo(0.8125);
    expect(speedStripProgress(1.1)).toBe(1);
    for (const invalid of [-1, NaN, Infinity]) expect(speedStripProgress(invalid)).toBe(0);
  });
});
