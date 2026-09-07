import type { FuelSnapshot } from "./fuel-management";

export interface FuelPresentation {
  readonly currentTotal: string;
  readonly consumption: string;
  readonly returnRequirement: string;
  readonly balance: string;
  readonly currentPercent: number;
  readonly returnMarkerPercent: number;
  readonly returnAvailable: boolean;
  readonly tone: FuelSnapshot["returnStatus"];
  readonly sourceLabel: string;
  readonly detail: string;
  readonly advice: string;
}

const reasons: Readonly<Record<string, string>> = {
  "fuel-unavailable": "等待新的燃油读数，已暂停估算",
  "on-ground": "地面油耗仅供参考，起飞后估算返航",
  "learning": "保持动力数秒，正在测量本机油耗",
  "no-airfield": "当前地图未识别到友方机场",
  "no-track": "等待有效地速，无法估算航路耗油",
  "maneuver": "滑翔或大幅升降中，暂不外推返航",
  "refuel": "检测到加油，正在重新测量",
  "fuel-jump": "油量突降，可能抛箱或漏油，正在重新测量",
  "empty": "燃油已耗尽",
};

export function fuelPresentation(fuel: FuelSnapshot): FuelPresentation {
  const currentKg = Math.max(0, fuel.currentKg);
  const totalKg = Math.max(0, fuel.initialKg);
  const currentPercent = totalKg > 0 ? clamp(currentKg / totalKg * 100) : 0;
  const returnAvailable = fuel.marginKg !== null;
  const returnMarkerPercent = returnAvailable && totalKg > 0 ? clamp(fuel.returnNeededKg / totalKg * 100) : 0;
  const currentTotal = fuel.available
    ? `当前 ${kg(currentKg)} / 初始 ${totalKg > 0 ? kg(totalKg) : "—"} kg`
    : "燃油读数暂不可用";
  const boost = fuel.engineType === "piston" ? "应急动力" : "加力 / 增推";
  const regime = ({ ground: "地面", idle: "怠速", cruise: "巡航动力", military: "大油门", boost, unknown: "当前动力" })[fuel.regime] ?? "当前动力";
  const sourceLabel = ({ measured: "本机实测", "aircraft-estimate": "机型初估 · 待校准", learning: "测量中", unavailable: "数据中断" })[fuel.source];
  const time = fuel.remainingMinutes === null ? "" : `${minutes(fuel.remainingMinutes)} 分`;
  const consumption = fuel.rateKgMin > 0
    ? `${regime} · ${kg(fuel.rateKgMin)} kg/min · 约 ${time}`
    : reasons[fuel.reason] ?? "正在测量本机油耗";
  const returnRequirement = returnAvailable
    ? `${fuel.stable ? "返航预算" : "机型参考"} ${kg(fuel.returnNeededKg)} kg` : "返航待估算";
  const balance = fuel.marginKg !== null
    ? fuel.marginKg >= 0 ? `余量 +${kg(fuel.marginKg)} kg` : `缺口 ${kg(-fuel.marginKg)} kg`
    : fuel.reason === "empty" ? "燃油耗尽" : "余量 —";
  const detail = returnAvailable
    ? `${fuel.returnTargetLabel} · ${fuel.returnDistanceKm!.toFixed(1)} km；航路 ${kg(fuel.tripKg!)} kg + 备用 ${kg(fuel.reserveKg!)} kg。按当前动力与地速，含 20% 航路裕量及 ${fuel.reserveMinutes} 分钟备用油；未计返航风向与机场可降落性。`
    : reasons[fuel.reason] ?? "正在收集燃油与航迹数据";
  const economy = fuel.economy;
  const advice = economy
    ? `本次已测：${Math.round(economy.throttlePercent)}% 油门、${Math.round(economy.groundSpeedKmh)} km/h 时，每公里省油约 ${Math.round(economy.savingPercent)}%；恢复此工况返航参考需 ${kg(economy.returnNeededKg)} kg。仅适用于相近高度与载荷。`
    : fuel.source === "aircraft-estimate" ? "机型参数尚未由本次油量变化校准，续航与返航预算仅供参考。"
      : fuel.regime === "boost" ? "当前预算按持续增推计算；收小油门并稳定平飞后可比较实测油耗。"
        : "续航按当前动力计算；备用油留给转弯、进近与复飞。";
  return { currentTotal, consumption, returnRequirement, balance, currentPercent, returnMarkerPercent,
    returnAvailable, tone: fuel.returnStatus, sourceLabel, detail, advice };
}

function kg(value: number): string { return Math.round(value).toLocaleString("en-US"); }
function minutes(value: number): string {
  return value < 10 ? Math.max(0, value).toFixed(1) : Math.floor(value).toString();
}
function clamp(value: number): number { return Math.max(0, Math.min(100, Number.isFinite(value) ? value : 0)); }
