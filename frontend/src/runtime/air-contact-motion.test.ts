import { describe, expect, it } from "vitest";
import { AirContactMotionEstimator, airContactClosingLabel, airContactColor } from "./air-contact-motion";
import { airRealisticSituation } from "./air-realistic-model";
import { PublicRuntime } from "./public-runtime";
import { editionPolicy } from "./edition-policy";
import type { EditionSnapshot } from "./runtime-types";

const base = new PublicRuntime({ edition: editionPolicy("Standard") }).snapshot();
function sample(at: number, points: readonly (readonly [number, number])[], player = [.5, .5]): EditionSnapshot {
  return { ...base, connected: true, sampledAtMs: 10000 + at, mapObjectsSampledAtMs: 10000 + at, mapObjectsFresh: true,
    navigation: { player: { x: player[0]!, y: player[1]! }, mapScaleM: [100000, 50000], selectionMode: "auto", target: null,
      items: points.map(([east, south], index) => ({ id: `row-${index}`, kind: "hostile", aircraft: true, hostile: true, friendly: false,
        x: .5 + east / 100000, y: .5 + south / 50000, officialIcon: "Fighter", label: "", distanceKm: 0, relativeDeg: 0, bearingDeg: 0, selected: false })) } };
}
function observe(estimator: AirContactMotionEstimator, snapshot: EditionSnapshot, now = snapshot.sampledAtMs) {
  const situation = airRealisticSituation(snapshot, 20, now);
  return estimator.observe(snapshot, situation.contacts, situation.contactsCurrent);
}

describe("current-contact map motion", () => {
  it("measures absolute metric motion, not ownship displacement or dx/dy", () => {
    const estimator = new AirContactMotionEstimator();
    expect(observe(estimator, sample(0, [[1000, -2000]]))[0]!.velocity).toBeNull();
    const result = observe(estimator, sample(1000, [[1100, -1800]], [.51, .49]))[0]!.velocity!;
    expect(result.eastMps).toBeCloseTo(100, 6);
    expect(result.southMps).toBeCloseTo(200, 6);
    const stationary = new AirContactMotionEstimator();
    observe(stationary, sample(0, [[1000, -2000]]));
    expect(observe(stationary, sample(1000, [[1000, -2000]], [.51, .49]))[0]!.velocity).toEqual({ eastMps: 0, southMps: 0 });
  });
  it("separates enemy ground speed from closure including ownship motion", () => {
    const headOn = new AirContactMotionEstimator();
    expect(observe(headOn, sample(0, [[0, -5000]]))[0]!.closingMps).toBeNull();
    const contact = observe(headOn, sample(1000, [[0, -4800]], [.5, .5 - 200 / 50000]))[0]!;
    expect(contact.groundSpeedMps).toBeCloseTo(200, 6);
    expect(contact.closingMps).toBeCloseTo(400, 6);
    const coMoving = new AirContactMotionEstimator();
    observe(coMoving, sample(0, [[1000, -3000]]));
    const unchanged = observe(coMoving, sample(1000, [[1300, -3000]], [.5 + 300 / 100000, .5]))[0]!;
    expect(unchanged.groundSpeedMps).toBeCloseTo(300, 6);
    expect(unchanged.closingMps).toBeCloseTo(0, 6);
  });
  it("projects relative velocity onto the current line of sight, including opening and crossing", () => {
    const estimator = new AirContactMotionEstimator();
    observe(estimator, sample(0, [[0, -5000], [3000, 0]]));
    const contacts = observe(estimator, sample(1000, [[0, -5150], [3000, 100]]));
    expect(contacts[1]!.closingMps).toBeCloseTo(-150, 6);
    expect(contacts[0]!.closingMps).toBeCloseTo(-100 * 100 / Math.hypot(3000, 100), 6);
    const repeated = observe(estimator, sample(1000, [[3000, 100], [0, -5150]]));
    expect(repeated.map(row => row.closingMps)).toEqual(contacts.map(row => row.closingMps));
  });
  it("smooths quantized map coordinates without assigning redraws a new speed", () => {
    const estimator = new AirContactMotionEstimator();
    const recent: number[] = [];
    let last = sample(0, [[1000, -4000]]);
    for (let at = 0; at <= 5000; at += 250) {
      last = sample(at, [[Math.round((1000 + .123 * at) / 20) * 20, Math.round((-4000 + .067 * at) / 20) * 20]]);
      const result = observe(estimator, last)[0]!;
      if (at >= 3000) recent.push(result.groundSpeedMps!);
    }
    const expected = Math.hypot(123, 67);
    expect(recent.every(value => Math.abs(value - expected) < 8)).toBe(true);
    expect(Math.max(...recent) - Math.min(...recent)).toBeLessThan(8);
    const before = observe(estimator, last)[0]!;
    for (let i = 0; i < 20; i++) expect(observe(estimator, last)[0]).toEqual(before);
  });
  it("does not turn an ownship position jump into a fabricated closing rate", () => {
    const estimator = new AirContactMotionEstimator();
    observe(estimator, sample(0, [[1000, -3000]]));
    const result = observe(estimator, sample(1000, [[1100, -3000]], [.52, .5]))[0]!;
    expect(result.groundSpeedMps).toBeCloseTo(100, 6);
    expect(result.closingMps).toBeNull();
  });
  it("matches geometry across reordered rows and rejects ambiguous crossings", () => {
    const estimator = new AirContactMotionEstimator();
    observe(estimator, sample(0, [[-2000, -3000], [2000, -3000]]));
    const result = observe(estimator, sample(1000, [[2100, -3000], [-2100, -3000]]));
    expect(result.map(v => Math.round(v.velocity!.eastMps)).sort((a,b) => a-b)).toEqual([-100, 100]);
    const reordered = sample(1000, [[2100, -3000], [-2100, -3000]], [.48, .5]);
    expect(observe(estimator, reordered).map(v => Math.round(v.velocity!.eastMps))).toEqual([-100, 100]);
    const crossing = new AirContactMotionEstimator();
    observe(crossing, sample(0, [[-100, -3000], [100, -3000]]));
    expect(observe(crossing, sample(1000, [[0, -3000], [0, -3000]])).every(v => v.velocity === null)).toBe(true);
  });
  it("does not count redraws, extrapolate vanished contacts, or reuse stale tracks", () => {
    const estimator = new AirContactMotionEstimator();
    const initial = sample(0, [[1000, -3000]]);
    observe(estimator, initial);
    for (let i = 0; i < 20; i++) expect(observe(estimator, initial)[0]!.velocity).toBeNull();
    const moved = sample(1000, [[1100, -3000]]);
    expect(observe(estimator, moved)[0]!.velocity).not.toBeNull();
    expect(observe(estimator, moved, moved.sampledAtMs + 1501)).toEqual([]);
    expect(observe(estimator, sample(1250, [[1125, -3000]]))[0]!.velocity).toBeNull();
    expect(observe(estimator, sample(1500, []))).toEqual([]);
    expect(observe(estimator, sample(1750, [[1175, -3000]]))[0]!.velocity).toBeNull();
    observe(estimator, { ...sample(2000, [[1200, -3000]]), mapObjectsFresh: false });
    expect(observe(estimator, sample(2250, [[1225, -3000]]))[0]!.velocity).toBeNull();
  });
  it("restarts on gaps, time rollback, map scale, sortie, aircraft and implausible jumps", () => {
    for (const change of [
      (s: EditionSnapshot) => ({ ...s, mapObjectsSampledAtMs: s.sampledAtMs - 2000 }),
      (s: EditionSnapshot) => ({ ...s, mapObjectsSampledAtMs: s.sampledAtMs + 600, sampledAtMs: s.sampledAtMs + 600 }),
      (s: EditionSnapshot) => ({ ...s, navigation: { ...s.navigation!, mapScaleM: [80000, 50000] as const } }),
      (s: EditionSnapshot) => ({ ...s, timer: { ...s.timer, lifeIndex: 99 } }),
      (s: EditionSnapshot) => ({ ...s, flight: { ...s.flight, aircraft: "new-aircraft" } }),
      (_s: EditionSnapshot) => sample(1000, [[9000, -3000]]),
    ]) {
      const estimator = new AirContactMotionEstimator();
      observe(estimator, sample(0, [[1000, -3000]]));
      expect(observe(estimator, change(sample(1000, [[1100, -3000]]))).every(v => v.velocity === null && v.closingMps === null && v.groundSpeedMps === null)).toBe(true);
    }
  });
  it("flags only sustained compact slow co-moving groups, with one uncertain label", () => {
    const estimator = new AirContactMotionEstimator();
    let result = observe(estimator, sample(0, [[0, -3000], [600, -3000], [300, -3600]]));
    for (let t = 250; t <= 8500; t += 250) {
      result = observe(estimator, sample(t, [[t * .1, -3000], [600 + t * .1, -3000], [300 + t * .1, -3600]]));
      if (t < 8000) expect(result.some(v => v.suspectedGroup)).toBe(false);
    }
    expect(result.every(v => v.suspectedGroup)).toBe(true);
    expect(result.filter(v => v.groupSize === 3)).toHaveLength(1);
    const split = observe(estimator, sample(8750, [[875, -3000], [1475, -3000]]));
    expect(split.some(v => v.suspectedGroup)).toBe(false);
  });
  it.each(["fast", "opposed", "stationary", "scattered"])("does not call %s contacts a slow formation", mode => {
    const estimator = new AirContactMotionEstimator();
    let result: ReturnType<typeof observe> = [];
    for (let t = 0; t <= 10000; t += 250) {
      const d = t * (mode === "fast" ? .25 : mode === "stationary" ? 0 : .1);
      result = observe(estimator, sample(t, [[d, -3000], [600 + (mode === "opposed" ? -d : d), -3000],
        [300 + d, mode === "scattered" ? -6000 : -3600]]));
    }
    expect(result.some(v => v.suspectedGroup)).toBe(false);
  });
  it("rejects a compact chain whose endpoints do not share the group's velocity", () => {
    const estimator = new AirContactMotionEstimator();
    let result: ReturnType<typeof observe> = [];
    for (let t = 0; t <= 10000; t += 250) {
      result = observe(estimator, sample(t, [[t * .06, -3000], [600 + t * .08, -3000], [300 + t * .1, -3600]]));
    }
    expect(result.every(v => v.velocity !== null)).toBe(true);
    expect(result.some(v => v.suspectedGroup)).toBe(false);
  });
  it("uses warm distance colors without changing at zoom boundaries", () => {
    expect(airContactColor(1)).toBe("rgb(255, 100, 109)");
    expect(airContactColor(5)).toBe("rgb(255, 178, 105)");
    expect(airContactColor(10)).toBe("rgb(226, 203, 149)");
    expect(airContactColor(40)).toBe(airContactColor(20));
    expect(airContactColor(4.999)).toBe(airContactColor(5.001));
  });
  it("keeps a short world trail and the relative velocity used for closure", () => {
    const estimator = new AirContactMotionEstimator();
    observe(estimator, sample(0, [[0, -2000]]));
    const row = observe(estimator, sample(1000, [[0, -1600]]))[0]!;
    expect(row.relativeVelocity!.southMps).toBeCloseTo(400, 6);
    expect(row.trail.map(point => point.ageMs)).toEqual([1000, 0]);
    expect(row.trail[0]).toMatchObject({ eastM: 0, southM: -2000 });
    expect(row.trail[1]).toMatchObject({ eastM: 0, southM: -1600 });
    expect(observe(estimator, sample(1500, [])) ).toEqual([]);
    expect(observe(estimator, sample(1750, [[0, -1500]]))[0]!.trail).toHaveLength(1);
  });
  it("keeps six seconds of slow-cadence trail, clearing it on observation loss", () => {
    const estimator = new AirContactMotionEstimator();
    let last = observe(estimator, sample(0, [[0, 3000]]))[0]!;
    for (let t = 1000; t <= 10000; t += 1000) last = observe(estimator, sample(t, [[0, 3000 - t * .08]]))[0]!;
    expect(last.trail).toHaveLength(7);
    expect(last.trail[0]!.ageMs).toBe(6000);
    expect(last.closingMps).toBeCloseTo(80);
    expect(observe(estimator, { ...sample(10100, [[0, 2192]]), mapObjectsFresh: false })).toEqual([]);
  });
  it("expresses distance trends plainly and leaves unobserved motion unknown", () => {
    expect(airContactClosingLabel(null)).toBe("");
    expect(airContactClosingLabel(184)).toBe("接近 180 m/s");
    expect(airContactClosingLabel(-146)).toBe("远离 150 m/s");
    expect(airContactClosingLabel(-5)).toBe("稳定 ≈0 m/s");
  });
});
