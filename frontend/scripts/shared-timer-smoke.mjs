import assert from "node:assert/strict";
import { mkdir, readFile } from "node:fs/promises";
import { chromium } from "playwright-core";
import { preview } from "vite";

// Actual Standard App UI, two independent browser stores, mocked Bridge/8111.
// Paired authorization is tested at the real Go HTTP boundary separately.
const site = await preview({ configFile: false, build: { outDir: "dist/Standard" }, preview: { host: "127.0.0.1", port: 0 } });
const browser = await chromium.launch({ channel: "msedge", headless: true });
const origin = new URL(site.resolvedUrls.local[0]).origin;
const html = await readFile("dist/Standard/index.html", "utf8");
const started = Date.now(), errors = [];
let timer = null, revision = 0, anchor = 0, desktopSeen = 0;
let flying = true, lastReader = 0;
const response = () => ({ schema_version: 1, epoch: "ui_bridge_epoch_123456", revision,
  server_now_ms: Date.now() - started, anchor_at_ms: anchor,
  desktop_present: Date.now() - desktopSeen < 5000, timer });
try {
  async function open(mobile, restoreTimer = !mobile) {
    const page = await browser.newPage({ viewport: mobile ? { width: 390, height: 844 } : { width: 1440, height: 900 } });
    page.setDefaultTimeout(10000);
    page.on("pageerror", error => errors.push(error.message));
    await page.addInitScript(restoreTimer => {
      localStorage.setItem("bomana:dau:disabled:v1", "1");
      if (restoreTimer) localStorage.setItem("bomana:timer-checkpoint:v1:Standard", JSON.stringify({
        lifeStartedAtMs: Date.now() - 120000, savedAtMs: Date.now(), cycleSeconds: 900, lifeIndex: 1, phase: "alive" }));
      window.__auditTones = [];
      window.__auditAudioReject = false;
      window.AudioContext = class {
        state = "suspended"; currentTime = 0; destination = {}; onstatechange = null;
        constructor() { window.__auditAudio = this; }
        async resume() { if (window.__auditAudioReject) throw new Error("Audio permission rejected"); this.state = "running"; this.onstatechange?.(); }
        createGain() { return { gain: { setValueAtTime() {}, linearRampToValueAtTime() {}, exponentialRampToValueAtTime() {} }, connect() {}, disconnect() {} }; }
        createOscillator() { const tone = { frequency: { value: 0 }, connect: gain => gain,
          start: () => window.__auditTones.push(tone.frequency.value), stop() {}, disconnect() {} }; return tone; }
      };
    }, restoreTimer);
    await page.route("**/*", async route => {
      const url = new URL(route.request().url());
      if (url.origin === origin) {
        if (url.pathname === "/" && mobile) return route.fulfill({ contentType: "text/html", body: html.replace("<body>", '<body data-mobile-paired="true">') });
        return route.continue();
      }
      if (url.pathname === "/api/v1/presentation/timer") {
        const readersPresent = lastReader > 0 && Date.now() - lastReader < 5000;
        lastReader = Date.now();
        if (!mobile) desktopSeen = Date.now();
        if (route.request().method() === "PUT") {
          const payload = route.request().postDataJSON();
          if (payload.epoch !== response().epoch || payload.expected_revision !== revision) return route.fulfill({ status: 409, json: response() });
          timer = payload.timer; revision++; anchor = Date.now() - started;
        }
        return route.fulfill({ json: { ...response(), readers_present: readersPresent } });
      }
      if (url.pathname.endsWith("/capabilities")) return route.fulfill({ json: { schema_version: 1, bridge_protocol: 1, cache_protocol: 4, mobile_pairing_protocol: 7, input: "official-8111-only", write_commands: false, bridge_version: "development" } });
      if (url.pathname.endsWith("/indicators")) return route.fulfill({ json: { valid: flying, type: "saab_jas39c", compass1: 15 } });
      if (url.pathname.endsWith("/state")) return route.fulfill({ json: { valid: flying, "IAS, km/h": 100, "TAS, km/h": 100, "H, m": 1000, "Vy, m/s": 0, "gear, %": 0, "Mfuel, kg": 1000 } });
      if (url.pathname.endsWith("/map-objects")) return route.fulfill({ json: flying
        ? [{ type: "player", x: .5, y: .5, dx: 0, dy: -1 }, { type: "bombing_point", x: .5, y: .3 }]
        : [{ type: "bombing_point", x: .5, y: .3 }] });
      if (url.pathname.endsWith("/map-info")) return route.fulfill({ json: { valid: true, map_min: [-50000,-50000], map_max: [50000,50000] } });
      return route.abort(); // No payments, analytics or real game/Bridge traffic.
    });
    const synchronized = !mobile ? page.waitForResponse(response => new URL(response.url()).pathname === "/api/v1/presentation/timer"
      && response.request().method() === "PUT" && response.request().postDataJSON()?.timer?.active && response.ok()) : null;
    await page.goto(site.resolvedUrls.local[0]);
    await page.locator('body[data-edition="Standard"]').waitFor();
    await page.waitForFunction(() => document.querySelector("#timer").textContent !== "--:--");
    await synchronized;
    return page;
  }
  // Cold entry and respawn must work without the checkpoint/reset that used
  // to hide automatic-start failures in this UI test.
  timer = { active: false, elapsed_sec: 0, cycle_seconds: 900, life_index: 0 }; revision = 1;
  const cold = await open(false, false);
  assert.ok(timer?.active, "Fresh Standard flight must publish its timer without reset");
  flying = false;
  await cold.waitForFunction(() => document.querySelector("#timer").textContent === "--:--");
  const respawnPublished = cold.waitForResponse(response => new URL(response.url()).pathname === "/api/v1/presentation/timer"
    && response.request().method() === "PUT" && response.request().postDataJSON()?.timer?.life_index === 2 && response.ok());
  flying = true;
  await cold.waitForFunction(() => document.querySelector("#timer").textContent.startsWith("14:"));
  await respawnPublished;
  assert.ok(timer?.active && timer.life_index === 2, "Respawn must automatically start and publish a second life");
  await mkdir("../.artifacts/shared-timer", { recursive: true });
  await cold.screenshot({ path: "../.artifacts/shared-timer/standard-auto-respawn.png" });
  await cold.close();
  timer = null; revision = 0; anchor = 0; desktopSeen = 0; lastReader = 0;
  const desktop = await open(false);
  await desktop.waitForFunction(() => document.querySelector("#timer-sync-status").textContent === "");
  assert.ok(timer?.active);
  assert.ok(timer.elapsed_sec < 10, "Launcher entry must reject the old browser checkpoint");
  // Advance the authoritative presentation to exercise a late phone joining
  // a running cycle without waiting two wall-clock minutes in this UI test.
  timer = { ...timer, elapsed_sec: 120 }; revision++; anchor = Date.now() - started;
  const phone = await open(true);
  await phone.waitForFunction(() => document.querySelector("#timer").textContent.startsWith("12:"));
  const seconds = async page => { const value = await page.locator("#timer").innerText(); const [m,s] = value.split(":").map(Number); return m*60+s; };
  assert.ok(Math.abs(await seconds(desktop) - await seconds(phone)) <= 1, "Late phone must share desktop timer");
  assert.equal(await phone.locator("#sound-ready").getAttribute("data-ready"), "true", "Audio initializes before any page click");
  assert.equal(await phone.locator("#sound-ready").isVisible(), false, "Ready audio needs no extra button");
  await phone.locator("#reset-timer").click();
  await desktop.waitForFunction(() => ["15:00", "14:59", "14:58"].includes(document.querySelector("#timer").textContent)).catch(async error => {
    console.log({ timer, revision, desktop: await desktop.locator("#timer").innerText(),
      phone: await phone.locator("#timer").innerText(), command: await phone.locator("#command-status").innerText(),
      sync: await phone.locator("#timer-sync-status").innerText(), errors }); throw error;
  });
  assert.ok(await seconds(phone) >= 898, "Phone reset must propagate to desktop");
  await phone.locator("#open-settings").click();
  await phone.locator("#cycle-minutes").fill("10");
  await phone.locator("#save-settings").click();
  await desktop.waitForFunction(() => document.querySelector("#timer-cycle").textContent.includes("10 分钟"));
  await desktop.locator("#reset-timer").click();
  await phone.waitForFunction(() => ["10:00", "09:59", "09:58"].includes(document.querySelector("#timer").textContent));
  assert.ok(Math.abs(await seconds(desktop) - await seconds(phone)) <= 1);
  await phone.waitForFunction(() => document.querySelector("#sound-ready").dataset.ready === "true");
  await phone.evaluate(() => {
    window.__auditAudio.state = "interrupted"; window.__auditAudioReject = true;
    window.__auditAudio.onstatechange?.(); document.dispatchEvent(new Event("visibilitychange"));
  });
  await phone.waitForFunction(() => document.querySelector("#sound-ready").dataset.ready === "false");
  await phone.locator("#sound-ready").click();
  assert.match(await phone.locator("#sound-ready").innerText(), /恢复/);
  await phone.evaluate(() => { window.__auditAudioReject = false; });
  await phone.locator("#open-settings").click();
  await phone.waitForFunction(() => document.querySelector("#sound-ready").dataset.ready === "true");
  assert.equal(await phone.locator("#sound-ready").isVisible(), false);
  await phone.locator("#settings-dialog").evaluate(dialog => dialog.close());
  const width = await phone.evaluate(() => ({ scroll: document.documentElement.scrollWidth, viewport: innerWidth }));
  assert.ok(width.scroll <= width.viewport, "Phone sound controls must not overflow the viewport");
  assert.deepEqual(errors, []);
  await mkdir("../.artifacts/shared-timer", { recursive: true });
  await phone.screenshot({ path: "../.artifacts/shared-timer/phone-ready.png" });
  console.log("Shared timer UI: cold auto-start, respawn without reset, late join, phone/desktop reset, period change, mobile sound recovery and layout passed");
} finally {
  await browser.close(); await new Promise(resolve => site.httpServer.close(resolve));
}
