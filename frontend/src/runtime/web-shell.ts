import logoURL from "../generated/bomana-logo.svg?url";

/** Common header, timer, flight readouts and fuel panel for every Web edition. */
export function mountWebShell(header: HTMLElement, flightPanel: HTMLElement): void {
  header.innerHTML = `
<div class="brand-stack">
        <div class="brand-row">
          <a
            class="brand brand-link"
            href="https://bomana.ruikang.wang/"
            target="_blank"
            rel="noopener noreferrer"
            aria-label="打开 Bomana 官网"
          >
            <img class="brand-logo" src="${logoURL}" alt="Bomana" />
            <div class="brand-copy">
              <small id="edition-access">PUBLIC EDITION</small>
              <strong>BOMANA · <span id="edition-name">--</span></strong>
              <span class="brand-version" id="app-web-version"></span>
            </div>
          </a>
          <div class="brand-actions">
            <button type="button" class="brand-action brand-action-primary brand-pip standard-only" id="toggle-pip"><strong>置顶导航窗</strong></button>
            <button type="button" class="brand-action brand-action-secondary standard-only" id="open-mobile-pairing"><strong>手机配对</strong></button>
          </div>
        </div>
        <div class="connection" id="connection-badge">
          <span class="connection-dot"></span>
          <div class="connection-copy"><span id="status">正在连接 Bridge</span><small id="connection-detail">自动连接 · 仅本机</small></div>
          <button type="button" class="connection-retry" id="connect">立即重试</button>
          <a id="update-bridge" class="connection-retry" href="/launcher/" target="_blank" rel="noopener" hidden>打开启动页更新 Bridge</a>
        </div>
      </div>
      <div id="flight-instruments" class="web-flight-instruments standard-only"></div>
      <bomana-site-header class="hud-product-nav" compact new-tab></bomana-site-header>
  `;
  flightPanel.innerHTML = `
<div class="hud-left-body">
        <div class="timer-block">
          <span class="eyebrow">RESPAWN TIMER</span>
          <strong id="timer">--:--</strong>
          <div class="mission-progress" aria-hidden="true"><i id="timer-progress"></i></div>
          <span class="meta" id="timer-cycle"></span>
          <button class="timer-customize" id="open-timer-settings" type="button">自定义倒计时</button>
        </div>
        <div class="flight-readout-group standard-only">
          <div class="readout-stack">
            <div class="readout"><span>IAS <i>指示空速</i></span><strong id="ias-value">---</strong><small>km/h</small></div>
            <div class="readout"><span>TAS <i>真空速</i></span><strong id="tas-value">---</strong><small>km/h</small></div>
            <div class="readout"><span>ALT <i>高度</i></span><strong id="altitude">---</strong><small>m</small></div>
            <div class="readout"><span>HDG <i>航向</i></span><strong id="heading-value">---</strong><small>deg</small></div>
          </div>
          <div class="fuel-panel-compact" id="fuel-panel" aria-label="燃油与返航">
            <strong class="fuel-current-total" id="fuel-current-total">等待燃油读数</strong>
            <span class="fuel-source" id="fuel-source">测量中</span>
            <div class="fuel-level-track" aria-label="当前油量与返航需求线"><b id="fuel-level-fill"></b><i id="fuel-return-marker"></i></div>
            <div class="fuel-relationship"><strong id="return-fuel">返航需求待估算</strong><span id="fuel-balance">余量待估算</span></div>
            <span class="fuel-consumption" id="fuel-rate">正在学习油耗</span>
            <details class="fuel-details"><summary>返航依据与省油建议</summary><p id="fuel-detail"></p><p id="fuel-advice"></p></details>
          </div>
        </div>
        <div class="aircraft-block standard-only"><span class="eyebrow">AIRFRAME</span><strong id="aircraft">--</strong></div>
      </div>
  `;
}
