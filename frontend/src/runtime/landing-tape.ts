import type { EditionSnapshot } from "./runtime-types";
import { landingConfigurationPresentation, landingLateralGuidance } from "./landing-presentation";
import { landingRunwayScene, landingRunwayCamera, projectLandingRunway, RunwaySceneMotion, type LandingRunwayScene, type ProjectedPoint } from "./landing-runway-projection";

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
  const identity = landing?.runwayLabel || "机场";
  const course = returning ? g.airportBearingDeg === null ? `${identity} —` : `${identity} · ${heading(g.airportBearingDeg)}°` : g ? `${identity} · RWY ${heading(g.courseDeg)}°` : "跑道 —";
  const distance = returning ? `距机场 ${(g.airportDistanceM / 1000).toFixed(1)}km`
    : g ? `${g.thresholdDistanceM < 0 ? "入口后 " : ""}${(Math.abs(g.thresholdDistanceM) / 1000).toFixed(1)}km` : "距离 —";
  const mode = landing?.settings.automatic ? returning ? "自动返航" : "自动进近" : returning ? "返航参考" : "降落参考";
  const speedText = finite(ias) ? `${Math.round(ias)}` : "—";
  const speedDetail = finite(targetIas) ? `参考 ${Math.round(targetIas)}` : configuration.speedDetail;
  const scene = !active || !g || landing?.status !== "guidance" ? "unavailable"
    : g.stage === "return" ? "return" : g.stage === "runway" || g.stage === "past-runway" ? "rollout"
      : glide !== null && lateral !== null ? "glide" : "align";
  const airportHeightText = scene === "return" && finite(g?.heightM)
    ? `${g.heightM >= 0 ? "↓" : "↑"}${Math.round(Math.abs(g.heightM))}m` : "";
  const stageLabel = scene === "unavailable" ? "等待数据" : lateral === null ? "航迹 —" : scene === "return" ? "返航"
    : scene === "rollout" ? "入口后" : scene === "glide" ? `${landing!.settings.glideAngleDeg}°`
      : g?.heightM === null ? "高程 —" : "对正";
  const cueLateral = scene === "unavailable" ? null : lateral;
  const cueGlide = scene === "glide" ? glide : null;
  const runway = scene === "unavailable" ? null : landingRunwayScene(g, snapshot.flight.headingDeg, landing!.settings.glideAngleDeg);
  // Stage boundaries do not change the physical runway. Keep its motion
  // continuous; approach/validity flags still change immediately in the scene.
  const selected = snapshot.navigation?.items.find(item => item.id === landing?.settings.runwayId);
  const cueKey = `${selected?.runwayStart && selected.runwayEnd ? JSON.stringify([selected.runwayStart, selected.runwayEnd]) : landing?.settings.runwayId}|${landing?.settings.reverse}|${runway === null}|${g?.lengthM}`;
  return { active, mode, course, distance, lateral: cueLateral, glide: cueGlide, airportHeightText, lateralText, glideText, vy, config, scene, stageLabel, cueKey,
    runway, speedText, speedDetail, speedTone, fuelText, fuelDetail, fuelTone, equipmentText,
    aria: `${mode}；${course}，${distance}${airportHeightText ? `；机场相对高度 ${airportHeightText}` : ""}${runway ? `；${g?.referenceWidthM ? "宽度采用同长度机场定义参考" : "跑道轮廓宽度为示意"}，跑道观察视角自动俯视和缩放，非飞机姿态` : ""}；IAS ${speedText} km/h，${speedDetail}；燃油续航 ${fuelDetail}；${lateralText}，${glideText}，${vy}；${config}；${equipmentAria}` };
}

export type LandingTapeView = ReturnType<typeof landingTapePresentation>;
/** Shared lifecycle boundary for the level-camera runway scene. */
export class LandingCueMotion {
  #key = "";
  readonly #motion = new RunwaySceneMotion();
  observe(p: LandingTapeView, now: number, reducedMotion = false): void {
    this.#motion.observe(p.runway, now, reducedMotion || p.cueKey !== this.#key);
    this.#key = p.cueKey;
  }
  step(now: number): LandingRunwayScene | null { return this.#motion.step(now); }
  isMoving(now: number): boolean { return this.#motion.isMoving(now); }
}

/** Perspective runway surface and two reference rails. No tunnel gates. */
export function drawLandingTape(ctx: CanvasRenderingContext2D, p: LandingTapeView, width: number, height: number, cue: LandingRunwayScene | null): void {
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

  const projected = cue ? projectLandingRunway(cue, landingRunwayCamera(cue)) : null;
  const verticalExtent = Math.max(Math.abs(projected?.threshold?.[1] ?? 0), Math.abs(projected?.end?.[1] ?? 0));
  // Use the available height for a legible runway, zooming the entire scene
  // uniformly. Never enlarge the far edge independently or flatten the plane.
  const cy = height * .48;
  const horizontalExtent = Math.max(.001, ...(projected?.surface.map(point => Math.abs(point[0])) ?? []));
  const focal = Math.max(height * .6, Math.min(height * 80, centerWidth * .43 / horizontalExtent, height * .23 / Math.max(.0001, verticalExtent)));
  const top = height * .18, bottom = height * .82;
  const pixel = (point: ProjectedPoint): ProjectedPoint => [center + point[0] * focal, cy + point[1] * focal];
  const inside = (point: ProjectedPoint) => point[0] >= left + 8 && point[0] <= right - 8 && point[1] >= top + 8 && point[1] <= bottom - 8;
  ctx.save();
  ctx.beginPath(); ctx.rect(left, top, centerWidth, bottom - top); ctx.clip();
  ctx.lineWidth = Math.max(1, height / 155);
  ctx.lineJoin = "round";
  // No artificial horizon: the camera tilts to inspect the selected runway.
  if (projected) {
    if (projected.surface.length >= 3) {
      const corners = projected.surface.map(pixel);
      ctx.beginPath(); ctx.moveTo(...corners[0]!);
      for (const corner of corners.slice(1)) ctx.lineTo(...corner);
      ctx.closePath();
      ctx.fillStyle = "#b4d2dc"; ctx.globalAlpha = .14; ctx.fill();
      ctx.strokeStyle = "#edf6fa"; ctx.globalAlpha = .85; ctx.stroke();
      // Mark the selected entrance with its actual projected near edge.
      if (projected.entrance) {
        ctx.strokeStyle = cyan; ctx.globalAlpha = .95; ctx.lineWidth *= 2;
        ctx.beginPath(); ctx.moveTo(...pixel(projected.entrance[0])); ctx.lineTo(...pixel(projected.entrance[1])); ctx.stroke();
        ctx.lineWidth /= 2;
      }
    }
    ctx.strokeStyle = cyan; ctx.globalAlpha = .65;
    for (const rail of projected.rails) {
      const a = pixel(rail[0]), b = pixel(rail[1]);
      // A constant-angle glide reference is straight in perspective. Do not
      // introduce a decorative bend that changes its indicated geometry.
      ctx.beginPath(); ctx.moveTo(...a); ctx.lineTo(...b); ctx.stroke();
    }
    if (projected.runway) {
      const a = pixel(projected.runway[0]), b = pixel(projected.runway[1]);
      ctx.strokeStyle = "#f0f8fc"; ctx.globalAlpha = .45; ctx.lineWidth = 1;
      ctx.setLineDash([3, 4]);
      ctx.beginPath(); ctx.moveTo(...a); ctx.lineTo(...b); ctx.stroke();
      ctx.setLineDash([]);
    }
    const target = projected.threshold ? pixel(projected.threshold) : null;
    if (!target || !inside(target)) {
      // A clipped or rearward runway remains a direction cue, never a fabricated projection.
      const x = target ? Math.max(left + 10, Math.min(right - 10, target[0])) : projected.bearing < 0 ? left + 10 : right - 10;
      const y = target ? Math.max(top + 10, Math.min(bottom - 10, target[1])) : cy;
      const angle = target ? Math.atan2(target[1] - cy, target[0] - center) : projected.bearing < 0 ? Math.PI : 0;
      ctx.save(); ctx.translate(x, y); ctx.rotate(angle); ctx.globalAlpha = .85; ctx.strokeStyle = "#f0f8fc";
      ctx.beginPath(); ctx.moveTo(-4, -4); ctx.lineTo(1, 0); ctx.lineTo(-4, 4); ctx.stroke(); ctx.restore();
    }
  } else if (p.scene !== "unavailable" && p.lateral !== null) {
    const x = center + p.lateral * centerWidth * .4;
    ctx.globalAlpha = .8; ctx.strokeStyle = cyan;
    ctx.beginPath(); ctx.moveTo(x - 4, cy + 5); ctx.lineTo(x, cy); ctx.lineTo(x + 4, cy + 5); ctx.stroke();
  }
  ctx.restore();
  text(p.scene !== "unavailable" && !cue ? "高程 —" : cue?.approach && p.scene !== "glide" ? `${p.stageLabel} · ${Number((Math.atan(cue.slope) * 180 / Math.PI).toFixed(1))}°` : p.stageLabel,
    center, height * .9, font, muted, "center", centerWidth);
  ctx.restore();
}
