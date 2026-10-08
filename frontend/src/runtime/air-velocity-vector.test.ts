import { describe, expect, it } from "vitest";
import { AirVelocityVectorEstimator } from "./air-velocity-vector";
import { PublicRuntime } from "./public-runtime";
import { editionPolicy } from "./edition-policy";
import type { EditionSnapshot } from "./runtime-types";

const base = new PublicRuntime({ edition: editionPolicy("Standard") }).snapshot();
function sample(at: number, x = .5 + at * .000002, y = .5): EditionSnapshot {
  return { ...base, connected: true, phase: "alive", sampledAtMs: at, speedSampledAtMs: at, mapObjectsSampledAtMs: at, mapObjectsFresh: true,
    flight: { ...base.flight, aircraft: "test", headingDeg: 0, onGround: false },
    navigation: { player: { x, y }, mapScaleM: [100000, 50000], items: [], target: null, selectionMode: "auto" } };
}
function established() {
  const estimator = new AirVelocityVectorEstimator();
  for (const at of [0, 100, 200]) estimator.observe(sample(at), at);
  return estimator;
}

describe("ownship horizontal velocity vector", () => {
  it("shows eastward motion despite a north-facing nose and handles heading wrap", () => {
    const estimator = established();
    const vector = estimator.observe(sample(200), 200)!;
    expect(vector.headingDeg).toBeCloseTo(90);
    expect(vector.relativeDeg).toBeCloseTo(90);
    expect(vector.groundSpeedMps).toBeCloseTo(200);
    const north = new AirVelocityVectorEstimator();
    let result;
    for (const at of [0, 100, 200]) {
      const snapshot = sample(at, .5, .5 - at * .000004);
      result = north.observe({ ...snapshot, flight: { ...snapshot.flight, headingDeg: 350 } }, at);
    }
    expect(result?.headingDeg).toBeCloseTo(0);
    expect(result?.relativeDeg).toBeCloseTo(10);
    expect(result?.groundSpeedMps).toBeCloseTo(200);
  });

  it("cannot create a vector by repainting one position, or from stopped/teleported positions", () => {
    const estimator = new AirVelocityVectorEstimator();
    for (const now of [0, 100, 200]) expect(estimator.observe(sample(0), now)).toBeNull();
    for (const at of [0, 100, 200, 300]) expect(estimator.observe(sample(at, .5), at)).toBeNull();
    expect(established().observe(sample(300, .8), 300)).toBeNull();
    expect(established().observe(sample(200), 701)).toBeNull();
    const frozen = established();
    for (const at of [300, 400, 500]) frozen.observe(sample(at, .5004), at);
    expect(frozen.observe(sample(600, .5004), 600)).toBeNull();
  });

  it("clears on missing, held, grounded and new-sortie observations and requires a new fit", () => {
    for (const change of [
      { connected: false }, { mapObjectsFresh: false }, { mapObjectsSampledAtMs: undefined }, { navigation: null },
      { speedSampledAtMs: null }, { speedSampledAtMs: -2000 },
      { phase: "idle" as const }, { flight: { ...sample(300).flight, onGround: true } },
      { flight: { ...sample(300).flight, aircraft: "other" } }, { timer: { ...base.timer, lifeIndex: 2 } },
      { navigation: { ...sample(300).navigation!, mapScaleM: [50000, 50000] as const } },
      { mapGrid: { minimum: [100, 100] as const, maximum: [100100, 50100] as const, zero: [0, 0] as const, steps: [1, 1] as const } },
    ]) {
      const estimator = established();
      expect(estimator.observe({ ...sample(300), ...change }, 300)).toBeNull();
      expect(estimator.observe(sample(400), 400)).toBeNull();
    }
  });
});
