import type { EditionSnapshot } from "./runtime-types";
import { landingConfigurationPresentation, landingLateralGuidance } from "./landing-presentation";
import { landingRunwayScene, landingRunwayFrame, projectLandingRunway, RunwaySceneMotion, type LandingRunwayScene, type ProjectedPoint } from "./landing-runway-projection";

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
  const runway = scene === "unavailable" ? null : landingRunwayScene(g, snapshot.flight.headingDeg, landing!.settings.glideAngleDeg, landing?.attitude);
  const otherRunways = active && landing?.reason !== "telemetry" ? (landing?.nearbyRunways ?? [])
    .filter(item => item.id !== landing?.settings.runwayId)
    .map(item => ({ ...item, scene: landingRunwayScene(item.geometry, snapshot.flight.headingDeg, landing!.settings.glideAngleDeg, landing?.attitude),
      bearing: ((item.geometry.airportBearingDeg ?? snapshot.flight.headingDeg) - snapshot.flight.headingDeg + 540) % 360 - 180 }))
    .filter(item => Math.abs(item.bearing) <= 30) : [];
  // Stage boundaries do not change the physical runway. Keep its motion
  // continuous; approach/validity flags still change immediately in the scene.
  const selected = snapshot.navigation?.items.find(item => item.id === landing?.settings.runwayId);
  const cueKey = `${selected?.runwayStart && selected.runwayEnd ? JSON.stringify([selected.runwayStart, selected.runwayEnd]) : landing?.settings.runwayId}|${landing?.settings.reverse}|${runway === null}|${g?.lengthM}`;
  return { active, mode, course, distance, lateral: cueLateral, glide: cueGlide, airportHeightText, lateralText, glideText, vy, config, scene, stageLabel, cueKey,
    runway, otherRunways, speedText, speedDetail, speedTone, fuelText, fuelDetail, fuelTone, equipmentText,
    aria: `${mode}；${course}，${distance}${airportHeightText ? `；机场相对高度 ${airportHeightText}` : ""}${runway ? `；${g?.referenceWidthM ? "宽度采用同长度机场定义参考" : "跑道轮廓宽度为示意"}；靠近时按真实透视，远处按距离放大跑道；下滑道显示接入跑道的可见段；姿态缺测使用可用航迹俯仰和水平滚转；曲线从当前高度与俯仰接入末段下滑线，底面低15m；高低偏差独立计算；非目标跑道仅显示轮廓；不表示转弯性能或净空保证` : ""}；IAS ${speedText} km/h，${speedDetail}；燃油续航 ${fuelDetail}；${lateralText}，${glideText}，${vy}；${config}；${equipmentAria}` };
}

export type LandingTapeView = ReturnType<typeof landingTapePresentation>;
/** Shared lifecycle boundary for all runway scenes in the aircraft camera. */
export class LandingCueMotion {
  #key = "";
  readonly #motion = new RunwaySceneMotion();
  readonly #others = new Map<string, RunwaySceneMotion>();
  #background: LandingTapeView["otherRunways"] = [];
  observe(p: LandingTapeView, now: number, reducedMotion = false): void {
    this.#motion.observe(p.runway, now, reducedMotion || p.cueKey !== this.#key);
    this.#key = p.cueKey;
    this.#background = p.otherRunways;
    const keys = new Set(p.otherRunways.map(item => item.key));
    for (const key of this.#others.keys()) if (!keys.has(key)) this.#others.delete(key);
    for (const item of p.otherRunways) {
      let motion = this.#others.get(item.key);
      if (!motion) { motion = new RunwaySceneMotion(); this.#others.set(item.key, motion); }
      motion.observe(item.scene ? { ...item.scene, approach: false } : null, now, reducedMotion);
    }
  }
  step(now: number): LandingRunwayScene | null { return this.#motion.step(now); }
  background(now: number): LandingTapeView["otherRunways"] {
    return this.#background.map(item => ({ ...item, scene: this.#others.get(item.key)?.step(now) ?? null }));
  }
  isMoving(now: number): boolean { return this.#motion.isMoving(now) || [...this.#others.values()].some(motion => motion.isMoving(now)); }
}

/** Perspective runway, datum ground plane and two heading-tangent approach rails. */
export function drawLandingTape(ctx: CanvasRenderingContext2D, p: LandingTapeView, width: number, height: number, cue: LandingRunwayScene | null, others = p.otherRunways): void {
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
  const frame = cue ? landingRunwayFrame(cue, centerWidth, height) : null;
  const projected = frame?.projected;
  // The selected runway frames one camera for the whole scene. Its uniform
  // scale and offset also apply to the guide ribbon and every other runway.
  const cy = frame?.y ?? height * .5, cx = left + (frame?.x ?? centerWidth / 2);
  const focal = frame?.focal ?? centerWidth / (2 * Math.tan(Math.PI / 6));
  const top = 4, bottom = height - 4;
  const pixel = (point: ProjectedPoint): ProjectedPoint => [cx + point[0] * focal, cy + point[1] * focal];
  const inside = (point: ProjectedPoint) => point[0] >= left + 8 && point[0] <= right - 8 && point[1] >= top + 8 && point[1] <= bottom - 8;
  ctx.save();
  ctx.beginPath(); ctx.rect(left, top, centerWidth, bottom - top); ctx.clip();
  ctx.lineWidth = Math.max(1, height / 155);
  ctx.lineJoin = "round";
  const polygon = (points: readonly ProjectedPoint[]) => {
    ctx.beginPath();
    points.forEach((point, i) => { const v = pixel(point); if (i) ctx.lineTo(...v); else ctx.moveTo(...v); });
    ctx.closePath();
  };
  // Farthest first. Unknown elevations get bearing-only marks, never the
  // selected runway's height or an invented sea-level surface.
  for (const item of [...others].sort((a, b) => b.geometry.airportDistanceM - a.geometry.airportDistanceM)) {
    const other = item.scene ? projectLandingRunway({ ...item.scene, approach: false }, frame?.pitch, frame?.roll, frame?.retreat, frame?.yaw) : null;
    const color = item.friendly ? muted : "#cc9992";
    ctx.strokeStyle = color; ctx.globalAlpha = .48; ctx.lineWidth = 1;
    if (other?.surface.length) { polygon(other.surface); ctx.stroke(); }
    const anchor = other?.threshold ? pixel(other.threshold) : null;
    if (Math.abs(item.bearing) <= 30 && (!anchor || !inside(anchor))) {
      // Unknown height stays on the heading rail, independent of adaptive zoom.
      const x = anchor ? Math.max(left + 8, Math.min(right - 8, anchor[0])) : center + item.bearing / 30 * (centerWidth / 2 - 8);
      const y = anchor ? Math.max(top + 25, Math.min(bottom - 9, anchor[1])) : bottom - 9;
      if (!item.scene) {
        // Schematic runway at its known bearing, not a fabricated altitude.
        ctx.save(); ctx.translate(x, y - 2);
        ctx.rotate((item.geometry.courseDeg - (item.geometry.airportBearingDeg ?? 0) + item.bearing) * Math.PI / 180);
        ctx.strokeRect(-2, -5, 4, 10); ctx.restore();
      } else {
        ctx.beginPath(); ctx.moveTo(x - 3, y - 2); ctx.lineTo(x, y + 2); ctx.lineTo(x + 3, y - 2); ctx.stroke();
      }
      text(item.label, x, y - 8, font * .75, color, "center", 65);
    }
  }
  // Sky stays the instrument background. The ground is a calm datum, not a
  // saturated fill and not an official map.
  if (projected) {
    if (projected.groundSurface.length >= 3 && projected.groundSurface.every((point) => {
      const [x, y] = pixel(point);
      return x >= left - centerWidth && x <= right + centerWidth && y >= -height && y <= bottom + height;
    })) {
      polygon(projected.groundSurface);
      ctx.fillStyle = "#1c4a46"; ctx.globalAlpha = .92; ctx.fill();
      ctx.strokeStyle = "#9eb8a4"; ctx.globalAlpha = .7; ctx.lineWidth = 1.5; ctx.stroke();
    }
    ctx.strokeStyle = "#b7cfc4"; ctx.globalAlpha = .4; ctx.lineWidth = 1;
    ctx.beginPath();
    for (const line of projected.ground) { ctx.moveTo(...pixel(line[0])); ctx.lineTo(...pixel(line[1])); }
    ctx.stroke();
    const placedInside = (point: ProjectedPoint) => {
      const [x, y] = pixel(point);
      return x >= left && x <= right && y >= top && y <= bottom;
    };
    // Far magnification stretches the path's near mouth into a loop. Keep the
    // leg that joins the runway until the picture is close enough to show the whole corridor.
    const natural = centerWidth / (2 * Math.tan(Math.PI / 6));
    const joiningOnly = frame.focal > natural * 3;
    const rails = joiningOnly ? projected.rails.map((rail) => rail.slice(-18)) : projected.rails;
    const ribbon = joiningOnly ? projected.ribbon.slice(-18) : projected.ribbon;
    ctx.lineWidth = Math.max(1.5, height / 90);
    ctx.fillStyle = cyan; ctx.globalAlpha = .28;
    // Only the part of the glide path that sits in the strip. A magnified segment
    // that merely crosses the panel reads as a scribble around an abstract runway.
    for (const quad of ribbon) {
      if (quad.some((point) => !placedInside(point))) continue;
      polygon(quad); ctx.fill();
    }
    ctx.strokeStyle = "#d7fff8"; ctx.globalAlpha = .95; ctx.lineWidth = Math.max(2, height / 55);
    for (const rail of rails) {
      ctx.beginPath();
      let previous: ProjectedPoint | null = null;
      for (const piece of rail) {
        if (!placedInside(piece[0]) || !placedInside(piece[1])) { previous = null; continue; }
        if (!previous || previous[0] !== piece[0][0] || previous[1] !== piece[0][1]) ctx.moveTo(...pixel(piece[0]));
        ctx.lineTo(...pixel(piece[1])); previous = piece[1];
      }
      ctx.stroke();
    }
    // Keep the target surface legible where the intercept overlaps it in a
    // steep/banked observation view. Guidance must not wash out the runway.
    if (projected.surface.length >= 3) {
      polygon(projected.surface);
      ctx.fillStyle = "#e7eef2"; ctx.globalAlpha = 1; ctx.fill();
      ctx.strokeStyle = "#071923"; ctx.globalAlpha = 1; ctx.lineWidth = Math.max(2, height / 70); ctx.stroke();
      if (projected.entrance) {
        ctx.strokeStyle = cyan; ctx.globalAlpha = .95; ctx.lineWidth *= 2;
        ctx.beginPath(); ctx.moveTo(...pixel(projected.entrance[0])); ctx.lineTo(...pixel(projected.entrance[1])); ctx.stroke();
        ctx.lineWidth /= 2;
      }
    }
    ctx.strokeStyle = "#edf6fa"; ctx.globalAlpha = .85; ctx.lineWidth = Math.max(1.5, height / 90);
    ctx.beginPath();
    for (const stripe of projected.markings) { ctx.moveTo(...pixel(stripe[0])); ctx.lineTo(...pixel(stripe[1])); }
    ctx.stroke();
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
      const y = target ? Math.max(top + 10, Math.min(bottom - 10, target[1])) : height / 2;
      const angle = target ? Math.atan2(target[1] - height / 2, target[0] - center) : projected.bearing < 0 ? Math.PI : 0;
      ctx.save(); ctx.translate(x, y); ctx.rotate(angle); ctx.globalAlpha = .85; ctx.strokeStyle = "#f0f8fc";
      ctx.beginPath(); ctx.moveTo(-4, -4); ctx.lineTo(1, 0); ctx.lineTo(-4, 4); ctx.stroke(); ctx.restore();
    }
  } else if (p.scene !== "unavailable" && p.lateral !== null) {
    const x = center + p.lateral * centerWidth * .4;
    ctx.globalAlpha = .8; ctx.strokeStyle = cyan;
    ctx.beginPath(); ctx.moveTo(x - 4, cy + 5); ctx.lineTo(x, cy); ctx.lineTo(x + 4, cy + 5); ctx.stroke();
  }
  ctx.restore();
  const stage = p.scene !== "unavailable" && !cue ? "高程 —" : cue?.approach && p.scene !== "glide"
    ? `${p.stageLabel} ${Number((Math.atan(cue.slope) * 180 / Math.PI).toFixed(1))}°` : p.stageLabel;
  const caption = `${p.course.replace("RWY ", "")} · ${p.distance.replace("距机场 ", "")} · ${stage}`;
  ctx.font = `600 ${font * .9}px "Microsoft YaHei", sans-serif`;
  const captionWidth = Math.min(centerWidth - 12, ctx.measureText(caption).width + 12);
  ctx.fillStyle = "#071923cc";
  ctx.fillRect(left + 4, top + 2, captionWidth, font + 8);
  text(caption, left + 10, top + 6 + font / 2, font * .9, muted, "left", captionWidth - 12);
  ctx.restore();
}
