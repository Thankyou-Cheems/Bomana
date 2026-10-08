import { describe, expect, it } from "vitest";
import { AirEnergyTrend } from "./air-energy";
import { PublicRuntime } from "./public-runtime";
import { editionPolicy } from "./edition-policy";
import type { EditionSnapshot } from "./runtime-types";

const base = new PublicRuntime({ edition: editionPolicy("Standard") }).snapshot();
function sample(at: number, altitudeM: number, tasKmh: number, extra: Partial<EditionSnapshot["flight"]> = {}): EditionSnapshot {
  return { ...base, connected: true, sampledAtMs: at, speedSampledAtMs: at,
    flight: { ...base.flight, altitudeM, tasKmh, tasObserved: true, onGround: false, ...extra } };
}

describe("ownship specific-energy trend", () => {
  it("shows a sustained climb and stays quiet while speed is traded for altitude", () => {
    const climb = new AirEnergyTrend();
    let cue = climb.observe(sample(0, 2000, 800), 0);
    for (let at = 250; at <= 2000; at += 250) cue = climb.observe(sample(at, 2000 + 30 * at / 1000, 800), at);
    expect(cue).toBe("up");
    const trade = new AirEnergyTrend();
    const ke = (tas: number) => (tas / 3.6) ** 2 / (2 * 9.80665);
    for (let at = 0; at <= 2000; at += 250) {
      const tas = 900 - 36 * at / 2000;
      cue = trade.observe(sample(at, 1000 + ke(900) - ke(tas), tas), at);
    }
    expect(cue).toBeNull();
  });
  it("shows a combined loss, holds a moderate trend, then clears when it flattens", () => {
    const loss = new AirEnergyTrend();
    let cue = loss.observe(sample(0, 2000, 800), 0);
    for (let at = 250; at <= 2000; at += 250) cue = loss.observe(sample(at, 2000 - 40 * at / 1000, 800 - 80 * at / 2000), at);
    expect(cue).toBe("down");
    const trend = new AirEnergyTrend();
    for (let at = 0; at <= 2000; at += 250) cue = trend.observe(sample(at, 2000 + 30 * at / 1000, 800), at);
    expect(cue).toBe("up");
    for (let at = 2250; at <= 5000; at += 250) cue = trend.observe(sample(at, 2060 + 10 * (at - 2000) / 1000, 800), at);
    expect(cue).toBe("up");
    for (let at = 5250; at <= 8000; at += 250) cue = trend.observe(sample(at, 2090, 800), at);
    expect(cue).toBeNull();
  });
  it("clears when TAS is not observed, the aircraft is on the ground, or the sample breaks", () => {
    const trend = new AirEnergyTrend();
    for (let at = 0; at <= 2000; at += 250) trend.observe(sample(at, 2000 + 30 * at / 1000, 800), at);
    expect(trend.observe(sample(2250, 2100, 800, { tasObserved: false }), 2250)).toBeNull();
    const grounded = new AirEnergyTrend();
    for (let at = 0; at <= 2000; at += 250) expect(grounded.observe(sample(at, 2000 + 30 * at / 1000, 800, { onGround: true }), at)).toBeNull();
    const reset = new AirEnergyTrend();
    for (let at = 0; at <= 2000; at += 250) reset.observe(sample(at, 2000 + 30 * at / 1000, 800), at);
    expect(reset.observe(sample(4000, 3000, 800), 4000)).toBeNull();
    expect(reset.observe({ ...sample(4250, 3010, 800), speedSampledAtMs: null }, 4250)).toBeNull();
  });
});
