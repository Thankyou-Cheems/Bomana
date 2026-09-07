import { describe, expect, it } from "vitest";
import { headingRayToMapEdge } from "./map-heading-ray";

describe("map heading ray", () => {
  it("extends ownship heading to the normalized map boundary", () => {
    expect(headingRayToMapEdge(.5, .5, 0)).toEqual({ start: [.5, .5], end: [.5, 0] });
    expect(headingRayToMapEdge(.25, .6, 90)).toEqual({ start: [.25, .6], end: [1, .6] });
    const diagonal = headingRayToMapEdge(.4, .7, 315);
    expect(diagonal?.end[0]).toBeCloseTo(0, 10);
    expect(diagonal?.end[1]).toBeCloseTo(.3, 10);
  });
});
