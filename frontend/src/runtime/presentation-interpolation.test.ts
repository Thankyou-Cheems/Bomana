import { describe, expect, it } from "vitest";
import { interpolatePresentationValue } from "./presentation-interpolation";

describe("presentation interpolation", () => {
  it("smooths visible flight numbers between 5 Hz official samples without overshooting", () => {
    const first = interpolatePresentationValue(100, 200, 16, 70);
    expect(first).toBeGreaterThan(100);
    expect(first).toBeLessThan(200);
    const settled = interpolatePresentationValue(first, 200, 500, 70);
    expect(settled).toBeCloseTo(200, 1);
  });

  it("snaps invalid or discontinuous values instead of animating stale data", () => {
    expect(interpolatePresentationValue(Number.NaN, 320, 16, 70)).toBe(320);
    expect(interpolatePresentationValue(100, 1_000, 16, 70, 500)).toBe(1_000);
  });
});
