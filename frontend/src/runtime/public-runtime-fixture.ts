import type { Official8111Frame } from "./telemetry-source";

export function publicFlight(at: number): Official8111Frame {
  return { sampledAtMs: at, bridgeReachable: true,
    indicators: { valid: true, type: "saab_jas39c", compass1: 0 },
    state: { valid: true, "IAS, km/h": 500, "TAS, km/h": 520, "Vy, m/s": 0, "H, m": 3000, "Mfuel, kg": 1000 - at / 1000, "Mfuel0, kg": 1200, "gear, %": 0, "throttle 1, %": 90 },
    mapObjects: [{ type: "player", x: .5, y: .5 - at * .000002, dx: 0, dy: -1 },
      { type: "bombing_point", x: .5, y: .3 }, { type: "airfield", side: "friendly", sx: .2, sy: .7, ex: .2, ey: .8 },
      { type: "point_of_interest", x: .51, y: .3 }, { type: "aircraft", color: "#ff0000", x: .5, y: .4 }],
    mapInfo: { valid: true, map_min: [-50000, -50000], map_max: [50000, 50000] },
    availability: { indicators: true, state: true, mapObjects: true, mapInfo: true } };
}
