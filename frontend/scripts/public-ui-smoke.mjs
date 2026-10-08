import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import { chromium } from "playwright-core";
import { preview } from "vite";
import { measureLandingGuidance } from "./landing-visibility.mjs";

const site = await preview({ configFile: false, build: { outDir: "dist/Standard" }, preview: { host: "127.0.0.1", port: 0 } });
const browser = await chromium.launch({ channel: "msedge", headless: true });
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.addInitScript(() => {
    localStorage.setItem("bomana:dau:disabled:v1", "1");
    const localFetch = fetch.bind(window), started = Date.now();
    window.__publicMapRevision = 0;
    window.__publicMapInactive = false;
    window.__publicGameInactive = false;
    window.__publicGearPercent = 100;
    window.__publicAirContacts = true;
    window.__publicMapHeld = false;
    window.__publicMapReads = 0;
    localStorage.setItem("bomana:web:pip-risk-consent:v1", "accepted");
    window.fetch = (input, init) => {
      const url = new URL(input instanceof Request ? input.url : input, location.href);
      if (url.origin === location.origin) return localFetch(input, init);
      const elapsed = Date.now() - started;
      if (url.pathname.endsWith("/capabilities")) return Promise.resolve(Response.json({ schema_version: 1, bridge_protocol: 1, cache_protocol: 4, input: "official-8111-only", write_commands: false, bridge_version: "1.0.0" }));
      if (url.pathname.endsWith("/indicators")) return Promise.resolve(Response.json({ valid: !window.__publicGameInactive, type: "saab_jas39c", compass1: 15 }));
      if (url.pathname.endsWith("/state")) return Promise.resolve(Response.json({ valid: !window.__publicGameInactive, "IAS, km/h": 700, "TAS, km/h": 720, "H, m": 3000, "Vy, m/s": 0, "Mfuel, kg": 1200 - elapsed / 1000, "Mfuel0, kg": 1400, "throttle 1, %": 90, "gear, %": window.__publicGearPercent, "flaps, %": 20 }));
      if (url.pathname.endsWith("/map-objects")) {
        window.__publicMapReads++;
        if (window.__publicMapHeld) return Promise.reject(new TypeError("simulated map outage"));
        return Promise.resolve(Response.json(window.__publicMapInactive ? [] : [{ type: "player", x: .5, y: .5 - elapsed * .000002, dx: 0, dy: -1 }, { type: "bombing_point", x: .5, y: .3 }, { type: "airfield", side: "friendly", sx: .2, sy: .7, ex: .2, ey: .8 }, { type: "point_of_interest", x: .49, y: .3 },
          ...(window.__publicAirContacts ? Array.from({ length: 8 }, (_, index) => ({ type: "aircraft", side: "hostile", icon: "fighter", id: index,
            x: .5 + (index + 1) * .004 + elapsed * .0000005, y: .49 - elapsed * .000002 + index * .002, dx: .2, dy: -.98 })) : []),
          ...(window.__publicAirContacts ? [{ type: "aircraft", side: "friendly", icon: "bomber", x: .49, y: .49 - elapsed * .000002, dx: 0, dy: -1 }] : [])]));
      }
      if (url.pathname.endsWith("/map-info")) return Promise.resolve(Response.json({ valid: !window.__publicMapInactive, map_min: [-50000, -50000], map_max: [50000 + window.__publicMapRevision, 50000] }));
      if (url.pathname.endsWith("/map-image")) {
        const image = async () => {
          const canvas = new OffscreenCanvas(256, 256), context = canvas.getContext("2d");
          context.fillStyle = "#214658"; context.fillRect(0, 0, 256, 256);
          return new Response(await canvas.convertToBlob({ type: "image/png" }));
        };
        return window.__publicMapRevision ? new Promise(resolve => { window.__releasePublicMapImage = () => resolve(image()); }) : image();
      }
      return Promise.reject(new TypeError("External service disabled in public UI test"));
    };
  });
  await page.goto(site.resolvedUrls.local[0]);
  await page.locator('body[data-edition="Standard"]').waitFor();
  await page.waitForFunction(() => document.querySelector("#timer").textContent !== "--:--");
  assert.equal(await page.locator("#navigation-select option").count(), 2, "Standard must not expose POI navigation");
  assert.equal(await page.locator("#strike-panel, #offline-cache-panel, #calibrate-y66, #chat-panel").count(), 0, "Paid controls must be absent from public HTML");
  await page.locator("#open-timer-settings").click();
  assert.equal(await page.locator("#settings-dialog").isVisible(), true);
  await page.locator("#close-settings").click();
  assert.equal(await page.locator("#ias-value").innerText(), "700");
  assert.match(await page.locator("#pip-speed-value").innerText(), /IAS 700\/533$/);
  assert.ok(await page.locator("#pip-speed-strip").evaluate(node => node.classList.contains("level-critical")), "Automatic flaps constrain the strip before landing mode is enabled");
  await page.waitForFunction(() => document.querySelector("#pip-gear-status-badge")?.textContent === "起落架未收");
  await page.evaluate(() => { window.__publicGearPercent = 40; });
  await page.waitForFunction(() => document.querySelector("#pip-gear-status-badge")?.textContent === "收轮 40%");
  const firstPipOpening = page.context().waitForEvent("page");
  await page.locator("#toggle-pip").click();
  const firstPip = await firstPipOpening;
  firstPip.setDefaultTimeout(10_000);
  await firstPip.locator("#pip-gear-status-badge").waitFor({ state: "visible" });
  assert.equal(await firstPip.locator("#pip-gear-status-badge").innerText(), "收轮 40%", "PiP must consume the page's current gear direction");
  await page.evaluate(() => { window.__publicGearPercent = 90; });
  await page.waitForFunction(() => document.querySelector("#pip-gear-status-badge")?.textContent === "放轮 90%");
  await firstPip.waitForFunction(() => [...document.querySelectorAll("#pip-gear-status-badge")].some(node => node.textContent === "放轮 90%"));
  await firstPip.close();
  await page.waitForTimeout(100);
  await page.locator("#open-settings").click();
  await page.locator("#cycle-minutes").fill("15");
  await page.locator("#save-settings").click();
  await page.waitForFunction(() => document.querySelector("#timer-cycle")?.textContent?.includes("15 分钟"));
  await page.evaluate(() => { window.__publicGearPercent = 40; });
  await page.waitForFunction(() => document.querySelector("#pip-gear-status-badge")?.textContent === "收轮 40%");
  const reopenedPipOpening = page.context().waitForEvent("page");
  await page.locator("#toggle-pip").click();
  const reopenedPip = await reopenedPipOpening;
  reopenedPip.setDefaultTimeout(10_000);
  await reopenedPip.locator("#pip-gear-status-badge").waitFor({ state: "visible" });
  assert.equal(await reopenedPip.locator("#pip-gear-status-badge").innerText(), "收轮 40%", "Reopened PiP must retain direction observed while closed");
  await reopenedPip.close();
  await page.evaluate(() => { window.__publicGearPercent = 0; });
  await page.waitForFunction(() => document.querySelector("#pip-gear-status-badge")?.hasAttribute("hidden"));
  await page.locator('.pip-header [data-mode="air-realistic"]').click();
  const air = page.locator(".air-realistic-instruments"), airCanvas = air.locator("canvas");
  await page.waitForFunction(() => document.querySelector(".ar-map canvas")?.dataset.contacts === "8"
    && document.querySelector(".ar-map canvas")?.dataset.friendlies === "1"
    && document.querySelector(".ar-map canvas")?.dataset.trails !== "0"
    && document.querySelector(".ar-velocity-readout")?.textContent.includes("航迹 000°"));
  assert.equal(await air.locator(".ar-velocity-toggle").getAttribute("aria-pressed"), "true");
  const vectorText = await air.locator(".ar-velocity-readout").innerText();
  assert.match(vectorText, /偏左 15°.*地速 \d+ km\/h/);
  assert.ok(Math.abs(Number(vectorText.match(/地速 (\d+)/)[1]) - 720) < 30, "Request-midpoint timing may vary slightly from the mocked game position time");
  assert.equal(await air.locator(".ar-speed").getAttribute("data-level"), "critical");
  assert.match(await air.locator(".ar-flaps").innerText(), /襟翼 超限/);
  assert.equal(await page.locator("#navigation-select option").count(), 2, "Aircraft observations never become Standard navigation targets");
  const airOpening = page.context().waitForEvent("page");
  await page.locator("#toggle-pip").click();
  const airPip = await airOpening;
  await airPip.setViewportSize({ width: 320, height: 320 });
  await airPip.waitForFunction(() => document.querySelector(".ar-map canvas")?.dataset.contacts === "8"
    && document.querySelector(".ar-velocity-readout")?.textContent.includes("航迹 000°"));
  assert.equal(await airPip.locator(".pip-mini-map").isVisible(), false);
  assert.equal(await airPip.locator("#pip-heading-canvas").isVisible(), false);
  await airPip.locator(".ar-velocity-toggle").click();
  await page.waitForFunction(() => document.querySelector(".ar-velocity-toggle")?.getAttribute("aria-pressed") === "false");
  assert.equal(await page.evaluate(() => localStorage.getItem("bomana:air-velocity-vector:v1")), "off");
  await page.locator(".ar-velocity-toggle").click();
  await airPip.waitForFunction(() => document.querySelector(".ar-velocity-toggle")?.getAttribute("aria-pressed") === "true");
  await mkdir("../.artifacts/public-ui", { recursive: true });
  const cdp = await page.context().newCDPSession(page), pipCdp = await page.context().newCDPSession(airPip);
  for (const session of [cdp, pipCdp]) {
    await session.send("Emulation.setCPUThrottlingRate", { rate: 4 });
    await session.send("Performance.enable");
  }
  const metric = async session => (await session.send("Performance.getMetrics")).metrics.find(item => item.name === "TaskDuration").value;
  const before = await Promise.all([metric(cdp), metric(pipCdp), page.evaluate(() => window.__publicMapReads)]);
  await page.waitForTimeout(3000);
  const after = await Promise.all([metric(cdp), metric(pipCdp), page.evaluate(() => window.__publicMapReads)]);
  const performance = { cpuThrottle: 4, durationSeconds: 3, contacts: 8, mainTaskSeconds: after[0] - before[0], pipTaskSeconds: after[1] - before[1], mapReads: after[2] - before[2] };
  assert.ok(performance.mapReads > 0 && performance.mapReads <= 40, "PiP must not create a second 8111 polling loop");
  for (const surface of [page, airPip]) {
    assert.equal(await surface.locator(".ar-map canvas").getAttribute("data-contacts"), "8");
    assert.ok(await surface.locator(".air-realistic-instruments").evaluate(root => root.scrollWidth <= root.clientWidth + 1));
  }
  await writeFile("../.artifacts/public-ui/Standard-air-performance.json", JSON.stringify(performance, null, 2));
  for (const session of [cdp, pipCdp]) await session.send("Emulation.setCPUThrottlingRate", { rate: 1 });
  await page.screenshot({ path: "../.artifacts/public-ui/Standard-air-main.png" });
  await airPip.waitForFunction(() => document.querySelector(".ar-velocity-readout")?.textContent.includes("航迹 000°"));
  await airPip.screenshot({ path: "../.artifacts/public-ui/Standard-air-pip-320.png" });
  await page.evaluate(() => { window.__publicMapHeld = true; });
  for (const surface of [page, airPip]) await surface.waitForFunction(() => document.querySelector(".ar-map canvas")?.dataset.contacts === "0"
    && document.querySelector(".ar-map canvas")?.dataset.friendlies === "0"
    && document.querySelector(".ar-velocity-readout")?.textContent === "速度矢量 —");
  await page.evaluate(() => { window.__publicMapHeld = false; window.__publicAirContacts = false; });
  await page.waitForFunction(() => document.querySelector(".ar-velocity-readout")?.textContent.includes("航迹 000°"));
  assert.equal(await airCanvas.getAttribute("data-contacts"), "0", "Successful empty aircraft observations remain authoritative");
  await airPip.locator('.ar-header [data-mode="simulator"]').click();
  await page.locator(".air-realistic-instruments").waitFor({ state: "hidden" });
  assert.equal(await page.locator('.pip-header [data-mode="simulator"]').getAttribute("aria-pressed"), "true");
  await airPip.close();
  await page.locator('.pip-header [data-mode="air-realistic"]').click();
  await page.locator(".ar-velocity-toggle").click();
  await page.reload();
  await page.locator(".air-realistic-instruments").waitFor({ state: "visible" });
  assert.equal(await page.locator(".ar-velocity-toggle").getAttribute("aria-pressed"), "false", "Standard remembers the disabled vector across reload");
  await page.evaluate(() => { window.__publicGearPercent = 0; });
  await page.waitForFunction(() => document.querySelector("#pip-gear-status-badge")?.hasAttribute("hidden"));
  await page.locator(".ar-velocity-toggle").click();
  for (const [width, height] of [[390, 844], [844, 390]]) {
    await page.setViewportSize({ width, height });
    await page.locator(".air-realistic-instruments").scrollIntoViewIfNeeded();
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
    const box = await page.locator(".air-realistic-instruments").boundingBox();
    assert.ok(box.width >= 300 && box.height >= 240, "Standard Air Realistic retains a usable central map on phones");
  }
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.locator('.ar-header [data-mode="simulator"]').click();
  console.log(`Standard Air Realistic: official aircraft, vector/preferences, main/PiP modes, stale withdrawal and 4x CPU smoke passed ${JSON.stringify(performance)}`);
  const landing = page.getByRole("region", {name:"降落辅助"});
  assert.equal(await landing.locator('[data-part="message"]').innerText(), '自动待命');
  const priorNavigation = await page.locator("#navigation-target").innerText();
  await landing.getByRole("button", {name:"开启",exact:true}).click();
  await landing.locator("[data-part='active']").waitFor({state:"visible"});
  assert.equal(await page.locator("#pip-heading-canvas").getAttribute("data-mode"),"landing");
  assert.match(await page.locator("#pip-heading-canvas").getAttribute("aria-label"),/IAS 700 km\/h.*燃油/);
  // Follow the real Standard runtime from official telemetry to both visible canvases,
  // with untouched default (unknown) airport elevation.
  const assertRoute = async surface => {
    const canvas = surface.locator("#pip-heading-canvas");
    await surface.waitForFunction(() => document.querySelector("#pip-heading-canvas")?.getAttribute("aria-label")?.includes("高程未知"));
    await surface.waitForFunction(() => {
      const canvas = document.querySelector("#pip-heading-canvas");
      return canvas?.dataset.mode === "landing" && canvas.width >= canvas.getBoundingClientRect().width;
    });
    const sample = await canvas.evaluate(measureLandingGuidance);
    assert.ok(sample.light > 6 && sample.routeArea > 12 && sample.routeSpan >= 24,
      `Default Standard route must be visible without manually supplying elevation: ${JSON.stringify(sample)}`);
  };
  await assertRoute(page);
  const landingPipOpening = page.context().waitForEvent("page");
  await page.locator("#toggle-pip").click();
  const landingPip = await landingPipOpening;
  await landingPip.setViewportSize({ width: 900, height: 120 });
  await mkdir("../.artifacts/public-ui", { recursive: true });
  const headingWidths = [];
  for (const showMap of [true, false]) {
    const map = landingPip.locator(".pip-mini-map");
    if (await map.isVisible() !== showMap) await landingPip.locator("#pip-map-toggle").click();
    await map.waitFor({ state: showMap ? "visible" : "hidden" });
    await landingPip.waitForFunction(() => {
      const canvas = document.querySelector("#pip-heading-canvas");
      return Math.abs(canvas.width / devicePixelRatio - canvas.getBoundingClientRect().width) < 2;
    });
    await assertRoute(landingPip);
    const heading = await landingPip.locator("#pip-heading-canvas").boundingBox();
    headingWidths.push(heading.width);
    if (showMap) {
      const box = await map.boundingBox();
      assert.ok(heading.x + heading.width <= box.x, "The perspective canvas must exclude the PiP map column");
    }
    await landingPip.screenshot({ path: `../.artifacts/public-ui/Standard-landing-map-${showMap ? "on" : "off"}-900x120.png` });
  }
  assert.ok(headingWidths[1] > headingWidths[0], "Hiding the map must release space for the perspective viewport");
  await landingPip.close();
  assert.equal(await landing.locator('[data-part="arrestor"]').isVisible(), false, 'Static capability belongs in the collapsed reference section');
  assert.equal(await landing.locator('[data-part="touchdown"]').isVisible(), false, 'Default panel omits static touchdown explanation');
  assert.equal(await landing.locator('[data-part="flapAdvice"]').isVisible(), true, 'Current overspeed advice remains visible');
  assert.match(await landing.locator("[data-part='configuration']").innerText(),/翼 20%/);
  assert.equal(await landing.locator("[data-part='flapAdvice']").innerText(), '襟翼超限');
  assert.match(await page.locator("#pip-heading-canvas").getAttribute("aria-label"),/襟翼超限/);
  assert.equal(await page.locator("#navigation-target").innerText(), priorNavigation, "Landing does not change the strike/navigation target");
  for (const theme of ['glacier', 'classic-dark']) {
    await page.evaluate(theme => { document.documentElement.dataset.theme = theme; }, theme);
    await page.setViewportSize({ width: 390, height: 844 });
    await mkdir(new URL('../../.artifacts/public-ui/', import.meta.url), { recursive: true });
    await landing.screenshot({ path: new URL(`../../.artifacts/public-ui/landing-${theme}.png`, import.meta.url).pathname.replace(/^\/(\w:)/, '$1') });
    assert.equal(await landing.locator('[data-part="flapAdvice"]').isVisible(), true);
  }
  await page.evaluate(() => { document.documentElement.dataset.theme = 'glacier'; });
  await page.setViewportSize({ width: 1440, height: 900 });
  await landing.locator("summary").click();
  await landing.locator('[data-part="limits"] .landing-limit').first().waitFor();
  assert.match(await landing.locator("[data-part='limits']").innerText(),/起落架 ≤ \d+ km\/h/);
  assert.ok(await landing.locator("meter:visible").count() >= 1, "Reference details retain the live IAS comparison");
  assert.equal(await landing.locator('[data-part="arrestor"]').isVisible(), true);
  await landing.locator("[data-part='ias']").fill("250");
  await landing.locator("[data-part='elevation']").fill("100");
  await landing.getByRole("button", {name:"应用",exact:true}).click();
  await page.waitForFunction(() => document.querySelector("[data-part='speed']").textContent.includes("/ 250"));
  assert.match(await page.locator("#pip-speed-value").innerText(), /IAS 700\/533$/, "Manual approach IAS must not replace the flap destruction reference");
  assert.equal(await landing.locator("[data-part='message']").innerText(), '返航');
  assert.equal(await landing.locator("[data-part='vertical-dot']").isVisible(), false, "Far return must not show a glide reference even with manual elevation");
  await landing.getByRole("button", {name:"反向进近"}).click();
  await page.waitForFunction(() => document.querySelector("[data-part='elevation']").value === "");
  await landing.locator("summary").click();
  const speedStrip = await page.locator("#pip-speed-track").evaluate(track => ({
    markers: [...track.querySelectorAll("b")].map(marker => marker.style.left),
    transition: getComputedStyle(track.querySelector("i")).transition,
  }));
  assert.deepEqual(speedStrip.markers, ["40%", "65%", "95%"], "Public speed strip shares the pre-limit warning scale");
  assert.match(speedStrip.transition, /width 0\.08s linear/, "Public speed fill must finish before the next normal observation");
  await page.waitForFunction(() => {
    const canvas = document.querySelector("#navigation-map");
    const pixel = canvas.getContext("2d").getImageData(canvas.width / 4, canvas.height / 4, 1, 1).data;
    // Alpha compositing can round a channel differently between GPU backends.
    return [24, 55, 71].every((value, index) => Math.abs(pixel[index] - value) <= 1);
  }).catch(async error => {
    console.error("Official map test state", await page.evaluate(() => {
      const canvas = document.querySelector("#navigation-map");
      return { status: document.querySelector("#status").textContent, pixel: [...canvas.getContext("2d").getImageData(canvas.width / 4, canvas.height / 4, 1, 1).data] };
    }), errors);
    throw error;
  });
  await page.locator("#open-settings").click();
  await page.locator("#cycle-minutes").fill("20");
  await page.locator("#save-settings").click();
  await page.waitForFunction(() => document.querySelector("#timer-cycle").textContent.includes("20 分钟"));
  await page.locator("#cycle-navigation-target").click();
  await page.locator(".encyclopedia summary").click();
  await page.locator("#calculate-damage").click();
  assert.notEqual(await page.locator("#damage-result").innerText(), "选择参数后计算");
  await page.locator(".encyclopedia summary").click();
  await mkdir("../.artifacts/public-ui", { recursive: true });
  for (const [width, height] of [[1440, 900], [390, 844], [320, 568], [844, 390]]) {
    await page.setViewportSize({ width, height });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `${width}: horizontal overflow`);
    const frame = await page.evaluate(() => {
      document.querySelector("#stage").scrollTop = 0;
      const box = selector => document.querySelector(selector).getBoundingClientRect().toJSON();
      return { header: box(".hud-top"), map: box(".map-stage"), left: box(".hud-left"), right: box(".hud-right"), actions: box(".hud-bottom") };
    });
    assert.ok(frame.map.top >= frame.header.bottom && frame.map.width > 250 && frame.map.height > 100, `Shared map viewport: ${JSON.stringify(frame)}`);
    if (width === 1440) {
      assert.ok(frame.map.left >= frame.left.right && frame.map.right <= frame.right.left, "Map uses the unobscured corridor between both columns");
    } else {
      assert.ok(frame.map.bottom <= frame.left.top && frame.left.bottom <= frame.right.top, "Compact cards follow the map without overlapping");
      assert.ok(frame.actions.bottom <= height + 1, "Settings remain reachable above the screen edge");
    }
    await page.screenshot({ path: `../.artifacts/public-ui/Standard-${width}x${height}.png`, fullPage: true });
  }
  await page.evaluate(() => { document.body.dataset.mobilePaired = "true"; });
  for (const [width, height] of [[390, 844], [844, 390]]) {
    await page.setViewportSize({ width, height });
    assert.equal(await page.locator(".hud-product-nav").isVisible(), false);
    assert.equal(await page.locator("#toggle-pip").isVisible(), false);
    assert.equal(await page.locator("#open-mobile-pairing").isVisible(), false);
    assert.equal(await page.locator("#open-settings").isVisible(), true);
    await page.locator("#open-settings").click();
    await page.locator("#close-settings").click();
    await page.locator("#cycle-navigation-target").scrollIntoViewIfNeeded();
    assert.equal(await page.locator("#cycle-navigation-target").isVisible(), true, "Paired phone retains navigation actions");
    await page.evaluate(() => { document.querySelector("#stage").scrollTop = 0; });
    const instruments = await page.locator(".web-flight-instruments").boundingBox();
    assert.ok(instruments.y >= 0 && instruments.y < 55 && instruments.height >= 120, "Paired heading must have a visible viewport, not a zero-height grid row");
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
    await page.screenshot({ path: `../.artifacts/public-ui/Standard-paired-${width}x${height}.png`, fullPage: true });
  }
  await page.evaluate(() => { delete document.body.dataset.mobilePaired; });
  await page.evaluate(() => { window.__publicMapRevision = 1; });
  await page.locator("#connect").click();
  await page.waitForFunction(() => typeof window.__releasePublicMapImage === "function");
  await page.evaluate(() => { window.__publicMapInactive = true; });
  await page.waitForFunction(() => {
    const canvas = document.querySelector("#navigation-map");
    return canvas.getContext("2d").getImageData(canvas.width / 2, canvas.height / 5, 1, 1).data[0] === 11;
  });
  await page.evaluate(() => window.__releasePublicMapImage());
  await page.waitForTimeout(100);
  assert.equal(await page.evaluate(() => {
    const canvas = document.querySelector("#navigation-map");
    return canvas.getContext("2d").getImageData(canvas.width / 2, canvas.height / 5, 1, 1).data[0];
  }), 11, "inactive map must reject the previous map's late image");
  await page.evaluate(() => { window.__publicGameInactive = true; });
  await page.waitForFunction(() => document.querySelector("#status").textContent === "Bridge 已连接 · 等待游戏出击");
  assert.equal(await page.locator("#map-empty").isVisible(), true);
  assert.deepEqual(errors, []);
  console.log("Standard UI: timer/settings, official-only targets/basemap lifecycle, encyclopedia, desktop/paired phone geometry and console passed");
  const liteSite = await preview({ configFile: false, build: { outDir: "dist/Lite" }, preview: { host: "127.0.0.1", port: 0 } });
  try {
    const lite = await browser.newPage();
    lite.on("pageerror", error => errors.push(error.message));
    await lite.addInitScript(() => { localStorage.setItem("bomana:dau:disabled:v1", "1"); });
    await lite.goto(liteSite.resolvedUrls.local[0]);
    await lite.locator('body[data-edition="Lite"]').waitFor();
    for (const [width, height] of [[1440, 900], [320, 568]]) {
      await lite.setViewportSize({ width, height });
      assert.equal(await lite.locator(".map-stage").isVisible(), false);
      assert.equal(await lite.locator(".web-flight-instruments").isVisible(), false);
      assert.equal(await lite.locator(".hud-right").isVisible(), false);
      await lite.locator("#open-timer-settings").click();
      await lite.locator("#cycle-minutes").fill("15");
      await lite.locator("#save-settings").click();
      await lite.locator("#settings-dialog").waitFor({ state: "hidden" });
      assert.ok(await lite.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
      await lite.screenshot({ path: `../.artifacts/public-ui/Lite-${width}x${height}.png`, fullPage: true });
    }
    await lite.close();
    assert.deepEqual(errors, []);
    console.log("Lite UI: shared header/timer settings, hidden navigation and desktop/phone geometry passed");
  } finally { await liteSite.close(); }
} finally { await browser.close(); await site.close(); }
