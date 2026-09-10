import { describe, expect, it } from "vitest";
import { PublicRuntime } from "./public-runtime";
import { editionPolicy } from "./edition-policy";
import { publicFlight } from "./public-runtime-fixture";
import { AircraftParameters } from "./aircraft-parameters";
import speedCases from "./speed-limit-cases.json";

describe("public runtime boundary", () => {
  it("keeps Standard navigation restricted and rejects private commands", async () => {
    const runtime = new PublicRuntime({ edition: editionPolicy("Standard") });
    await runtime.ingest(publicFlight(0)); const result = await runtime.ingest(publicFlight(2000));
    expect(result.navigation?.items.map((item) => item.kind).sort()).toEqual(["airfield", "zone"]);
    expect(result.strike).toBeNull(); expect(result.markedZones).toEqual([]); expect(result.gameChat).toEqual([]);
    await expect(runtime.command({ type: "navigation.set-poi", x: .3, y: .3 })).rejects.toThrow("disabled");
    await expect(runtime.command({ type: "strike.select-weapon", weaponId: "test" })).rejects.toThrow("disabled");
  });
  it("keeps Lite timer only while retaining sortie continuity", async () => {
    const runtime = new PublicRuntime({ edition: editionPolicy("Lite") });
    await runtime.ingest(publicFlight(0)); const result = await runtime.ingest(publicFlight(2000));
    expect(result.timer.remainingSec).not.toBeNull(); expect(result.navigation).toBeNull(); expect(result.fuel).toBeNull();
  });
});

describe("current flap speed constraint", () => {
  const profile = { gearIasKmh: 500, gearControl: true,
    flapsIasKmh: [[0, 600], [.2, 420], [.4, 360], [1, 300]] as const, flapsControl: false };
  function runtime(ias: number | null = 1000, curve = true) {
    return new PublicRuntime({ edition: editionPolicy("Standard"), aircraftParameters: new AircraftParameters({
      schema_version: 1, unit_to_fm: { saab_jas39c: "test" }, loadouts: {},
      flight_models: { test: { speed: { ias, mach: 2 }, fuel: null,
        landing: { ...profile, flapsIasKmh: curve ? profile.flapsIasKmh : null } } },
    }) });
  }
  it.each(speedCases)("$name", async test => {
    const frame = publicFlight(2000);
    const result = await runtime(test.airframeIas, test.curve).ingest({ ...frame,
      state: { ...frame.state, "IAS, km/h": test.ias, "flaps, %": test.flaps, M: test.mach } });
    expect(result.flight.overspeed).toMatchObject(test.expected);
    expect(result.landing?.settings.enabled).toBe(false);
  });
  it("withdraws held, stale, invalid or missing flap observations without depending on map or landing mode", async () => {
    const manager = runtime(), original = publicFlight(2000);
    const frame = { ...original, state: { ...original.state, "IAS, km/h": 400, "flaps, %": 25 } };
    const unavailable = { ...frame.availability, state: false };
    for (const invalid of [
      { ...frame, holdover: { state: true, indicators: false, mapObjects: false } },
      { ...frame, holdover: { state: false, indicators: true, mapObjects: false } },
      { ...frame, stateSampledAtMs: 400 }, { ...frame, indicatorsSampledAtMs: 400 },
      { ...frame, state: { ...frame.state, valid: false } },
      { ...frame, indicators: { ...frame.indicators, valid: false } },
      { ...frame, state: { ...frame.state, "IAS, km/h": null } },
      { ...frame, availability: unavailable },
      { ...frame, availability: { ...frame.availability, indicators: false } },
    ]) {
      expect((await manager.ingest(frame)).flight.overspeed.iasLimitKmh).toBe(405);
      expect((await manager.ingest(invalid)).flight.overspeed).toMatchObject({ iasLimitKmh: 1000, iasLimitSource: "airframe" });
    }
    const mapMissing = await manager.ingest({ ...frame, mapObjects: null,
      availability: { ...frame.availability, mapObjects: false } });
    expect(mapMissing.flight.overspeed).toMatchObject({ iasLimitKmh: 405, level: "warning", iasLimitSource: "flaps" });
    expect(mapMissing.alerts).toContain("接近襟翼参考限速");
    expect((await manager.ingest({ ...frame, indicators: { valid: true, type: "unknown" } }))
      .flight.overspeed).toMatchObject({ matched: false, iasLimitKmh: 0 });
  });
});
