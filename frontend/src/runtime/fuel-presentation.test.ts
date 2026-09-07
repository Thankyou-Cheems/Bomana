import { describe, expect, it } from "vitest";
import { FuelManager, type FuelSnapshot } from "./fuel-management";
import { fuelPresentation } from "./fuel-presentation";

function snapshot(change: Partial<FuelSnapshot>): FuelSnapshot {
  return { ...new FuelManager().view(0, false, null, false), ...change };
}

describe("fuel presentation", () => {
  it("shows a measured budget and reserve on the same scale as current fuel", () => {
    expect(fuelPresentation(snapshot({ available: true, currentKg: 800, initialKg: 1200,
      rateKgMin: 50, stable: true, source: "measured", remainingMinutes: 16, regime: "cruise",
      returnNeededKg: 300, returnStatus: "safe", marginKg: 500, tripKg: 50, reserveKg: 250,
      returnDistanceKm: 10, returnTargetLabel: "友方机场 1", reason: "ready" }))).toMatchObject({
      currentTotal: "当前 800 / 初始 1,200 kg", consumption: "巡航动力 · 50 kg/min · 约 16 分",
      returnRequirement: "返航预算 300 kg", balance: "余量 +500 kg",
      currentPercent: 800 / 1200 * 100, returnMarkerPercent: 25, returnAvailable: true, tone: "safe",
      sourceLabel: "本机实测",
    });
  });

  it("explains the missing input instead of displaying a zero return requirement", () => {
    const result = fuelPresentation(snapshot({ reason: "no-track", available: true, currentKg: 1000 }));
    expect(result.detail).toContain("等待有效地速");
    expect(result.currentTotal).toContain("初始 —");
    expect(result.returnAvailable).toBe(false);
    expect(result.returnRequirement).toBe("返航待估算");
  });

  it("labels static estimates as references without a positive return verdict", () => {
    const result = fuelPresentation(snapshot({ available: true, source: "aircraft-estimate", currentKg: 1000,
      rateKgMin: 100, remainingMinutes: 10, marginKg: 300, returnNeededKg: 700,
      returnDistanceKm: 30, tripKg: 200, reserveKg: 500, reason: "ready" }));
    expect(result.sourceLabel).toContain("待校准");
    expect(result.returnRequirement).toBe("机型参考 700 kg");
    expect(result.tone).toBe("unknown");
  });
});
