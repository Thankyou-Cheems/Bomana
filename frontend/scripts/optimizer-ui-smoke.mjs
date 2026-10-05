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
  const applyRecommendation = async () => {
    const apply = page.locator('[data-optimizer-apply]');
    if (await apply.isEnabled()) await page.locator('[data-optimizer-preset]').click();
    assert.equal(await page.locator('#loadoutOptimizer').getAttribute('data-applied'), 'true', 'The recommendation is the current loadout');
  };
  await waitResult();
  const guidedOnly = page.locator('[data-optimizer-guided-only]');
  const guidanceFilters = ['noLaser', 'noOptical', 'noSatellite'];
  await guidedOnly.click();
  for (const key of guidanceFilters) await page.locator(`[data-optimizer-filter="${key}"]`).click();
  assert.equal(await guidedOnly.getAttribute('aria-checked'), 'false', 'Excluding the last guidance family exits guided-only mode');
  for (const key of guidanceFilters) assert.equal(await page.locator(`[data-optimizer-filter="${key}"]`).getAttribute('aria-checked'), 'false');
  await guidedOnly.click();
  for (const key of guidanceFilters) assert.equal(await page.locator(`[data-optimizer-filter="${key}"]`).getAttribute('aria-checked'), 'true', 'Guided-only restores guidance families when all were excluded');
  await guidedOnly.click();
  await waitResult();
  assert.equal(await page.locator('[data-optimizer-priority][value="balanced"]').isChecked(), true);
  assert.equal(await page.locator('[data-optimizer-filter="noRockets"]').getAttribute('aria-checked'), 'true');
  await page.locator('[data-optimizer-filter="noRockets"]').click();
  assert.equal(await page.locator('[data-optimizer-filter="noRockets"]').getAttribute('aria-checked'), 'false');
  await waitResult();
  await page.locator('[data-optimizer-filter="noRockets"]').click();
  await page.locator('.optimizer-priority label:has([value="reward"])').click();
  await waitResult();
  assert.equal(await page.locator('[data-optimizer-priority][value="reward"]').isChecked(), true);
  await page.locator('.optimizer-priority label:has([value="balanced"])').click();
  await waitResult();
  assert.equal(await page.locator("#combinationCalculator").getAttribute("open"), null);
  await page.locator('#toolDirectoryLinks a[href="#combinationCalculator"]').click();
  assert.equal(await page.locator("[data-combination-add]").isVisible(), true);
  await applyRecommendation();
  assert.equal(await page.locator("#calcSortieCount").textContent(), "1");
  for (const [mode, hp] of [["legacy_ab", "50,400"], ["legacy_rb", "12,000"], ["respawning", "25,900"]]) {
    await page.locator(`#calcBaseModeSegments [data-value="${mode}"]`).click();
    await waitResult();
    await applyRecommendation();
    assert.match(await page.locator("#calcStats").textContent(), new RegExp(`目标耐久${hp}`));
    assert.equal(await page.locator("#calcSortieCount").textContent(), "1");
  }
  await page.locator('[data-optimizer-mode="targets"]').click();
  await waitResult();
  assert.match(await page.locator(".optimizer-metrics").textContent(), /可收 \d+ 个战区/);
  // Retain a user's guided bomb while filling the remaining points and its pod.
  await page.locator("#calcAircraftSearch").fill("a_10c");
  await page.locator('[data-aircraft-id="a_10c"]').click();
  await page.locator('[data-optimizer-mode="reward"]').click();
  await page.locator("[data-custom-body]").waitFor();
  await page.locator(".current-loadout-clear").click();
  const custom = JSON.parse(await readFile(resolve(root,"api/v1/calculator/custom-loadouts.json")));
  const guided = custom.aircraft.a_10c.options.find(option => option.weapons.some(([id]) => id.includes("gbu_12")) && option.requires.some(relation => relation.preset === "sniper_pod"));
  await page.locator(`[data-custom-tier="${guided.tier}"]`).click();
  await page.locator(`[data-custom-option="${guided.key}"]`).click();
  await waitResult();
  assert.match(await page.locator("[data-optimizer-context]").textContent(), /保留已选 1 个挂点/);
  await page.locator('.optimizer-priority label:has([value="simple"])').click();
  await waitResult();
  assert.equal(await page.locator('[data-optimizer-priority][value="simple"]').isChecked(), true);
  await page.locator("[data-optimizer-apply]").click();
  assert.equal(await page.locator(`[data-custom-tier="${guided.tier}"]`).getAttribute("data-custom-selected"), guided.key);
  assert.equal(await page.locator("[data-custom-save]").isEnabled(), true);
  assert.equal(await page.locator("#calcSortieCount").textContent(), "1");
  await waitResult();
  await mkdir("../.artifacts/calculator-ui", {recursive:true});
  for (const width of [1440,390,320]) {
    await page.setViewportSize({width,height:1050});
    await page.locator("#loadoutOptimizer").screenshot({path:`../.artifacts/calculator-ui/optimizer-${width}.png`,style:"bomana-site-header {visibility:hidden;}"});
    await page.locator('.loadout-workspace').screenshot({path:`../.artifacts/calculator-ui/loadout-layout-${width}.png`,style:"bomana-site-header {visibility:hidden;}"});
    for (const selector of ['.hangar-hud', '#loadoutOptimizer', '#calcAircraftSearch', '#calcPresetPanel']) {
      assert.equal(await page.locator(selector).isVisible(), true, `${width}: ${selector} remains usable`);
    }
    if (width === 1440) {
      const summary = await Promise.all(['.hangar-result-primary','.hangar-sorties','.loadout-reward'].map(selector => page.locator(selector).boundingBox()));
      assert.ok(summary.every(box => Math.abs(box.y - summary[0].y) < 20), 'key settlement values share one horizontal strip');
    }
    assert.equal(await page.locator('.optimizer-zone-plan > [data-plan-zone="1"]').isVisible(), true);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
  }
  // Airport targets retain score recommendations; battle-zone objectives are hidden.
  await page.locator('#calcTargetSegments [data-value="airport_storage"]').click();
  assert.equal(await page.locator("#loadoutOptimizer").isVisible(), true);
  assert.equal(await page.locator("#loadoutOptimizer").getAttribute("data-objective"), "sim_score");
  for (const mode of ["reward", "targets"]) {
    assert.equal(await page.locator(`[data-optimizer-mode="${mode}"]`).isVisible(), false);
  }
  await waitResult();
  assert.match(await page.locator("[data-optimizer-result]").textContent(), /全挂载预计.*分/);
  await page.locator('#calcTargetSegments [data-value="bombing_point_planes"]').click();
  await page.locator('[data-optimizer-mode="reward"]').click();
  await page.locator('#calcBrSegments [role="radio"]').first().click();
  await page.locator('#calcBrSegments [role="radio"]').last().click();
  await waitResult();
  assert.match(await page.locator("[data-optimizer-status]").textContent(), /推荐配置|可用配置/);
  // A locked Hydra rack keeps rocket-only completion in the simple preference.
  // The visible plan must give projectile counts, rather than rack counts.
  await page.locator('[data-custom-new]').click();
  await page.locator('#calcBrSegments [role="radio"]').first().click();
  const rockets = custom.aircraft.a_10c.options.find(option => option.weapons.some(([id,count]) => id === 'us_hydra_70_m247' && count === 21));
  await page.locator(`[data-custom-tier="${rockets.tier}"]`).click();
  await page.locator(`[data-custom-option="${rockets.key}"]`).click();
  await waitResult();
  const weaponCatalog = JSON.parse(await readFile(resolve(root,'api/v1/calculator/weapons.json')));
  const hydra = weaponCatalog.weapons.find(weapon => weapon.id === 'us_hydra_70_m247');
  const hp = Number((await page.locator('#calcBrSegments [aria-checked="true"]').textContent()).match(/([\d,]+) HP/)[1].replaceAll(',',''));
  const shots = Math.ceil(hp * .9 / hydra.dmg);
  const rocketRow = page.locator('.optimizer-zone-plan > [data-plan-zone="1"] [data-weapon-id="us_hydra_70_m247"]');
  assert.equal(Number(await rocketRow.getAttribute('data-projectile-count')), shots);
  assert.match(await rocketRow.textContent(), new RegExp(`\\b${shots}\\b`));
  await page.locator('[data-optimizer-mode="targets"]').click();
  await waitResult();
  assert.ok(await page.locator('.optimizer-zone-plan > [data-plan-zone]').count() > 1);
  for (const zone of await page.locator('.optimizer-zone-plan > [data-plan-zone]').all()) {
    assert.equal(await zone.isVisible(),true);
    const rows = await zone.locator('[data-projectile-count]').evaluateAll(elements => elements.map(element => ({id:element.dataset.weaponId,count:Number(element.dataset.projectileCount),text:element.textContent})));
    assert.ok(rows.length > 0);
    assert.ok(rows.every(row => Number.isInteger(row.count) && row.count > 0 && new RegExp(`\\b${row.count}\\b`).test(row.text)));
    assert.ok(rows.reduce((sum,row) => sum + weaponCatalog.weapons.find(weapon => weapon.id === row.id).dmg * row.count,0) >= hp * .9);
  }
  const illustrated = await page.locator('.optimizer-slot-shares [data-projectile-count]').evaluateAll(nodes => nodes.map(node => ({zone:node.dataset.planZone,id:node.dataset.weaponId,count:Number(node.dataset.projectileCount),color:getComputedStyle(node).backgroundColor})));
  const planned = await page.locator('.optimizer-zone-plan [data-projectile-count]').evaluateAll(nodes => nodes.map(node => ({zone:node.closest('[data-plan-zone]').dataset.planZone,id:node.dataset.weaponId,count:Number(node.dataset.projectileCount)})));
  for (const item of planned) {
    assert.equal(illustrated.filter(share => share.zone === item.zone && share.id === item.id).reduce((sum,share) => sum + share.count,0), item.count, 'Rack allocation matches the zone delivery plan exactly');
  }
  const zoneColors = new Map(illustrated.map(share => [share.zone,share.color]));
  assert.equal(new Set(zoneColors.values()).size, zoneColors.size, 'Each zone has a distinct visible color');
  await page.locator('#loadoutOptimizer').screenshot({path:'../.artifacts/calculator-ui/rocket-zone-plan.png',style:'bomana-site-header {visibility:hidden;}'});
  assert.deepEqual(errors,[]);
  console.log("Optimizer UI passed: ordered settlement/recommendation/editor/native panels, positive store filters, reward preferences, visible zone plans, both objectives, user locks, apply, desktop/mobile layout and cancellation.");
} finally {await browser.close(); await new Promise(done => server.close(done));}
