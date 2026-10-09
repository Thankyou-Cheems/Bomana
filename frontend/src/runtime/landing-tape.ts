import type { EditionSnapshot } from "./runtime-types";
import { fuelEndurance } from "./fuel-presentation";
import { landingConfigurationPresentation, landingHeightPresentation, landingLateralGuidance, landingSurfacePresentation, landingRunwayRemaining } from "./landing-presentation";
import { landingRunwayScene, landingRunwayFrame, landingPerspectiveViewport, projectLandingRunway, RunwaySceneMotion, type LandingRunwayScene, type ProjectedPoint } from "./landing-runway-projection";

const finite = (n: number | null | undefined): n is number => typeof n === "number" && Number.isFinite(n);
const clamp = (n: number) => Math.max(-1, Math.min(1, n));
const heading = (n: number) => Math.round((n % 360 + 360) % 360).toString().padStart(3, "0");

/** Compact flight references only; no learned-fuel diagnostics or landing safety claim. */
export function landingTapePresentation(snapshot: EditionSnapshot) {
  const landing = snapshot.landing, g = landing?.geometry;
  const surface = landingSurfacePresentation(landing);
  const remainingM = landingRunwayRemaining(g);
  const height = landingHeightPresentation(landing);
  const returning = g?.stage === "return";
  const active = landing?.settings.enabled === true;
  const ias = landing?.iasKmh, targetIas = landing?.settings.targetIasKmh;
  const fuel = snapshot.fuel;
  const fuelAvailable = fuel?.available === true && snapshot.sortieContinuity.state === "live"
    && landing?.reason !== "telemetry" && finite(fuel.currentKg) && fuel.currentKg >= 0;
  const minutes = fuelAvailable && fuel?.source === "measured" && finite(fuel.remainingMinutes) && fuel.remainingMinutes >= 0
    ? fuel.remainingMinutes : null;
  const endurance = fuelEndurance(fuelAvailable ? fuel : null);
  const fuelText = endurance.text;
  const fuelDetail = endurance.detail;
  const equipmentState = (value: boolean | null | undefined) => value === true ? "✓" : value === false ? "×" : "?";
  const equipmentText = `钩${equipmentState(landing?.aircraft?.arrestorHook)} 伞${equipmentState(landing?.aircraft?.brakeChute)}`;
  const equipmentDescription = (value: boolean | null | undefined) => value === true ? "已配备" : value === false ? "未配备" : "未知";
  const equipmentAria = `机型配置：尾钩${equipmentDescription(landing?.aircraft?.arrestorHook)}，减速伞${equipmentDescription(landing?.aircraft?.brakeChute)}；仅为静态配备，非当前展开或挂索状态`;
  const configuration = landingConfigurationPresentation(landing);
  const speedTone = configuration.tone === "danger" ? "danger"
    : configuration.tone === "caution" || !surface && finite(ias) && finite(targetIas) && Math.abs(ias - targetIas) > targetIas * .1 ? "caution" : "reference";
  const fuelTone = fuelAvailable && (fuel!.currentKg <= 0 || minutes !== null && minutes < 3) ? "danger"
    : minutes !== null && minutes < 5 ? "caution" : "reference";
  const { position: lateral, text: lateralText } = surface ? { position: null, text: "跑道内位置参考" } : landingLateralGuidance(g);
  // A stale/older producer must never leave a vertical cue beyond the threshold.
  const glide = landing?.terrainCorridor === undefined && g?.stage === "final" && g.thresholdDistanceM > 0 && finite(g.heightM) && finite(g.glideDeviationM)
    ? clamp(g.glideDeviationM / Math.max(20, g.thresholdDistanceM * .02)) : null;
  const glideText = surface ? "地面阶段参考" : !g ? "" : landing?.terrainCorridor !== undefined
    ? landing.terrainCorridor ? landing.terrainCorridor.raised ? "注意地形" : "地形返航参考" : "地形航道暂无数据"
    : returning ? "返航中" : g.stage === "runway" || g.stage === "past-runway" ? "下滑结束"
    : g.heightM === null ? "高程未知" : g.glideDeviationM === null ? "先对准"
      : Math.abs(g.glideDeviationM) <= 10 ? "参考线附近" : `${g.glideDeviationM > 0 ? "高" : "低"} ${Math.round(Math.abs(g.glideDeviationM))}m`;
  const vy = finite(landing?.verticalSpeedMps) ? `${landing!.verticalSpeedMps! < 0 ? "↓" : "↑"}${Math.abs(landing!.verticalSpeedMps!).toFixed(1)}m/s` : "Vy —";
  const gear = landing?.aircraft?.gearControl === false ? "无收放控制"
    : finite(landing?.gearPercent) ? `轮 ${Math.round(landing!.gearPercent!)}%` : "轮 —";
  const config = configuration.cue || (g && !returning && g.thresholdDistanceM < 3000 && g.thresholdDistanceM > 0
      && landing?.aircraft?.gearControl !== false && finite(landing?.gearPercent) && landing!.gearPercent! < 99 ? "检查放轮" : gear);
  const identity = landing?.runwayLabel || "机场";
  const course = returning ? g.airportBearingDeg === null ? `${identity} —` : `${identity} · ${heading(g.airportBearingDeg)}°` : g ? `${identity} · RWY ${heading(g.courseDeg)}°` : "跑道 —";
  const distance = surface ? `余跑道 ${(surface.remainingM / 1000).toFixed(1)}km` : remainingM !== null ? `至末端 ${(remainingM / 1000).toFixed(1)}km` : returning ? `距机场 ${(g.airportDistanceM / 1000).toFixed(1)}km`
    : g ? `${g.thresholdDistanceM < 0 ? "入口后 " : ""}${(Math.abs(g.thresholdDistanceM) / 1000).toFixed(1)}km` : "距离 —";
  const mode = surface ? "跑道地面参考" : landing?.settings.automatic ? returning ? "自动返航" : "自动进近" : returning ? "返航参考" : "降落参考";
  const speedText = finite(ias) ? `${Math.round(ias)}` : "—";
  const speedDetail = !surface && finite(targetIas) ? `参考 ${Math.round(targetIas)}` : configuration.speedDetail;
  const scene = !active || !g || landing?.status !== "guidance" ? "unavailable"
    : surface ? "ground" : g.stage === "return" ? "return" : g.stage === "runway" || g.stage === "past-runway" ? "rollout"
      : glide !== null && lateral !== null ? "glide" : "align";
  const airportHeightText = scene === "return" && finite(g?.heightM)
    ? `${g.heightM >= 0 ? "↓" : "↑"}${Math.round(Math.abs(g.heightM))}m` : "";
  const stageLabel = surface?.label ?? (scene === "unavailable" ? "等待数据" : lateral === null ? "航迹 —" : scene === "return" ? "返航"
    : scene === "rollout" ? remainingM !== null ? "沿跑道" : "入口后" : scene === "glide" ? `${landing!.settings.glideAngleDeg}°`
      : g?.heightM === null ? "高程 —" : "对正");
  const cueLateral = scene === "unavailable" ? null : lateral;
  const cueGlide = scene === "glide" ? glide : null;
  const projectedScene = scene === "unavailable" || surface ? null : landingRunwayScene(g, snapshot.flight.headingDeg, landing!.settings.glideAngleDeg, landing?.attitude);
  const projectedRunway: LandingRunwayScene | null = projectedScene ? { ...projectedScene, terrainCorridor: landing?.terrainCorridor } : null;
  // Height can differ from a raised runway platform. Passing the selected
  // entrance still ends its inbound curve, without claiming wheel contact.
  const runway = projectedRunway && (g?.stage === "runway" || g?.stage === "past-runway")
    ? { ...projectedRunway, approach: false } : projectedRunway;
  const horizontal = scene !== "unavailable" && !surface && g?.heightM === null
    ? { geometry: g, headingDeg: snapshot.flight.headingDeg } : null;
  const otherRunways = active && !surface && landing?.reason !== "telemetry" ? (landing?.nearbyRunways ?? [])
    .filter(item => item.id !== landing?.settings.runwayId)
    .map(item => ({ ...item, scene: item.geometry.heightM === null ? null : landingRunwayScene(item.geometry, snapshot.flight.headingDeg, landing!.settings.glideAngleDeg, landing?.attitude),
      bearing: ((item.geometry.airportBearingDeg ?? snapshot.flight.headingDeg) - snapshot.flight.headingDeg + 540) % 360 - 180 }))
    .filter(item => Math.abs(item.bearing) <= 30) : [];
  // Stage boundaries keep motion continuous. A changed altitude datum must
  // reset relative-height interpolation so the absolute aircraft camera stays put.
  const selected = snapshot.navigation?.items.find(item => item.id === landing?.settings.runwayId);
  const cueKey = `${landing?.runwayKey || (selected?.runwayStart && selected.runwayEnd ? JSON.stringify([selected.runwayStart, selected.runwayEnd]) : landing?.settings.runwayId)}|${landing?.settings.reverse}|${runway?.heightKnown}|${landing?.elevationM}`;
  return { heightReference: height.reference, heightCaption: height.compactReference, ground: surface, active, mode, course, distance, lateral: cueLateral, glide: cueGlide, airportHeightText, lateralText, glideText, vy, config, scene, stageLabel, cueKey,
    runway, horizontal, otherRunways, speedText, speedDetail, speedTone, fuelText, fuelDetail, fuelTone, equipmentText,
    aria: `${mode}${surface ? `；${surface.label}；跑道位置示意，观测推断，不证明轮胎接触、损伤或刹车状态` : ""}；${course}，${distance}${horizontal ? "；前向航线透视，垂直数据不完整，无下滑指令" : ""}${g ? `；${height.reference}` : ""}${runway && !horizontal ? `；${g?.referenceWidthM ? "宽度采用同长度机场定义参考" : "跑道轮廓宽度为示意"}；以玩家前向视角呈现，近端以中央透视区两侧为翼端参考、远端按深度收缩；视野外机场保留方向提示；姿态缺测使用可用航迹俯仰和水平滚转${landing?.terrainCorridor === undefined ? "；曲线从当前高度与俯仰接入末段下滑线；近端显示面随翼端衔接，远端接入跑道；高低偏差独立计算" : landing.terrainCorridor ? "；返航路径按沿途地形抬升，显示面预留75米，其中50米为植被余量而非实测树高；淡琥珀色表示路线抬升；对正后最后1.5公里交回普通降落参考，该末段未验证植被净空" : "；地形包线暂不可用，保留机场方向"}；非目标跑道仅显示轮廓；不表示转弯性能或净空保证` : ""}；IAS ${speedText} km/h，${speedDetail}；燃油续航 ${fuelDetail}；${lateralText}，${glideText}，${vy}；${config}；${equipmentAria}` };
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

/** Perspective runway and two heading-tangent approach rails. */
export function drawLandingTape(ctx: CanvasRenderingContext2D, p: LandingTapeView, width: number, height: number, cue: LandingRunwayScene | null, others = p.otherRunways, simplified = false): void {
  const pad = Math.max(8, Math.min(20, width * .025));
  const side = Math.max(54, Math.min(125, width * .18));
  const { left } = landingPerspectiveViewport(width), right = width - left, center = width / 2;
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
  // A stale interpolation/caller may still supply the preceding approach.
  // Current post-entrance semantics revoke its curve before drawing any paths.
  const frame = cue && !p.ground ? landingRunwayFrame(p.scene === "rollout" ? { ...cue, approach: false } : cue, centerWidth, height, simplified) : null;
  const projected = frame?.projected;
  // The player owns the camera. All runway geometry shares its perspective;
  // the near corridor uses only the central perspective viewport as its wings.
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
  for (const item of (p.horizontal ? [] : [...others].sort((a, b) => b.geometry.airportDistanceM - a.geometry.airportDistanceM))) {
    const other = item.scene ? projectLandingRunway({ ...item.scene, approach: false }, frame?.pitch, frame?.roll, frame?.retreat, frame?.yaw, { simplified: true }) : null;
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
  if (projected) {
    const rails = projected.rails;
    const ribbon = projected.ribbon;
    ctx.lineWidth = Math.max(1.5, height / 90);
    ctx.fillStyle = cyan; ctx.globalAlpha = .14 * frame.routeWeight;
    // The canvas clips crossing segments. No focal-length threshold suddenly
    // removes the near half of the curve while the same approach is active.
    for (const quad of ribbon) {
      polygon(quad); ctx.fill();
    }
    ctx.strokeStyle = cue?.terrainCorridor?.raised ? "#e8bd72" : "#70dace"; ctx.globalAlpha = .95 * frame.routeWeight; ctx.lineWidth = Math.max(1.5, height / 75);
    for (const rail of rails) {
      ctx.beginPath();
      let previous: ProjectedPoint | null = null;
      for (const piece of rail) {
        if (!previous || previous[0] !== piece[0][0] || previous[1] !== piece[0][1]) ctx.moveTo(...pixel(piece[0]));
        ctx.lineTo(...pixel(piece[1])); previous = piece[1];
      }
      ctx.stroke();
    }
    // A low aircraft can be below the entire raised route. Keep a small steady
    // upward cue at the viewport edge instead of pulling the path through rock.
    if (cue?.terrainCorridor && cue.terrainCorridor.floorsM[0]! > cue.height + 25) {
      ctx.globalAlpha = .95; ctx.strokeStyle = "#e8bd72";
      ctx.beginPath(); ctx.moveTo(center - 6, top + 8); ctx.lineTo(center, top + 3); ctx.lineTo(center + 6, top + 8); ctx.stroke();
    }
    // Keep the target surface legible where the intercept overlaps it in a
    // steep/banked observation view. Guidance must not wash out the runway.
    if (projected.surface.length >= 3) {
      polygon(projected.surface);
      const nearPavement = projected.detailLod !== "outline" || cue && cue.heightKnown !== false && cue.height < 120
        && cue.along < 1500 && cue.along >= -cue.length;
      // A broad nearby surface should read as pavement, rather than an opaque
      // white wedge. Far entrances retain their small high-contrast silhouette.
      // Muted grey/brown concrete is informed by the decoded A detail material;
      // its texture footprint is not a measured visible pavement boundary.
      ctx.fillStyle = nearPavement ? "#81766b" : "#e7eef2"; ctx.globalAlpha = 1; ctx.fill();
      // A dark outline erases a sub-pixel far runway in a short navigation strip.
      // A light edge preserves its silhouette without changing the projection.
      ctx.strokeStyle = "#e7eef2"; ctx.globalAlpha = 1; ctx.lineWidth = 1.5; ctx.stroke();
      if (projected.entrance) {
        ctx.strokeStyle = cyan; ctx.globalAlpha = .95; ctx.lineWidth *= 2;
        ctx.beginPath(); ctx.moveTo(...pixel(projected.entrance[0])); ctx.lineTo(...pixel(projected.entrance[1])); ctx.stroke();
        ctx.lineWidth /= 2;
      }
    }
    // Batch the cached vector pattern into at most two clipped fill layers.
    // Paint shares the physical runway plane, so center dashes and end keys
    // shrink with perspective rather than retaining arbitrary screen lengths.
    for (const rubber of [true, false]) {
      ctx.beginPath();
      let count = 0;
      for (const detail of projected.details) {
        if ((detail.kind === "rubber") !== rubber) continue;
        detail.points.forEach((point, index) => {
          const v = pixel(point); if (index) ctx.lineTo(...v); else ctx.moveTo(...v);
        });
        ctx.closePath(); count++;
      }
      if (count) {
        ctx.fillStyle = rubber ? "#302d28" : "#edf6fa"; ctx.globalAlpha = rubber ? .35 : .9; ctx.fill();
      }
    }
  } else if (p.ground) {
    // Small unfilled position schematic replaces the near-surface white
    // perspective. Its bounded corridor is a reference, not collision width.
    const span = Math.min(180, centerWidth * .55), x = center - span / 2, y = height * .52;
    ctx.globalAlpha = .7; ctx.strokeStyle = muted; ctx.lineWidth = 1;
    ctx.strokeRect(x, y - 5, span, 10);
    ctx.setLineDash([3, 4]);
    ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x + span, y); ctx.stroke(); ctx.setLineDash([]);
    ctx.globalAlpha = 1; ctx.strokeStyle = cyan; ctx.lineWidth = 1.5;
    ctx.beginPath(); ctx.arc(x + span * p.ground.progress, y + clamp(p.ground.crossTrackM / 60) * 5, 3, 0, Math.PI * 2); ctx.stroke();
    text("跑道位置示意", center, height * .73, font * .85, muted, "center", centerWidth - 16);
  } else if (p.scene !== "unavailable" && p.lateral !== null) {
    const x = center + p.lateral * centerWidth * .4;
    ctx.globalAlpha = .8; ctx.strokeStyle = cyan;
    ctx.beginPath(); ctx.moveTo(x - 4, cy + 5); ctx.lineTo(x, cy); ctx.lineTo(x + 4, cy + 5); ctx.stroke();
  }
  ctx.restore();
  text("IAS", pad, height * .21, font, muted, "left", side - pad);
  text(p.speedText, pad, height * .45, large, tone(p.speedTone), "left", side - pad);
  text(p.speedDetail.replace("参考", "目标").replace("IAS 目标未设", "目标 —"), pad, height * .67, font, muted, "left", side - pad);
  text("余油 · s", width - pad, height * .21, font, muted, "right", side - pad);
  text(p.fuelText, width - pad, height * .45, large, tone(p.fuelTone), "right", side - pad);
  text(p.vy, width - pad, height * .67, font, muted, "right", side - pad);
  text(p.equipmentText, width - pad, height * .87, font * .85, muted, "right", side - pad);
  const configColor = /超限/.test(p.config) ? tone("danger") : /检查|减速|近限/.test(p.config) ? tone("caution") : muted;
  text(p.config, pad, height * .87, font * .9, configColor, "left", side - pad);
  const stage = p.ground ? p.stageLabel : p.horizontal ? "方位透视" : p.scene !== "unavailable" && !cue ? "高程 —" : cue?.approach && cue.terrainCorridor === undefined && p.scene !== "glide"
    ? `${p.stageLabel} ${Number((Math.atan(cue.slope) * 180 / Math.PI).toFixed(1))}°` : p.stageLabel;
  const caption = `${p.scene === "return" ? "返航 " : ""}${p.course.replace("RWY ", "")} · ${p.distance.replace("距机场 ", "")}${p.scene === "return" ? "" : ` · ${stage}`}`;
  const captionFont = Math.max(9, font * .9);
  ctx.font = `600 ${captionFont}px "Microsoft YaHei", sans-serif`;
  const joinedCaption = `${caption} · ${p.heightCaption}`;
  // Compact return context fits on one line when the window permits it. Phone
  // windows keep two short lines; full reference wording remains in ARIA/panel.
  const captions = p.scene === "unavailable" ? [caption]
    : p.scene === "return" && ctx.measureText(joinedCaption).width <= centerWidth - 24 ? [joinedCaption]
      : [caption, p.heightCaption];
  const captionWidth = Math.min(centerWidth - 12, Math.max(...captions.map(line => ctx.measureText(line).width)) + 12);
  const captionHeight = (captionFont + 2) * captions.length + 4;
  const passedEntrance = p.scene === "rollout";
  const target = !passedEntrance && projected?.threshold ? pixel(projected.threshold) : null;
  const offscreen = !passedEntrance && projected && (!target || !inside(target));
  const cueX = offscreen ? target ? target[0] < left + 8 ? left + 10 : target[0] > right - 8 ? right - 10 : target[0]
    : projected.bearing < 0 ? left + 10 : right - 10 : target?.[0];
  const cueY = offscreen ? target && cueX === target[0] ? Math.max(top + 10, Math.min(bottom - 10, target[1])) : height / 2 : target?.[1];
  const overlapsCue = (x: number) => cueX != null && cueY != null
    && cueX + 8 >= x && cueX - 8 <= x + captionWidth && cueY + 8 >= top + 2 && cueY - 8 <= top + 2 + captionHeight;
  // Keep the familiar corner unless the airport cue needs that space. A small
  // window may leave neither corner clear; the final cue overlay still wins.
  const rightCaptionX = right - captionWidth - 4;
  const captionX = overlapsCue(left + 4) && !overlapsCue(rightCaptionX) ? rightCaptionX : left + 4;
  // Text only: no opaque or translucent airport-debug panel over the route.
  captions.forEach((line, index) => text(line, captionX + 6, top + 5 + captionFont / 2 + index * (captionFont + 2),
    captionFont, muted, "left", captionWidth - 12));
  // Airport entrance/direction is essential even when its projected position
  // overlaps a caption. Draw it last, within the same instrument-free viewport.
  if (projected && !passedEntrance) {
    ctx.save();
    ctx.beginPath(); ctx.rect(left, top, centerWidth, bottom - top); ctx.clip();
    if (offscreen) {
      // A clipped or rearward runway remains a direction cue, never a fabricated projection.
      const angle = target ? Math.atan2(target[1] - height / 2, target[0] - center) : projected.bearing < 0 ? Math.PI : 0;
      ctx.save(); ctx.translate(cueX!, cueY!); ctx.rotate(angle); ctx.globalAlpha = 1; ctx.strokeStyle = "#f0f8fc"; ctx.lineWidth = 1.5;
      ctx.beginPath(); ctx.moveTo(-5, -5); ctx.lineTo(1, 0); ctx.lineTo(-5, 5); ctx.stroke(); ctx.restore();
    } else if (target && (
      // Even a broad known runway can lose contrast beneath a text caption.
      // Preserve its true threshold position with the same compact marker.
      target[0] >= captionX - 3 && target[0] <= captionX + captionWidth + 3
        && target[1] >= top - 1 && target[1] <= top + captionHeight + 5
      || !projected.entrance || Math.hypot(...projected.entrance[0].map((v, i) => v - projected.entrance![1][i]!)) * focal < 6)) {
      // Mark a distant/unknown-height entrance without zooming its geometry.
      ctx.globalAlpha = 1; ctx.strokeStyle = "#f0f8fc"; ctx.lineWidth = 1.5;
      ctx.beginPath(); ctx.moveTo(target[0], target[1] - 3); ctx.lineTo(target[0] + 3, target[1]);
      ctx.lineTo(target[0], target[1] + 3); ctx.lineTo(target[0] - 3, target[1]); ctx.closePath(); ctx.stroke();
    }
    ctx.restore();
  }
  ctx.restore();
}
