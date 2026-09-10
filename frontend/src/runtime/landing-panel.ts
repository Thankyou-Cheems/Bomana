import { DEFAULT_LANDING_SETTINGS, type LandingSettings, type LandingSnapshot } from "./landing-assist";
import { landingConfigurationPresentation, landingLateralGuidance, landingPresentation } from "./landing-presentation";

/** Shared controls/presentation only. The caller owns every calculation. */
export class LandingPanel {
  readonly element: HTMLElement;
  #snapshot: LandingSnapshot | null = null;
  #runways = "";
  constructor(parent: HTMLElement, submit: (settings: LandingSettings) => void) {
    const panel = document.createElement("section"); panel.className = "landing-panel"; panel.setAttribute("aria-label", "降落辅助");
    panel.innerHTML = `<header><strong>降落辅助 <small>参考</small></strong><label class="landing-auto"><input type="checkbox" data-part="automatic">自动切换</label><button type="button" data-part="toggle" aria-pressed="false">开启</button></header>
      <p data-part="message"></p><button type="button" data-part="confirm-runway" hidden>确认新端点</button><div data-part="active" hidden>
      <div class="landing-runway"><select data-part="runway" aria-label="降落跑道"></select><button type="button" data-part="reverse" title="反向进近会清空手动高程">反向进近</button></div>
      <div class="landing-deviations"><div><span data-part="lateral"></span><div class="landing-axis"><i data-part="lateral-dot"></i></div></div><div><span data-part="vertical"></span><div class="landing-axis"><i data-part="vertical-dot"></i></div></div></div>
      <div class="landing-readouts"><span data-part="distance"></span><span data-part="course"></span><span data-part="speed"></span><span data-part="verticalSpeed"></span></div>
      <p class="landing-projection" data-part="projection"></p>
      <p class="landing-configuration" data-part="configuration"></p>
      <div class="landing-airframe"><span data-part="gearLimit"></span><div class="landing-limits" data-part="limits" aria-label="构型 IAS 参考上限"></div><strong data-part="gearAdvice"></strong><strong data-part="flapAdvice"></strong><span data-part="braking"></span><span data-part="arrestor"></span><span data-part="touchdown"></span></div>
      <details><summary>进近参考参数</summary><div class="landing-fields">
        <label>参考 IAS · km/h<input type="number" min="60" max="600" step="1" data-part="ias" placeholder="按机型手动设定"></label>
        <label>参考下滑角 · °<input type="number" min="1" max="8" step="0.1" data-part="angle"></label>
        <label>跑道高程 · m<input type="number" min="-1000" max="10000" step="1" data-part="elevation" placeholder="留空使用可用地形"></label>
      </div><button type="button" data-part="apply">应用参考参数</button><p>高程须与 8111 高度使用相同基准。参考线在入口上方 15 m；角度和 IAS 需按机型、载荷自行选择。地形不含跑道设施与障碍物，越过入口后不提供拉平或接地判定。</p><p>构型限速来自机型离线数据，襟翼参考点不等于可选档位；按展开比例插值，不能当作失速、安全落地速度或实际损坏判定。轮刹、伞和钩仅表示机型配置，实际展开、接触和挂索需在游戏内确认。</p></details>
      </div><p class="landing-error" data-part="error" role="alert"></p>`;
    parent.append(panel); this.element = panel;
    const change = (patch: Partial<LandingSettings>) => submit({ ...(this.#snapshot?.settings ?? DEFAULT_LANDING_SETTINGS), ...patch });
    this.part("toggle").addEventListener("click", () => change({ enabled: !this.#snapshot?.settings.enabled, automatic: false }));
    this.part<HTMLInputElement>("automatic").addEventListener("change", event => change({ automatic: (event.target as HTMLInputElement).checked, enabled: false }));
    this.part<HTMLSelectElement>("runway").addEventListener("change", event => change({ runwayId: (event.target as HTMLSelectElement).value }));
    this.part("reverse").addEventListener("click", () => change({ reverse: !this.#snapshot?.settings.reverse }));
    this.part("confirm-runway").addEventListener("click", () => change({}));
    this.part("apply").addEventListener("click", () => {
      const ias = this.part<HTMLInputElement>("ias"), angle = this.part<HTMLInputElement>("angle"), elevation = this.part<HTMLInputElement>("elevation");
      if (![ias,angle,elevation].every(input => input.reportValidity()) || angle.value === "") return;
      change({ targetIasKmh: ias.value === "" ? null : ias.valueAsNumber, glideAngleDeg: angle.valueAsNumber,
        runwayElevationM: elevation.value === "" ? null : elevation.valueAsNumber });
    });
  }
  part<T extends HTMLElement = HTMLElement>(name: string): T { return this.element.querySelector<T>(`[data-part="${name}"]`)!; }
  update(snapshot: LandingSnapshot | null | undefined): void {
    const previous = this.#snapshot; this.#snapshot = snapshot ?? null; this.element.hidden = !snapshot;
    if (!snapshot) return;
    const p = landingPresentation(snapshot), enabled = snapshot.settings.enabled;
    this.part("active").hidden = !enabled;
    this.part("confirm-runway").hidden = !enabled || snapshot.reason !== "runway-changed";
    this.part("toggle").textContent = enabled ? "关闭" : "开启";
    this.part("toggle").setAttribute("aria-pressed", String(enabled));
    this.part<HTMLInputElement>("automatic").checked = snapshot.settings.automatic === true;
    this.part<HTMLButtonElement>("toggle").disabled = !enabled && snapshot.runways.length === 0;
    for (const name of ["message","lateral","vertical","speed","distance","course","verticalSpeed","configuration","gearLimit","gearAdvice","arrestor","touchdown","flapAdvice","projection","braking"] as const) this.part(name).textContent = p[name];
    this.part("gearAdvice").dataset.risk = snapshot.gearRisk ?? "unknown";
    this.part("flapAdvice").dataset.risk = snapshot.flapReference?.risk ?? "unknown";
    const limits = landingConfigurationPresentation(snapshot).limits;
    this.part("limits").replaceChildren(...limits.map(({ label, limit, risk }) => {
      const row = document.createElement("div"), text = document.createElement("span"), bar = document.createElement("meter");
      row.className = "landing-limit"; row.dataset.risk = risk;
      text.textContent = `${label} ≤ ${Math.round(limit)} km/h`;
      bar.min = 0; bar.max = limit * 1.2; bar.low = 0; bar.high = limit * .9; bar.optimum = 0;
      bar.value = snapshot.iasKmh ?? 0; bar.hidden = snapshot.iasKmh === null;
      bar.setAttribute("aria-label", `${label}：当前 IAS ${Math.round(snapshot.iasKmh ?? 0)}，参考上限 ${Math.round(limit)}`);
      row.append(text, bar); return row;
    }));
    this.part("gearLimit").hidden = limits.some(row => row.label === "起落架");
    const g = snapshot.geometry;
    const optionsKey = JSON.stringify(snapshot.runways.map(r => [r.id,r.label]));
    if (optionsKey !== this.#runways) {
      this.#runways = optionsKey;
      this.part<HTMLSelectElement>("runway").replaceChildren(...snapshot.runways.map(r => new Option(r.label,r.id)));
    }
    this.part<HTMLSelectElement>("runway").value = snapshot.settings.runwayId ?? "";
    for (const [part, value] of [["ias",snapshot.settings.targetIasKmh],["angle",snapshot.settings.glideAngleDeg],["elevation",snapshot.settings.runwayElevationM]] as const) {
      if (!previous || JSON.stringify(previous.settings) !== JSON.stringify(snapshot.settings)) this.part<HTMLInputElement>(part).value = value === null ? "" : String(value);
    }
    const lateralOffset = landingLateralGuidance(g).position;
    for (const [part, value, extent] of [["lateral-dot",lateralOffset,1],["vertical-dot",g?.glideDeviationM ?? null, g ? Math.max(20,Math.abs(g.thresholdDistanceM)*.02) : 20]] as const) {
      this.part(part).hidden = value === null;
      this.part(part).style.left = `${50 + Math.max(-1,Math.min(1,(value ?? 0)/extent))*46}%`;
    }
  }
}
