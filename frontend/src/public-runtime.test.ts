import { describe, expect, it } from "vitest";
import { PublicRuntime, type PublicFrame } from "./public-runtime";

const frame = (atMs: number): PublicFrame => ({
  sampledAtMs: atMs,
  connected: true,
  indicators: { valid: true, compass1: 0 },
  state: { "IAS, km/h": 500, "H, m": 3000, "Mfuel, kg": 900 },
  mapInfo: { map_min: [-50_000, -50_000], map_max: [50_000, 50_000] },
  mapObjects: [
    { type: "player", x: 0.5, y: 0.5 },
    { type: "bombing_point", x: 0.5, y: 0.3 },
    { type: "airfield", side: "friendly", sx: 0.2, sy: 0.7, ex: 0.2, ey: 0.8 },
    { type: "poi", x: 0.7, y: 0.2 },
    { type: "aircraft", side: "enemy", x: 0.7, y: 0.4 },
  ],
});

describe("public runtime", () => {
  it("keeps Lite timer-only", () => {
    const runtime = new PublicRuntime("Lite");
    const snapshot = runtime.ingest(frame(0));
    expect(snapshot.remainingSec).toBe(900);
    expect(snapshot.flight).toBeNull();
    expect(snapshot.targets).toEqual([]);
    expect(snapshot.target).toBeNull();
  });

  it("limits Standard navigation to official zones and airfields", () => {
    const runtime = new PublicRuntime("Standard");
    const snapshot = runtime.ingest(frame(0));
    expect(snapshot.targets.map((target) => target.kind).sort()).toEqual(["airfield", "zone"]);
    expect(snapshot.targets.every((target) => Number.isFinite(target.bearingDeg) && Number.isFinite(target.distanceKm))).toBe(true);
  });

  it("tracks timer cycles without an Enhanced adapter", () => {
    const runtime = new PublicRuntime("Standard", 15);
    runtime.ingest(frame(1_000));
    expect(runtime.ingest(frame(902_000))).toMatchObject({ cycle: 2, remainingSec: 899 });
  });
});
