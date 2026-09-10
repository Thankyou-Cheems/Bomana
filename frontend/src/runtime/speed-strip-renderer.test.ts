import { describe, expect, it, vi } from "vitest";
import { SpeedStripRenderer, speedStripPresentation } from "./speed-strip-renderer";
import type { EditionSnapshot } from "./runtime-types";

function snapshot(options: {
  readonly iasKmh: number;
  readonly iasLimitKmh: number;
  readonly mach: number | null;
  readonly machLimit: number;
  readonly ratio: number;
  readonly level: "none" | "caution" | "warning" | "critical";
  readonly matched: boolean;
  readonly iasLimitSource?: "airframe" | "flaps";
}): EditionSnapshot {
  return {
    flight: {
      aircraft: "saab_jas39c_south_africa",
      iasKmh: options.iasKmh,
      mach: options.mach,
      overspeed: {
        level: options.level,
        ratio: options.ratio,
        iasLimitKmh: options.iasLimitKmh,
        machLimit: options.machLimit,
        matched: options.matched,
        iasLimitSource: options.iasLimitSource,
      },
    },
  } as EditionSnapshot;
}

describe("speed strip presentation", () => {
  it("combines IAS and Mach constraints exactly once for both main and PiP views", () => {
    const presentation = speedStripPresentation(snapshot({
      iasKmh: 900,
      iasLimitKmh: 1500,
      mach: 1.9,
      machLimit: 2,
      ratio: 0.6,
      level: "warning",
      matched: true,
    }));
    expect(presentation.stateText).toBe("接近极限");
    expect(presentation.valueText).toBe("95% · IAS 900/1500 · 结构");
    expect(presentation.machText).toBe("M1.90/2.00");
    expect(presentation.fillPercent).toBeGreaterThan(50);
    expect(presentation.markerPercents).toHaveLength(3);
  });

  it("labels the flap reference without claiming safe flight or masking Mach warnings", () => {
    const observed = { iasKmh: 100, iasLimitKmh: 400, mach: null, machLimit: 2,
      ratio: .25, level: "none" as const, matched: true, iasLimitSource: "flaps" as const };
    expect(speedStripPresentation(snapshot(observed))).toMatchObject({
      stateText: "速度参考", valueText: "25% · IAS 100/400 · 襟翼参考",
    });
    expect(speedStripPresentation(snapshot({ ...observed, mach: 1.99, level: "critical" })))
      .toMatchObject({ stateText: "超速危险", valueText: "100% · IAS 100/400 · 襟翼参考" });
  });

  it("shows a truthful empty scale before aircraft limits are matched", () => {
    const presentation = speedStripPresentation(snapshot({
      iasKmh: 0,
      iasLimitKmh: 0,
      mach: null,
      machLimit: 0,
      ratio: 0,
      level: "none",
      matched: false,
    }));
    expect(presentation).toMatchObject({ stateText: "速度监视", fillPercent: 0, valueText: "IAS --" });
  });

  it("places the colored bands and markers on the same expanded fixed scale", () => {
    const createElement = () => ({
      classList: { remove: vi.fn(), add: vi.fn() },
      style: { left: "", width: "", setProperty: vi.fn() },
      textContent: "",
    });
    const root = createElement();
    const track = createElement();
    const markers = [createElement(), createElement(), createElement()] as const;
    const renderer = new SpeedStripRenderer({
      root,
      state: createElement(),
      value: createElement(),
      mach: createElement(),
      track,
      fill: createElement(),
      markers,
    } as unknown as ConstructorParameters<typeof SpeedStripRenderer>[0]);
    renderer.update(snapshot({
      iasKmh: 1050,
      iasLimitKmh: 1500,
      mach: null,
      machLimit: 0,
      ratio: 0.7,
      level: "caution",
      matched: true,
    }));
    expect(track.style.setProperty).toHaveBeenCalledWith("--speed-caution", "64%");
    expect(track.style.setProperty).toHaveBeenCalledWith("--speed-warning", "82%");
    expect(track.style.setProperty).toHaveBeenCalledWith("--speed-critical", "95.2%");
    expect(markers.map(marker => marker.style.left)).toEqual(["64%", "82%", "95.2%"]);
  });
});
