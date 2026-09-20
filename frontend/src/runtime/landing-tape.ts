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
  const minutes = fuelAvailable && fuel?.source === "measured" && fuel.stable && finite(fuel.remainingMinutes) && fuel.remainingMinutes >= 0
    ? fuel.remainingMinutes : null;
  const fuelText = minutes !== null ? `${Math.round(minutes * 60)}` : "—";
  const fuelDetail = minutes !== null ? `约 ${fuelText} 秒` : "— 秒";
  const equipmentState = (value: boolean | null | undefined) => value === true ? "✓" : value === false ? "×" : "?";
  const equipmentText = `钩${equipmentState(landing?.aircraft?.arrestorHook)} 伞${equipmentState(landing?.aircraft?.brakeChute)}`;
  const equipmentDescription = (value: boolean | null | undefined) => value === true ? "已配备" : value === false ? "未配备" : "未知";
  const equipmentAria = `机型配置：尾钩${equipmentDescription(landing?.aircraft?.arrestorHook)}，减速伞${equipmentDescription(landing?.aircraft?.brakeChute)}；仅为静态配备，非当前展开或挂索状态`;
  const configuration = landingConfigurationPresentation(landing);
  const speedTone = configuration.tone === "danger" ? "danger"
    : configuration.tone === "caution" || finite(ias) && finite(targetIas) && Math.abs(ias - targetIas) > targetIas * .1 ? "caution" : "reference";
  const fuelTone = fuelAvailable && (fuel!.currentKg <= 0 || minutes !== null && minutes < 3) ? "danger"
    : minutes !== null && minutes < 5 ? "caution" : "reference";
  const { position: lateral, text: lateralText } = landingLateralGuidance(g);
  // A stale/older producer must never leave a vertical cue beyond the threshold.
  const glide = g?.stage === "final" && g.thresholdDistanceM > 0 && finite(g.heightM) && finite(g.glideDeviationM)
    ? clamp(g.glideDeviationM / Math.max(20, g.thresholdDistanceM * .02)) : null;
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
  const scene = !active || !g || landing?.status !== "guidance" ? "unavailable"
    : g.stage === "return" ? "return" : g.stage === "runway" || g.stage === "past-runway" ? "rollout"
      : glide !== null && lateral !== null ? "glide" : "align";
  const stageLabel = scene === "unavailable" ? "等待数据" : lateral === null ? "航迹 —" : scene === "return" ? "返航"
    : scene === "rollout" ? "入口后" : scene === "glide" ? `${landing!.settings.glideAngleDeg}°`
      : g?.heightM === null ? "高程 —" : "对正";
  const cueLateral = scene === "unavailable" ? null : lateral;
  const cueGlide = scene === "glide" ? glide : null;
  const cueKey = `${landing?.settings.runwayId}|${landing?.settings.reverse}|${g?.stage}|${scene}|${cueLateral === null}`;
  return { active, mode, course, distance, lateral: cueLateral, glide: cueGlide, lateralText, glideText, vy, config, scene, stageLabel, cueKey,
    speedText, speedDetail, speedTone, fuelText, fuelDetail, fuelTone, equipmentText,
    aria: `${mode}；${course}，${distance}；IAS ${speedText} km/h，${speedDetail}；燃油续航 ${fuelDetail}；${lateralText}，${glideText}，${vy}；${config}；${equipmentAria}` };
}

export type LandingTapeView = ReturnType<typeof landingTapePresentation>;
type LandingCue = { lateral: number | null; glide: number | null };

/** Bounded interpolation only. Never extrapolate stale telemetry or animate an outage. */
export class LandingCueMotion {
  #key = "";
  #start = 0;
  #from: LandingCue = { lateral: null, glide: null };
  #to: LandingCue = { lateral: null, glide: null };
  observe(p: LandingTapeView, now: number, reducedMotion = false): void {
    const next = { lateral: p.lateral, glide: p.glide };
    if (!reducedMotion && p.cueKey === this.#key && next.lateral === this.#to.lateral && next.glide === this.#to.glide) return;
    const current = this.step(now);
    const jump = reducedMotion || p.cueKey !== this.#key || next.lateral === null;
    this.#from = jump ? next : current;
    this.#to = next;
    this.#key = p.cueKey;
    this.#start = jump ? now - 180 : now;
  }
  step(now: number): LandingCue {
    const t = Math.max(0, Math.min(1, (now - this.#start) / 180));
    if (t === 1) return this.#to;
    const ease = t * t * (3 - 2 * t);
    const mix = (a: number | null, b: number | null) => a === null || b === null ? b : a + (b - a) * ease;
    return { lateral: mix(this.#from.lateral, this.#to.lateral), glide: mix(this.#from.glide, this.#to.glide) };
  }
  isMoving(now: number): boolean {
    return now < this.#start + 180 && (this.#from.lateral !== this.#to.lateral || this.#from.glide !== this.#to.glide);
  }
}

/** A schematic steering funnel, not synthetic terrain or a measured runway width.
 * Five gates and four rails; no textures, shadows, DOM churn or free-running animation. */
export function drawLandingTape(ctx: CanvasRenderingContext2D, p: LandingTapeView, width: number, height: number, cue: LandingCue): void {
  const pad = Math.max(8, Math.min(20, width * .025));
  const side = Math.max(54, Math.min(125, width * .18));
  const left = side + pad, right = width - side - pad, center = width / 2;
  const centerWidth = right - left;
  const font = Math.max(8, Math.min(13, height * .085, width * .021));
  const large = Math.max(18, Math.min(34, height * .24, side * .4));
  const cyan = "#8bdddc", muted = "#91aebc";
  const tone = (v: string) => v === "danger" ? "#ff877c" : v === "caution" ? "#ffd076" : "#e4f5fb";
  ctx.save();
  ctx.textBaseline = "middle";
  const text = (value: string, x: number, y: number, size: number, color: string, align: CanvasTextAlign, maxWidth?: number) => {
    ctx.font = `600 ${size}px "Microsoft YaHei", sans-serif`; ctx.textAlign = align; ctx.fillStyle = color;
    ctx.fillText(value, x, y, maxWidth);
  };
  text("IAS", pad, height * .21, font, muted, "left", side - pad);
  text(p.speedText, pad, height * .45, large, tone(p.speedTone), "left", side - pad);
  text(p.speedDetail.replace("参考", "目标").replace("IAS 目标未设", "目标 —"), pad, height * .67, font, muted, "left", side - pad);
  text("余油 · s", width - pad, height * .21, font, muted, "right", side - pad);
  text(p.fuelText, width - pad, height * .45, large, tone(p.fuelTone), "right", side - pad);
  text(p.vy, width - pad, height * .67, font, muted, "right", side - pad);
  text(p.equipmentText, width - pad, height * .87, font * .85, muted, "right", side - pad);
  const configColor = /超限/.test(p.config) ? tone("danger") : /检查|减速|近限/.test(p.config) ? tone("caution") : muted;
  text(p.config, pad, height * .87, font * .9, configColor, "left", side - pad);
  text(p.course, left, height * .09, font, cyan, "left", centerWidth * .57);
  text(p.distance.replace("距机场 ", ""), right, height * .09, font, muted, "right", centerWidth * .4);

  const cy = height * .51, halfW = centerWidth * .44, halfH = height * .27;
  const x = center + (cue.lateral ?? 0) * halfW * .73;
  const y = cy + (cue.glide ?? 0) * halfH * .68;
  const aligned = cue.lateral !== null && Math.abs(cue.lateral) < .08 && cue.glide !== null && Math.abs(cue.glide) < .12;
  const guideColor = aligned ? "#8ae3b5" : cyan;
  ctx.save();
  ctx.beginPath(); ctx.rect(left, height * .18, centerWidth, height * .64); ctx.clip();
  ctx.lineWidth = Math.max(1, height / 155);
  ctx.lineJoin = "round";
  if (p.scene === "glide" && cue.lateral !== null && cue.glide !== null) {
    // The far gate moves toward the required correction. The fixed ring is ownship.
    for (let i = 0; i < 5; i++) {
      const z = i / 4, scale = .13 + z * z * .87;
      const gx = x + (center - x) * z, gy = y + (cy - y) * z;
      ctx.strokeStyle = guideColor; ctx.globalAlpha = .72 - z * .53;
      ctx.beginPath(); ctx.rect(gx - halfW * scale, gy - halfH * scale, halfW * scale * 2, halfH * scale * 2); ctx.stroke();
    }
    ctx.globalAlpha = .25;
    for (const sx of [-1, 1]) for (const sy of [-1, 1]) {
      ctx.beginPath(); ctx.moveTo(x + sx * halfW * .13, y + sy * halfH * .13);
      ctx.lineTo(center + sx * halfW, cy + sy * halfH); ctx.stroke();
    }
    ctx.globalAlpha = .85;
    ctx.beginPath(); ctx.moveTo(x - 3, y); ctx.lineTo(x + 3, y); ctx.moveTo(x, y - 3); ctx.lineTo(x, y + 3); ctx.stroke();
  } else if (p.scene !== "unavailable" && cue.lateral !== null) {
    // Horizontal-only guidance has no box that could imply a valid glide path.
    ctx.strokeStyle = cyan; ctx.globalAlpha = .3;
    for (const sign of [-1, 1]) {
      ctx.beginPath(); ctx.moveTo(x + sign * halfW * .12, cy - halfH * .7);
      ctx.lineTo(center + sign * halfW, cy + halfH * .7); ctx.stroke();
    }
    ctx.globalAlpha = .95;
    ctx.beginPath(); ctx.moveTo(x, cy - 6); ctx.lineTo(x + 5, cy); ctx.lineTo(x, cy + 6); ctx.lineTo(x - 5, cy); ctx.closePath(); ctx.stroke();
  }
  ctx.restore();

  // Fixed flight-path reference. Neutral dashed ring when telemetry is unavailable.
  const unavailableCue = p.scene === "unavailable" || cue.lateral === null;
  ctx.strokeStyle = unavailableCue ? muted : "#eef9fc";
  ctx.lineWidth = 1.5;
  if (unavailableCue) ctx.setLineDash([2, 3]);
  const r = Math.max(4, Math.min(7, height * .045));
  ctx.beginPath(); ctx.arc(center, cy, r, 0, Math.PI * 2);
  ctx.moveTo(center - r, cy); ctx.lineTo(center - r - 9, cy);
  ctx.moveTo(center + r, cy); ctx.lineTo(center + r + 9, cy);
  ctx.moveTo(center, cy - r); ctx.lineTo(center, cy - r - 5); ctx.stroke();
  ctx.setLineDash([]);
  text(p.stageLabel, center, height * .9, font, p.scene === "glide" ? guideColor : muted, "center", centerWidth);
  ctx.restore();
}
