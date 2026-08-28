import "./public-styles.css";
import { PublicRuntime, type PublicSnapshot } from "./public-runtime";
import { PublicTelemetry } from "./public-telemetry";

const edition = __BOMANA_EDITION__;
const cycleKey = `bomana:public-cycle:${edition}`;
const cycleMinutes = readCycle();
const runtime = new PublicRuntime(edition, cycleMinutes);
const telemetry = new PublicTelemetry("", fetch, { includeNavigation: edition === "Standard" });

document.body.dataset.edition = edition;
text("edition-name", edition === "Lite" ? "Lite · 纯计时" : "Standard · 基础导航");
for (const node of document.querySelectorAll<HTMLElement>(".standard-only")) node.hidden = edition !== "Standard";
input("cycle-minutes").value = String(cycleMinutes);

button("reset-timer").addEventListener("click", () => {
  runtime.resetTimer(Date.now());
  render(runtime.snapshot());
});
input("cycle-minutes").addEventListener("change", () => {
  const value = Number(input("cycle-minutes").value);
  if (!Number.isInteger(value) || value < 1 || value > 180) return;
  localStorage.setItem(cycleKey, String(value));
  runtime.setCycleMinutes(value);
  runtime.resetTimer(Date.now());
});
button("cycle-target").addEventListener("click", () => {
  runtime.cycleTarget();
  render(runtime.snapshot());
});

let stopped = false;
window.addEventListener("pagehide", () => { stopped = true; }, { once: true });
void poll();

async function poll(): Promise<void> {
  while (!stopped) {
    const snapshot = runtime.ingest(await telemetry.read());
    render(snapshot);
    await new Promise((resolve) => window.setTimeout(resolve, 1_000));
  }
}

function render(snapshot: PublicSnapshot): void {
  text("connection", snapshot.connected ? "Bridge 已连接" : "等待 Bridge · 请从 Launcher 下载并运行");
  const remaining = snapshot.remainingSec;
  text("timer", remaining === null ? "--:--" : formatTime(remaining));
  text("timer-cycle", snapshot.cycle === null ? "等待出击" : `第 ${snapshot.cycle} 个周期`);
  element("timer-progress").style.width = `${Math.max(0, Math.min(1, snapshot.progress)) * 100}%`;
  if (edition !== "Standard") return;
  text("ias", snapshot.flight ? `${Math.round(snapshot.flight.iasKmh)} km/h` : "-- km/h");
  text("altitude", snapshot.flight ? `${Math.round(snapshot.flight.altitudeM)} m` : "-- m");
  text("heading", snapshot.flight ? `${Math.round(snapshot.flight.headingDeg).toString().padStart(3, "0")}°` : "--°");
  text("fuel", snapshot.flight ? `${Math.round(snapshot.flight.fuelKg)} kg` : "-- kg");
  text("target-name", snapshot.target?.label ?? "暂无目标");
  text("target-bearing", snapshot.target ? `方位 ${Math.round(snapshot.target.bearingDeg).toString().padStart(3, "0")}°` : "方位 ---");
  text("target-distance", snapshot.target ? `距离 ${snapshot.target.distanceKm.toFixed(1)} km` : "距离 ---");
  drawMap(snapshot);
}

function drawMap(snapshot: PublicSnapshot): void {
  const canvas = element<HTMLCanvasElement>("map");
  const context = canvas.getContext("2d");
  if (!context) return;
  context.clearRect(0, 0, canvas.width, canvas.height);
  context.fillStyle = "#07171f";
  context.fillRect(0, 0, canvas.width, canvas.height);
  const x = (value: number) => 30 + value * (canvas.width - 60);
  const y = (value: number) => 30 + value * (canvas.height - 60);
  for (const target of snapshot.targets) {
    context.strokeStyle = target.kind === "zone" ? "#ff6671" : target.friendly ? "#6ea2ff" : "#ff6671";
    context.fillStyle = context.strokeStyle;
    context.lineWidth = target.id === snapshot.target?.id ? 5 : 2;
    context.beginPath();
    if (target.kind === "zone") context.arc(x(target.x), y(target.y), 10, 0, Math.PI * 2);
    else context.rect(x(target.x) - 10, y(target.y) - 6, 20, 12);
    context.stroke();
  }
  if (snapshot.player) {
    context.fillStyle = "#ffd65a";
    context.beginPath(); context.arc(x(snapshot.player.x), y(snapshot.player.y), 7, 0, Math.PI * 2); context.fill();
  }
}

function readCycle(): number {
  const value = Number(localStorage.getItem(cycleKey));
  return Number.isInteger(value) && value >= 1 && value <= 180 ? value : 15;
}

function element<T extends HTMLElement = HTMLElement>(id: string): T {
  const value = document.getElementById(id);
  if (!value) throw new Error(`missing element: ${id}`);
  return value as T;
}
function text(id: string, value: string): void { element(id).textContent = value; }
function button(id: string): HTMLButtonElement { return element<HTMLButtonElement>(id); }
function input(id: string): HTMLInputElement { return element<HTMLInputElement>(id); }
function formatTime(seconds: number): string {
  const whole = Math.ceil(seconds);
  return `${Math.floor(whole / 60).toString().padStart(2, "0")}:${(whole % 60).toString().padStart(2, "0")}`;
}
