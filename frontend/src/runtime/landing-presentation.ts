import type { LandingSnapshot } from "./landing-assist";

const metres = (n: number) => `${Math.round(Math.abs(n))} m`;
export function landingPresentation(landing: LandingSnapshot | null | undefined) {
  const g = landing?.geometry;
  const unavailable = landing?.reason === "runway-missing" ? "所选跑道暂不可见，等待恢复或重新选择"
    : landing?.reason === "runway-changed" ? "跑道端点已改变，请确认固定跑道的新端点"
      : "等待新鲜遥测与本机位置";
  const stage = g ? ({ intercept: "建立进近", final: "跑道进近", runway: "入口后方", "past-runway": "末端后方" })[g.stage] : "等待数据";
  const lateral = g ? Math.abs(g.crossTrackM) < 20 ? "轴线附近" : g.stage === "final"
    ? `向${g.crossTrackM > 0 ? "左" : "右"}修正 ${metres(g.crossTrackM)}`
    : `轴线${g.crossTrackM > 0 ? "右" : "左"}侧 ${metres(g.crossTrackM)}` : "横向 —";
  const vertical = !g ? "垂直 —" : g.stage === "runway" || g.stage === "past-runway" ? "下滑参考已结束"
    : g.heightM === null ? "高程未知 · 仅水平引导" : g.glideDeviationM === null ? "对准后显示下滑参考"
      : Math.abs(g.glideDeviationM) <= Math.max(10, g.thresholdDistanceM * Math.tan(.4 * Math.PI / 180)) ? "参考下滑线附近"
        : `${g.glideDeviationM > 0 ? "偏高" : "偏低"} ${metres(g.glideDeviationM)}`;
  const target = landing?.settings.targetIasKmh;
  const speed = landing?.iasKmh == null ? "IAS —" : target == null ? `IAS ${Math.round(landing.iasKmh)} · 未设参考`
    : `IAS ${Math.round(landing.iasKmh)} / ${target} · ${Math.abs(landing.iasKmh - target) <= target * .1 ? "参考附近" : landing.iasKmh > target ? "高于参考" : "低于参考"}`;
  const configuration = landing ? [landing.aircraft?.gearControl === false ? "无起落架收放控制" : landing.gearPercent === null ? "起落架未知" : landing.gearPercent >= 99 ? "放轮 100%" : landing.gearPercent <= 1 ? "收轮 0%" : "起落架过渡中",
    landing.flapsPercent === null ? "襟翼未知" : `襟翼 ${Math.round(landing.flapsPercent)}%`,
    landing.airbrakePercent === null ? "减速板未知" : `减速板 ${Math.round(landing.airbrakePercent)}%`].join(" · ") : "";
  const distance = g ? g.thresholdDistanceM >= 0 ? `距入口 ${(g.thresholdDistanceM / 1000).toFixed(2)} km` : `入口后方 ${metres(g.thresholdDistanceM)}` : "距离 —";
  const verticalSpeed = landing?.verticalSpeedMps == null ? "下降率 —" : `垂直 ${landing.verticalSpeedMps.toFixed(1)} m/s${g?.referenceDescentMps == null ? "" : ` · 参考 ${g.referenceDescentMps.toFixed(1)}`}`;
  const elevation = landing?.elevationM == null ? "等待跑道高程" : `${landing.elevationSource === "terrain" ? "地形初估" : "手动高程"} ${Math.round(landing.elevationM)} m`;
  const limit = landing?.aircraft?.gearIasKmh;
  const gearLimit = limit ? `起落架参考上限 IAS ${Math.round(limit)} km/h` : "起落架限速资料未知";
  const gearAdvice = ({ "over-limit":"已超过静态限速 · 起落架可能损坏", "near-limit":"接近起落架静态限速", "extension-too-fast":"当前超过放轮参考限速 · 放轮前减速", reference:"", unknown:"当前起落架超速风险未知" })[landing?.gearRisk ?? "unknown"];
  const hook = landing?.aircraft?.arrestorHook;
  const arrestor = hook === true ? "着舰钩：静态支持 · 放轮自动放钩"
    : hook === false ? "着舰钩：当前配置未配备" : "着舰钩：资料未确认";
  const fastDescent = g?.referenceDescentMps != null && landing?.verticalSpeedMps != null
    && landing.verticalSpeedMps < g.referenceDescentMps - Math.max(2,Math.abs(g.referenceDescentMps)*.5);
  const touchdown = fastDescent ? "下降快于参考 · 注意接地前减小下沉" : "触地损伤阈值未知 · 按实际姿态和下沉率拉平";
  const compact = !landing?.settings.enabled ? "" : !g ? `降落 · ${unavailable}`
    : `降落 ${Math.round(g.courseDeg).toString().padStart(3,"0")}° · ${g.thresholdDistanceM < 0 ? "入口后" : "距入口"}${(Math.abs(g.thresholdDistanceM)/1000).toFixed(1)}km`;
  return { stage, lateral, vertical, speed, configuration, distance, verticalSpeed, elevation, compact, gearLimit, gearAdvice, arrestor, touchdown,
    message: landing?.status === "disabled" ? landing.settings.automatic ? "自动待命 · 持续飞向友方跑道时切换，也可手动开启" : "开启后锁定友方跑道，独立于投弹目标" : g ? `${landing?.settings.automatic ? "自动" : ""}${stage} · ${elevation}` : unavailable };
}
