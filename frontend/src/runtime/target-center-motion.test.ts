import { describe, expect, it } from "vitest";
import { TargetCenterMotion } from "./target-center-motion";

describe("display-only target centre bearing", () => {
  it("damps alternating map noise without extrapolating past observations", () => {
    const motion = new TargetCenterMotion();
    motion.observe("zone", 4); motion.step(0);
    for (let t = 100; t <= 2000; t += 100) {
      const raw = 4 + (t % 200 ? .03 : -.03);
      motion.observe("zone", raw);
      expect(Math.abs(motion.step(t) - 4)).toBeLessThan(.03);
    }
  });
  it("bounds lag in a real turn, settles while idle, and resets on target change", () => {
    const motion = new TargetCenterMotion();
    motion.observe("zone", 0); motion.step(0);
    motion.observe("zone", 30);
    expect(motion.step(100)).toBeGreaterThanOrEqual(29.9);
    for (let t = 150; t <= 1200; t += 50) motion.step(t);
    expect(motion.step(1250)).toBeCloseTo(30, 5);
    motion.observe("module", -12);
    expect(motion.step(1260)).toBe(-12);
  });
  it("handles the wrap boundary and duplicate command projections without resets", () => {
    const motion = new TargetCenterMotion();
    motion.observe("zone", 179.98); motion.step(0);
    motion.observe("zone", -179.98);
    const first = motion.step(16);
    expect(Math.abs(first)).toBeGreaterThan(179.9);
    motion.observe("zone", -179.98);
    expect(motion.step(16)).toBeCloseTo(first, 10);
  });
});
