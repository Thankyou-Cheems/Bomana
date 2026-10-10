import assert from "node:assert/strict";
import { readFile, mkdir } from "node:fs/promises";
import { createServer } from "node:http";
import { resolve, sep } from "node:path";
import { chromium } from "playwright-core";

const root = resolve("../docs");
const data = JSON.parse(await readFile(resolve(root, "api/v1/calculator/custom-loadouts.json"), "utf8"));
const weaponData = JSON.parse(await readFile(resolve(root, "api/v1/calculator/weapons.json"), "utf8"));
const weapons = new Map(weaponData.weapons.map(weapon => [weapon.id, weapon]));
const server = createServer(async (req, res) => {
  let path = decodeURIComponent(new URL(req.url, "http://localhost").pathname);
  if (path.endsWith("/")) path += "index.html";
  const file = resolve(root, `.${path}`);
  if (!file.startsWith(root + sep)) { res.writeHead(403).end(); return; }
  try {
    const type = file.endsWith(".mjs") || file.endsWith(".js") ? "text/javascript" : file.endsWith(".wasm") ? "application/wasm" : file.endsWith(".css") ? "text/css" : file.endsWith(".webp") ? "image/webp" : file.endsWith(".json") ? "application/json" : "text/html; charset=utf-8";
    res.setHeader("Content-Type", type); res.end(await readFile(file));
  } catch { res.writeHead(404).end(); }
});
await new Promise(done => server.listen(0, "127.0.0.1", done));
const url = `http://127.0.0.1:${server.address().port}/calculator/`;
const browser = await chromium.launch({channel: "msedge", headless: true});
try {
  const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
  const errors = []; page.on("pageerror", error => errors.push(error.message));
  await page.goto(url);
  await page.locator('#calcPresetList [data-preset-id="pe-8_fab5000"]').waitFor();
  assert.equal(await page.locator("[data-custom-open]").isVisible(), false);
  const chooseAircraft = async id => {
    await page.locator("#calcAircraftSearch").fill(id);
    await page.locator(`[data-aircraft-id="${id}"]`).click();
    await page.locator("[data-custom-body]").waitFor();
    assert.ok(await page.locator('[data-custom-selected]:not([data-custom-selected=""])').count(), 'The selected preset is present in the current editor');
    await page.locator(".current-loadout-clear").click();
    assert.equal(await page.locator('[data-custom-selected]:not([data-custom-selected=""])').count(), 0, 'Clear removes every current store');
    assert.equal(await page.locator('#calcSortieCount').textContent(), '—', 'Clear does not use the previous preset for calculations');
    if (await page.locator('.current-loadout-options').getAttribute('open') === null) await page.locator('.current-loadout-options > summary').click();
  };
  await chooseAircraft("a_10c");
  await page.locator("[data-custom-body]").waitFor();
  const aircraft = data.aircraft.a_10c;
  const guided = aircraft.options.find(row => row.weapons.some(([id]) => id.includes("gbu_12")) && row.requires.some(item => item.preset === "sniper_pod"));
  assert.ok(guided);
  const slot = page.locator(`[data-custom-tier="${guided.tier}"]`);
  const picker = page.locator("[data-custom-picker]");
  await slot.click();
  assert.equal(await picker.isVisible(), true);
  assert.equal(await page.locator("[data-custom-option]").count(), aircraft.options.filter(option => option.tier === guided.tier).length + 1);
  assert.ok(await page.locator(`[data-custom-option="${guided.key}"] img`).count());
  await page.locator("[data-custom-picker-search]").fill("GBU-12");
  assert.equal(await page.locator(`[data-custom-option="${guided.key}"]`).isVisible(), true);
  await page.locator("[data-custom-picker-search]").fill("no-such-weapon-987654");
  assert.equal(await page.locator("[data-custom-option]").count(), 1);
  await page.keyboard.press("Escape");
  await picker.waitFor({state: "hidden"});
  assert.equal(await picker.isVisible(), false);
  assert.equal(await slot.evaluate(node => node === document.activeElement), true);
  await slot.click();
  await page.locator(`[data-custom-option="${guided.key}"]`).click();
  assert.equal(await picker.isVisible(), false);
  assert.equal(await slot.getAttribute("data-custom-selected"), guided.key);
  assert.ok(await slot.locator("img").count());
  assert.match(await page.locator("[data-custom-errors]").textContent(), /需在挂点.*配备/);
  assert.equal(await page.locator("[data-custom-save]").isDisabled(), true);
  assert.match(await page.locator("#calcHint").textContent(), /未通过挂载限制校验/);
  await page.locator("[data-custom-dependencies]").click();
  assert.equal(await page.locator("[data-custom-errors]").textContent(), "");
  assert.equal(await page.locator("[data-custom-save]").isEnabled(), true);
  const assertTotals = async (options, hp = 25900, hasFire = true) => {
    const damage = options.flatMap(option => option.weapons).reduce((sum, [id, count]) => sum + weapons.get(id).dmg * count, 0);
    const sorties = Math.ceil(hp * (hasFire ? .9 : 1) / damage);
    assert.equal(await page.locator("#calcDestroyCount").textContent(), String(sorties), "HUD uses all current stores before saving");
    assert.equal(await page.locator("#calcSortieCount").textContent(), String(sorties));
    assert.match(await page.locator("#calcDestroyLabel").textContent(), /次出击/);
  };
  await assertTotals([guided]);
  assert.match(await page.locator("#calcPresetTitle").textContent(), /自定义挂载/);
  const extra = aircraft.options.find(option => option.tier !== guided.tier && !guided.requires.some(relation => relation.slot === option.slot)
    && option.weapons.some(([id, count]) => id.includes("mk_82") && count === 1) && !option.requires.length && !option.bans.length);
  assert.ok(extra);
  await page.locator(`[data-custom-tier="${extra.tier}"]`).click();
  await page.locator(`[data-custom-option="${extra.key}"]`).click();
  await assertTotals([guided, extra]);
  await page.locator('#calcTargetSegments [data-value="airport_storage"]').click();
  await assertTotals([guided, extra], 160000, false);
  await page.locator('#calcBrSegments [role="radio"]').first().click();
  await assertTotals([guided, extra], 12000, false);
  await page.locator('#calcTargetSegments [data-value="bombing_point_planes"]').click();
  await page.locator('#calcBrSegments [role="radio"]').last().click();
  await page.locator("[data-custom-name]").fill("制导炸弹与吊舱");
  await page.locator("[data-custom-save]").click();
  assert.match(await page.locator("#calcPresetTitle").textContent(), /制导炸弹与吊舱/);
  assert.equal(await page.locator('#calcPresetList [data-preset-id^="user:"]').count(),0, 'native grid excludes saved custom loadouts');
  await assertTotals([guided, extra]);
  await page.locator('[data-preset-id="a_10c_mk82_default"]').click();
  assert.doesNotMatch(await page.locator("#calcDestroyLabel").textContent(), /次出击/);
  if (await page.locator('.custom-saved').getAttribute('open') === null) await page.locator('.custom-saved summary').click();
  await page.getByRole('button',{name:'制导炸弹与吊舱',exact:true}).click();
  await assertTotals([guided, extra]);
  await page.locator("#combinationCalculator > summary").click();
  await page.locator("[data-combination-preset]").click();
  assert.match(await page.locator("[data-combination-result]").textContent(), /完整摧毁轮次\d+ 轮/);
  await page.reload();
  await page.locator('#calcPresetList [data-preset-id="pe-8_fab5000"]').waitFor();
  await chooseAircraft("a_10c"); await page.locator("[data-custom-body]").waitFor();
  await page.locator(".custom-saved summary").click();
  await page.getByRole("button", {name: "制导炸弹与吊舱", exact: true}).click();
  assert.equal(await slot.getAttribute("data-custom-selected"), guided.key);
  assert.equal(await page.locator("[data-custom-save]").isEnabled(), true);
  await assertTotals([guided, extra]);
  // Editable presets can hold no strike weapon; that must not crash selection.
  await page.locator("[data-custom-new]").click();
  assert.equal(await page.locator("#calcDestroyCount").textContent(), "—");
  assert.equal(await page.locator("#calcSortieCount").textContent(), "—");
  await page.locator("[data-custom-name]").fill("空载"); await page.locator("[data-custom-save]").click();
  assert.equal(await page.locator("#calcPresetTitle").textContent(), "未挂载");
  await page.getByRole("button", {name: "删除挂载 空载", exact: true}).click();
  await page.getByRole("button", {name: "制导炸弹与吊舱", exact: true}).click();
  const out = resolve("../.artifacts/calculator-ui"); await mkdir(out, {recursive: true});
  for (const width of [1440, 390]) {
    await page.setViewportSize({width, height: 1050});
    await page.locator("[data-custom-body]").scrollIntoViewIfNeeded();
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, `overflow ${width}`);
    await page.screenshot({path: resolve(out, `custom-loadout-${width}.png`)});
    await slot.click();
    assert.equal(await picker.evaluate(node => node.scrollWidth > node.clientWidth), false, `dialog overflow ${width}`);
    await page.screenshot({path: resolve(out, `custom-picker-${width}.png`)});
    await page.locator("[data-custom-picker-close]").click();
  }
  await slot.click();
  await page.locator('[data-custom-option=""]').click();
  assert.equal(await slot.getAttribute("data-custom-selected"), "");
  await assertTotals([extra]);
  // Long catalogs must scroll inside the window, keeping the close control reachable.
  const busiestTier = Array.from({length: aircraft.columns}, (_, tier) => ({tier, count: aircraft.options.filter(option => option.tier === tier).length})).sort((a, b) => b.count - a.count)[0].tier;
  await page.setViewportSize({width: 390, height: 700});
  await page.locator(`[data-custom-tier="${busiestTier}"]`).click();
  assert.equal(await picker.evaluate(node => {
    const rect = node.getBoundingClientRect();
    return rect.top >= 0 && rect.bottom <= innerHeight;
  }), true);
  assert.equal(await page.locator("[data-custom-picker-options]").evaluate(node => node.scrollHeight > node.clientHeight), true);
  await page.locator("[data-custom-option]").last().scrollIntoViewIfNeeded();
  assert.equal(await page.locator("[data-custom-picker-close]").evaluate(node => {
    const rect = node.getBoundingClientRect();
    return rect.top >= 0 && rect.bottom <= innerHeight;
  }), true);
  await page.locator("[data-custom-option]").last().click();
  await picker.waitFor({state: "hidden"});
  // Reproduce the reported Typhoon mixed-loadout: 8 stores plus a targeting pod.
  await page.setViewportSize({width: 1440, height: 1050});
  await chooseAircraft("ef_2000_typhoon_aesa");
  await page.locator("[data-custom-body]").waitFor();
  const typhoon = data.aircraft.ef_2000_typhoon_aesa;
  const reported = ["11:mk18_slot11", "10:paveway_iv_slot10_x2", "7:litening", "4:epv2_mk13_slot4", "3:brimstone_dm_slot3", "2:500lbs_gbu_54b_slot2"]
    .map(key => typhoon.options.find(option => option.key === key));
  assert.ok(reported.every(Boolean));
  for (const option of reported) {
    await page.locator(`[data-custom-tier="${option.tier}"]`).click();
    await page.locator(`[data-custom-option="${option.key}"]`).click();
  }
  await assertTotals(reported);
  assert.equal(await page.locator("#calcSortieCount").textContent(), "2");
  assert.match(await page.locator("#calcPresetStats").textContent(), /19,359 HP/);
  for (const [mode, hp, rounds] of [["legacy_rb", 12000, "1"], ["legacy_ab", 50400, "3"], ["respawning", 25900, "2"]]) {
    await page.locator(`#calcBaseModeSegments [data-value="${mode}"]`).click();
    await assertTotals(reported, hp);
    assert.equal(await page.locator("#calcSortieCount").textContent(), rounds);
    for (const option of reported) assert.equal(await page.locator(`[data-custom-tier="${option.tier}"]`).getAttribute("data-custom-selected"), option.key);
  }
  assert.equal(await page.locator("[data-custom-save]").isEnabled(), true);
  await page.locator("[data-custom-save]").click();
  await assertTotals(reported);
  await page.locator(".hangar-hud").screenshot({path: resolve(out, "custom-total-typhoon.png"), style: "bomana-site-header { visibility:hidden; }"});
  // Missing damage for one store must not silently calculate from the others.
  await page.route("**/weapons.json", route => route.fulfill({contentType: "application/json", body: JSON.stringify({
    ...weaponData, weapons: weaponData.weapons.map(weapon => weapon.id === "fr_mk18" ? {...weapon, dmg: null} : weapon),
  })}));
  await page.reload();
  await page.locator('#calcPresetList [data-preset-id="pe-8_fab5000"]').waitFor();
  await chooseAircraft("ef_2000_typhoon_aesa");
  await page.locator("[data-custom-body]").waitFor();
  await page.locator(".custom-saved summary").click();
  await page.getByRole("button", {name: "自定义挂载", exact: true}).last().click();
  assert.equal(await page.locator("#calcSortieCount").textContent(), "—");
  assert.match(await page.locator("#calcHint").textContent(), /缺少伤害数据/);
  await page.unroute("**/weapons.json");
  await page.locator("#calcAircraftSearch").fill("");
  await page.locator("#calcCustomOnly").click();
  assert.equal(await page.locator("#calcCustomOnly").getAttribute("aria-pressed"), "true");
  const customAircraftIds = await page.locator("#calcAircraftList [data-aircraft-id]").evaluateAll(nodes => nodes.map(node => node.dataset.aircraftId));
  assert.ok(customAircraftIds.length > 0);
  assert.ok(customAircraftIds.every(id => id in data.aircraft), 'Custom-only results all have a custom-loadout definition');
  assert.equal(new Set(customAircraftIds).size, customAircraftIds.length, 'Custom-only results contain no duplicate aircraft IDs');
  if (await page.locator('#calcIndividualWeapons').getAttribute('open') === null) await page.locator('#calcIndividualWeapons > summary').click();
  await page.locator('#calcSearch').fill('');
  await page.locator('#calcWeaponList [data-weapon-id]').first().click();
  assert.equal(await page.locator('.current-loadout-options').isVisible(), false, 'switching to a single weapon hides the previous loadout save/configuration details');
  // A stale CDN response must not be combined with the current calculator.
  const retryPage = await browser.newPage();
  retryPage.on("pageerror", error => errors.push(error.message));
  await retryPage.route("**/custom-loadouts.json", route => route.fulfill({
    contentType: "application/json", body: JSON.stringify({...data, source: {...data.source, version: "0.0.0"}}),
  }));
  await retryPage.goto(url);
  await retryPage.locator('#calcPresetList [data-preset-id="pe-8_fab5000"]').waitFor();
  await retryPage.locator("#calcAircraftSearch").fill("a_10c");
  await retryPage.locator('[data-aircraft-id="a_10c"]').click();
  await retryPage.locator("[data-custom-open]").click();
  await retryPage.waitForFunction(() => document.querySelector("[data-custom-status]").textContent.includes("请重试"));
  assert.equal(await retryPage.locator("[data-custom-body]").isVisible(), false);
  await retryPage.unroute("**/custom-loadouts.json");
  await retryPage.locator("[data-custom-open]").click();
  await retryPage.locator("[data-custom-body]").waitFor();
  // Browser storage can be blocked while the current editor remains usable.
  await retryPage.evaluate(() => { Storage.prototype.setItem = () => { throw new DOMException("blocked", "SecurityError"); }; });
  await retryPage.locator('.current-loadout-options > summary').click();
  await retryPage.locator("[data-custom-save]").click();
  assert.match(await retryPage.locator("[data-custom-notice]").textContent(), /本次页面有效/);
  await retryPage.close();
  assert.deepEqual(errors, []);
  console.log("Custom loadout UI passed: live total damage, mixed Typhoon regression, target/BR changes, saved/empty/unknown stores, icon picker, required pod, desktop/mobile, stale-source retry and blocked storage.");
} finally { await browser.close(); await new Promise(done => server.close(done)); }
