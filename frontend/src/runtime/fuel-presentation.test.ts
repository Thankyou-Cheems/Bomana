import { describe, expect, it } from "vitest";
import { FuelManager, type FuelSnapshot } from "./fuel-management";
import { fuelPresentation, fuelEndurance } from "./fuel-presentation";

function snapshot(change: Partial<FuelSnapshot>): FuelSnapshot {
  return { ...new FuelManager().view(0, false, null, false), ...change };
}

describe("fuel presentation", () => {
  it("shows a measured budget and reserve on the same scale as current fuel", () => {
    expect(fuelPresentation(snapshot({ available: true, currentKg: 800, initialKg: 1200,
      rateKgMin: 50, stable: true, source: "measured", remainingMinutes: 16, regime: "cruise",
      returnNeededKg: 300, returnStatus: "safe", marginKg: 500, tripKg: 50, reserveKg: 250,
      returnDistanceKm: 10, returnTargetLabel: "友方机场 1", reason: "ready" }))).toMatchObject({
      currentTotal: "燃油 800 / 1,200 kg", consumption: "巡航 50 kg/min  ≈16:00",
      returnRequirement: "返航 300 kg", balance: "余量 +500 kg",
      currentPercent: 800 / 1200 * 100, returnMarkerPercent: 25, returnAvailable: true, tone: "safe",
      sourceLabel: "实测",
    });
  });

  it("explains the missing input instead of displaying a zero return requirement", () => {
    const result = fuelPresentation(snapshot({ reason: "no-track", available: true, currentKg: 1000 }));
    expect(result.detail).toContain("等待有效地速");
    expect(result.currentTotal).toContain("/ —");
    expect(result.returnAvailable).toBe(false);
    expect(result.returnRequirement).toBe("返航 —");
  });

  it("labels calibrated fallback estimates without a positive return verdict", () => {
    const result = fuelPresentation(snapshot({ available: true, source: "aircraft-estimate", currentKg: 1000,
      rateKgMin: 100, remainingMinutes: 10, marginKg: 300, returnNeededKg: 700,
      returnDistanceKm: 30, tripKg: 200, reserveKg: 500, reason: "ready" }));
    expect(result.sourceLabel).toBe("已校准参考");
    expect(result.returnRequirement).toBe("返航参考 700 kg");
    expect(result.tone).toBe("unknown");
    expect(fuelEndurance(snapshot({ available: true, currentKg: 1000, source: "aircraft-estimate", remainingMinutes: 10 })).text).toBe("≈600");
  });
  it.each(["zh-CN", "zh-Hant", "en"] as const)("renders low rates and convergence without rounded zero or separators in %s", (locale) => {
    const fuel = snapshot({ available: true, currentKg: .12, source: "measured", rateKgMin: .06, remainingMinutes: 2, stable: false, regime: "idle", flowState: "consuming" });
    const result = fuelPresentation(fuel, locale);
    expect(result.consumption).toContain("0.06 kg/min");
    expect(result.consumption).toContain("≈2:00");
    expect(result.sourceLabel).toBe(({ "zh-CN": "收敛中", "zh-Hant": "收斂中", en: "Converging" })[locale]);
    expect(Object.values(result).filter(value => typeof value === "string").join("")).not.toContain("·");
    expect(fuelEndurance(fuel, locale).text).toBe("≈120");
    expect(fuelEndurance({ ...fuel, available: false }, locale).text).toBe("—");
    expect(fuelPresentation({ ...fuel, rateKgMin: .00006 }, locale).consumption).toContain("0.00006 kg/min");
    expect(fuelEndurance({ ...fuel, currentKg: 0, source: "learning" }, locale).text).toBe("0");
  });
});
