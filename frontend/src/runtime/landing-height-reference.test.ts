import { describe, expect, it } from "vitest";
import { DEFAULT_LANDING_SETTINGS, LandingAssist, type LandingInput } from "./landing-assist";
import { landingHeightPresentation } from "./landing-presentation";

// Historical Vietnam H3 coordinates and terrain samples, not a current game survey.
const near = [.327635, .908216] as const, far = [.325010, .883943] as const;
const sample = (swapped = false): LandingInput => ({
  context: "vietnam-historical", fresh: true, sampledAtMs: 1000,
  navigation: { player: { x: .327577, y: .907609 }, mapScaleM: [131072, 131072], selectionMode: "auto", target: null,
    items: [{ id: "h3", kind: "airfield", friendly: true, hostile: false, selected: false, label: "友方机场 H3",
      x: .3263225, y: .8960795, runwayStart: swapped ? far : near, runwayEnd: swapped ? near : far,
      distanceKm: 1.52, bearingDeg: 0, relativeDeg: 0 }] },
  altitudeM: 399, iasKmh: 0, verticalSpeedMps: 0, gearPercent: 100, airbrakePercent: 0, flapsPercent: 0, track: null,
});
const terrain = (p: readonly [number, number]) => p[0] === near[0] ? 384.09332699037316 : 360.6868862161798;

describe("runway threshold height reference for every airfield", () => {
  it("names the verified platform without a separate row or a natural-terrain claim", () => {
    const assist = new LandingAssist(), input = sample();
    assist.configure({ ...DEFAULT_LANDING_SETTINGS, enabled: true, automatic: false }, input.navigation);
    const view = assist.update(input, () => 396.9197692871094, () => "runway");
    expect(view.geometry?.heightM).toBeCloseTo(2.08023,4);
    expect(landingHeightPresentation(view).compactReference).toBe("机场397m · 高差+2m");
    expect(landingHeightPresentation(view).relative).toBe("高于机场 2 m");
  });

  it.each([false, true])("selects the physically near entrance independently of ordered endpoints (swapped=%s)", swapped => {
    const assist = new LandingAssist(), input = sample(swapped);
    assist.configure({ ...DEFAULT_LANDING_SETTINGS, enabled: true, automatic: false }, input.navigation);
    const view = assist.update(input, terrain);
    expect(view.settings.reverse).toBe(swapped);
    expect(view.elevationM).toBeCloseTo(384.0933, 4);
    expect(view.geometry?.heightM).toBeCloseTo(14.9067, 4);
    expect(landingHeightPresentation(view).reference).toContain("入口地形");
    expect(landingHeightPresentation(view).relative).toContain("高于入口");
  });

  it("retains the explicitly reversed threshold and names its reference, rather than claiming airport surface height", () => {
    const assist = new LandingAssist(), input = sample();
    assist.configure({ ...DEFAULT_LANDING_SETTINGS, enabled: true, automatic: false }, input.navigation);
    assist.configure({ ...assist.settings(), reverse: true }, input.navigation);
    const view = assist.update(input, terrain);
    expect(view.elevationM).toBeCloseTo(360.6869, 4);
    expect(view.geometry?.heightM).toBeCloseTo(38.3131, 4);
    expect(landingHeightPresentation(view).compactReference).toBe("入口地形361m · 高差+38m");
  });

  it("keeps the selected entrance locked as the aircraft crosses the midpoint", () => {
    const assist = new LandingAssist(), input = sample();
    assist.configure({ ...DEFAULT_LANDING_SETTINGS, enabled: true, automatic: false }, input.navigation);
    const view = assist.update({ ...input, navigation: { ...input.navigation!, player: { x: far[0], y: far[1] } } }, terrain);
    expect(view.settings.reverse).toBe(false);
    expect(view.elevationM).toBeCloseTo(384.0933, 4);
  });
});
