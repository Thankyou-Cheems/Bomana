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
export type FuelLocale = "zh-CN" | "zh-Hant" | "en";
export function fuelLocale(): FuelLocale {
  const lang = typeof document === "undefined" ? "zh-CN" : document.documentElement.lang;
  return /^en/i.test(lang) ? "en" : /Hant|TW|HK/i.test(lang) ? "zh-Hant" : "zh-CN";
}
const labels = {
  "zh-CN": {
    fuel: "燃油", unavailable: "数据中断", measured: "实测", converging: "收敛中", reference: "已校准参考", learning: "观察中",
    return: "返航", estimate: "返航参考", pending: "返航 —", surplus: "余量", deficit: "缺口", empty: "耗尽", sec: "秒",
    noLoss: "尚未观测到耗油", outputZero: "动力为零", budget: "航路", reserve: "备用", uncertainty: "耗率分辨范围", sample: "观测",
    regimes: { ground: "地面", idle: "怠速", cruise: "巡航", military: "大油门", boost: "增推", unknown: "当前工况" },
    reasons: { "fuel-unavailable": "等待新油量读数，估算暂停", "on-ground": "地面耗油，返航待起飞", learning: "等待可辨识的油量下降", "no-airfield": "未识别友方机场", "no-track": "等待有效地速", maneuver: "滑翔或升降中，返航待估算", refuel: "加油后重新测量", "fuel-jump": "油量阶跃后重新测量", empty: "燃油已耗尽" },
    assumptions: "按当前工况，含20%航路裕量及5分钟备用油；不保证机场可用或未来风向。",
    conditional: "续航按当前工况估算。动力、损伤、放油和补给变化后重新测量。",
    weak: "油量变化尚未充分解析；近似续航可能变化，暂不给安全返航判断。",
    zero: "发动机输出为零，未证明燃油流量为零；不推导无限续航。",
    economy: "本次已测省油工况", saving: "每公里省油", same: "仅供相近高度与载荷参考。",
  },
  "zh-Hant": {
    fuel: "燃油", unavailable: "資料中斷", measured: "實測", converging: "收斂中", reference: "已校準參考", learning: "觀察中",
    return: "返航", estimate: "返航參考", pending: "返航 —", surplus: "餘量", deficit: "缺口", empty: "耗盡", sec: "秒",
    noLoss: "尚未觀測到耗油", outputZero: "動力為零", budget: "航路", reserve: "備用", uncertainty: "耗率分辨範圍", sample: "觀測",
    regimes: { ground: "地面", idle: "怠速", cruise: "巡航", military: "大油門", boost: "增推", unknown: "當前工況" },
    reasons: { "fuel-unavailable": "等待新油量讀數，估算暫停", "on-ground": "地面耗油，返航待起飛", learning: "等待可辨識的油量下降", "no-airfield": "未識別友方機場", "no-track": "等待有效地速", maneuver: "滑翔或升降中，返航待估算", refuel: "加油後重新測量", "fuel-jump": "油量階躍後重新測量", empty: "燃油已耗盡" },
    assumptions: "按當前工況，含20%航路裕量及5分鐘備用油；不保證機場可用或未來風向。",
    conditional: "續航按當前工況估算。動力、損傷、放油和補給變化後重新測量。",
    weak: "油量變化尚未充分解析；近似續航可能變化，暫不給安全返航判斷。",
    zero: "發動機輸出為零，未證明燃油流量為零；不推導無限續航。",
    economy: "本次已測省油工況", saving: "每公里省油", same: "僅供相近高度與載荷參考。",
  },
  en: {
    fuel: "Fuel", unavailable: "No data", measured: "Measured", converging: "Converging", reference: "Calibrated reference", learning: "Observing",
    return: "Return", estimate: "Return estimate", pending: "Return —", surplus: "Surplus", deficit: "Deficit", empty: "Empty", sec: "s",
    noLoss: "No loss resolved", outputZero: "Zero output", budget: "Route", reserve: "Reserve", uncertainty: "Rate resolution range", sample: "Observed",
    regimes: { ground: "Ground", idle: "Idle", cruise: "Cruise", military: "High power", boost: "Boost", unknown: "Current power" },
    reasons: { "fuel-unavailable": "Waiting for fresh fuel data", "on-ground": "Ground burn; return pending takeoff", learning: "Waiting for resolvable fuel loss", "no-airfield": "No friendly airfield", "no-track": "Waiting for ground speed", maneuver: "Gliding or vertical maneuver; return pending", refuel: "Relearning after refuel", "fuel-jump": "Relearning after mass step", empty: "Fuel exhausted" },
    assumptions: "Current conditions, 20% route allowance and five-minute reserve; future wind and runway availability unknown.",
    conditional: "Endurance assumes current conditions. Power, damage, dumping or service changes require remeasurement.",
    weak: "Loss is not fully resolved. Approximate endurance may change; no safe return verdict yet.",
    zero: "Engine output is zero; zero fuel flow is unproven. Infinite endurance is not inferred.",
    economy: "Measured economy setting", saving: "less fuel per km", same: "Reference for similar altitude and load only.",
  },
};

export function fuelPresentation(fuel: FuelSnapshot, locale = fuelLocale()): FuelPresentation {
  const l = labels[locale];
  const currentKg = Math.max(0, fuel.currentKg), totalKg = Math.max(0, fuel.initialKg);
  const currentPercent = totalKg > 0 ? clamp(currentKg / totalKg * 100) : 0;
  const returnAvailable = fuel.marginKg !== null;
  const returnMarkerPercent = returnAvailable && totalKg > 0 ? clamp(fuel.returnNeededKg / totalKg * 100) : 0;
  const currentTotal = fuel.available ? `${l.fuel} ${kg(currentKg)} / ${totalKg > 0 ? kg(totalKg) : "—"} kg` : l.unavailable;
  const regime = l.regimes[fuel.regime as keyof typeof l.regimes] ?? l.regimes.unknown;
  const sourceLabel = fuel.source === "measured" ? fuel.stable ? l.measured : l.converging
    : fuel.source === "aircraft-estimate" ? l.reference : fuel.source === "unavailable" ? l.unavailable : l.learning;
  const reason = l.reasons[fuel.reason as keyof typeof l.reasons] ?? l.reasons.learning;
  const time = fuel.remainingMinutes !== null && Number.isFinite(fuel.remainingMinutes) ? duration(fuel.remainingMinutes) : "—";
  const consumption = fuel.rateKgMin > 0 ? `${regime} ${kg(fuel.rateKgMin)} kg/min  ≈${time}`
    : fuel.reason === "empty" ? l.empty : fuel.flowState === "output-zero" ? l.outputZero
      : fuel.available && fuel.sampleSeconds >= 6 ? l.noLoss : reason;
  const returnRequirement = returnAvailable ? `${fuel.stable ? l.return : l.estimate} ${kg(fuel.returnNeededKg)} kg` : l.pending;
  const balance = fuel.marginKg !== null ? fuel.marginKg >= 0 ? `${l.surplus} +${kg(fuel.marginKg)} kg` : `${l.deficit} ${kg(-fuel.marginKg)} kg`
    : fuel.reason === "empty" ? l.empty : `${l.surplus} —`;
  const budget = returnAvailable ? `${fuel.returnTargetLabel} ${fuel.returnDistanceKm!.toFixed(1)} km; ${l.budget} ${kg(fuel.tripKg!)} kg + ${l.reserve} ${kg(fuel.reserveKg!)} kg. ${l.assumptions}` : reason;
  const uncertainty = fuel.rateUncertaintyKgMin;
  const range = uncertainty !== null ? ` ${l.uncertainty} ${kg(Math.max(0, fuel.rateKgMin - uncertainty))}–${kg(fuel.rateKgMin + uncertainty)} kg/min (${l.sample} ${Math.round(fuel.sampleSeconds)} ${l.sec}).` : "";
  const detail = budget + range;
  const economy = fuel.economy;
  const advice = economy ? `${l.economy}: ${Math.round(economy.throttlePercent)}% / ${Math.round(economy.groundSpeedKmh)} km/h, ${l.saving} ${Math.round(economy.savingPercent)}%. ${l.same}`
    : fuel.flowState === "output-zero" ? l.zero : fuel.source === "measured" && !fuel.stable ? l.weak : l.conditional;
  return { currentTotal, consumption, returnRequirement, balance, currentPercent, returnMarkerPercent,
    returnAvailable, tone: fuel.returnStatus, sourceLabel, detail, advice };
}

export function fuelEndurance(fuel: FuelSnapshot | null | undefined, locale = fuelLocale()) {
  const l = labels[locale];
  if (!fuel?.available) return { text: "—", detail: `— ${l.sec} ${l.unavailable}` };
  if (fuel.currentKg === 0) return { text: "0", detail: `0 ${l.sec} ${l.empty}` };
  const minutes = fuel.remainingMinutes;
  if (fuel.source === "measured" && minutes !== null && Number.isFinite(minutes) && minutes >= 0) {
    const text = `${fuel.stable ? "" : "≈"}${Math.round(minutes * 60)}`;
    return { text, detail: `${fuel.stable ? l.measured : l.converging} ${text} ${l.sec}` };
  }
  return { text: "—", detail: `— ${l.sec} ${fuel.flowState === "output-zero" ? l.outputZero : l.noLoss}` };
}

function kg(value: number): string {
  return value.toLocaleString("en-US", value > 0 && value < 1 ? { maximumSignificantDigits: 3 } : { maximumFractionDigits: value < 10 ? 2 : 0 });
}
function duration(value: number): string {
  const seconds = Math.max(0, Math.round(value * 60));
  return seconds >= 3600 ? `${Math.floor(seconds / 3600)}h${Math.floor(seconds % 3600 / 60).toString().padStart(2, "0")}`
    : `${Math.floor(seconds / 60)}:${(seconds % 60).toString().padStart(2, "0")}`;
}
function clamp(value: number): number { return Math.max(0, Math.min(100, Number.isFinite(value) ? value : 0)); }
