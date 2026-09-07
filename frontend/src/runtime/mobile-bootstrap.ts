import { reportDailyActive } from "./anonymous-daily-active";

export async function authorizeMobileStandard(start: () => Promise<unknown>): Promise<void> {
  const mobileModule = await import("./mobile-pairing");
  const browser = mobileModule.inspectMobileLanBrowser();
  if (!mobileModule.isPrivateLanOrigin()) {
    renderMobilePairingGate("请扫描电脑上为普通版生成的二维码。", "Standard");
    return;
  }
  if (browser === "embedded-webview") {
    renderMobilePairingGate(mobileModule.mobileLanBrowserMessage(browser), "Standard");
    return;
  }
  await authorizeMobileSession(mobileModule, "Standard", undefined, start);
}

export async function authorizeMobileSession(
  mobileModule: typeof import("./mobile-pairing"),
  edition: import("./mobile-pairing").MobileEdition,
  verifyLease: import("./mobile-pairing").MobileLeaseVerifier | undefined,
  start: () => Promise<unknown>,
): Promise<void> {
  if (mobileModule.isPrivateLanOrigin()) mobileModule.reloadOnMobilePairingHashChange();
  try {
    const mobileAuthorized = await mobileModule.claimOrRestoreMobilePairingSession({ edition, verifyLease }) === "authorized";
    if (!mobileAuthorized && mobileModule.isPrivateLanOrigin()) {
      renderMobilePairingCodeGate(async (pairingCode) => {
        await mobileModule.completeMobilePairingWithCode({ edition, pairingCode, verifyLease });
      }, edition);
      return;
    }
    if (!mobileAuthorized) {
      renderMobilePairingGate("请扫描桌面 Bomana 生成的手机配对二维码。", edition);
      return;
    }
    if (typeof history !== "undefined" && location.hash) {
      history.replaceState(null, "", `${location.pathname}${location.search}`);
    }
    let mobileSession = mobileModule.refreshMobilePairingReopenWindow(localStorage, Date.now(), edition);
    document.body.dataset.mobilePaired = "true";
    if (mobileSession) document.body.dataset.mobileLeaseExpiresAt = String(mobileSession.expiresAt);
    const refreshMobileReopenWindow = (): void => {
      mobileSession = mobileModule.refreshMobilePairingReopenWindow(localStorage, Date.now(), edition, mobileSession);
    };
    window.setInterval(refreshMobileReopenWindow, 60_000);
    window.addEventListener("pagehide", refreshMobileReopenWindow);
    const sameOriginPairing = mobileModule.isPrivateLanOrigin();
    const permission = sameOriginPairing ? "granted" : await mobileModule.queryLocalNetworkPermission();
    try {
      if (permission === "granted") await mobileModule.connectMobileBridge();
      else await renderMobileBridgeConnectionGate(() => mobileModule.connectMobileBridge(), undefined, sameOriginPairing);
    } catch (error) {
      await renderMobileBridgeConnectionGate(() => mobileModule.connectMobileBridge(), error, sameOriginPairing);
    }
    await start();
    void reportDailyActive(edition);
  } catch (error) {
    renderMobilePairingGate(error instanceof Error ? error.message : "手机配对不可用", edition);
  }
}

export function renderMobilePairingCodeGate(
  complete: (pairingCode: string) => Promise<void>,
  edition: import("./mobile-pairing").MobileEdition = "Enhanced",
): void {
  document.title = "输入手机配对码 · Bomana";
  document.body.dataset.access = "denied";
  const gate = createAccessGate({
    kicker: "LOCAL MOBILE PAIRING",
    title: "输入电脑上的配对码",
    message: "二维码自动配对未完成。你仍可输入电脑 Bomana 显示的 8 位备用码。",
    boundary: edition === "Enhanced"
      ? "配对码仅在当前局域网和短时间内有效；验证成功前不会加载 Enhanced 解算器、WASM 或高级离线目录。"
      : "配对码仅在当前局域网和短时间内有效；普通版不需要 CheemsPay 登录。",
  });
  const form = document.createElement("form");
  form.className = "enhanced-access-pairing-form";
  const input = document.createElement("input");
  input.type = "text";
  input.name = "pairing-code";
  input.inputMode = "text";
  input.autocomplete = "one-time-code";
  input.autocapitalize = "characters";
  input.maxLength = 9;
  input.placeholder = "ABCD-2345";
  input.setAttribute("aria-label", "8 位手机配对码");
  const submit = document.createElement("button");
  submit.type = "submit";
  submit.className = "enhanced-access-primary";
  submit.textContent = "完成配对";
  form.append(input, submit);
  gate.actions.append(form);
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    submit.disabled = true;
    submit.textContent = "正在配对…";
    gate.message.textContent = "正在向这台电脑验证配对码…";
    void complete(input.value).then(() => {
      location.reload();
    }).catch((error) => {
      gate.message.textContent = error instanceof Error ? error.message : "手机配对失败";
      submit.disabled = false;
      submit.textContent = "重新配对";
      input.focus();
      input.select();
    });
  });
  document.body.replaceChildren(gate.shell);
  input.focus();
}

export function renderMobileBridgeConnectionGate(
  connect: () => Promise<URL>,
  error?: unknown,
  sameOriginPairing = false,
): Promise<void> {
  const preservedNodes = [...document.body.childNodes];
  const previousTitle = document.title;
  document.title = "连接本地 Bridge · Bomana";
  document.body.dataset.access = "denied";
  const gate = createAccessGate({
    kicker: "LOCAL NETWORK ACCESS",
    title: "连接本地 Bridge",
    message: error instanceof Error
      ? error.message
      : sameOriginPairing
        ? "授权已完成。请确认手机与电脑连接同一 Wi-Fi。"
        : "授权已完成。请确认手机与电脑连接同一 Wi-Fi，然后允许浏览器访问本地网络。",
    boundary: sameOriginPairing
      ? "请用系统相机或 Safari / Chrome 独立打开电脑上的局域网页面；微信、QQ 等内置浏览器无法访问局域网 Bridge。"
      : "请使用最新版 Android Chrome 独立打开；微信、QQ 等内置浏览器无法访问局域网 Bridge。",
  });
  const connectButton = document.createElement("button");
  connectButton.type = "button";
  connectButton.className = "enhanced-access-primary";
  connectButton.textContent = sameOriginPairing ? "连接电脑上的 Bridge" : "允许访问本地网络并连接";
  gate.actions.append(connectButton);
  document.body.replaceChildren(gate.shell);

  return new Promise((resolve) => {
    connectButton.addEventListener("click", () => {
      connectButton.disabled = true;
      connectButton.textContent = "正在连接…";
      gate.message.textContent = "正在查找二维码中的局域网 Bridge…";
      void connect().then(() => {
        document.body.replaceChildren(...preservedNodes);
        delete document.body.dataset.access;
        document.title = previousTitle;
        resolve();
      }).catch((failure) => {
        gate.message.textContent = failure instanceof Error
          ? failure.message
          : "仍未连接。请允许本地网络权限，关闭 VPN，并确认手机与电脑位于同一 Wi-Fi。";
        connectButton.disabled = false;
        connectButton.textContent = "重新连接本地 Bridge";
      });
    });
  });
}

export function renderMobilePairingGate(
  messageText: string,
  edition: import("./mobile-pairing").MobileEdition = "Enhanced",
): void {
  document.title = "手机配对不可用 · Bomana";
  document.body.dataset.access = "denied";
  const gate = createAccessGate({
    kicker: "MOBILE PAIRING",
    title: "手机配对不可用",
    message: messageText,
    boundary: edition === "Enhanced"
      ? "票据、局域网端点或手机 Enhanced Lease 验证失败时不会加载解算器。"
      : "普通版仅使用局域网一次性配对能力，不会请求 CheemsPay。",
  });
  const rescan = document.createElement("button");
  rescan.type = "button";
  rescan.className = "enhanced-access-primary";
  rescan.textContent = "查看重新扫码步骤";
  rescan.addEventListener("click", () => {
    gate.message.textContent = "请先在电脑端点击“重新生成二维码和配对码”，然后切回 iPhone 系统相机 App 扫描新二维码。Safari 不允许局域网 HTTP 页面直接唤起系统相机。";
  });
  gate.actions.append(rescan);
  document.body.replaceChildren(gate.shell);
}

export function createAccessGate(input: {
  readonly kicker: string;
  readonly title: string;
  readonly message: string;
  readonly boundary: string;
}): { readonly shell: HTMLElement; readonly message: HTMLParagraphElement; readonly actions: HTMLDivElement } {
  const shell = document.createElement("main");
  shell.className = "enhanced-access-gate";
  const card = document.createElement("section");
  card.className = "enhanced-access-card";
  const kicker = document.createElement("span");
  kicker.textContent = input.kicker;
  const title = document.createElement("h1");
  title.textContent = input.title;
  const message = document.createElement("p");
  message.textContent = input.message;
  const actions = document.createElement("div");
  actions.className = "enhanced-access-actions";
  const boundary = document.createElement("small");
  boundary.textContent = input.boundary;
  card.append(kicker, title, message, actions, boundary);
  shell.append(card);
  return { shell, message, actions };
}
