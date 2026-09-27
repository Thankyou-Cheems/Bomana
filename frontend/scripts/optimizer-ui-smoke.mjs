import assert from "node:assert/strict";
import {readFile, mkdir} from "node:fs/promises";
import {createServer} from "node:http";
import {resolve, sep, extname} from "node:path";
import {chromium} from "playwright-core";
const root = resolve("../docs");
const server = createServer(async (req, res) => {
  let path = decodeURIComponent(new URL(req.url, "http://localhost").pathname);
  if (path.endsWith("/")) path += "index.html";
  const file = resolve(root, `.${path}`);
  if (!file.startsWith(root + sep)) { res.writeHead(403).end(); return; }
  try {
    res.setHeader("Content-Type", ({".mjs":"text/javascript", ".js":"text/javascript", ".wasm":"application/wasm", ".css":"text/css", ".json":"application/json", ".webp":"image/webp"})[extname(file)] || "text/html; charset=utf-8");
    res.end(await readFile(file));
  } catch { res.writeHead(404).end(); }
});
await new Promise(done => server.listen(0, "127.0.0.1", done));
const browser = await chromium.launch({channel:"msedge", headless:true});
try {
  const page = await browser.newPage({viewport:{width:1440,height:1050}}), errors=[];
  page.on("pageerror", error => errors.push(error.message));
  await page.goto(`http://127.0.0.1:${server.address().port}/calculator/`);
  const waitResult = async () => {
    await page.waitForFunction(() => {
      const state = document.querySelector("#loadoutOptimizer").dataset.state;
      return state && state !== "searching";
    }, null, {timeout:35000});
    assert.ok(["optimal", "feasible"].includes(await page.locator("#loadoutOptimizer").getAttribute("data-state")), await page.locator("#loadoutOptimizer").textContent());
  };
  await waitResult();
  assert.equal(await page.locator("#combinationCalculator").getAttribute("open"), null);
  await page.locator('#toolDirectoryLinks a[href="#combinationCalculator"]').click();
  assert.equal(await page.locator("[data-combination-add]").isVisible(), true);
  await page.locator("[data-optimizer-apply]").click();
  assert.equal(await page.locator("#calcSortieCount").textContent(), "1");
  await page.locator('[data-optimizer-mode="targets"]').click();
  await waitResult();
  assert.match(await page.locator(".optimizer-metrics").textContent(), /可收 \d+ 个战区/);
  // Retain a user's guided bomb while filling the remaining points and its pod.
  await page.locator("#calcAircraftSearch").fill("a_10c");
  await page.locator('[data-aircraft-id="a_10c"]').click();
  await page.locator('[data-optimizer-mode="reward"]').click();
  await page.locator("[data-custom-open]").click();
  const custom = JSON.parse(await readFile(resolve(root,"api/v1/calculator/custom-loadouts.json")));
  const guided = custom.aircraft.a_10c.options.find(option => option.weapons.some(([id]) => id.includes("gbu_12")) && option.requires.some(relation => relation.preset === "sniper_pod"));
  await page.locator(`[data-custom-tier="${guided.tier}"]`).click();
  await page.locator(`[data-custom-option="${guided.key}"]`).click();
  await waitResult();
  assert.match(await page.locator("[data-optimizer-context]").textContent(), /保留已选 1 个挂点/);
  await page.locator("[data-optimizer-apply]").click();
  assert.equal(await page.locator(`[data-custom-tier="${guided.tier}"]`).getAttribute("data-custom-selected"), guided.key);
  assert.equal(await page.locator("[data-custom-save]").isEnabled(), true);
  assert.equal(await page.locator("#calcSortieCount").textContent(), "1");
  await waitResult();
  await mkdir("../.artifacts/calculator-ui", {recursive:true});
  for (const width of [1440,390]) {
    await page.setViewportSize({width,height:1050});
    await page.locator("#loadoutOptimizer").screenshot({path:`../.artifacts/calculator-ui/optimizer-${width}.png`,style:".site-header {visibility:hidden;}"});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
  }
  // Changing target hides this battle-zone tool and cancels its in-flight work.
  await page.locator('#calcTargetSegments [data-value="airport_storage"]').click();
  assert.equal(await page.locator("#loadoutOptimizer").isVisible(), false);
  await page.locator('#calcTargetSegments [data-value="bombing_point_planes"]').click();
  await page.locator('#calcBrSegments [role="radio"]').first().click();
  await page.locator('#calcBrSegments [role="radio"]').last().click();
  await waitResult();
  assert.match(await page.locator("[data-optimizer-context]").textContent(), /23,310 HP/);
  assert.deepEqual(errors,[]);
  console.log("Optimizer UI passed: folded tool, ordered navigation, both objectives, locked guided store, native pod completion, apply, responsive layout and cancellation.");
} finally {await browser.close(); await new Promise(done => server.close(done));}
