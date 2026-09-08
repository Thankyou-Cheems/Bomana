import { editionPolicy } from "./runtime/edition-policy";
import { PublicRuntime, BrowserRuntimeSettingsStore, BrowserTimerCheckpointStore } from "./runtime/public-runtime";
import type { EditionSnapshot, EditionCommand } from "./runtime/runtime-types";
import { BrowserSortieRecoveryStore } from "./runtime/sortie-recovery";
import { loadAircraftParameters, loadStrikeResources } from "./runtime/runtime-resources";
import { TelemetrySource, type Official8111Frame } from "./runtime/telemetry-source";
import { AutoConnectionLoop } from "./runtime/auto-connection-loop";
import { LatestSampleProcessor } from "./runtime/latest-sample-processor";
import { bindPageSession } from "./runtime/page-session";
import { IncompatibleBridgeError } from "./runtime/bridge-discovery";
import { fuelPresentation } from "./runtime/fuel-presentation";
import { LandingPanel } from "./runtime/landing-panel";
import { StrikeEncyclopedia, roomMaxBattleRatings, type AirportModule } from "./runtime/strike-encyclopedia";
import { PipRiskConsentStore } from "./runtime/pip-risk-consent";
import { readPipMapVisible } from "./runtime/pip-map-preference";
import { WindowClock } from "./runtime/window-clock";
import { SpeedStripRenderer } from "./runtime/speed-strip-renderer";
import { PictureInPictureHeadingRenderer } from "./runtime/pip-heading-renderer";
import { FlightStatusPresenter, FlightStatusBadgeRenderer } from "./runtime/flight-status-badges";
import { SoundCues, SoundCuePreferencesStore, type SoundCuePreset } from "./runtime/sound-cues";
import { applyTheme, readTheme, saveTheme, type WebTheme } from "./runtime/theme-preference";
import type { DesktopMobilePairingOffer } from "./runtime/mobile-pairing";
import type { PublicNavigationMap } from "./runtime/public-pip-mini-map";
import type { PublicPictureInPicture } from "./runtime/public-pip";

const edition = editionPolicy(__BOMANA_EDITION__);
if (edition.channel === "Enhanced") throw new Error("private edition requires its own entry point");
const aircraftParameters = await loadAircraftParameters();
const encyclopedia = new StrikeEncyclopedia(await loadStrikeResources(aircraftParameters));
const pipConsent = new PipRiskConsentStore();
const pageClock = new WindowClock(() => window);
const settings = new BrowserRuntimeSettingsStore(edition.channel);
const runtime = new PublicRuntime({ edition, aircraftParameters, settingsStore: settings,
  timerCheckpointStore: new BrowserTimerCheckpointStore(edition.channel),
  sortieRecoveryStore: edition.channel === "Lite" ? null : new BrowserSortieRecoveryStore(edition.channel) });
const telemetry = new TelemetrySource("", fetch, Date.now, { includeGameChat: false });
const landingPanel = new LandingPanel(element("landing-slot"), landing => execute({ type: "landing.configure", landing }));
const soundStore = new SoundCuePreferencesStore();
const sound = new SoundCues(soundStore.load());
let map: PublicNavigationMap | null = null;
let pip: PublicPictureInPicture | null = null;
let heading: PictureInPictureHeadingRenderer | null = null;
let pairing: DesktopMobilePairingOffer | null = null;
let pairingBusy = false;
let latestFrame: Official8111Frame | null = null;
const speed = new SpeedStripRenderer({ root: element("speed-strip"), state: element("overspeed"), value: element("speed-limit-value"), mach: element("speed-limit-mach"), track: element("speed-track"), fill: element("speed-fill"), markers: [element("speed-caution-mark"), element("speed-warning-mark"), element("speed-critical-mark")] });
const flightPresenter = new FlightStatusPresenter();
const flightBadges = new FlightStatusBadgeRenderer({ flight: element("flight-phase-badge"), gear: element("gear-status-badge") });
document.body.dataset.edition = edition.channel;
text("edition-name", edition.displayName);
for (const node of document.querySelectorAll<HTMLElement>(".standard-only")) node.hidden = edition.channel === "Lite";
if (document.body.dataset.mobilePaired === "true") { element("open-mobile-pairing").hidden = true; element("toggle-pip").hidden = true; }
if (!window.isSecureContext || !("documentPictureInPicture" in window)) {
  element<HTMLButtonElement>("toggle-pip").disabled = true;
  element("toggle-pip").title = "置顶导航窗需要桌面 Edge / Chrome 的 HTTPS 页面";
}
if (__BOMANA_EDITION__ !== "Lite") {
  const { PublicNavigationMap } = await import("./runtime/public-pip-mini-map");
  const { PublicPictureInPicture } = await import("./runtime/public-pip");
  map = new PublicNavigationMap(element<HTMLCanvasElement>("navigation-map"), selectTarget);
  pip = new PublicPictureInPicture(selectTarget, cycleTarget, (visible) => { element<HTMLInputElement>("pip-map-visible").checked = visible; }, map);
  heading = new PictureInPictureHeadingRenderer({ view: window, canvas: element<HTMLCanvasElement>("heading-tape") });
}
const processor = new LatestSampleProcessor(async (frame: Official8111Frame) => {
  latestFrame = frame;
  render(await runtime.ingest(frame));
}, showError);
const connection = new AutoConnectionLoop<Official8111Frame>({
  attempt: (signal) => telemetry.readFrame(signal),
  isConnected: (frame) => frame.bridgeReachable || runtime.snapshot().phase === "alive" || runtime.snapshot().phase === "loss-pending",
  onSample: (frame) => processor.push(frame), onInterrupt: () => telemetry.cancelPending(),
  wait: (milliseconds, signal) => pip ? pip.wait(milliseconds, signal) : pageClock.wait(milliseconds, signal),
  onState: (state) => {
    if (state.error instanceof IncompatibleBridgeError) element("update-bridge").hidden = false;
    if (state.phase !== "connected") text("status", state.error?.message ?? (state.phase === "connecting" ? "正在连接 Bridge" : `等待 Bridge · ${Math.ceil(state.retryDelayMs / 1000)} 秒后重试`));
  },
});
bindPageSession({ document, window, save: () => runtime.saveTimerCheckpoint(), suspend: () => connection.stop(), reconnect: () => connection.retryNow() });
on("connect", () => connection.retryNow());
on("reset-timer", () => execute({ type: "timer.reset" }));
on("undo-sortie-reset", () => execute({ type: "sortie.undo-reset" }));
on("cycle-navigation-target", cycleTarget);
on("clear-navigation-target", () => execute({ type: "navigation.resume-auto" }));
element<HTMLSelectElement>("navigation-select").addEventListener("change", (event) => selectTarget((event.target as HTMLSelectElement).value));
on("toggle-pip", () => {
  if (pipConsent.accepted()) void pip?.toggle(runtime.snapshot()).catch(showError);
  else element<HTMLDialogElement>("pip-risk-dialog").showModal();
});
on("accept-pip-risk", () => {
  pipConsent.accept(element<HTMLInputElement>("remember-pip-risk").checked);
  element<HTMLDialogElement>("pip-risk-dialog").close();
  void pip?.toggle(runtime.snapshot()).catch(showError);
});
on("cancel-pip-risk", () => element<HTMLDialogElement>("pip-risk-dialog").close());
on("open-settings", () => {
  element<HTMLInputElement>("cycle-minutes").value = String(runtime.snapshot().timer.cycleMinutes);
  element<HTMLSelectElement>("theme-select").value = readTheme();
  element<HTMLInputElement>("sound-enabled").checked = sound.enabled;
  element<HTMLSelectElement>("sound-preset").value = sound.preferences.timerPreset;
  element<HTMLTextAreaElement>("checklist-items").value = runtime.snapshot().checklist?.items.join("\n") ?? "";
  element<HTMLDialogElement>("settings-dialog").showModal();
});
on("save-settings", () => { void saveSettings().catch(showError); });
element<HTMLInputElement>("pip-map-visible").checked = readPipMapVisible("Standard");
element("pip-map-visible").addEventListener("change", () => pip?.setMapVisible(element<HTMLInputElement>("pip-map-visible").checked));
on("open-mobile-pairing", () => { void openPairing(false); });
on("regenerate-mobile-pairing", () => { void openPairing(true); });
on("generate-mobile-pairing", () => { void generateQR().catch(showError); });
on("close-mobile-pairing", () => element<HTMLDialogElement>("mobile-pairing-dialog").close());
document.addEventListener("pointerdown", () => { void sound.enable().catch(showError); }, { once: true });
document.addEventListener("keydown", (event) => {
  if (event.ctrlKey && event.key.toLowerCase() === "z" && !(event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement) && runtime.snapshot().sortieContinuity.resetUndo) {
    event.preventDefault(); execute({ type: "sortie.undo-reset" });
  }
});
render(runtime.snapshot());
connection.start();
for (const value of roomMaxBattleRatings()) element<HTMLSelectElement>("room-br").add(new Option(value.toFixed(1), String(value)));
element<HTMLSelectElement>("room-br").value = "14.7";
element<HTMLSelectElement>("damage-aircraft").replaceChildren(new Option("全部机型", ""), ...encyclopedia.aircraft().map((aircraft) => new Option(aircraft.displayName, aircraft.id)));
const damageWeapons = (): void => { element<HTMLSelectElement>("damage-weapon").replaceChildren(...encyclopedia.weapons(element<HTMLSelectElement>("damage-aircraft").value || undefined).map((weapon) => new Option(weapon.displayNameZh || weapon.displayName, weapon.weaponId))); };
damageWeapons();
element("damage-aircraft").addEventListener("change", damageWeapons);
on("calculate-damage", () => {
  try {
    const targetKind = element<HTMLSelectElement>("damage-target").value === "airport_module" ? "airport_module" : "bombing_point";
    const result = encyclopedia.calculate({ roomMaxBr: Number(element<HTMLSelectElement>("room-br").value), targetKind,
      airportModule: targetKind === "airport_module" ? element<HTMLSelectElement>("airport-module").value as AirportModule : undefined,
      weaponId: element<HTMLSelectElement>("damage-weapon").value });
    text("damage-result", result.practicalCount === null ? result.message : `建议 ${result.practicalCount} 枚 · 满血 ${result.fullDestroyCount} 枚 · 单发 ${Math.round(result.damagePerHitMissionHp!)} HP`);
  } catch (error) { text("damage-result", error instanceof Error ? error.message : "无法计算"); }
});
void fetch("https://bomana.ruikang.wang/app/app-release.json", { cache: "no-store", credentials: "omit", referrerPolicy: "no-referrer" }).then(async (response) => {
  if (!response.ok) return;
  const release: unknown = await response.json();
  if (release && typeof release === "object" && "app_web_version" in release && typeof release.app_web_version === "string") text("app-web-version", `Web ${release.app_web_version}`);
}).catch(() => {});

function render(snapshot: EditionSnapshot): void {
  landingPanel.update(snapshot.landing);
  text("status", !snapshot.connected ? "等待 Bridge · 从在线启动器下载并运行" : !latestFrame?.availability.state ? "Bridge 已连接 · 等待游戏出击" : "Bridge 已连接 · 官方 8111 实时数据");
  const remaining = snapshot.timer.remainingSec;
  const seconds = remaining === null ? null : Math.max(0, Math.ceil(remaining));
  text("timer", seconds === null ? "--:--" : `${Math.floor(seconds / 60).toString().padStart(2, "0")}:${(seconds % 60).toString().padStart(2, "0")}`);
  text("timer-cycle", snapshot.timer.cycle === null ? "等待出击" : `第 ${snapshot.timer.cycle} 周期 · ${snapshot.timer.cycleMinutes} 分钟`);
  element("timer-progress").style.width = `${snapshot.timer.progress * 100}%`;
  const undo = snapshot.sortieContinuity.resetUndo;
  element("undo-sortie-reset").hidden = !undo || undo.expiresAtMs <= Date.now();
  if (edition.channel === "Lite") { sound.update(snapshot); return; }
  text("aircraft", snapshot.flight.aircraft || "等待飞机");
  for (const [id, value] of [["ias-value", snapshot.flight.iasKmh], ["tas-value", snapshot.flight.tasKmh], ["altitude", snapshot.flight.altitudeM], ["heading-value", snapshot.flight.headingDeg]] as const) text(id, Math.round(value).toString());
  if (snapshot.flight.tasObserved === false) text("tas-value", "—");
  text("heading-tape-value", `HDG ${Math.round(snapshot.flight.headingDeg).toString().padStart(3, "0")}°`);
  const target = snapshot.navigation?.target;
  text("navigation-target", target?.label ?? "暂无目标");
  text("navigation-bearing", target ? `方位 ${Math.round(target.bearingDeg).toString().padStart(3, "0")}°` : "方位 ---");
  text("navigation-distance", target ? `${target.distanceKm.toFixed(1)} km` : "距离 ---");
  const select = element<HTMLSelectElement>("navigation-select");
  const options = snapshot.navigation?.items ?? [];
  if ([...select.options].map((option) => option.value).join("|") !== options.map((item) => item.id).join("|")) {
    select.replaceChildren(...options.map((item) => new Option(item.label, item.id)));
  }
  select.value = target?.id ?? "";
  const fuel = snapshot.fuel;
  element("fuel-panel").hidden = !fuel;
  if (fuel) {
    const display = fuelPresentation(fuel);
    for (const [id, value] of [["fuel-current-total", display.currentTotal], ["fuel-source", display.sourceLabel], ["return-fuel", display.returnRequirement], ["fuel-balance", display.balance], ["fuel-rate", display.consumption], ["fuel-detail", display.detail], ["fuel-advice", display.advice]]) text(id!, value!);
    element("fuel-level-fill").style.width = `${display.currentPercent}%`;
    element("fuel-return-marker").style.left = `${display.returnMarkerPercent}%`;
    element("fuel-return-marker").hidden = !display.returnAvailable;
  }
  const checklist = snapshot.checklist;
  const list = element("checklist");
  if (list.dataset.items !== JSON.stringify(checklist?.items)) {
    list.dataset.items = JSON.stringify(checklist?.items);
    list.replaceChildren(...(checklist?.items ?? []).map((item, index) => {
      const label = document.createElement("label"), input = document.createElement("input"), copy = document.createElement("span");
      input.type = "checkbox"; input.addEventListener("change", () => execute({ type: "checklist.toggle", index })); copy.textContent = item; label.append(input, copy); return label;
    }));
  }
  list.querySelectorAll<HTMLInputElement>("input").forEach((input, index) => { input.checked = checklist?.checked[index] ?? false; });
  text("alerts", snapshot.alerts.join(" · ") || "当前无告警");
  heading?.update(snapshot); speed.update(snapshot); flightBadges.update(flightPresenter.update(snapshot)); map?.update(snapshot, latestFrame?.mapInfo ?? null); pip?.update(snapshot); sound.update(snapshot);
}
function execute(command: EditionCommand): void { void runtime.command(command).then(render).catch(showError); }
function selectTarget(id: string): void { if (id) execute({ type: "navigation.select", targetId: id }); }
function cycleTarget(): void {
  const navigation = runtime.snapshot().navigation;
  const items = navigation?.items ?? [];
  if (!items.length) return;
  const index = items.findIndex((item) => item.id === navigation?.target?.id);
  selectTarget(items[(index + 1) % items.length]!.id);
}
async function saveSettings(): Promise<void> {
  await runtime.command({ type: "timer.set-cycle", minutes: Number(element<HTMLInputElement>("cycle-minutes").value) });
  if (edition.capabilities.checklist) await runtime.command({ type: "checklist.set", items: element<HTMLTextAreaElement>("checklist-items").value.split("\n") });
  const theme = element<HTMLSelectElement>("theme-select").value as WebTheme; applyTheme(theme); saveTheme(theme);
  const preferences = sound.configure({ ...sound.preferences, masterEnabled: element<HTMLInputElement>("sound-enabled").checked, timerPreset: element<HTMLSelectElement>("sound-preset").value as SoundCuePreset });
  soundStore.save(preferences); await sound.enable(); render(runtime.snapshot()); element<HTMLDialogElement>("settings-dialog").close();
}
async function openPairing(forceNew: boolean): Promise<void> {
  if (pairingBusy) return;
  pairingBusy = true;
  const dialog = element<HTMLDialogElement>("mobile-pairing-dialog"); if (!dialog.open) dialog.showModal();
  element("mobile-pairing-qr").hidden = true; text("mobile-pairing-code", ""); text("mobile-pairing-status", "正在检查 Bridge…");
  try {
    const { beginDesktopMobilePairing } = await import("./runtime/mobile-pairing");
    pairing = await beginDesktopMobilePairing({ edition: "Standard", forceNew, soundPreferences: sound.preferences });
    element<HTMLSelectElement>("mobile-pairing-networks").replaceChildren(...pairing.networks.map((network) => new Option(`${network.interface} · ${network.address}`, network.endpoint)));
    text("mobile-pairing-code", `备用配对码：${pairing.pairingCode}`);
    text("mobile-pairing-status", "无需登录。选择手机所在 Wi-Fi，用系统相机扫描二维码。");
    await generateQR();
  } catch (error) { pairing = null; text("mobile-pairing-status", error instanceof Error ? error.message : "配对失败"); }
  finally { pairingBusy = false; }
}
async function generateQR(): Promise<void> {
  if (!pairing) return;
  const endpoint = element<HTMLSelectElement>("mobile-pairing-networks").value;
  if (!endpoint) throw new Error("Bridge 没有可用于手机配对的局域网地址。");
  const qr = await import("qrcode"); const image = element<HTMLImageElement>("mobile-pairing-qr");
  image.src = await qr.toDataURL(pairing.pairingURL(endpoint), { width: 280, margin: 1, errorCorrectionLevel: "M" }); image.hidden = false;
}
function element<T extends HTMLElement = HTMLElement>(id: string): T { const node = document.getElementById(id); if (!node) throw new Error(`missing element: ${id}`); return node as T; }
function text(id: string, value: string): void { element(id).textContent = value; }
function on(id: string, run: () => void): void { element(id).addEventListener("click", run); }
function showError(error: unknown): void { text("command-status", error instanceof Error ? error.message : "操作失败"); }
