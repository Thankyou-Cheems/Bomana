import type { EditionSnapshot } from "./runtime-types";
import { landingConfigurationPresentation, landingLateralGuidance } from "./landing-presentation";

const finite = (n: number | null | undefined): n is number => typeof n === "number" && Number.isFinite(n);
const clamp = (n: number) => Math.max(-1, Math.min(1, n));
const heading = (n: number) => Math.round((n % 360 + 360) % 360).toString().padStart(3, "0");

/** Compact flight references only; no learned-fuel diagnostics or landing safety claim. */
export function landingTapePresentation(snapshot: EditionSnapshot) {
  const landing = snapshot.landing, g = landing?.geometry;
  const returning = g?.stage === "return";
  const active = landing?.settings.enabled === true;
  const ias = landing?.iasKmh, targetIas = landing?.settings.targetIasKmh;
  const fuel = snapshot.fuel;
  const fuelAvailable = fuel?.available === true && snapshot.sortieContinuity.state === "live"
    && landing?.reason !== "telemetry" && finite(fuel.currentKg) && fuel.currentKg >= 0;
  const minutes = fuelAvailable && fuel?.source === "measured" && fuel.stable && finite(fuel.remainingMinutes)
    ? fuel.remainingMinutes : null;
  const fuelText = fuelAvailable ? fuel!.currentKg >= 10_000 ? `${(fuel!.currentKg / 1000).toFixed(1)}t` : `${Math.round(fuel!.currentKg)}` : "—";
  const fuelDetail = minutes !== null ? `约 ${Math.max(0, minutes).toFixed(1)} 分`
    : fuelAvailable && finite(fuel?.initialKg) && fuel!.initialKg > 0 && finite(fuel?.percent) ? `${Math.round(fuel!.percent)}%` : "续航 —";
  const configuration = landingConfigurationPresentation(landing);
  const speedTone = configuration.tone === "danger" ? "danger"
    : configuration.tone === "caution" || finite(ias) && finite(targetIas) && Math.abs(ias - targetIas) > targetIas * .1 ? "caution" : "reference";
  const fuelTone = fuelAvailable && (fuel!.currentKg <= 0 || minutes !== null && minutes < 3) ? "danger"
    : minutes !== null && minutes < 5 ? "caution" : "reference";
  const { position: lateral, text: lateralText } = landingLateralGuidance(g);
  const glide = !g || g.glideDeviationM === null ? null : clamp(g.glideDeviationM / Math.max(20, Math.abs(g.thresholdDistanceM) * .02));
  const glideText = !g ? "" : returning ? "返航中" : g.stage === "runway" || g.stage === "past-runway" ? "下滑结束"
    : g.heightM === null ? "高程未知" : g.glideDeviationM === null ? "先对准"
      : Math.abs(g.glideDeviationM) <= 10 ? "参考线附近" : `${g.glideDeviationM > 0 ? "高" : "低"} ${Math.round(Math.abs(g.glideDeviationM))}m`;
  const vy = finite(landing?.verticalSpeedMps) ? `${landing!.verticalSpeedMps! < 0 ? "↓" : "↑"}${Math.abs(landing!.verticalSpeedMps!).toFixed(1)}m/s` : "Vy —";
  const gear = landing?.aircraft?.gearControl === false ? "无收放控制"
    : finite(landing?.gearPercent) ? `轮 ${Math.round(landing!.gearPercent!)}%` : "轮 —";
  const config = configuration.cue || (g && !returning && g.thresholdDistanceM < 3000 && g.thresholdDistanceM > 0
      && landing?.aircraft?.gearControl !== false && finite(landing?.gearPercent) && landing!.gearPercent! < 99 ? "检查放轮" : gear);
  const course = returning ? g.airportBearingDeg === null ? "机场 —" : `机场 ${heading(g.airportBearingDeg)}°` : g ? `RWY ${heading(g.courseDeg)}°` : "跑道 —";
  const distance = returning ? `距机场 ${(g.airportDistanceM / 1000).toFixed(1)}km`
    : g ? `${g.thresholdDistanceM < 0 ? "入口后 " : ""}${(Math.abs(g.thresholdDistanceM) / 1000).toFixed(1)}km` : "距离 —";
  const mode = landing?.settings.automatic ? returning ? "自动返航" : "自动进近" : returning ? "返航参考" : "降落参考";
  const speedText = finite(ias) ? `${Math.round(ias)}` : "—";
  const speedDetail = finite(targetIas) ? `参考 ${Math.round(targetIas)}` : configuration.speedDetail;
  return { active, mode, course, distance, lateral, glide, lateralText, glideText, vy, config,
    speedText, speedDetail, speedTone, fuelText, fuelDetail, fuelTone,
    aria: `${mode}；${course}，${distance}；IAS ${speedText} km/h，${speedDetail}；燃油 ${fuelAvailable ? Math.round(fuel!.currentKg) : "未知"} kg，${fuelDetail}；${lateralText}，${glideText}，${vy}；${config}` };
}

export function drawLandingTape(ctx: CanvasRenderingContext2D, snapshot: EditionSnapshot, width: number, height: number, displayHeading: number): void {
  const p = landingTapePresentation(snapshot);
  const compact = width < 330;
  const pad = Math.max(6, Math.min(18, width * .02));
  const side = compact ? width * .22 : Math.max(66, Math.min(150, width * .2));
  const left = side + pad, right = width - side - pad, center = (left + right) / 2;
  const font = Math.max(9, Math.min(16, height * .10, width * .021));
  const large = Math.max(18, Math.min(38, height * .25, side * .32));
  const cyan = "#8bdddc", muted = "#9bb6c5", tone = (v: string) => v === "danger" ? "#ff877c" : v === "caution" ? "#ffd076" : "#e4f5fb";
  ctx.save();
  ctx.fillStyle = "rgba(4,30,40,.58)"; ctx.fillRect(0, 0, width, height);
  ctx.textBaseline = "middle";
  const text = (value: string, x: number, y: number, size: number, color: string, align: CanvasTextAlign, maxWidth?: number) => {
    ctx.font = `600 ${size}px "Microsoft YaHei", sans-serif`; ctx.textAlign = align; ctx.fillStyle = color;
    ctx.fillText(value, x, y, maxWidth);
  };
  text(compact ? "IAS" : "IAS · km/h", pad, height * .17, font, muted, "left", side - pad);
  text(p.speedText, pad, height * .48, large, tone(p.speedTone), "left", side - pad);
  text(p.speedDetail, pad, height * .80, font, muted, "left", side - pad);
  text(compact || p.fuelText.endsWith("t") ? "燃油" : "燃油 · kg", width - pad, height * .17, font, muted, "right", side - pad);
  text(p.fuelText, width - pad, height * .48, large, tone(p.fuelTone), "right", side - pad);
  text(compact && p.fuelDetail === "续航 —" ? "kg" : p.fuelDetail, width - pad, height * .80, font, muted, "right", side - pad);
  ctx.strokeStyle = "rgba(139,221,220,.25)"; ctx.lineWidth = 1;
  for (const x of [side, width - side]) { ctx.beginPath(); ctx.moveTo(x, height * .12); ctx.lineTo(x, height * .88); ctx.stroke(); }
  const centerWidth = right - left;
  text(compact ? p.course : `${p.course} · ${p.distance}`, center, height * .12, font, cyan, "center", centerWidth);
  text(compact ? p.distance : `${p.mode} · HDG ${heading(displayHeading)}°`, center, height * .30, font * .88, muted, "center", centerWidth);
  const axisY = height * (compact ? .46 : .52), axisHalf = centerWidth * .34;
  ctx.strokeStyle = "rgba(139,221,220,.45)";
  ctx.beginPath(); ctx.moveTo(center - axisHalf, axisY); ctx.lineTo(center + axisHalf, axisY); ctx.stroke();
  for (const t of [-1, -.5, 0, .5, 1]) {
    ctx.beginPath(); ctx.moveTo(center + t * axisHalf, axisY - 3); ctx.lineTo(center + t * axisHalf, axisY + 3); ctx.stroke();
  }
  const diamond = (x: number, y: number) => {
    const s = Math.max(3, font * .38); ctx.fillStyle = cyan;
    ctx.beginPath(); ctx.moveTo(x, y-s); ctx.lineTo(x+s, y); ctx.lineTo(x, y+s); ctx.lineTo(x-s, y); ctx.closePath(); ctx.fill();
  };
  if (p.lateral !== null) diamond(center + p.lateral * axisHalf, axisY);
  const glideX = right - 3, glideHalf = height * .14;
  ctx.beginPath(); ctx.moveTo(glideX, axisY - glideHalf); ctx.lineTo(glideX, axisY + glideHalf);
  ctx.moveTo(glideX - 4, axisY); ctx.lineTo(glideX + 4, axisY); ctx.stroke();
  if (p.glide !== null) diamond(glideX, axisY + p.glide * glideHalf);
  text(compact ? p.lateralText : `${p.lateralText}${p.glideText ? ` · ${p.glideText}` : ""}`, center, height * (compact ? .64 : .73), font, cyan, "center", centerWidth);
  if (compact) text(`${p.glideText} · ${p.vy}`, center, height * .78, font * .9, muted, "center", centerWidth);
  text(compact ? p.config : `${p.config} · ${p.vy}`, center, height * (compact ? .93 : .91), font * .9,
    p.config.includes("超限") ? tone("danger") : p.config.includes("检查") || p.config.includes("减速") || p.config.includes("近限") ? tone("caution") : muted, "center", centerWidth);
  ctx.restore();
}
