import { describe, expect, it } from "vitest";
import { PublicRuntime } from "./public-runtime";
import { MemorySortieRecoveryStore } from "./sortie-recovery";
import { editionPolicy } from "./edition-policy";
import { publicFlight } from "./public-runtime-fixture";
import { AircraftParameters } from "./aircraft-parameters";
import speedCases from "./speed-limit-cases.json";
import { airRealisticSituation } from "./air-realistic-model";

describe("public runtime boundary", () => {
  it.each([1000, 4700])("counts spawn confirmation latency (%i ms) in the cycle", async delayMs => {
    const runtime = new PublicRuntime({ edition: editionPolicy("Lite") });
    expect((await runtime.ingest(publicFlight(1000))).timer.remainingSec).toBeNull();
    expect((await runtime.ingest(publicFlight(1000 + delayMs))).timer.remainingSec).toBeCloseTo(900 - delayMs / 1000, 6);
    const nextCycle = await runtime.ingest({ ...publicFlight(1000), sampledAtMs: 901250 });
    expect(nextCycle.timer.cycle).toBe(2);
    expect(nextCycle.timer.remainingSec).toBeCloseTo(899.75, 6);
  });
  it("requires fresh spawn observations after a held or missing route", async () => {
    const runtime = new PublicRuntime({ edition: editionPolicy("Lite"), now: () => 4000 });
    await runtime.ingest(publicFlight(1000));
    const held = publicFlight(2500);
    expect((await runtime.ingest({ ...held, holdover: { indicators: true, state: false, mapObjects: false } })).timer.remainingSec).toBeNull();
    expect((await runtime.ingest(publicFlight(3000))).timer.remainingSec).toBeNull();
    expect((await runtime.ingest(publicFlight(4000))).timer.remainingSec).toBe(899);
    await runtime.command({ type: "timer.reset" });
    expect(runtime.snapshot().timer.remainingSec).toBe(900);
  });
  it("does not anchor a spawn to an explicitly invalid state", async () => {
    const runtime = new PublicRuntime({ edition: editionPolicy("Lite") });
    const invalid = publicFlight(1000);
    await runtime.ingest({ ...invalid, state: { ...invalid.state, valid: false } });
    expect((await runtime.ingest(publicFlight(3000))).timer.remainingSec).toBeNull();
    expect((await runtime.ingest(publicFlight(4000))).timer.remainingSec).toBe(899);
  });
  it("keeps Standard navigation restricted and rejects private commands", async () => {
    const runtime = new PublicRuntime({ edition: editionPolicy("Standard") });
    await runtime.ingest(publicFlight(0)); const result = await runtime.ingest(publicFlight(2000));
    expect(result.navigation?.items.map((item) => item.kind).sort()).toEqual(["airfield", "zone"]);
    expect(result.navigation?.aircraftObservations).toHaveLength(1);
    expect(airRealisticSituation(result, 20).contacts).toHaveLength(1);
    expect(result.strike).toBeNull(); expect(result.markedZones).toEqual([]); expect(result.gameChat).toEqual([]);
    await expect(runtime.command({ type: "navigation.set-poi", x: .3, y: .3 })).rejects.toThrow("disabled");
    await expect(runtime.command({ type: "strike.select-weapon", weaponId: "test" })).rejects.toThrow("disabled");
  });
  it("keeps Lite timer only while retaining sortie continuity", async () => {
    const runtime = new PublicRuntime({ edition: editionPolicy("Lite") });
    await runtime.ingest(publicFlight(0)); const result = await runtime.ingest(publicFlight(2000));
    expect(result.timer.remainingSec).not.toBeNull(); expect(result.navigation).toBeNull(); expect(result.fuel).toBeNull();
  });
  it("withdraws Standard aircraft observations on held, stale and empty map data", async () => {
    const runtime = new PublicRuntime({ edition: editionPolicy("Standard") });
    await runtime.ingest(publicFlight(0));
    const original = publicFlight(2000);
    const frame = { ...original, mapObjects: [...original.mapObjects as Record<string, unknown>[],
      { type: "aircraft", side: "friendly", icon: "fighter", x: .55, y: .4, dx: 1, dy: 0 },
      { type: "tank", side: "hostile", icon: "fighter", x: .55, y: .4 },
      { type: "aircraft", side: "hostile", x: 1.5, y: .4 }] };
    const snapshot = await runtime.ingest(frame);
    const situation = airRealisticSituation(snapshot, 20);
    expect(situation.contacts).toHaveLength(1);
    expect(situation.teammates).toHaveLength(1);
    expect(snapshot.navigation?.items.every(item => item.kind === "zone" || item.kind === "airfield")).toBe(true);
    expect(airRealisticSituation(snapshot, 20, 3501).contacts).toEqual([]);
    const held = await runtime.ingest({ ...publicFlight(2100), mapObjectsSampledAtMs: 2000,
      holdover: { mapObjects: true, indicators: false, state: false }, mapObjects: frame.mapObjects });
    expect(airRealisticSituation(held, 20).contacts).toEqual([]);
    expect(airRealisticSituation(held, 20).teammates).toEqual([]);
    const empty = await runtime.ingest({ ...publicFlight(2200), mapObjects: [{ type: "player", x: .5, y: .49 }] });
    expect(empty.navigation?.aircraftObservations).toEqual([]);
    expect(airRealisticSituation(empty, 20).contacts).toEqual([]);
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
    expect(mapMissing.alerts).toContain("接近襟翼参考限速，请减速");
    expect(mapMissing.alerts).not.toContain("达到襟翼参考限速");
    const exceeded = await manager.ingest({ ...frame, state: { ...frame.state, "IAS, km/h": 406 } });
    expect(exceeded.alerts).toContain("达到襟翼参考限速");
    expect((await manager.ingest({ ...frame, indicators: { valid: true, type: "unknown" } }))
      .flight.overspeed).toMatchObject({ matched: false, iasLimitKmh: 0 });
  });
});

// Synthetic official-route inputs, not a recording of the game's return warning.
describe("map-edge sortie continuity", () => {
  const edgePlayer = { type: "player", x: .999, y: .5, dx: 1, dy: 0 };
  const observation = (at: number, player: Record<string, unknown> | null = edgePlayer) => {
    const frame = publicFlight(at);
    return { ...frame, mapObjects: [...(player ? [player] : []),
      { type: "bombing_point", x: .5, y: .3 }] };
  };
  async function flying(channel: "Lite" | "Standard" | "Enhanced" = "Standard") {
    const runtime = new PublicRuntime({ edition: editionPolicy(channel), now: () => 2_000 });
    await runtime.ingest(observation(0));
    await runtime.ingest(observation(1_000));
    await runtime.ingest(observation(1_500));
    return runtime;
  }

  it.each(["Lite", "Standard", "Enhanced"] as const)("keeps %s's original cycle through edge loss and return", async channel => {
    const runtime = await flying(channel);
    const missing = await runtime.ingest(observation(1_600, null));
    expect(missing.phase).toBe("alive");
    expect(missing.timer.remainingSec).toBe(898.4);
    expect(missing.sortieContinuity).toMatchObject({ state: "partial-data", resetUndo: null });
    expect(missing.navigation?.player ?? null).toBeNull();
    const waiting = await runtime.ingest(observation(46_000, null));
    expect(waiting.timer.remainingSec).toBe(854);
    const returned = await runtime.ingest(observation(46_100, { ...edgePlayer, x: .8, dx: -1 }));
    expect(returned).toMatchObject({ phase: "alive", timer: { lifeIndex: 1, remainingSec: 853.9 },
      sortieContinuity: { state: "live", resetUndo: null } });
  });

  it.each([15, 20, 30, 45])("keeps the original cycle through %i seconds of fresh flight with no map marker", async durationSec => {
    const runtime = await flying();
    for (let elapsedSec = 0; elapsedSec <= durationSec; elapsedSec += 1) {
      const at = 1_600 + elapsedSec * 1_000;
      const snapshot = await runtime.ingest(observation(at, null));
      expect(snapshot).toMatchObject({ phase: "alive", timer: { lifeIndex: 1, remainingSec: 900 - at / 1_000 },
        sortieContinuity: { state: "partial-data", graceExpiresAtMs: null, resetUndo: null } });
      expect(snapshot.navigation?.player).toBeNull();
    }
    const at = 1_700 + durationSec * 1_000;
    const returned = await runtime.ingest(observation(at, { ...edgePlayer, x: .8, dx: -1 }));
    expect(returned).toMatchObject({ phase: "alive", timer: { lifeIndex: 1, remainingSec: 900 - at / 1_000 },
      sortieContinuity: { state: "live", resetUndo: null } });
  });

  it.each([
    { x: .001, y: .5, dx: -1, dy: 0 }, { x: .5, y: .001, dx: 0, dy: -1 },
    { x: .5, y: .999, dx: 0, dy: 1 }, { x: 1.01, y: .5, dx: -1, dy: 0 },
  ])("recognizes all edges and already off-map ownship: %j", async point => {
    const runtime = await flying();
    await runtime.ingest(observation(1_500, { type: "player", ...point }));
    expect((await runtime.ingest(observation(1_600, null))).timer.remainingSec).toBe(898.4);
  });

  it("does not let repeated missing markers extend the sixty-second bound", async () => {
    const runtime = await flying();
    for (const at of [1_600, 20_000, 61_599]) {
      expect((await runtime.ingest(observation(at, null))).phase).toBe("alive");
    }
    expect(await runtime.ingest(observation(61_600, null))).toMatchObject({
      phase: "wait-next", timer: { remainingSec: null },
      sortieContinuity: { resetUndo: { reason: "aircraft-loss" } },
    });
  });

  it.each([
    { name: "interior", player: { ...edgePlayer, x: .5 } },
    { name: "inward motion", player: { ...edgePlayer, dx: -1 } },
    { name: "almost parallel motion", player: { ...edgePlayer, dx: .001, dy: 1 } },
  ])("preserves immediate aircraft-loss for $name", async ({ player }) => {
    const runtime = await flying();
    await runtime.ingest(observation(1_500, player));
    expect((await runtime.ingest(observation(1_600, null))).sortieContinuity.resetUndo?.reason).toBe("aircraft-loss");
  });

  it("rejects stale boundary evidence and current invalid/grounded death evidence", async () => {
    for (const change of [
      { sampledAtMs: 3_001 },
      { state: { ...observation(1_600).state, valid: false } },
      { indicators: { valid: false } },
      { state: { ...observation(1_600).state, "IAS, km/h": 0, "Vy, m/s": 0 } },
    ]) {
      const runtime = await flying();
      const result = await runtime.ingest({ ...observation(1_600, null), ...change });
      expect(result.sortieContinuity.resetUndo?.reason).toBe("aircraft-loss");
    }
  });

  it("preserves an admitted boundary gap through incomplete fields but expires unconfirmed loss after twelve seconds", async () => {
    const runtime = await flying();
    await runtime.ingest(observation(1_600, null));
    const incomplete = (at: number) => ({ ...observation(at, null), indicators: {}, state: {} });
    for (const at of [2_000, 4_000, 13_999]) {
      expect(await runtime.ingest(incomplete(at))).toMatchObject({ phase: "alive",
        sortieContinuity: { state: "no-data-grace", graceExpiresAtMs: 14_000 } });
    }
    expect((await runtime.ingest(incomplete(14_000))).sortieContinuity.resetUndo?.reason).toBe("telemetry-timeout");
  });

  it("retains short bridge gaps and their original twelve-second timeout", async () => {
    const runtime = await flying();
    await runtime.ingest(observation(1_600, null));
    const disconnected = (at: number) => ({ ...observation(at, null), bridgeReachable: false,
      indicators: null, state: null, mapObjects: null,
      availability: { indicators: false, state: false, mapObjects: false, mapInfo: true } });
    await runtime.ingest(disconnected(2_000));
    expect((await runtime.ingest(disconnected(4_000))).timer.remainingSec).toBe(896);
    expect((await runtime.ingest(observation(4_100))).timer.remainingSec).toBe(895.9);
    await runtime.ingest(disconnected(5_000));
    expect((await runtime.ingest(disconnected(17_000))).sortieContinuity.resetUndo?.reason).toBe("telemetry-timeout");
  });

  it("does not extend the boundary deadline by losing the map route just before expiry", async () => {
    const runtime = await flying();
    await runtime.ingest(observation(1_600, null));
    await runtime.ingest(observation(61_000, null));
    const unavailable = (at: number) => ({ ...observation(at, null), mapObjects: null,
      availability: { ...observation(at).availability, mapObjects: false } });
    expect(await runtime.ingest(unavailable(61_500))).toMatchObject({ phase: "alive",
      sortieContinuity: { graceExpiresAtMs: 61_600 } });
    expect((await runtime.ingest(unavailable(61_600))).sortieContinuity.resetUndo?.reason).toBe("telemetry-timeout");
  });

  it("does not revive an expired boundary absence when the next poll returns after suspension", async () => {
    const runtime = await flying();
    await runtime.ingest(observation(1_600, null));
    expect((await runtime.ingest(observation(80_000))).timer.remainingSec).toBeNull();
    expect((await runtime.ingest(observation(81_000))).timer.remainingSec).toBe(899);
  });

  it("starts a new cycle when a different aircraft or map first returns with a player", async () => {
    for (const changed of [
      { mapInfo: { valid: true, map_min: [0, 0], map_max: [200_000, 200_000] } },
      { indicators: { valid: true, type: "other_aircraft" } },
    ]) {
      const runtime = await flying();
      await runtime.ingest(observation(1_600, null));
      const returned = await runtime.ingest({ ...observation(2_000), ...changed });
      expect(returned.timer.remainingSec).toBeNull();
      expect((await runtime.ingest({ ...observation(3_000), ...changed })).timer.remainingSec).toBe(899);
    }
  });

  it("clears persisted old-map undo immediately, including reopen before the next periodic save", async () => {
    const store = new MemorySortieRecoveryStore();
    const runtime = new PublicRuntime({ edition: editionPolicy("Standard"), sortieRecoveryStore: store, now: () => 0 });
    await runtime.ingest(observation(0)); await runtime.ingest(observation(1_000));
    await runtime.ingest(observation(1_500)); await runtime.ingest(observation(1_600, null));
    await runtime.ingest({ ...observation(2_000), mapInfo: { valid: true, map_min: [0, 0], map_max: [200_000, 200_000] } });
    expect(store.value).toBeNull();
    const reopened = new PublicRuntime({ edition: editionPolicy("Standard"), sortieRecoveryStore: store, now: () => 2_100 });
    expect(reopened.snapshot().sortieContinuity.resetUndo).toBeNull();
  });

  it.each(["invalid", "grounded", "changed-aircraft"])("ends boundary context on %s even while map reads fail", async kind => {
    const runtime = await flying();
    await runtime.ingest(observation(1_600, null));
    const failed = { ...observation(2_000, null), mapObjects: null,
      availability: { ...observation(2_000).availability, mapObjects: false } };
    const changed = kind === "invalid" ? { indicators: { valid: false } }
      : kind === "changed-aircraft" ? { indicators: { valid: true, type: "other_aircraft" } }
        : { state: { ...failed.state, "IAS, km/h": 0, "Vy, m/s": 0 } };
    await runtime.ingest({ ...failed, ...changed });
    expect((await runtime.ingest(observation(2_100, null))).timer.remainingSec).toBeNull();
  });

  it("does not carry boundary evidence through manual reset, exit, respawn or changed map/aircraft", async () => {
    const manual = await flying();
    await manual.command({ type: "timer.reset" });
    expect((await manual.ingest(observation(2_100, null))).sortieContinuity.resetUndo?.reason).toBe("aircraft-loss");
    for (const changed of [
      { mapInfo: { valid: true, map_min: [0, 0], map_max: [200_000, 200_000] } },
      { indicators: { valid: true, type: "other_aircraft" } },
    ]) {
      const runtime = await flying();
      await runtime.ingest(observation(1_600, null));
      expect((await runtime.ingest({ ...observation(2_000, null), ...changed })).timer.remainingSec).toBeNull();
      await runtime.ingest({ ...observation(3_000), ...changed });
      expect((await runtime.ingest({ ...observation(4_000), ...changed })).timer.remainingSec).toBe(899);
    }
    const runtime = await flying();
    await runtime.ingest(observation(1_600, null));
    const hangar = (at: number) => ({ ...observation(at, null), mapObjects: [],
      indicators: { valid: false }, state: { valid: false } });
    await runtime.ingest(hangar(2_000));
    await runtime.ingest(hangar(2_100));
    expect((await runtime.ingest(hangar(3_400))).phase).toBe("hangar");
    await runtime.ingest(observation(4_000));
    expect((await runtime.ingest(observation(5_000))).timer).toMatchObject({ lifeIndex: 1, remainingSec: 899 });
  });
});
