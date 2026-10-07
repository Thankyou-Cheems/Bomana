import assert from "node:assert/strict";
import { chromium } from "playwright-core";
import { createServer } from "vite";

const server = await createServer({ server: { host: "127.0.0.1", port: 0 } });
await server.listen();
let browser;
try {
  browser = await chromium.launch({ channel: "msedge", headless: true });
  const page = await browser.newPage();
  page.setDefaultTimeout(5000);
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.addInitScript(() => {
    const originalFetch = window.fetch.bind(window);
    window.cacheFixture = { connected: localStorage.getItem("cache-fixture-connected") === "true", state: "ready", requests: [], old: null, delayOld: false };
    window.fetch = async (input, init) => {
      const url = new URL(input instanceof Request ? input.url : input, location.href);
      if (url.origin === location.origin) return originalFetch(input, init);
      const f = window.cacheFixture;
      f.requests.push({ path: url.pathname, method: init?.method ?? "GET" });
      if (url.pathname === "/api/v1/capabilities") {
        if (!f.connected) throw new TypeError("Bridge offline");
        return Response.json({ schema_version: 1, bridge_protocol: 1, cache_protocol: 4,
          bridge_version: "1.8.4", build_provenance: "github-actions-sigstore", authenticode: false,
          input: "official-8111-only", write_commands: false, routes: [] });
      }
      if (url.pathname === "/api/v1/cache/status") {
        if (f.delayOld) {
          f.delayOld = false;
          return new Promise(resolve => { f.old = () => resolve(new Response("old error", { status: 503 })); });
        }
        return Response.json({ schema_version: 1, state: f.state, map_count: 23, cached_map_count: 23,
          selected_map_count: 23, selected_cached_map_count: 23, cached_object_count: 23,
          total_bytes: 66684808, cached_bytes: 66684808, maps: [{ id: "air_vietnam", state: "cached", selected: true,
            cached_bytes: 7097331, total_bytes: 7097331 }] });
      }
      throw new TypeError("External service disabled in cache regression");
    };
  });
  await page.goto(`${server.resolvedUrls.local[0]}launcher.html`);
  await page.waitForFunction(() => document.body.dataset.busy !== "true" && document.querySelector("#account-actions button"), null, { timeout: 5000 })
    .catch(error => { throw new Error(`${error.message}; page errors: ${JSON.stringify(errors)}`); });
  await page.evaluate(() => { window.cacheFixture.connected = true; });
  await page.locator("#connect-bridge").click();
  await page.waitForFunction(() => document.querySelector("#connection-step").dataset.connected === "true");
  await page.waitForFunction(() => document.querySelector("#activity-message").textContent.includes("23 / 23"));
  assert.match(await page.locator("#cache-map-summary").textContent(), /23/);

  // Disconnect/reconnect must update both panels, using the same cache protocol on 1.8.4.
  await page.evaluate(() => { window.cacheFixture.connected = false; });
  await page.locator("#connect-bridge").click();
  await page.waitForFunction(() => document.querySelector("#connection-step").dataset.connected === "false");
  assert.doesNotMatch(await page.locator("#activity-message").textContent(), /23 \/ 23/);
  await page.evaluate(() => { window.cacheFixture.connected = true; });
  await page.locator("#connect-bridge").click();
  await page.waitForFunction(() => document.querySelector("#activity-message").textContent.includes("23 / 23"));

  // A full refresh starts an older failing cache request; reconnect finishes first.
  await page.evaluate(() => { window.cacheFixture.delayOld = true; });
  await page.locator("#refresh-catalog").click();
  await page.waitForFunction(() => window.cacheFixture.old !== null);
  // The busy full-refresh UI blocks pointers; the automatic Bridge recheck
  // reaches this same handler independently of that page-level busy state.
  await page.locator("#connect-bridge").evaluate(button => button.click());
  await page.waitForFunction(() => window.cacheFixture.requests.filter(r => r.path === "/api/v1/cache/status").length >= 4);
  await page.waitForFunction(() => document.querySelector("#connect-bridge").disabled === false);
  await page.evaluate(() => window.cacheFixture.old());
  await page.waitForFunction(() => document.body.dataset.busy !== "true");
  assert.match(await page.locator("#activity-message").textContent(), /23 \/ 23/);
  assert.doesNotMatch(await page.locator("#activity-message").textContent(), /不可用|失败/);
  for (const state of ["checking", "syncing"]) {
    await page.evaluate(state => { window.cacheFixture.state = state; }, state);
    await page.locator("#connect-bridge").click();
    await page.waitForFunction(() => document.querySelector("#mode-badge").textContent !== "已就绪");
    await page.evaluate(() => { window.cacheFixture.state = "ready"; });
    await page.waitForFunction(() => document.querySelector("#mode-badge").textContent === "已就绪");
  }
  const cacheCalls = await page.evaluate(() => window.cacheFixture.requests.filter(r => r.path.startsWith("/api/v1/cache/")));
  assert.ok(cacheCalls.length >= 4);
  assert.ok(cacheCalls.every(r => r.path === "/api/v1/cache/status" && r.method === "GET"), "reconnect only reads status; no selection write or map redownload");
  await page.evaluate(() => localStorage.setItem("cache-fixture-connected", "true"));
  await page.reload();
  await page.waitForFunction(() => document.querySelector("#mode-badge").textContent === "已就绪");
  assert.deepEqual(errors, []);
  console.log("Launcher cache: initial connection, reconnect, stale response and Bridge 1.8.4 protocol 4 passed without downloads");
} finally { await browser?.close(); await server.close(); }
