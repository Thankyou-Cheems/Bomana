import { describe, expect, it } from "vitest";
import { overspeedDynamicProjection, speedStripProgress } from "./overspeed-scale";

describe("shared fixed overspeed scale", () => {
  it("reserves 85 percent for the upper half and 46 percent for the final fifth", () => {
    expect(overspeedDynamicProjection(0).fillRatio).toBe(0);
    expect(overspeedDynamicProjection(0.5).fillRatio).toBeCloseTo(0.15, 8);
    expect(overspeedDynamicProjection(0.8).fillRatio).toBeCloseTo(0.54, 8);
    expect(overspeedDynamicProjection(1).fillRatio).toBe(1);
  });

  it("joins the compressed and expanded regions without a jump in movement rate", () => {
    const step = 0.0001;
    for (const join of [0.5, 0.8]) {
      const left = (speedStripProgress(join) - speedStripProgress(join - step)) / step;
      const right = (speedStripProgress(join + step) - speedStripProgress(join)) / step;
      expect(left).toBeGreaterThan(0);
      expect(Math.abs(right - left)).toBeLessThan(0.00001);
    }
  });

  it("gives equal speed increments equal distances throughout the approach to overspeed", () => {
    for (let percent = 80; percent < 100; percent++) {
      expect(speedStripProgress((percent + 1) / 100) - speedStripProgress(percent / 100)).toBeCloseTo(0.023, 10);
    }
    let previous = 0;
    for (let sample = 1; sample <= 1000; sample++) {
      const progress = speedStripProgress(sample / 1000);
      expect(progress).toBeGreaterThan(previous);
      expect(progress - previous).toBeLessThanOrEqual(0.002301);
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
    for (const [index, expected] of [0.862, 0.931, 0.9816].entries()) {
      expect(projection.markerRatios[index]).toBeCloseTo(expected, 10);
    }
  });

  it("caps actual overspeed at a full bar and does not invent progress from invalid input", () => {
    expect(speedStripProgress(1.1)).toBe(1);
    for (const invalid of [-1, NaN, Infinity]) expect(speedStripProgress(invalid)).toBe(0);
  });
});
