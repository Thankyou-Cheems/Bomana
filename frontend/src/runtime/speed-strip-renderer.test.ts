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
    expect(presentation.stateText).toBe("减速");
    expect(presentation.levelClass).toBe("warning");
    expect(presentation.valueText).toBe("IAS 900/1500");
    expect(presentation.machText).toBe("95% · M1.90/2.00");
    expect(presentation.fillPercent).toBeCloseTo(43.75);
    expect(presentation.markerPercents).toEqual([25, 43.75, 62.5]);
  });

  it("labels the flap reference without claiming safe flight or masking Mach warnings", () => {
    const observed = { iasKmh: 100, iasLimitKmh: 400, mach: null, machLimit: 2,
      ratio: .25, level: "none" as const, matched: true, iasLimitSource: "flaps" as const };
    expect(speedStripPresentation(snapshot(observed))).toMatchObject({
      stateText: "襟翼参考", valueText: "IAS 100/400", machText: "25%",
    });
    expect(speedStripPresentation(snapshot({ ...observed, mach: 1.99, level: "critical" })))
      .toMatchObject({ stateText: "减速", levelClass: "warning", machText: "99.5% · M1.99/2.00" });
    expect(speedStripPresentation(snapshot({ ...observed, mach: 2, level: "critical" })))
      .toMatchObject({ stateText: "超限", levelClass: "critical", valueText: "IAS 100/400", machText: "100% · M2.00/2.00" });
    expect(speedStripPresentation(snapshot({ ...observed, mach: 1.9998, level: "none" })))
      .toMatchObject({ machText: "99.9% · M2.00/2.00", levelClass: "warning" });
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
    expect(presentation).toMatchObject({ stateText: "", fillPercent: 0, valueText: "IAS 0", machText: "", limitsKnown: false });
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
    expect(track.style.setProperty).toHaveBeenCalledWith("--speed-limit", "62.5%");
    expect(track.style.setProperty).toHaveBeenCalledWith("--speed-caution", "25%");
    expect(track.style.setProperty).toHaveBeenCalledWith("--speed-warning", "43.75%");
    expect(markers.map(marker => marker.style.left)).toEqual(["25%", "43.75%", "62.5%"]);
  });
});
