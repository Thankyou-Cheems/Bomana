import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import { chromium } from "playwright-core";
import { preview } from "vite";

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
    window.fetch = (input, init) => {
      const url = new URL(input instanceof Request ? input.url : input, location.href);
      if (url.origin === location.origin) return localFetch(input, init);
      const elapsed = Date.now() - started;
      if (url.pathname.endsWith("/capabilities")) return Promise.resolve(Response.json({ schema_version: 1, bridge_protocol: 1, cache_protocol: 4, input: "official-8111-only", write_commands: false, bridge_version: "1.0.0" }));
      if (url.pathname.endsWith("/indicators")) return Promise.resolve(Response.json({ valid: true, type: "saab_jas39c", compass1: 15 }));
      if (url.pathname.endsWith("/state")) return Promise.resolve(Response.json({ valid: true, "IAS, km/h": 700, "TAS, km/h": 720, "H, m": 3000, "Vy, m/s": 0, "Mfuel, kg": 1200 - elapsed / 1000, "Mfuel0, kg": 1400, "throttle 1, %": 90, "gear, %": 0, "flaps, %": 20 }));
      if (url.pathname.endsWith("/map-objects")) return Promise.resolve(Response.json(window.__publicMapInactive ? [] : [{ type: "player", x: .5, y: .5 - elapsed * .000002, dx: 0, dy: -1 }, { type: "bombing_point", x: .5, y: .3 }, { type: "airfield", side: "friendly", sx: .2, sy: .7, ex: .2, ey: .8 }, { type: "point_of_interest", x: .49, y: .3 }]));
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
  assert.equal(await page.locator("#ias-value").innerText(), "700");
  assert.match(await page.locator("#speed-limit-value").innerText(), /IAS 700\/533 · 襟翼参考$/);
  assert.ok(await page.locator("#speed-strip").evaluate(node => node.classList.contains("level-critical")), "Automatic flaps constrain the strip before landing mode is enabled");
  const landing = page.getByRole("region", {name:"降落辅助"});
  const priorNavigation = await page.locator("#navigation-target").innerText();
  await landing.getByRole("button", {name:"开启",exact:true}).click();
  await landing.locator("[data-part='active']").waitFor({state:"visible"});
  assert.equal(await page.locator("#heading-tape").getAttribute("data-mode"),"landing");
  assert.match(await page.locator("#heading-tape").getAttribute("aria-label"),/IAS 700 km\/h.*燃油/);
  assert.match(await landing.locator("[data-part='limits']").innerText(),/起落架 ≤ \d+ km\/h/);
  assert.ok(await landing.locator("meter:visible").count() >= 1, "The live IAS comparison is visible without a manually chosen approach speed");
  assert.match(await landing.locator("[data-part='configuration']").innerText(),/襟翼 20%（无手动控制）/);
  assert.match(await landing.locator("[data-part='flapAdvice']").innerText(),/襟翼超过参考上限 · 减速$/);
  assert.match(await page.locator("#heading-tape").getAttribute("aria-label"),/襟翼超限/);
  assert.equal(await page.locator("#navigation-target").innerText(), priorNavigation, "Landing does not change the strike/navigation target");
  await landing.locator("summary").click();
  await landing.locator("[data-part='ias']").fill("250");
  await landing.locator("[data-part='elevation']").fill("100");
  await landing.getByRole("button", {name:"应用参考参数"}).click();
  await page.waitForFunction(() => document.querySelector("[data-part='speed']").textContent.includes("/ 250"));
  assert.match(await page.locator("#speed-limit-value").innerText(), /IAS 700\/533 · 襟翼参考$/, "Manual approach IAS must not replace the flap destruction reference");
  assert.match(await landing.locator("[data-part='message']").innerText(), /返航机场/);
  assert.equal(await landing.locator("[data-part='vertical-dot']").isVisible(), false, "Far return must not show a glide reference even with manual elevation");
  await landing.getByRole("button", {name:"反向进近"}).click();
  await page.waitForFunction(() => document.querySelector("[data-part='elevation']").value === "");
  await landing.locator("summary").click();
  const speedStrip = await page.locator("#speed-track").evaluate(track => ({
    markers: [...track.querySelectorAll("b")].map(marker => marker.style.left),
    transition: getComputedStyle(track.querySelector("i")).transition,
  }));
  assert.deepEqual(speedStrip.markers, ["64%", "82%", "95.2%"], "Public speed strip shares the expanded warning scale");
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
    await page.screenshot({ path: `../.artifacts/public-ui/Standard-${width}x${height}.png`, fullPage: true });
  }
  await page.evaluate(() => { document.body.dataset.mobilePaired = "true"; });
  for (const [width, height] of [[390, 844], [844, 390]]) {
    await page.setViewportSize({ width, height });
    assert.equal(await page.locator(".public-header nav").isVisible(), false);
    assert.equal(await page.locator("#toggle-pip").isVisible(), false);
    assert.equal(await page.locator("#open-mobile-pairing").isVisible(), false);
    assert.equal(await page.locator("#open-settings").isVisible(), true);
    assert.ok(await page.locator(".heading-tape-wrap").evaluate(node => node.getBoundingClientRect().top < 55));
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
  assert.deepEqual(errors, []);
  console.log("Standard UI: timer/settings, official-only targets/basemap lifecycle, encyclopedia, desktop/paired phone geometry and console passed");
} finally { await browser.close(); await site.close(); }
