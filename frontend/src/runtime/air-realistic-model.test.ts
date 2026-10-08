import { describe, expect, it } from "vitest";
import { PublicRuntime } from "./public-runtime";
import { editionPolicy } from "./edition-policy";
import { speedStripPresentation } from "./speed-strip-renderer";
import type { Official8111Frame } from "./telemetry-source";
import { AirMapAutoRange, airMapAircraftAngle, airMapMarker, airMapOffset, airMapRings, airRealisticSituation } from "./air-realistic-model";

const objects = [
  { type: "player", x: .5, y: .5, dx: 0, dy: -1 },
  { type: "aircraft", side: "hostile", x: .53, y: .46 },
  { type: "aircraft", side: "friendly", x: .501, y: .501 },
  { type: "tank", side: "hostile", x: .501, y: .501 },
  { type: "aircraft", x: .501, y: .501 },
];
function frame(at: number, mapObjects: readonly Record<string, unknown>[] = objects): Official8111Frame {
  return { sampledAtMs: at, mapObjectsSampledAtMs: at, bridgeReachable: true,
    indicators: { valid: true, type: "test", compass1: 0 }, state: { valid: true, "IAS, km/h": 600, "H, m": 2000 },
    mapInfo: { valid: true, map_min: [0, 0], map_max: [100000, 50000] }, mapObjects,
    availability: { indicators: true, state: true, mapObjects: true, mapInfo: true } };
}
function runtime() { return new PublicRuntime({ edition: editionPolicy("Standard"), now: () => 10000 }); }

describe("Air Realistic current map observations", () => {
  it("positions live bombing zones independently of aircraft and clears vanished or stale zones", async () => {
    const source = runtime();
    const snapshot = await source.ingest(frame(10000, [...objects,
      { type: "bombing_point", side: "hostile", x: .53, y: .46 },
    ]));
    const situation = airRealisticSituation(snapshot, 20);
    expect(situation.zones).toHaveLength(1);
    expect(situation.zones[0]!.eastM).toBeCloseTo(3000);
    expect(situation.zones[0]!.southM).toBeCloseTo(-2000);
    expect(situation.zones[0]!.distanceKm).toBeCloseTo(Math.sqrt(13));
    expect(situation.contacts).toHaveLength(1);
    expect(airRealisticSituation({ ...snapshot, mapObjectsFresh: false }, 20).zones).toHaveLength(0);
    expect(airRealisticSituation(snapshot, 20, 11501).zones).toHaveLength(0);
    expect(airRealisticSituation({ ...snapshot, connected: false }, 20).zones).toHaveLength(0);
    expect(airRealisticSituation(await source.ingest(frame(10250)), 20).zones).toHaveLength(0);
  });
  it("aligns aircraft to official direction on both map orientations from the first observation", async () => {
    const snapshot = await runtime().ingest(frame(10000, [objects[0]!,
      { type: "aircraft", side: "hostile", icon: "Fighter", x: .53, y: .46, dx: 1, dy: -1 },
    ]));
    const item = airRealisticSituation(snapshot, 20).contacts[0]!.item;
    // Direction is independent of the non-square map dimensions and overrides ground track.
    const velocity = { eastMps: 0, southMps: 100 };
    expect(airMapAircraftAngle(item, velocity, 90, false)).toBeCloseTo(Math.PI / 4);
    expect(airMapAircraftAngle(item, velocity, 90, true)).toBeCloseTo(-Math.PI / 4);
    for (const [dx, dy, angle] of [[0, -1, 0], [1, 0, Math.PI / 2], [0, 1, Math.PI], [-1, 0, -Math.PI / 2]]) {
      expect(airMapAircraftAngle({ dx, dy }, null, 0, true)).toBeCloseTo(angle!);
    }
  });
  it("uses a valid moving ground track only when official direction is unavailable", () => {
    for (const item of [{}, { dx: 0, dy: 0 }, { dx: NaN, dy: -1 }, { dx: 1 }]) {
      expect(airMapAircraftAngle(item, { eastMps: 100, southMps: 0 }, 90, true)).toBeCloseTo(0);
      expect(airMapAircraftAngle(item, null, 90, true)).toBeNull();
      expect(airMapAircraftAngle(item, { eastMps: 1, southMps: 0 }, 90, true)).toBeNull();
      expect(airMapAircraftAngle(item, { eastMps: Infinity, southMps: 0 }, 90, true)).toBeNull();
    }
  });
  it("keeps friendly aircraft display-only and expires them with map observations", async () => {
    const source = runtime();
    const snapshot = await source.ingest(frame(10000, [...objects,
      { type: "ground_model", side: "friendly", icon: "Fighter", x: .52, y: .52 },
      { type: "aircraft", color: "#174DFF", icon: "Bomber", x: .55, y: .55, dx: 0, dy: 1 },
    ]));
    expect(snapshot.navigation?.friendlyAircraft).toHaveLength(2);
    expect(snapshot.navigation?.items.some(item => item.friendly && item.aircraft)).toBe(false);
    expect(airRealisticSituation(snapshot, 20).teammates).toHaveLength(2);
    expect(airMapAircraftAngle(snapshot.navigation!.friendlyAircraft![1]!, null, 90, true)).toBeCloseTo(Math.PI / 2);
    expect(airMapAircraftAngle(snapshot.navigation!.friendlyAircraft![0]!, null, 90, true)).toBeNull();
    expect(airRealisticSituation(snapshot, 20, 11501).teammates).toHaveLength(0);
    expect(airRealisticSituation({ ...snapshot, mapObjectsFresh: false }, 20).teammates).toHaveLength(0);
    expect(airRealisticSituation(await source.ingest(frame(10250, [objects[0]!])), 20).teammates).toHaveLength(0);
  });
  it("retains the 20 km auto-range ceiling", () => {
    const range = new AirMapAutoRange();
    let result = 0;
    for (let at = 0; at <= 6000; at += 50) {
      result = range.update([30, 40, 50], true, at);
      expect(result).toBeLessThanOrEqual(20);
    }
    expect(result).toBeCloseTo(20, 2);
  });
  it("draws equally spaced rings in the current metric scale without extra wording", () => {
    for (const ppm of [.009, .036, .08]) {
      const rings = airMapRings(ppm, 144);
      expect(rings.length).toBeGreaterThanOrEqual(3);
      rings.forEach((ring, index) => {
        expect(ring.radiusPx).toBeCloseTo(rings[0]!.radiusPx * (index + 1), 8);
        expect(ring.radiusPx).toBeLessThanOrEqual(144);
        expect(ring.label).toMatch(/^\d+(\.\d+)? (km|m)$/);
        const metres = parseFloat(ring.label) * (ring.label.endsWith('km') ? 1000 : 1);
        expect(ring.radiusPx).toBeCloseTo(metres * ppm, 6);
      });
    }
  });
  it("keeps current speed when the map fails, but expires held or stopped speed observations", async () => {
    const source = runtime();
    await source.ingest(frame(10000));
    const input = { ...frame(10250), mapObjects: null,
      availability: { ...frame(10250).availability, mapObjects: false } };
    const observed = await source.ingest(input);
    expect(observed.connected).toBe(false);
    expect(observed.speedSampledAtMs).toBe(10250);
    const snapshot = { ...observed, flight: { ...observed.flight,
      overspeed: { level: "critical" as const, ratio: 1.2, iasLimitKmh: 500, machLimit: 0, matched: true } } };
    expect(speedStripPresentation(snapshot)).toMatchObject({ valueText: "IAS 600/500", levelClass: "critical", limitsKnown: true });
    expect(speedStripPresentation(snapshot, 11751)).toMatchObject({ valueText: "IAS —", limitsKnown: false });
    for (const route of ["state", "indicators"] as const) {
      const held = await source.ingest({ ...input, holdover: { state: false, indicators: false, mapObjects: false, [route]: true } });
      expect(held.speedSampledAtMs).toBeNull();
      expect(speedStripPresentation(held).valueText).toBe("IAS —");
    }
  });
  it("excludes official ground and mission objects without guessing which aircraft are AI", async () => {
    const red = { color: "#fa0C00", "color[]": [250, 12, 0], x: .53, y: .46 };
    const air = ["Fighter", "Assault", "Bomber", "unrecognized-role"].map(icon => ({ ...red, type: "aircraft", icon }));
    const ground = ["LightTank", "MediumTank", "TankDestroyer", "SPAA", "SAM", "Fighter"].map(icon => ({ ...red, type: "ground_model", icon }));
    const snapshot = await runtime().ingest(frame(10000, [
      objects[0]!, ...air, ...ground,
      { ...red, type: "capture_zone", icon: "Fighter" },
      { ...red, type: "unknown", icon: "Fighter" },
      { ...red, type: "aircraft", icon: "Fighter", color: "#174DFF", "color[]": [23, 77, 255] },
    ]));
    expect(airRealisticSituation(snapshot, 5).contacts).toHaveLength(4);
    expect(snapshot.navigation?.aircraftObservations?.map(item => item.officialIcon))
      .toEqual(["Fighter", "Assault", "Bomber", "unrecognized-role"]);
  });
  it("uses rectangular corners and projects off-map contacts onto the correct edge", () => {
    expect(airMapMarker(90, 90, 100, 100).outside).toBe(false);
    expect(airMapMarker(300, 150, 100, 80)).toMatchObject({ x: 100, y: 50, outside: true });
    expect(airMapMarker(-40, -200, 100, 80)).toMatchObject({ x: -16, y: -80, outside: true });
  });
  it("zooms to nearby contacts smoothly without an isolated far target crushing the view", () => {
    const range = new AirMapAutoRange();
    expect(range.update([3, 4, 5, 90], true, 0)).toBe(5);
    let result = 0;
    for (let at = 50; at <= 2000; at += 50) result = range.update([3, 4, 5, 90], true, at);
    expect(result).toBeCloseTo(6.5, 1);
    const previous = result;
    for (let at = 2050; at <= 4000; at += 50) result = range.update([1], true, at);
    expect(result).toBeGreaterThanOrEqual(previous);
    for (let at = 4050; at <= 9000; at += 50) result = range.update([1], true, at);
    expect(result).toBeLessThan(2.3);
  });
  it("keeps the view range when contacts vanish or become stale", () => {
    const range = new AirMapAutoRange();
    range.update([4], true, 0);
    // 4 * 1.3 is inside the expansion deadband around 5 km.
    for (let at = 50; at < 5000; at += 50) expect(range.update([], at < 1000, at)).toBe(5);
  });
  it("uses only explicitly hostile aircraft and scales each map axis in metres", async () => {
    const snapshot = await runtime().ingest(frame(10000));
    const situation = airRealisticSituation(snapshot, 5);
    expect(situation.contacts).toHaveLength(1);
    expect(situation.contacts[0]!.distanceKm).toBeCloseTo(Math.hypot(3, 2), 8);
    expect(situation.contacts[0]!.clock).toBe(2);
    expect(airRealisticSituation(snapshot, 2).nearby).toHaveLength(0);
  });
  it("clears a disappeared aircraft immediately, including a successful empty response", async () => {
    const source = runtime();
    expect(airRealisticSituation(await source.ingest(frame(10000)), 10).contacts).toHaveLength(1);
    expect(airRealisticSituation(await source.ingest(frame(10250, objects.slice(0, 1))), 10).contacts).toHaveLength(0);
    expect(airRealisticSituation(await source.ingest(frame(10500, [])), 10).contacts).toHaveLength(0);
  });
  it("does not replay enemies from a failed acquisition even inside the 3-second Holdover", async () => {
    const source = runtime();
    await source.ingest(frame(10000));
    const held = await source.ingest({ ...frame(10250), mapObjectsSampledAtMs: 10000,
      holdover: { state: false, indicators: false, mapObjects: true } });
    expect(held.mapObjectsFresh).toBe(false);
    expect(airRealisticSituation(held, 10).contacts).toHaveLength(0);
  });
  it("expires enemies if updates stop, and fails closed for older snapshots without freshness", async () => {
    const snapshot = await runtime().ingest(frame(10000));
    expect(airRealisticSituation(snapshot, 10, 11501).contacts).toHaveLength(0);
    expect(airRealisticSituation(snapshot, 10, 13001).available).toBe(false);
    expect(airRealisticSituation({ ...snapshot, mapObjectsFresh: undefined }, 10).contacts).toHaveLength(0);
    expect(airRealisticSituation({ ...snapshot, connected: false }, 10).available).toBe(false);
  });
  it("rotates geometry without changing its distance and keeps north-up independent of heading", () => {
    const east = airMapOffset(1000, 0, 90, true);
    expect(east.x).toBeCloseTo(0); expect(east.y).toBeCloseTo(-1000);
    expect(airMapOffset(1000, 0, 90, false)).toEqual({ x: 1000, y: 0 });
    const diagonal = airMapOffset(3000, -2000, 123, true);
    expect(Math.hypot(diagonal.x, diagonal.y)).toBeCloseTo(Math.hypot(3000, 2000));
  });
});
