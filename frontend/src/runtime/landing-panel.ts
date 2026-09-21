import { DEFAULT_LANDING_SETTINGS, type LandingSettings, type LandingSnapshot } from "./landing-assist";
import { landingConfigurationPresentation, landingPresentation } from "./landing-presentation";

/** Shared controls/presentation only. The caller owns every calculation. */
export class LandingPanel {
  readonly element: HTMLElement;
  #snapshot: LandingSnapshot | null = null;
  #runways = "";
  #limitsKey = "";
  constructor(parent: HTMLElement, submit: (settings: LandingSettings) => void) {
    const panel = document.createElement("section"); panel.className = "landing-panel"; panel.setAttribute("aria-label", "降落辅助");
    panel.innerHTML = `<header><strong>降落</strong><label class="landing-auto" title="持续飞向友方机场 3 秒后自动开启；也可手动开启"><input type="checkbox" data-part="automatic">自动</label><button type="button" data-part="toggle" aria-pressed="false">开启</button></header>
      <p data-part="message"></p><button type="button" data-part="confirm-runway" hidden>确认新端点</button><div data-part="active" hidden>
      <div class="landing-runway"><select data-part="runway" aria-label="降落跑道"></select><button type="button" data-part="reverse" title="反向进近会清空手动高程">反向进近</button></div>
      <p class="landing-configuration" data-part="configuration"></p>
      <div class="landing-airframe"><strong data-part="gearAdvice"></strong><strong data-part="flapAdvice"></strong><strong data-part="descentAdvice"></strong></div>
      <details><summary>进近设置</summary><div class="landing-fields">
        <label>目标 IAS · km/h<input type="number" min="60" max="600" step="1" data-part="ias" placeholder="未设定"></label>
        <label>下滑角 · °<input type="number" min="1" max="8" step="0.1" data-part="angle"></label>
        <label>跑道高程 · m<input type="number" min="-1000" max="10000" step="1" data-part="elevation" placeholder="留空使用可用地形"></label>
      </div><button type="button" data-part="apply">应用</button><div class="landing-airframe"><span data-part="speed"></span><div class="landing-limits" data-part="limits" aria-label="构型 IAS 参考上限"></div><span data-part="arrestor"></span></div><p class="landing-note">宽度匹配游戏机场定义，否则为示意；不代表碰撞边界。高程为地形参考，高台或甲板需手动修正。入口参考高度 15 m，带面在参考线下方 15 m；不含接地或挂索判定。</p></details>
      </div><p class="landing-error" data-part="error" role="alert"></p>`;
    parent.append(panel); this.element = panel;
    panel.querySelector("details")!.addEventListener("toggle", () => { if (this.#snapshot) this.update(this.#snapshot); });
    const change = (patch: Partial<LandingSettings>) => submit({ ...(this.#snapshot?.settings ?? DEFAULT_LANDING_SETTINGS), ...patch });
    this.part("toggle").addEventListener("click", () => change({ enabled: !this.#snapshot?.settings.enabled, automatic: false }));
    this.part<HTMLInputElement>("automatic").addEventListener("change", event => change({ automatic: (event.target as HTMLInputElement).checked, enabled: false }));
    this.part<HTMLSelectElement>("runway").addEventListener("change", event => change({ runwayId: (event.target as HTMLSelectElement).value, automatic: false }));
    this.part("reverse").addEventListener("click", () => change({ reverse: !this.#snapshot?.settings.reverse, automatic: false }));
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
    const g = snapshot.geometry;
    this.part("message").textContent = !enabled ? snapshot.runways.length === 0 ? "等待友方机场" : snapshot.settings.automatic ? "自动待命" : "手动待命"
      : !g ? snapshot.reason === "runway-changed" ? "跑道已变化" : snapshot.reason === "runway-missing" ? "跑道不可见" : "等待数据"
        : ({ return: "返航", intercept: "对正", final: "进近", runway: "入口后", "past-runway": "末端后" })[g.stage];
    this.part("message").title = p.message;
    const percent = (value: number | null) => value === null ? "—" : `${Math.round(value)}%`;
    this.part("configuration").textContent = `轮 ${percent(snapshot.gearPercent)} · 翼 ${percent(snapshot.flapsPercent)} · 板 ${percent(snapshot.airbrakePercent)}`;
    this.part("configuration").title = p.configuration;
    this.part("speed").textContent = p.speed;
    const equipment = (value: boolean | null | undefined) => value === true ? "✓" : value === false ? "×" : "?";
    this.part("arrestor").textContent = `配备：钩 ${equipment(snapshot.aircraft?.arrestorHook)} · 伞 ${equipment(snapshot.aircraft?.brakeChute)}`;
    this.part("arrestor").title = "机型静态配备，不表示当前展开或挂索";
    this.part("gearAdvice").hidden = snapshot.gearRisk == null || snapshot.gearRisk === "unknown";
    this.part("descentAdvice").textContent = p.descentAdvice ? "下沉过快" : "";
    this.part("gearAdvice").textContent = p.gearCue.replace(" · 减速", "");
    this.part("gearAdvice").title = p.gearAdvice;
    this.part("gearAdvice").dataset.risk = snapshot.gearRisk ?? "unknown";
    this.part("flapAdvice").dataset.risk = snapshot.flapReference?.risk ?? "unknown";
    this.part("flapAdvice").textContent = snapshot.flapReference?.risk === "over-limit" ? "襟翼超限" : snapshot.flapReference?.risk === "near-limit" ? "襟翼近限" : "";
    const limits = landingConfigurationPresentation(snapshot).limits;
    const limitsKey = JSON.stringify(limits);
    if (this.element.querySelector("details")!.open && limitsKey !== this.#limitsKey) {
      this.#limitsKey = limitsKey;
      this.part("limits").replaceChildren(...limits.map(({ label, limit, risk }) => {
      const row = document.createElement("div"), text = document.createElement("span"), bar = document.createElement("meter");
      row.className = "landing-limit"; row.dataset.risk = risk;
      text.textContent = `${label} ≤ ${Math.round(limit)} km/h`;
      bar.min = 0; bar.max = limit * 1.2; bar.low = 0; bar.high = limit * .9; bar.optimum = 0;
      bar.value = snapshot.iasKmh ?? 0; bar.hidden = snapshot.iasKmh === null;
      bar.setAttribute("aria-label", `${label}：当前 IAS ${Math.round(snapshot.iasKmh ?? 0)}，参考上限 ${Math.round(limit)}`);
      row.append(text, bar); return row;
      }));
    }
    if (this.element.querySelector("details")!.open) for (const meter of this.part("limits").querySelectorAll("meter")) {
      meter.value = snapshot.iasKmh ?? 0; meter.hidden = snapshot.iasKmh === null;
      meter.setAttribute("aria-label", `当前 IAS ${snapshot.iasKmh === null ? "未知" : Math.round(snapshot.iasKmh)}，参考上限 ${Math.round(meter.high / .9)}`);
    }
    const optionsKey = JSON.stringify(snapshot.runways.map(r => [r.id,r.label]));
    if (optionsKey !== this.#runways) {
      this.#runways = optionsKey;
      this.part<HTMLSelectElement>("runway").replaceChildren(...snapshot.runways.map(r => new Option(r.label,r.id)));
    }
    this.part<HTMLSelectElement>("runway").value = snapshot.settings.runwayId ?? "";
    // Update text in place so live distances never rebuild an open select.
    for (const option of this.part<HTMLSelectElement>("runway").options) {
      const r = snapshot.runways.find(runway => runway.id === option.value)!;
      const course = r.courseDeg == null ? "" : ` · ${Math.round(r.courseDeg).toString().padStart(3, "0")}°`;
      const length = r.lengthM == null ? "" : ` · ${(r.lengthM / 1000).toFixed(2)}km`;
      const label = `${r.label}${r.grid ? ` ${r.grid}` : ""}${course}${length} · 距 ${r.distanceKm.toFixed(1)}km`;
      if (option.text !== label) option.text = label;
    }
    for (const [part, value] of [["ias",snapshot.settings.targetIasKmh],["angle",snapshot.settings.glideAngleDeg],["elevation",snapshot.settings.runwayElevationM]] as const) {
      if (!previous || JSON.stringify(previous.settings) !== JSON.stringify(snapshot.settings)) this.part<HTMLInputElement>(part).value = value === null ? "" : String(value);
    }
  }
}
