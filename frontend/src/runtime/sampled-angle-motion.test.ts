import { describe, expect, it } from "vitest";
import { SampledAngleMotion, sampledAtPerformanceTime } from "./sampled-angle-motion";

describe("SampledAngleMotion", () => {
  it("continues moving between 5 Hz samples instead of settling into plateaus", () => {
    const motion = new SampledAngleMotion();
    motion.observe(0, 0);
    motion.step(0);
    motion.observe(10, 200);
    const afterSample = motion.step(200);
    const betweenSamples = motion.step(300);
    const beforeNextSample = motion.step(390);
    expect(afterSample).toBeLessThan(betweenSamples);
    expect(betweenSamples).toBeLessThan(beforeNextSample);
    expect(beforeNextSample).toBeLessThanOrEqual(20);
  });

  it("uses the shortest path across north and rejects discontinuous jumps", () => {
    const motion = new SampledAngleMotion();
    motion.observe(358, 0);
    motion.step(0);
    motion.observe(2, 200);
    expect(motion.step(300)).toBeGreaterThan(358);
    motion.observe(180, 400);
    expect(motion.step(400)).toBe(180);
  });

  it("preserves official sample spacing when delivery is delayed or coalesced", () => {
    expect(sampledAtPerformanceTime(1_000, 1_300, 500)).toBe(200);
    expect(sampledAtPerformanceTime(1_100, 1_350, 550)).toBe(300);
    expect(sampledAtPerformanceTime(1_000, 5_000, 800)).toBe(-3_200);
  });
});
