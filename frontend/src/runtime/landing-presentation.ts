import type { LandingGeometry, LandingSnapshot } from "./landing-assist";

/** One correction convention for panel, Web/PiP, phone and native presentation. */
export function landingLateralGuidance(g: LandingGeometry | null | undefined) {
  if (!g) return { position: null, text: "引导待恢复" };
  const returning = g.stage === "return";
  const error = g.guidanceErrorDeg;
  if (error !== undefined) return error === null ? { position: null, text: "航迹 —" }
    : { position: Math.max(-1, Math.min(1, -error / 25)), text: Math.abs(error) < 2
      ? returning ? "正飞向机场" : "航迹已对准" : `${error > 0 ? "左" : "右"}修 ${Math.abs(error).toFixed(1)}°` };
  // Older manually distributed Desktop snapshots lack interception fields.
  if (returning) return { position: g.airportTrackErrorDeg === null ? null : Math.max(-1, Math.min(1, -g.airportTrackErrorDeg / 25)),
    text: g.airportTrackErrorDeg === null ? "航迹 —" : Math.abs(g.airportTrackErrorDeg) < 2 ? "正飞向机场"
      : `${g.airportTrackErrorDeg > 0 ? "左" : "右"}修 ${Math.abs(g.airportTrackErrorDeg).toFixed(1)}°` };
  return { position: Math.max(-1, Math.min(1, -g.crossTrackM / Math.max(80, Math.abs(g.thresholdDistanceM) * .1))),
    text: Math.abs(g.crossTrackM) < 20 ? "轴线附近" : `${g.crossTrackM > 0 ? "左" : "右"}修 ${Math.round(Math.abs(g.crossTrackM))}m` };
}

const metres = (n: number) => `${Math.round(Math.abs(n))} m`;

/** Present packaged configuration caps separately from a chosen approach IAS. */
export function landingConfigurationPresentation(landing: LandingSnapshot | null | undefined) {
  const profile = landing?.aircraft, flap = landing?.flapReference;
  const gearLimit = profile?.gearControl === false ? null : profile?.gearIasKmh;
  const limits: { label: string; limit: number; risk: string }[] = [];
  if (gearLimit) limits.push({ label: "起落架", limit: gearLimit, risk: landing?.gearRisk ?? "unknown" });
  if (flap?.limitIasKmh != null) limits.push({ label: `襟翼 ${Math.round(landing?.flapsPercent ?? 0)}%`, limit: flap.limitIasKmh, risk: flap.risk });
  if (flap?.next) limits.push({ label: `翼 ${Math.round(flap.next.percent)}% 参考点`, limit: flap.next.limitIasKmh, risk: "reference" });
  const gearRisk = landing?.gearRisk;
  const cue = gearRisk === "over-limit" ? "起落架超限" : flap?.risk === "over-limit" ? "襟翼超限"
    : gearRisk === "near-limit" ? "起落架近限" : flap?.risk === "near-limit" ? "襟翼近限"
      : gearRisk === "extension-too-fast" ? "放轮前减速" : "";
  const tone = gearRisk === "over-limit" || flap?.risk === "over-limit" ? "danger"
    : cue ? "caution" : "reference";
  let speedDetail = "IAS 参考未设";
  if (flap?.limitIasKmh != null) speedDetail = `翼参 ≤${Math.round(flap.limitIasKmh)}`;
  else if (gearLimit && (landing?.gearPercent == null || landing.gearPercent < 99)) speedDetail = `轮参 ≤${Math.round(gearLimit)}`;
  else if (flap?.next) speedDetail = `翼${Math.round(flap.next.percent)}% ≤${Math.round(flap.next.limitIasKmh)}`;
  else if (gearLimit) speedDetail = `轮参 ≤${Math.round(gearLimit)}`;
  const support = [profile?.wheelBrakeControl === true ? "轮刹" : "", profile?.brakeChute === true ? "减速伞" : ""].filter(Boolean);
  return { limits, cue, tone, speedDetail, braking: support.length ? `减速配置：${support.join(" · ")}` : "" };
}

export function landingPresentation(landing: LandingSnapshot | null | undefined) {
  const g = landing?.geometry;
  const returning = g?.stage === "return";
  const unavailable = landing?.reason === "runway-missing" ? "所选跑道暂不可见，等待恢复或重新选择"
    : landing?.reason === "runway-changed" ? "跑道端点已改变，请确认固定跑道的新端点"
      : "等待新鲜遥测与本机位置";
  const stage = g ? ({ return: "返航机场", intercept: "建立进近", final: "跑道进近", runway: "入口后方", "past-runway": "末端后方" })[g.stage] : "等待数据";
  const lateral = landingLateralGuidance(g).text;
  const vertical = !g ? "垂直 —" : returning ? "近场对准后显示下滑参考" : g.stage === "runway" || g.stage === "past-runway" ? "下滑参考已结束"
    : g.heightM === null ? "高程未知 · 仅水平引导" : g.glideDeviationM === null ? "对准后显示下滑参考"
      : Math.abs(g.glideDeviationM) <= Math.max(10, g.thresholdDistanceM * Math.tan(.4 * Math.PI / 180)) ? "参考下滑线附近"
        : `${g.glideDeviationM > 0 ? "偏高" : "偏低"} ${metres(g.glideDeviationM)}`;
  const target = landing?.settings.targetIasKmh;
  const speed = landing?.iasKmh == null ? "IAS —" : target == null ? `IAS ${Math.round(landing.iasKmh)} km/h`
    : `IAS ${Math.round(landing.iasKmh)} / ${target} · ${Math.abs(landing.iasKmh - target) <= target * .1 ? "参考附近" : landing.iasKmh > target ? "高于参考" : "低于参考"}`;
  const configuration = landing ? [landing.aircraft?.gearControl === false ? "无起落架收放控制" : landing.gearPercent === null ? "起落架未知" : landing.gearPercent >= 99 ? "放轮 100%" : landing.gearPercent <= 1 ? "收轮 0%" : "起落架过渡中",
    `${landing.flapsPercent === null ? "襟翼 —" : `襟翼 ${Math.round(landing.flapsPercent)}%`}${landing.aircraft?.flapsControl === false ? "（无手动控制）" : ""}`,
    landing.aircraft?.airbrakeControl === false ? "无减速板" : landing.airbrakePercent === null ? "减速板 —" : `减速板 ${Math.round(landing.airbrakePercent)}%`].join(" · ") : "";
  const distance = returning ? `距机场 ${(g.airportDistanceM / 1000).toFixed(1)} km`
    : g ? g.thresholdDistanceM >= 0 ? `距入口 ${(g.thresholdDistanceM / 1000).toFixed(2)} km` : `入口后方 ${metres(g.thresholdDistanceM)}` : "距离 —";
  const course = returning ? g.airportBearingDeg === null ? "机场方位 —" : `机场方位 ${Math.round(g.airportBearingDeg).toString().padStart(3,"0")}°`
    : g ? `跑道方向 ${Math.round(g.courseDeg).toString().padStart(3,"0")}°` : "跑道方向 —";
  const verticalSpeed = landing?.verticalSpeedMps == null ? "下降率 —" : `垂直 ${landing.verticalSpeedMps.toFixed(1)} m/s${g?.referenceDescentMps == null ? "" : ` · 参考 ${g.referenceDescentMps.toFixed(1)}`}`;
  const elevation = landing?.elevationM == null ? "等待跑道高程" : `${landing.elevationSource === "terrain" ? "地形初估" : "手动高程"} ${Math.round(landing.elevationM)} m`;
  const limit = landing?.aircraft?.gearIasKmh;
  const gearLimit = limit ? `起落架参考上限 IAS ${Math.round(limit)} km/h` : "起落架限速资料未知";
  const gearAdvice = ({ "over-limit":"已超过静态限速 · 起落架可能损坏", "near-limit":"接近起落架静态限速", "extension-too-fast":"当前超过放轮参考限速 · 放轮前减速", reference:"", unknown:"当前起落架超速风险未知" })[landing?.gearRisk ?? "unknown"];
  const config = landingConfigurationPresentation(landing);
  const flapAdvice = landing?.flapReference?.risk === "over-limit" ? `襟翼超过参考上限 · ${landing.aircraft?.flapsControl === true ? "减速/收翼" : "减速"}`
    : landing?.flapReference?.risk === "near-limit" ? "襟翼接近参考上限" : "";
  const projection = !returning && g?.predictedThresholdCrossM != null && g.thresholdTimeS != null
    ? `按当前航迹：约 ${Math.round(g.thresholdTimeS)} s 到入口 · ${Math.abs(g.predictedThresholdCrossM) < 20 ? "轴线附近" : `${g.predictedThresholdCrossM > 0 ? "右" : "左"}偏 ${metres(g.predictedThresholdCrossM)}`}` : "";
  const hook = landing?.aircraft?.arrestorHook;
  const arrestor = hook === true ? "着舰钩：静态支持"
    : hook === false ? "着舰钩：当前配置未配备" : "着舰钩：资料未确认";
  const fastDescent = g?.referenceDescentMps != null && landing?.verticalSpeedMps != null
    && landing.verticalSpeedMps < g.referenceDescentMps - Math.max(2,Math.abs(g.referenceDescentMps)*.5);
  const touchdown = returning ? "返航阶段 · 近场再检查进近构型" : fastDescent ? "下降快于参考 · 注意接地前减小下沉" : "触地损伤阈值未知 · 按实际姿态和下沉率拉平";
  const compact = !landing?.settings.enabled ? "" : !g ? `降落 · ${unavailable}`
    : returning ? `返航 · ${course} · ${distance}`
    : `降落 ${Math.round(g.courseDeg).toString().padStart(3,"0")}° · ${g.thresholdDistanceM < 0 ? "入口后" : "距入口"}${(Math.abs(g.thresholdDistanceM)/1000).toFixed(1)}km`;
  return { stage, lateral, vertical, speed, configuration, distance, course, verticalSpeed, elevation, compact, gearLimit, gearAdvice, arrestor, touchdown, flapAdvice, projection, braking: config.braking,
    message: landing?.status === "disabled" ? landing.settings.automatic ? "自动待命 · 飞向友方机场 3 秒后切换，也可手动开启" : "开启后锁定友方跑道，独立于投弹目标" : g ? `${landing?.settings.automatic ? "自动" : ""}${stage} · ${returning ? landing.runwayLabel : elevation}` : unavailable };
}
