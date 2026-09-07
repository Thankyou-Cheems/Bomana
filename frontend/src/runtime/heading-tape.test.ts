import { describe, expect, it } from "vitest";
import {
  headingGuidanceText,
  headingTapeMarks,
  headingTapeScale,
  headingTapeTargetMarkers,
  headingTargetSymbol,
  projectHeadingGuidanceRatio,
} from "./heading-tape";

describe("heading tape center clearance", () => {
  it("reserves the central readout area instead of drawing a duplicate canvas label", () => {
    const center = headingTapeMarks(0).find((mark) => mark.deltaDeg === 0);
    expect(center).toMatchObject({ headingDeg: 0, major: true, label: null });
  });

  it("keeps labels outside the center clearance", () => {
    const labels = headingTapeMarks(355).filter((mark) => mark.label !== null);
    expect(labels.some((mark) => mark.deltaDeg === -20 && mark.label === "335")).toBe(true);
    expect(labels.some((mark) => mark.deltaDeg === 20 && mark.label === "015")).toBe(true);
  });

  it("projects the active target and nearby mission points onto the tape", () => {
    const markers = headingTapeTargetMarkers([
      { id: "airfield_2", kind: "airfield", label: "机场", relativeDeg: 4, distanceKm: 12.4, isTarget: true },
      { id: "zone_0.1234_0.5678", kind: "zone", label: "战区 1", relativeDeg: -18, distanceKm: 8.2, isTarget: false },
      { id: "poi_1", kind: "poi", label: "兴趣点", relativeDeg: 46, distanceKm: 20, isTarget: false },
    ]);

    expect(markers).toEqual([
      expect.objectContaining({ id: "airfield_2", markerLabel: "场2", deltaDeg: 4, isTarget: true, overflow: false }),
      expect.objectContaining({ id: "zone_0.1234_0.5678", markerLabel: "战区1", deltaDeg: -18, isTarget: false, overflow: false }),
    ]);
  });

  it("keeps an off-axis active target visible as an edge cue", () => {
    expect(headingTapeTargetMarkers([
      { id: "airfield_3", kind: "airfield", label: "机场", relativeDeg: 72, distanceKm: 31, isTarget: true },
    ])).toEqual([
      expect.objectContaining({ markerLabel: "场3", deltaDeg: 29, overflow: true, isTarget: true }),
    ]);
  });

  it("keeps an active zone on the tape outside the nearby-marker field", () => {
    expect(headingTapeTargetMarkers([
      { id: "zone_1", kind: "zone", label: "战区 1", relativeDeg: 52, distanceKm: 4.2, isTarget: true },
    ])).toEqual([
      expect.objectContaining({ id: "zone_1", markerLabel: "战区1", deltaDeg: 29, overflow: true, isTarget: true }),
    ]);
  });

  it("keeps Y66 module markers distinguishable instead of collapsing every module to 场1", () => {
    expect(headingTapeTargetMarkers([
      { id: "y66:y66_airfield_1:parking", kind: "airfield", label: "Y66 机场 1 · 停机 / 维修", relativeDeg: 4, distanceKm: 8, isTarget: false },
      { id: "y66:y66_airfield_1:storage", kind: "airfield", label: "Y66 机场 1 · 油库 / 仓储", relativeDeg: 6, distanceKm: 8.4, isTarget: false },
      { id: "y66:y66_airfield_1:dwelling", kind: "airfield", label: "1居", relativeDeg: 8, distanceKm: 8.2, isTarget: false },
    ]).map((marker) => marker.markerLabel)).toEqual(["1停", "1油", "1居"]);
  });

  it("reproduces the Python distance-focused heading scale and fine CDI", () => {
    expect(headingTapeScale(20)).toBe(1);
    expect(headingTapeScale(9)).toBeCloseTo(2.5, 5);
    expect(headingTapeScale(3)).toBe(4);
    expect(projectHeadingGuidanceRatio(0.1, 3)).toBeGreaterThan(0.1 / 3);
    expect(projectHeadingGuidanceRatio(3, 3)).toBe(1);
  });

  it("keeps the Python precision wording inside the guidance lane", () => {
    expect(headingGuidanceText(0.24, 7)).toBe("精确·右0.24° · 7.0km");
    expect(headingGuidanceText(0, 7)).toBe("已对准 · 7.0km");
    expect(headingGuidanceText(-4, 7)).toBe("左转4.0° · 7.0km");
  });

  it("uses an aircraft silhouette for airfields on both heading surfaces", () => {
    expect(headingTargetSymbol("airfield")).toBe("aircraft");
    expect(headingTargetSymbol("zone")).toBe("target");
  });
});
