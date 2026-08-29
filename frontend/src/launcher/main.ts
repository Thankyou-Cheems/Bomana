import "./styles.css";
import { BridgeClient, BrowserAccessClient, type BridgeProbe, type BrowserAccess, type Channel } from "./launcher-client";
import { openBridgeAssetStore, type OfflineCacheStatus } from "../runtime/persistent-asset-store";
import {
  bridgeVersionState,
  fetchBridgeRelease,
  type BridgeRelease,
} from "./bridge-release";
import { fetchAppWebRelease, type AppWebRelease } from "./app-web-release";
import {
  acceptsAuthorizationCompletion,
  authorizationVerificationURL,
  beginAuthorizationAttempt,
  openAuthorizationPopup,
  type AuthorizationPopup,
} from "./launcher-auth-popup";

interface LauncherViewState {
  readonly bridge: BridgeProbe;
  readonly access: BrowserAccess;
  readonly cache: OfflineCacheStatus;
  readonly bridgeRelease: BridgeRelease | null;
  readonly appWebRelease: AppWebRelease | null;
}

const bridge = new BridgeClient(import.meta.env.VITE_BRIDGE_URL || "");
const cheemsPayBase = new URL(import.meta.env.VITE_CHEEMSPAY_BASE_URL || "https://pay.ruikang.wang");
const accessClient = new BrowserAccessClient(cheemsPayBase);
const bridgeReleaseURL = new URL("../downloads/bridge-release.json", new URL("./", location.href));
const appWebReleaseURL = new URL("../app/app-release.json", new URL("./", location.href));
const offlineStore = await openBridgeAssetStore();
let refreshing = false;
let bridgeProbeBusy = false;
let bridgeDownloadStarted = false;
let currentState: LauncherViewState | null = null;
let authorizationPopup: AuthorizationPopup | null = null;
let pendingAuthorizationCode = "";
let fallbackAccess: BrowserAccess | null = null;

const hostState = required("launcher-host-state");
const channelGrid = required("channel-grid");
const accountLabel = required("account-label");
const accountDescription = required("account-description");
const accountActions = required("account-actions");
const activityMessage = required("activity-message");
const activityProgress = required("activity-progress");
const modeBadge = required("mode-badge");
const hostHelp = required("host-help");
const bridgePermissionGuide = required("bridge-permission-guide");
const toast = required("toast");
const authorizationCode = required("authorization-code");
const authorizationCodeValue = required("authorization-code-value");
const connectBridge = requiredButton("connect-bridge");
const downloadBridge = requiredLink("download-bridge");
const openBridge = requiredLink("open-bridge");
const hostHelpTitle = required("host-help-title");
const hostHelpDescription = required("host-help-description");
const cacheMapSummary = required("cache-map-summary");
const cacheMapList = required("cache-map-list");
const cachePanel = required("cache-panel");
const accountPanel = required("account-panel");
const bridgeTechnical = required("bridge-technical");
const bridgeVersionPanel = required("bridge-version-panel");
const bridgeVersionValue = required("bridge-version-value");
const bridgeVersionMessage = required("bridge-version-message");
const updateBridge = requiredLink("update-bridge");
const cacheTechnical = required("cache-technical");
const authorizationFallbackDialog = requiredDialog("authorization-fallback-dialog");
const authorizationFallbackCode = required("authorization-fallback-code");
const authorizationCurrentTab = requiredButton("authorization-current-tab");
const authorizationRetryPopup = requiredButton("authorization-retry-popup");
const authorizationFallbackClose = requiredButton("authorization-fallback-close");

authorizationCode.classList.add("hidden");
required("refresh-catalog").textContent = "刷新状态";
required("refresh-catalog").addEventListener("click", () => void refresh());
connectBridge.addEventListener("click", () => void refreshBridge(true));
downloadBridge.addEventListener("click", markBridgeDownloadStarted);
updateBridge.addEventListener("click", markBridgeDownloadStarted);
authorizationCurrentTab.addEventListener("click", () => fallbackAccess && continueAuthorizationInCurrentPage(fallbackAccess));
authorizationRetryPopup.addEventListener("click", () => {
  const access = fallbackAccess;
  closeAuthorizationFallback();
  if (access) openPendingAuthorization(access);
});
authorizationFallbackClose.addEventListener("click", closeAuthorizationFallback);
authorizationFallbackDialog.addEventListener("close", () => { fallbackAccess = null; });
window.addEventListener("message", (event) => {
  if (!authorizationPopup || !pendingAuthorizationCode) return;
  if (acceptsAuthorizationCompletion(event, authorizationPopup, cheemsPayBase.origin, pendingAuthorizationCode)) {
    void pollAccess();
  }
});

const returnedFromAuthorization = consumeAuthorizationReturnMarker();
const requestedEnhancedSubscription = consumeEnhancedIntent();
void refresh().then(() => {
  if (returnedFromAuthorization && accessClient.hasPending()) void pollAccess();
  if (requestedEnhancedSubscription) {
    accountPanel.classList.add("intent-highlight");
    accountPanel.scrollIntoView({ behavior: "smooth", block: "center" });
    window.setTimeout(() => accountPanel.classList.remove("intent-highlight"), 3_000);
  }
});
window.setInterval(() => {
  if (!refreshing && accessClient.hasPending()) void pollAccess();
}, 5_000);

async function refresh(): Promise<void> {
  if (refreshing) return;
  refreshing = true;
  document.body.dataset.busy = "true";
  setActivity("正在检查 Bridge、账户与本地缓存…", .18);
  const [bridgeState, access, cache, bridgeRelease, appWebRelease] = await Promise.all([
    bridge.probe(),
    accessClient.snapshot(),
    offlineStore.status().catch(() => ({ objectCount: 0, objectBytes: 0, persistent: true, quotaBytes: null, usageBytes: null, storageKind: "bridge" as const, state: "degraded" as const, mapCount: 0, cachedMapCount: 0, totalBytes: 0, cachedBytes: 0, maps: [], error: "Bridge 缓存状态暂不可用" })),
    fetchBridgeRelease(bridgeReleaseURL).catch(() => null),
    fetchAppWebRelease(appWebReleaseURL).catch(() => null),
  ]);
  render({ bridge: bridgeState, access, cache, bridgeRelease, appWebRelease });
  refreshing = false;
  delete document.body.dataset.busy;
}

function render(state: LauncherViewState): void {
  currentState = state;
  cachePanel.classList.toggle("hidden", !state.access.enhanced);
  renderBridge(state.bridge, state.bridgeRelease, state.appWebRelease);
  renderAccess(state.access);
  renderChannels(state);
  modeBadge.textContent = cacheModeLabel(state.cache.state);
  const mapCount = state.cache.mapCount ?? 0;
  const selectedMaps = state.cache.selectedMapCount ?? 0;
  const selectedCachedMaps = state.cache.selectedCachedMapCount ?? 0;
  const cachedBytes = state.cache.cachedBytes ?? state.cache.objectBytes;
  const totalBytes = state.cache.totalBytes ?? cachedBytes;
  const progress = totalBytes > 0 ? cachedBytes / totalBytes : state.cache.state === "ready" ? 1 : 0;
  setActivity(mapCount > 0
    ? `已选地图 ${selectedCachedMaps} / ${selectedMaps} 就绪 · ${cacheStateLabel(state.cache.state)}`
    : state.cache.error || "正在初始化本机地图缓存…", progress);
  cacheTechnical.textContent = `${state.cache.objectCount} 个对象 · ${formatSize(cachedBytes)} / ${formatSize(totalBytes)} · Bridge 本机存储`;
  cacheMapSummary.textContent = mapCount > 0 ? `Web 控制台管理 · 共 ${mapCount} 张` : "地图缓存尚未初始化";
  cacheMapList.replaceChildren(...(state.cache.maps ?? []).map((map) => {
    const row = document.createElement("span");
    row.className = `cache-map-row ${map.state}`;
    row.append(labelled(map.id, `${cacheMapStateLabel(map.state)} · ${formatSize(map.cachedBytes)} / ${formatSize(map.totalBytes)}`));
    return row;
  }));
}

function renderBridge(probe: BridgeProbe, release: BridgeRelease | null, appRelease: AppWebRelease | null): void {
  connectBridge.disabled = false;
  const permissionDenied = probe.state === "permission-denied";
  bridgePermissionGuide.classList.toggle("hidden", !permissionDenied);
  hostHelp.classList.toggle("permission-denied", permissionDenied);
  downloadBridge.classList.toggle("hidden", permissionDenied);
  renderBridgeVersion(probe, release, appRelease);
  if (probe.state === "connected") {
    const capabilities = probe.capabilities;
    const versionState = release ? bridgeVersionState(capabilities.bridge_version, release.bridgeVersion) : "unknown";
    hostState.className = "host-pill online";
    const provenance = capabilities.build_provenance === "github-actions-sigstore" ? "GitHub Sigstore 构建" : "本地未证明构建";
    hostState.replaceChildren(statusDot(), labelled(
      `Bridge v${capabilities.bridge_version} 已连接`,
      versionState === "outdated" ? "可以使用，但建议先更新" : "可以进入 Bomana",
    ));
    bridgeTechnical.textContent = `${probe.endpoint} · Bridge v${capabilities.bridge_version} · App Web v${appRelease?.appWebVersion ?? "--"} · 协议 v${capabilities.bridge_protocol} · ${provenance}`;
    hostHelp.classList.add("hidden");
    openBridge.href = `${probe.endpoint}/`;
    openBridge.classList.remove("hidden");
    connectBridge.textContent = "重新检测";
    return;
  }
  hostState.className = `host-pill ${permissionDenied ? "permission-denied" : probe.state === "blocked" ? "blocked" : "offline"}`;
  hostState.replaceChildren(statusDot(), labelled(
    permissionDenied ? "浏览器权限已关闭" : probe.state === "blocked" ? "Bridge 版本不兼容" : "Bridge 未连接",
    permissionDenied ? "Bridge 可能正在运行，但网页访问被拒绝" : "运行 Bridge 后点击连接",
  ));
  bridgeTechnical.textContent = probe.message;
  hostHelpTitle.textContent = permissionDenied ? "请允许访问“设备上的应用”" : probe.state === "blocked" ? "检测到旧版 Bridge" : "还没有 Bomana Bridge？";
  hostHelpDescription.textContent = permissionDenied
    ? "这不是 Bridge 未启动提示：Edge 已明确拒绝 Launcher 连接本机 Bridge。请按下面步骤恢复权限。"
    : probe.state === "blocked"
    ? "请从托盘退出旧版 Bridge，再运行这里下载的最新版本。"
    : "请手动运行下载好的 BomanaBridge.exe，看到系统托盘图标则代表启动成功。";
  hostHelp.classList.remove("hidden");
  openBridge.classList.add("hidden");
  openBridge.removeAttribute("href");
  connectBridge.textContent = permissionDenied ? "权限已开放，重新连接" : "连接 Bridge";
}

function renderBridgeVersion(probe: BridgeProbe, release: BridgeRelease | null, appRelease: AppWebRelease | null): void {
  updateBridge.href = bridgeDownloadURL().toString();
  updateBridge.classList.add("hidden");
  const latest = release?.bridgeVersion ?? null;
  if (probe.state !== "connected") {
    bridgeVersionPanel.className = "bridge-version-panel checking";
    bridgeVersionValue.textContent = `本机 -- · 最新 ${latest ? `v${latest}` : "--"}`;
    bridgeVersionMessage.textContent = appRelease ? `App Web v${appRelease.appWebVersion}` : "线上版本暂不可用";
    return;
  }
  const local = probe.capabilities.bridge_version;
  const state = latest ? bridgeVersionState(local, latest) : "unknown";
  bridgeVersionPanel.className = `bridge-version-panel ${state}`;
  bridgeVersionValue.textContent = `本机 v${local} · 最新 ${latest ? `v${latest}` : "--"}`;
  bridgeVersionMessage.textContent = state === "outdated"
    ? "检测到更新，请退出旧 Bridge 后安装"
    : state === "current"
      ? `Bridge 已是最新 · App Web v${appRelease?.appWebVersion ?? "--"}`
      : state === "newer"
        ? "本机构建比线上版本更新"
        : "无法比较当前构建与线上版本";
  updateBridge.classList.toggle("hidden", state !== "outdated");
}

function renderAccess(access: BrowserAccess): void {
  accountActions.replaceChildren();
  accountLabel.textContent = access.accountLabel;
  authorizationCode.classList.toggle("hidden", access.state !== "pending");
  if (access.state === "pending") {
    accountDescription.textContent = "在 CheemsPay 页面确认本次浏览器授权";
    authorizationCodeValue.textContent = access.userCode || "——";
    if (access.verificationURL) {
      accountActions.append(actionButton("打开授权窗口", "primary", () => openPendingAuthorization(access)));
      accountActions.append(actionButton("在当前页继续", "secondary", () => continueAuthorizationInCurrentPage(access)));
    }
    accountActions.append(actionButton("我已确认", "secondary", () => pollAccess()));
    return;
  }
  if (access.state === "authorized") {
    accountDescription.textContent = access.offline
      ? `${access.enhanced ? "Enhanced" : "公共版本"} 本地授权可用；联网后自动刷新 14 天期限`
      : access.enhanced ? "超级爆弹版订阅已验证；本地保留 14 天" : "公共版本可用，当前账户没有超级爆弹版订阅";
    accountActions.append(linkButton("管理账户", new URL("/account", cheemsPayBase), "secondary"));
    accountActions.append(actionButton("退出授权", "text-button", () => {
      accessClient.clearAuthorization();
      return refresh();
    }));
    return;
  }
  if (access.state === "signed_out") {
    accountDescription.textContent = "Lite / Standard 无需登录；超级爆弹版需要订阅";
    accountActions.append(actionButton("登录 CheemsPay", "primary", () => beginAccess()));
    return;
  }
  accountDescription.textContent = "不影响 Lite / Standard；可稍后重试 Enhanced 鉴权";
  accountActions.append(actionButton("重试账户状态", "secondary", () => refresh()));
}

function renderChannels(state: LauncherViewState): void {
  const channels: readonly Channel[] = ["Lite", "Standard", "Enhanced"];
  channelGrid.replaceChildren(...channels.map((channel) => channelCard(channel, state)));
}

function channelCard(channel: Channel, state: LauncherViewState): HTMLElement {
  const enhancedAllowed = channel !== "Enhanced" || state.access.enhanced;
  const ready = state.bridge.state === "connected" && enhancedAllowed;
  const card = document.createElement("article");
  card.className = `channel-card ${channel.toLowerCase()}${ready ? "" : " locked"}`;
  const top = document.createElement("div");
  top.className = "channel-top";
  const identity = document.createElement("div");
  const eyebrow = document.createElement("p");
  eyebrow.className = "eyebrow";
  eyebrow.textContent = channel.toUpperCase();
  const title = document.createElement("h3");
  title.textContent = displayChannel(channel);
  identity.append(eyebrow, title);
  const badge = document.createElement("span");
  badge.className = "version-badge";
  badge.textContent = channel === "Enhanced" ? "订阅" : "公开";
  top.append(identity, badge);
  const description = document.createElement("p");
  description.className = "channel-description";
  description.textContent = channelDescription(channel);
  const features = document.createElement("ul");
  features.className = "channel-features";
  features.replaceChildren(...channelFeatures(channel).map((label) => {
    const item = document.createElement("li");
    item.textContent = label;
    return item;
  }));
  const bottom = document.createElement("div");
  bottom.className = "channel-bottom";
  const stateBadge = document.createElement("span");
  stateBadge.className = "channel-state";
  stateBadge.textContent = channelState(channel, state);
  const actions = document.createElement("div");
  actions.className = "channel-actions";
  if (state.bridge.state !== "connected") {
    actions.append(bridgeDownloadAction(channel === "Enhanced" ? "locked-button" : "primary"));
  } else if (!enhancedAllowed) {
    actions.append(actionButton("登录后进入超级爆弹版", "locked-button", () => beginAccess()));
  } else {
    actions.append(linkButton(`进入${displayChannel(channel)}`, appWebURL(channel), "primary"));
  }
  bottom.append(stateBadge, actions);
  card.append(top, description, features, bottom);
  return card;
}

function bridgeDownloadURL(): URL {
  return new URL("../downloads/BomanaBridge.exe", new URL("./", location.href));
}

function bridgeDownloadAction(style: string): HTMLElement {
  if (bridgeDownloadStarted) return actionButton("连接 Bridge", style, () => { void refreshBridge(true); });
  const link = linkButton("下载并运行 Bridge", bridgeDownloadURL(), style);
  link.addEventListener("click", markBridgeDownloadStarted);
  return link;
}

function markBridgeDownloadStarted(): void {
  if (bridgeDownloadStarted) return;
  bridgeDownloadStarted = true;
  window.setTimeout(() => {
    if (!currentState || currentState.bridge.state === "connected") return;
    renderBridge(currentState.bridge, currentState.bridgeRelease, currentState.appWebRelease);
    renderChannels(currentState);
  }, 0);
}

function appWebURL(channel: Channel): URL {
  const base = import.meta.env.VITE_APP_WEB_BASE_URL
    ? new URL(import.meta.env.VITE_APP_WEB_BASE_URL)
    : new URL("./", location.href);
  return new URL(`${channel}/`, base);
}

async function beginAccess(): Promise<void> {
  try {
    const attempt = await beginAuthorizationAttempt(
      () => accessClient.begin(),
      window.open.bind(window),
      cheemsPayBase.origin,
    );
    const { access, popup } = attempt;
    authorizationPopup = popup;
    if (access.state === "pending" && access.verificationURL && access.userCode) {
      pendingAuthorizationCode = access.userCode.trim().toUpperCase();
      if (attempt.blocked) showAuthorizationFallback(access);
    }
    await refresh();
  } catch (error) {
    authorizationPopup = null;
    pendingAuthorizationCode = "";
    showToast(messageOf(error));
  }
}

async function pollAccess(): Promise<void> {
  if (refreshing) return;
  try {
    const access = await accessClient.poll();
    if (access.state === "authorized") {
      if (authorizationPopup && !authorizationPopup.closed) authorizationPopup.close();
      authorizationPopup = null;
      pendingAuthorizationCode = "";
      closeAuthorizationFallback();
    }
    await refresh();
  } catch (error) { showToast(messageOf(error)); }
}

function openPendingAuthorization(access: BrowserAccess): void {
  if (!access.verificationURL || !access.userCode) return;
  const popup = openAuthorizationPopup(window.open.bind(window));
  if (!popup) {
    showAuthorizationFallback(access);
    return;
  }
  authorizationPopup = popup;
  pendingAuthorizationCode = access.userCode.trim().toUpperCase();
  popup.location.replace(authorizationVerificationURL(access.verificationURL, cheemsPayBase.origin, "popup").href);
}

function showAuthorizationFallback(access: BrowserAccess): void {
  fallbackAccess = access;
  authorizationFallbackCode.textContent = access.userCode || "——";
  showToast("浏览器拦截了授权窗口，已提供当前页面授权方式");
  if (!authorizationFallbackDialog.open) authorizationFallbackDialog.showModal();
}

function closeAuthorizationFallback(): void {
  fallbackAccess = null;
  if (authorizationFallbackDialog.open) authorizationFallbackDialog.close();
}

function continueAuthorizationInCurrentPage(access: BrowserAccess): void {
  if (!access.verificationURL || !access.userCode) return;
  const destination = authorizationVerificationURL(access.verificationURL, cheemsPayBase.origin, "redirect");
  location.assign(destination.href);
}

function consumeAuthorizationReturnMarker(): boolean {
  const url = new URL(location.href);
  if (url.searchParams.get("authorization") !== "complete") return false;
  url.searchParams.delete("authorization");
  history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
  return true;
}

function consumeEnhancedIntent(): boolean {
  const url = new URL(location.href);
  if (url.searchParams.get("intent") !== "Enhanced") return false;
  url.searchParams.delete("intent");
  history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
  return true;
}

function channelState(channel: Channel, state: LauncherViewState): string {
  if (state.bridge.state === "blocked") return "Bridge 冲突";
  if (state.bridge.state !== "connected") return "等待 Bridge";
  if (channel === "Enhanced" && !state.access.enhanced) return "需要订阅";
  return "可直接打开";
}

function displayChannel(channel: Channel): string {
  if (channel === "Lite") return "轻量版";
  if (channel === "Standard") return "标准版";
  return "超级爆弹版";
}

function channelDescription(channel: Channel): string {
  if (channel === "Lite") return "只提供复活周期计时，界面与能力保持最精简。";
  if (channel === "Standard") return "加入官方战区与机场的基础导航、燃油管理和检查单。";
  return "在 Standard 之上解锁战术情报、离线高程、机场模块与武器解算。";
}

function channelFeatures(channel: Channel): readonly string[] {
  if (channel === "Lite") return [
    "复活周期计时与自定义时长",
    "当前出击周期、进度与手动重置",
    "纯计时界面，无导航与战术功能",
  ];
  if (channel === "Standard") return [
    "包含 Lite 的计时功能",
    "官方战区与机场目标切换",
    "方位、距离与基础航向提示",
    "燃油消耗、续航与返航估算",
    "起飞检查单与任务告警",
    "不含格子坐标、聊天识别、战区倒计时与高程",
  ];
  return [
    "包含 Standard 的全部功能",
    "战术地图格子坐标、聊天识别与战区倒计时",
    "机场模块标记、Y66 标定与本机离线高程",
    "常规与高阻炸弹实时投放解算",
    "卫星制导、滑翔武器与 AAM / AGM",
    "手机 Enhanced 配对与本地 Worker / WASM",
  ];
}

function setActivity(message: string, progress: number): void {
  activityMessage.textContent = message;
  activityProgress.style.width = `${Math.max(0, Math.min(1, progress)) * 100}%`;
}

function linkButton(label: string, url: URL, style: string): HTMLAnchorElement {
  const link = document.createElement("a");
  link.className = `button ${style}`;
  link.href = url.href;
  link.textContent = label;
  return link;
}

function actionButton(label: string, style: string, action: () => void | Promise<void>): HTMLButtonElement {
  const button = document.createElement("button");
  button.type = "button";
  button.className = `button ${style}`;
  button.textContent = label;
  button.addEventListener("click", () => void action());
  return button;
}

function statusDot(): HTMLElement {
  const dot = document.createElement("span");
  dot.className = "status-dot";
  return dot;
}

function labelled(title: string, subtitle: string): HTMLElement {
  const stack = document.createElement("span");
  const strong = document.createElement("strong");
  strong.textContent = title;
  const small = document.createElement("small");
  small.textContent = subtitle;
  stack.append(strong, small);
  return stack;
}

function showToast(message: string): void {
  toast.textContent = message;
  toast.classList.add("visible");
  window.setTimeout(() => toast.classList.remove("visible"), 3600);
}

function formatSize(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
  if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${Math.ceil(bytes / 1024)} KB`;
}

function cacheStateLabel(state: OfflineCacheStatus["state"]): string {
  if (state === "ready") return "全部就绪";
  if (state === "syncing") return "自动同步中";
  if (state === "checking") return "正在校验";
  return "部分资源待恢复";
}

function cacheModeLabel(state: OfflineCacheStatus["state"]): string {
  if (state === "ready") return "已就绪";
  if (state === "syncing") return "同步中";
  if (state === "checking") return "检查中";
  return "需重试";
}

function cacheMapStateLabel(state: string): string {
  if (state === "not-selected") return "未选择";
  if (state === "cached") return "已缓存";
  if (state === "downloading") return "下载中";
  if (state === "error") return "失败待重试";
  return "等待下载";
}

function required(id: string): HTMLElement {
  const element = document.getElementById(id);
  if (!element) throw new Error(`missing launcher element: ${id}`);
  return element;
}

function messageOf(error: unknown): string { return error instanceof Error ? error.message : "CheemsPay 授权失败"; }

async function refreshBridge(showResult: boolean): Promise<BridgeProbe> {
  if (bridgeProbeBusy) return currentState?.bridge ?? { state: "disconnected", message: "Bridge 正在检测" };
  bridgeProbeBusy = true;
  connectBridge.disabled = true;
  connectBridge.textContent = "检测中…";
  try {
    const [probe, bridgeRelease, appWebRelease] = await Promise.all([
      bridge.probe(),
      fetchBridgeRelease(bridgeReleaseURL).catch(() => currentState?.bridgeRelease ?? null),
      fetchAppWebRelease(appWebReleaseURL).catch(() => currentState?.appWebRelease ?? null),
    ]);
    if (currentState) {
      currentState = { ...currentState, bridge: probe, bridgeRelease, appWebRelease };
      renderBridge(probe, bridgeRelease, appWebRelease);
      renderChannels(currentState);
    }
    if (showResult) showToast(probe.state === "connected" ? "Bomana Bridge 已连接" : probe.message);
    return probe;
  } finally {
    bridgeProbeBusy = false;
    connectBridge.disabled = false;
  }
}

function requiredButton(id: string): HTMLButtonElement {
  const element = document.getElementById(id);
  if (!(element instanceof HTMLButtonElement)) throw new Error(`missing launcher button: ${id}`);
  return element;
}

function requiredLink(id: string): HTMLAnchorElement {
  const element = document.getElementById(id);
  if (!(element instanceof HTMLAnchorElement)) throw new Error(`missing launcher link: ${id}`);
  return element;
}

function requiredDialog(id: string): HTMLDialogElement {
  const element = document.getElementById(id);
  if (!(element instanceof HTMLDialogElement)) throw new Error(`missing Launcher dialog: ${id}`);
  return element;
}
