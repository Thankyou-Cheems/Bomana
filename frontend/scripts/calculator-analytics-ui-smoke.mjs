import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { resolve, extname, sep } from "node:path";
import { chromium } from "playwright-core";

const root = resolve("../docs");
const origin = "https://bomana.ruikang.wang";
const endpoint = "https://bomanaupdate.ruikang.wang/api/v2/metrics/events";
const browser = await chromium.launch({ channel: "msedge", headless: true });
try {
  for (const scenario of ["app-first", "disabled", "offline"]) {
    const context = await browser.newContext();
    const requests = [];
    await context.route(`${origin}/**`, async route => {
      let path = new URL(route.request().url()).pathname;
      if (path.endsWith("/")) path += "index.html";
      const file = resolve(root, `.${path}`);
      assert.ok(file.startsWith(root + sep));
      try {
        await route.fulfill({ body: await readFile(file), contentType: ({ ".mjs": "text/javascript", ".js": "text/javascript", ".json": "application/json", ".wasm": "application/wasm", ".css": "text/css", ".webp": "image/webp", ".ttf": "font/ttf" })[extname(file)] || "text/html; charset=utf-8" });
      } catch { await route.fulfill({ status: 404 }); }
    });
    await context.route(endpoint, async route => {
      requests.push(route.request().postDataJSON());
      if (scenario === "offline") await route.abort();
      else await route.fulfill({ status: 202, headers: { "Access-Control-Allow-Origin": origin }, json: { accepted: true, duplicate: false } });
    });
    await context.addInitScript(mode => {
      localStorage.setItem("bomana:dau:reported-utc-day:v1", new Date().toISOString().slice(0, 10));
      if (mode === "disabled") localStorage.setItem("bomana:dau:disabled:v1", "1");
    }, scenario);
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", error => errors.push(error.message));
    const loaded = async () => {
      await page.waitForFunction(() => document.querySelector("#calcPresetList [data-preset-id]"));
      // Boot reports after its final animation frame, without blocking the UI.
      await page.evaluate(() => new Promise(done => requestAnimationFrame(() => requestAnimationFrame(done))));
    };
    await page.goto(`${origin}/calculator/`);
    await loaded();
    if (scenario !== "disabled") {
      await page.waitForFunction(() => localStorage.getItem("bomana:dau:reported-utc-day:v1:calculator") !== null);
      await page.waitForTimeout(100);
      assert.equal(requests.length, 1);
      assert.equal(requests[0].channel, "Calculator");
      assert.match(requests[0].dailyToken, /^[a-f0-9]{64}$/);
      assert.deepEqual(Object.keys(requests[0]).sort(), ["channel", "dailyToken", "day", "type"]);
      assert.equal(requests[0].type, "dau");
    } else assert.equal(requests.length, 0);
    await page.reload();
    await loaded();
    assert.equal(requests.length, scenario === "disabled" ? 0 : 1);
    assert.deepEqual(errors, []);
    await context.close();
  }
  console.log("Calculator analytics UI passed: production boot, App-first visit, exact anonymous payload, reload deduplication, opt-out and offline isolation; no live signals sent.");
} finally { await browser.close(); }
