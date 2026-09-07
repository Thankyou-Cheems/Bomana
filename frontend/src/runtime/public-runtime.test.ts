import { describe, expect, it } from "vitest";
import { PublicRuntime } from "./public-runtime";
import { editionPolicy } from "./edition-policy";
import { publicFlight } from "./public-runtime-fixture";

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
