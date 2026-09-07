import { readFile } from "node:fs/promises";
import { describe, expect, it } from "vitest";
import { AircraftParameters, type AircraftParameterData } from "./aircraft-parameters";

const data: AircraftParameterData = {
  schema_version: 1,
  unit_to_fm: { variant_a: "shared", variant_b: "shared", missing: "absent" },
  flight_models: {
    shared: { speed: { ias: [[0, 1000], [.5, 1400], [1, 1600]], mach: [[0, 1], [1, 2]] },
      fuel: { engineType: "jet", modelConfidence: "reference-only", engines: [{ kind: "jet", consumption: [1, 1, 1, 2] }] } },
    absent: { speed: null, fuel: null },
  },
  loadouts: {
    variant_a: { name: "A", weapon_max_counts: { bomb: 2 } },
    variant_b: { name: "B", weapon_max_counts: { missile: 1 } },
  },
};

describe("shared aircraft parameter lookup", () => {
  it("shares flight characteristics without merging variant loadouts", () => {
    const parameters = new AircraftParameters(data);
    expect(parameters.fuel(" VARIANT_A ")).toBe(parameters.fuel("variant_b"));
    expect(parameters.speed("variant_a", .25)).toEqual({ ias: 1200, mach: 1.25, estimated: false });
    expect(parameters.strikeCatalog().aircraft).toEqual([
      { id: "variant_a", name: "A", weapon_max_counts: { bomb: 2 }, weapons: ["bomb"] },
      { id: "variant_b", name: "B", weapon_max_counts: { missile: 1 }, weapons: ["missile"] },
    ]);
    expect(parameters.speed("variant_a_guess", 1)).toBeNull();
    expect(parameters.speed("missing", 1)).toBeNull();
  });
  it("uses conservative limits when sweep telemetry is unavailable", () => {
    const parameters = new AircraftParameters(data);
    expect(parameters.speed("shared")).toEqual({ ias: 1000, mach: 1, estimated: true });
    expect(parameters.speed("shared", NaN)).toEqual(parameters.speed("shared"));
    expect(parameters.speed("shared", 2)).toEqual({ ias: 1600, mach: 2, estimated: false });
  });
  it("rejects missing bindings and invalid speed curves", () => {
    expect(() => AircraftParameters.parse({ ...data, unit_to_fm: { wrong: "unknown" } })).toThrow(/关联缺失/);
    expect(() => AircraftParameters.parse({ ...data, flight_models: { ...data.flight_models,
      shared: { speed: { ias: [[0, 1000], [0, 2000]], mach: null }, fuel: null } } })).toThrow(/速度参数/);
  });
  it("loads the shipped index and evaluates extracted F-14 sweep limits", async () => {
    const parameters = AircraftParameters.parse(JSON.parse(await readFile(new URL("../../../bomana/data/aircraft_parameters.json", import.meta.url), "utf8")));
    expect(parameters.speed("f_14a_early", .5)).toMatchObject({ ias: 1360, mach: 2, estimated: false });
    expect(parameters.speed("f_14a_early")).toMatchObject({ ias: 1021, mach: .96, estimated: true });
    expect(parameters.fuel("f_14a_early")?.modelConfidence).toBe("reference-only");
  });
});
