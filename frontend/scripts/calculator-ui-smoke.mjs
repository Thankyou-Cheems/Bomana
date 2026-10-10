import assert from "node:assert/strict";
import { mkdir, readFile } from "node:fs/promises";
import { createServer } from "node:http";
import { resolve, sep } from "node:path";
import { chromium } from "playwright-core";

const root = resolve("../docs");
const remote = process.env.BOMANA_CALCULATOR_TEST_URL;
const site = createServer(async (request, response) => {
  let pathname = decodeURIComponent(new URL(request.url, "http://localhost").pathname);
  if (pathname.endsWith("/")) pathname += "index.html";
  const file = resolve(root, `.${pathname}`);
  if (!file.startsWith(root + sep)) { response.writeHead(403).end(); return; }
  try {
    const bytes = await readFile(file);
    const extension = file.slice(file.lastIndexOf("."));
    response.setHeader("Content-Type", ({ ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".mjs": "text/javascript", ".wasm": "application/wasm", ".css": "text/css", ".json": "application/json", ".webp": "image/webp", ".svg": "image/svg+xml" })[extension] || "application/octet-stream");
    response.end(bytes);
  } catch { response.writeHead(404).end(); }
});
if (!remote) await new Promise(resolve => site.listen(0, "127.0.0.1", resolve));
const url = remote || `http://127.0.0.1:${site.address().port}/calculator/`;
const browser = await chromium.launch({ channel: "msedge", headless: true });
const errors = [];
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1050 } });
  page.on("pageerror", error => errors.push(error.message));
  await page.goto(url);
  await page.waitForFunction(() => document.querySelector("#chargeWeaponA").options.length > 600);
  await page.waitForFunction(() => document.querySelector("#airCompare button") !== null);
  await page.waitForFunction(() => document.querySelector("#calcPresetList [data-preset-id]") !== null);
  assert.equal(await page.locator('.hangar-result-primary').isVisible(),true,'Native single-weapon loadouts retain their required projectile count');
  const open = async id => { if (!await page.locator(id).getAttribute("open").then(value => value !== null)) await page.locator(`${id} > summary`).click(); };
  const close = async id => { if (await page.locator(id).getAttribute("open").then(value => value !== null)) await page.locator(`${id} > summary`).click(); };
  const text = selector => page.locator(selector).textContent();
  // The same selected Pe-8 FAB-50 preset must recalculate against each native rule.
  for (const [mode, hitPoints, count] of [["legacy_rb", "12,000", "10"], ["legacy_ab", "50,400", "40"], ["respawning", "25,900", "21"]]) {
    await page.locator(`#calcBaseModeSegments [data-value="${mode}"]`).click();
    assert.match(await text("#calcStats"), new RegExp(`目标耐久${hitPoints}`));
    assert.equal(await text("#calcDestroyCount"), count);
    assert.equal(await page.locator('#calcBaseModeSegments [aria-checked="true"]').count(), 1);
  }
  await page.locator('#calcBaseModeSegments [data-value="legacy_ab"]').click();
  for (const [index, hp] of [[0, "15,000"], [1, "25,600"], [2, "32,000"], [3, "50,400"]]) {
    await page.locator('#calcBrSegments [role="radio"]').nth(index).click();
    assert.match(await text("#calcStats"), new RegExp(`目标耐久${hp}`));
  }
  await page.locator('#calcBaseModeSegments [data-value="legacy_rb"]').focus();
  await page.keyboard.press("Home");
  assert.equal(await page.locator("#calcBaseMode").inputValue(), "respawning");
  // A wide legacy bracket must not promote a previously selected BR on return.
  await page.locator('#calcBrSegments [data-value="6.3"]').click();
  await page.locator('#calcBaseModeSegments [data-value="legacy_rb"]').click();
  assert.equal(await page.locator("#calcBr").inputValue(), "14.7");
  await page.locator('#calcBaseModeSegments [data-value="respawning"]').click();
  assert.equal(await page.locator("#calcBr").inputValue(), "6.3");
  assert.match(await text("#calcStats"), /目标耐久16,000/);
  await page.locator('#calcBrSegments [role="radio"]').last().click();
  assert.equal(await page.locator("#combinationCalculator").getAttribute("open"), null);
  const directoryTargets = await page.locator("#toolDirectoryLinks a").evaluateAll(links => links.map(link => ({hash: link.hash, exists: Boolean(document.querySelector(link.hash))})));
  assert.ok(directoryTargets.every(target => target.exists), 'Every grouped shortcut reaches an existing tool');
  assert.equal(new Set(directoryTargets.map(target => target.hash)).size, directoryTargets.length, 'Tool shortcuts are not duplicated');
  await page.locator("#calcAircraftSearch").fill("taif");
  for (const id of ["ef_2000_aesa", "ef_2000_fgr4", "ef_2000a", "typhoon_mk1a"]) {
    assert.equal(await page.locator(`[data-aircraft-id="${id}"]`).count(), 1);
  }
  await page.locator("#calcAircraftSearch").fill("");
  // Both segmented sliders choose exactly one context and support keyboard navigation.
  assert.equal(await page.locator('#calcTargetSegments [aria-checked="true"]').count(), 1);
  await page.locator('#calcTargetSegments [data-value="airport_storage"]').click();
  assert.equal(await page.locator("#calcTarget").inputValue(), "airport_storage");
  assert.equal(await page.locator("#calcRepairNote").isVisible(), true);
  assert.equal(await page.locator("#calcBaseModeControl").isVisible(), false);
  await page.locator('#calcBrSegments [role="radio"]').first().click();
  const lowBr = await page.locator("#calcBr").inputValue();
  await page.keyboard.press("End");
  assert.notEqual(await page.locator("#calcBr").inputValue(), lowBr);
  assert.equal(await page.locator('#calcBrSegments [aria-checked="true"]').count(), 1);
  await page.locator('#calcTargetSegments [data-value="bombing_point_planes"]').click();
  assert.equal(await page.locator("#calcRepairNote").isVisible(), false);
  assert.equal(await page.locator("#calcBaseModeControl").isVisible(), true);
  await page.locator('#calcBrSegments [role="radio"]').last().click();
  // Game font code points must not leak into browser aircraft labels.
  await page.locator("#calcAircraftSearch").fill("a_4e_early_iaf");
  assert.doesNotMatch(await text("#calcAircraftList"), /[\uF059\u2580-\u2585\u2417]/u);
  assert.match(await text("#calcAircraftList"), /🇮🇱/u);
  await page.locator("#calcAircraftSearch").fill("");
  assert.equal(await page.locator("#calcPresetList [data-preset-id]").count(), 6);
  await page.locator('[data-preset-id="pe-8_fab5000"]').click();
  assert.match(await text("#calcPresetTitle"), /FAB-5000.*×1/);
  assert.doesNotMatch(await text("#calcStats"), /预设携带|预计出击|武器/);
  assert.equal(await page.locator("#calcHint").isVisible(), false);
  assert.equal(await page.locator('#calcWeaponList [aria-selected="true"]').getAttribute("data-weapon-id"), "su_fab5000");
  assert.equal(await page.locator('#calcPresetList [aria-selected="true"] .ordnance-icon').count(), 1);
  assert.equal(await page.locator('#calcPresetList [aria-selected="true"] .ordnance-icon').getAttribute("data-icon"), "bombs_heavy");
  await page.locator('#calcPresetList [aria-selected="true"]').focus();
  await page.keyboard.press("Home");
  assert.match(await text("#calcPresetTitle"), /×40/);
  assert.doesNotMatch(await text("#calcPresetStats"), /对地弹药|整套投放轮次/);
  assert.match(await text("#calcPresetStats"), /整套伤害45,440 HP/);
  assert.equal(await page.locator('#calcPresetList [aria-selected="true"] .ordnance-icon').count(), 10);
  assert.equal(await page.locator('#calcPresetList [aria-selected="true"] .ordnance-icon').first().getAttribute("data-icon"), "bombs_small_group_x4");
  // Filtering available presets must not discard the current loadout or its settlement.
  const selectedPresetBeforeSearch = await page.locator('#calcPresetList [aria-selected="true"]').getAttribute("data-preset-id");
  const currentLoadout = async () => ({
    title: await text("#calcPresetTitle"),
    stats: await text("#calcPresetStats"),
    destroyCount: await text("#calcDestroyCount"),
    sortieCount: await text("#calcSortieCount"),
    rewardCount: await text("#calcRewardCount"),
  });
  const loadoutBeforeSearch = await currentLoadout();
  await page.locator("#calcSearch").fill("not-a-real-loadout-12345");
  assert.equal(await page.locator("#calcPresetList [data-preset-id]").count(), 0);
  assert.equal(await page.locator("#calcPresetDetail").isVisible(), true);
  assert.deepEqual(await currentLoadout(), loadoutBeforeSearch);
  await page.locator("#calcSearch").fill("");
  assert.equal(await page.locator('#calcPresetList [aria-selected="true"]').getAttribute("data-preset-id"), selectedPresetBeforeSearch);
  assert.equal(await page.locator("#calcPresetDetail").isVisible(), true);
  assert.deepEqual(await currentLoadout(), loadoutBeforeSearch);
  await page.locator('[data-preset-id="pe-8_12xfab250"]').click();
  await page.locator(".ordnance-icon").evaluateAll(images => Promise.all(images.map(image => image.decode())));
  await mkdir("../.artifacts/calculator-ui", { recursive: true });
  for (const [width, height] of [[1440, 1050], [390, 844], [320, 568]]) {
    await page.setViewportSize({ width, height });
    if (width < 1280) {
      assert.equal(await page.locator("#toolDirectoryLinks").isVisible(), false);
      await page.locator("#toolDirectoryToggle").click();
      await page.locator('#toolDirectoryLinks a[href="#airportStatus"]').click();
      assert.equal(await page.locator("#toolDirectoryLinks").isVisible(), false);
      assert.equal(new URL(page.url()).hash, "#airportStatus");
      await page.locator("#toolDirectoryToggle").click();
      await page.keyboard.press("Escape");
      assert.equal(await page.locator("#toolDirectoryToggle").getAttribute("aria-expanded"), "false");
    } else assert.equal(await page.locator("#toolDirectoryLinks").isVisible(), true);
    await page.locator('#calcBrSegments [role="radio"]').last().click();
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: `../.artifacts/calculator-ui/overview-${width}.png` });
    await page.locator("#calcAircraftSearch").fill("f-16");
    await page.locator(".loadout-summary").screenshot({ path: `../.artifacts/calculator-ui/aircraft-search-${width}.png` });
    await page.locator("#calcAircraftSearch").fill("");
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `${width}: loadout horizontal overflow`);
    await page.locator(".loadout-workspace").screenshot({ path: `../.artifacts/calculator-ui/loadout-${width}.png`, style: "bomana-site-header { visibility: hidden; }" });
  }
  await page.setViewportSize({ width: 1440, height: 1050 });
  await page.locator("#calcAircraftSearch").fill("f_15e");
  await page.locator('[data-aircraft-id="f_15e"]').click();
  await page.locator('[data-preset-id="f_15e_mk82"]').click();
  assert.match(await text("#calcPresetTitle"), /×24/);
  assert.equal(await page.locator('#calcPresetList [aria-selected="true"] [data-icon="bombs_middle_group_x6"]').count(), 4);
  assert.ok(await page.locator('#calcPresetList [aria-selected="true"] .loadout-cell').evaluateAll(cells => cells.every(cell => cell.querySelectorAll(".ordnance-icon").length <= 1)));
  await page.locator("#calcAircraftSearch").fill("a-20g");
  await page.locator('[data-aircraft-id="a-20g"]').click();
  await page.locator('[data-preset-id="a20g_2x250_2x500lb"]').click();
  const loadouts = JSON.parse(await readFile(resolve(root, "api/v1/calculator/loadouts.json"), "utf8"));
  const weaponData = JSON.parse(await readFile(resolve(root, "api/v1/calculator/weapons.json"), "utf8"));
  const mixed = loadouts.aircraft["a-20g"].find(row => row.id === "a20g_2x250_2x500lb");
  const mixedDamage = mixed.weapons.reduce((sum, [id, count]) => sum + weaponData.weapons.find(weapon => weapon.id === id).dmg * count, 0);
  assert.equal(await text("#calcDestroyCount"), String(Math.ceil(25900 * .9 / mixedDamage)));
  assert.equal(await text("#calcSortieCount"), String(Math.ceil(25900 * .9 / mixedDamage)));
  assert.match(await text("#calcDestroyLabel"), /次出击/);
  assert.doesNotMatch(await text("#calcStats"), /每枚伤害|所选弹药|末次所需/);
  assert.equal(await page.locator("#calcPresetWeapon").count(), 0);
  await page.locator('#calcTargetSegments [data-value="airport_storage"]').click();
  assert.equal(await text("#calcSortieCount"), String(Math.ceil(160000 / mixedDamage)));
  await page.locator('#calcBrSegments [role="radio"]').first().click();
  assert.equal(await text("#calcSortieCount"), String(Math.ceil(12000 / mixedDamage)));
  await page.locator('#calcTargetSegments [data-value="bombing_point_planes"]').click();
  await page.locator('#calcBrSegments [role="radio"]').last().click();
  await page.locator("#calcAircraftClear").click();
  await page.locator("#calcSearch").fill("Mk 83");
  await page.locator('#calcWeaponList [data-weapon-id="us_1000lb_mk_83_ldgp"]').click();
  assert.match(await text("#repairResult"), /完好.*参考规则不触发/);
  assert.equal(await page.locator("#repairChart .chart-current").getAttribute("data-repair-gain"), "0");
  assert.match(await text("#airportPalette"), /0%.*>0～25%.*>25～75%.*>75%/s);
  assert.match(await text("#airportPaletteSource"), /剩余耐久.*示意位置/);
  assert.equal(await page.locator("#airportDiagram").isVisible(), true);
  assert.equal(await page.locator("#airportDiagramReversed").isVisible(), true);
  assert.equal(await page.locator("#airportDiagram [data-module]").count(), 4);
  const checkOppositeEndpoints = async () => {
    const positions = await page.locator("#airportDiagramDetails .airport-reference").evaluateAll(containers => containers.map(container => {
      const svg = container.querySelector("svg"), cx = svg.viewBox.baseVal.width / 2, cy = svg.viewBox.baseVal.height / 2;
      return [...container.querySelectorAll("[data-module]")].map(bar => ({
        module: bar.dataset.module,
        x: (Number(bar.getAttribute("x1")) + Number(bar.getAttribute("x2"))) / 2 - cx,
        y: (Number(bar.getAttribute("y1")) + Number(bar.getAttribute("y2"))) / 2 - cy,
      }));
    }));
    positions[0].forEach((bar, index) => {
      assert.equal(positions[1][index].module, bar.module);
      assert.ok(Math.abs(bar.x + positions[1][index].x) < 1e-6);
      assert.ok(Math.abs(bar.y + positions[1][index].y) < 1e-6);
    });
  };
  await checkOppositeEndpoints();
  await page.locator('[data-airport-rotate="90"]').click();
  await checkOppositeEndpoints();
  for (let index = 0; index < 3; index++) await page.locator('[data-airport-rotate="90"]').click();
  assert.match(await text("#airportDiagramDetails"), /起终点相反.*180°.*起终点确实相反.*不是实时血量/s);
  await page.locator("#repairPercent").fill("0.9");
  assert.match(await text("#repairResult"), /不足 1%.*未达到.*修复门槛/);
  assert.equal(await page.locator("#repairChart .chart-current").getAttribute("data-repair-gain"), "0");
  await page.locator("#repairPercent").fill("1");
  assert.match(await text("#repairResult"), /400 HP/);
  await page.locator('[data-dwelling="50"]').click();
  assert.match(await text("#repairResult"), /2,000.03 HP/);
  assert.equal(await page.locator("#repairPercent").inputValue(), "50");
  await page.locator('[data-dwelling="0"]').click();
  assert.match(await text("#repairResult"), /停止/);
  await page.locator('[data-dwelling="100"]').click();
  assert.equal(await page.locator("#rewardVehicle").inputValue(), "f_15e");
  assert.match(await text("#rewardSource"), /客户端.*SL\/min.*不是 RP\/min/);
  assert.equal(await page.locator("#rewardFraction").isVisible(), false);
  assert.equal(await page.locator("#rewardSlRate").isVisible(), false);
  assert.equal(await page.locator("#chargeMassA").isVisible(), false);
  assert.equal(await page.locator("#chargeFactorB").isVisible(), false);
  assert.equal(await page.locator("#rewardChart svg").isVisible(), true);
  assert.match(await text(".reference-pill"), /2024.*历史/);
  assert.match(await text("#rewardResult"), /17,854.*4,463/s);
  assert.doesNotMatch(await text("#rewardResult"), /有效.*比例|SL\/min|即时 RP/);
  assert.match(await text("#rewardFormula"), /86.00%/);
  assert.equal(Number(await page.locator("#rewardChart .chart-current").getAttribute("data-immediate")), 1730 * 15 * .86 * .8);
  await page.locator(".score-presets [data-score='800']").click();
  assert.equal(await page.locator("#rewardScore").inputValue(), "800");
  assert.equal(await page.locator("#rewardScoreSlider").inputValue(), "800");
  assert.equal(await page.locator("#rewardChart .chart-current").getAttribute("data-score"), "800");
  await page.locator("#rewardScoreSlider").focus();
  await page.keyboard.press("ArrowLeft");
  assert.equal(await page.locator("#rewardScore").inputValue(), "775");
  assert.equal(await page.locator("#rewardChart .chart-current").getAttribute("data-score"), "775");
  await page.locator("#rewardScore").fill("600");
  await page.locator("#rewardAccount").selectOption("premium");
  assert.equal(await page.locator("#rewardSlRate").inputValue(), "2595");
  assert.match(await text("#rewardResult"), /26,780/);
  await open("#rewardAdvanced");
  await page.locator("#rewardBooster").fill("100");
  assert.match(await text("#rewardCardPreview"), /4,325 SL\/min/);
  assert.equal(await page.locator("#rewardSlRate").inputValue(), "4325");
  await page.locator("#rewardAccount").selectOption("regular");
  await page.locator("#rewardBooster").fill("0");
  await page.locator("#rewardManualRate").check();
  assert.equal(await page.locator("#rewardAccount").isDisabled(), true);
  await page.locator("#rewardSlRate").fill("");
  assert.match(await text("#rewardResult"), /大于 0 的 SL\/min/);
  assert.equal(await page.locator("#rewardResult dd").count(), 0);
  assert.equal(await page.locator("#rewardChart svg").count(), 0);
  await page.locator("#rewardManualRate").uncheck();
  assert.equal(await page.locator("#rewardSlRate").inputValue(), "1730");
  await page.locator("#rewardScore").fill("1500");
  assert.equal(await page.locator("#rewardResult dd").count(), 0);
  assert.match(await text("#rewardResult"), /不外推/);
  assert.equal(await page.locator("#rewardChart svg").count(), 1);
  assert.equal(await page.locator("#rewardChart .chart-current").count(), 0);
  await page.locator("#rewardScore").fill("600");
  await page.locator("#rewardMethod").selectOption("observed");
  await page.locator("#rewardManualRate").check();
  await page.locator("#rewardSlRate").fill("1000");
  await page.locator("#rewardObserved").fill("9600");
  assert.match(await text("#rewardFormula"), /80.00%.*600 分 → 9,600 即时 SL/s);
  assert.match(await text("#rewardResult"), /已即时到账/);
  assert.equal(await page.locator("#rewardChart svg").count(), 0);
  await page.locator("#rewardMinutes").fill("7.5");
  await page.locator("#rewardObserved").fill("4800");
  assert.match(await text("#rewardResult"), /不足整周期仅作算术核对/);
  await page.locator("#rewardMinutes").fill("15");
  await page.locator("#rewardObserved").fill("20000");
  assert.match(await text("#rewardResult"), /超过 100%/);
  assert.equal(await page.locator("#rewardResult dd").count(), 0);
  await page.locator("#rewardMode").selectOption("heli_pve");
  assert.equal(await page.locator("#rewardMinutes").inputValue(), "10");
  assert.equal(await page.locator("#rewardObserved").inputValue(), "");
  assert.equal(await page.locator("#rewardManualRate").isChecked(), false);
  assert.equal(await page.locator("#rewardMethod").inputValue(), "reference");
  assert.equal(await page.locator("#rewardVehicle").inputValue(), "ka_52");
  assert.match(await text("#rewardFormula"), /69.80%/);
  assert.doesNotMatch(await text("#rewardResult"), /成功着陆后追加/);
  assert.equal(await page.locator(".chart-landing-area").count(), 0);
  await page.locator("#rewardSearch").fill("Ka-50");
  await page.locator("#rewardVehicle").selectOption("ka_50");
  assert.equal(await page.locator("#rewardResult dd").count(), 0);
  assert.match(await text("#rewardResult"), /不能套用 Ka-52/);
  assert.equal(await page.locator("#rewardChart svg").count(), 0);
  assert.match(await text("#rewardCardPreview"), /1,630 × 2 ×.*3,260 SL\/min/);
  await page.locator("#rewardAccount").selectOption("premium");
  assert.equal(await page.locator("#rewardSlRate").inputValue(), "4890");
  await page.locator("#rewardBooster").fill("");
  assert.equal(await page.locator("#rewardSlRate").inputValue(), "");
  await page.locator("#rewardAccount").selectOption("regular");
  await page.locator("#rewardBooster").fill("0");
  await page.locator("#rewardMode").selectOption("air_sim");
  await close("#rewardAdvanced");

  assert.equal(await page.locator("#chargeMassA").inputValue(), "201.8");
  assert.equal(await page.locator("#chargeMassB").inputValue(), "87.1");
  assert.match(await text("#chargeSourceA"), /272.43 kg TNT/);
  assert.match(await text("#chargeResult strong"), /3 枚 B/);
  assert.match(await text("#chargeDamageResult"), /向上取整为 2 枚 B/);
  assert.equal(await page.locator(".conversion-chart svg").isVisible(), true);
  assert.equal(await page.getByRole("spinbutton", { name: "已有 A 的数量", exact: true }).inputValue(), "1");
  await page.locator('label[for="chargeCount"]').click();
  assert.equal(await page.locator("#chargeCount").inputValue(), "1", "quantity label must focus input, not decrement it");
  assert.equal(Number(await page.locator(".chart-bar-a").getAttribute("data-total")), 272.43);
  assert.ok(Number(await page.locator("[data-surplus]").getAttribute("data-surplus")) > 0);
  await page.locator("#chargeMore").click();
  assert.equal(await page.locator("#chargeCount").inputValue(), "2");
  await page.locator("#chargeLess").click();
  await page.locator("#chargeSearchA").fill("Mk 83");
  await page.locator("#chargeSearchB").fill("Mk 82");
  await page.locator("#chargeSwap").click();
  assert.equal(await page.locator("#chargeWeaponA").inputValue(), "us_500lb_mk_82_ldgp");
  assert.equal(await page.locator("#chargeWeaponB").inputValue(), "us_1000lb_mk_83_ldgp");
  await page.locator("#chargeSwap").click();
  await page.locator("#chargeWeaponA").selectOption("su_zb_500");
  assert.match(await text("#chargeSourceA"), /特殊任务伤害模型/);
  await open("#chargeCustomA");
  await page.locator("#chargeUseA").click();
  assert.equal(await page.locator("#chargeMassA").inputValue(), "201.8");
  await page.locator("#chargeWeaponA").selectOption("");
  assert.equal(await page.locator("#chargeMassA").inputValue(), "201.8", "custom keeps current filler");
  assert.equal(await page.locator("#chargeDamageA").inputValue(), "");
  await page.locator("#chargeMassA").fill("100");
  await page.locator("#chargeFactorA").fill("1.5");
  await open("#chargeCustomB");
  await page.locator("#chargeMassB").fill("80");
  await page.locator("#chargeTypeB").selectOption("tnt:1");
  await page.locator("#chargeCount").fill("2");
  assert.equal(await page.locator("#chargeDamageB").inputValue(), "");
  assert.match(await text("#chargeSourceA"), /自定义装药/);
  assert.match(await text("#chargeResult"), /3.75 枚 B/);
  assert.match(await text("#chargeResult strong"), /4 枚 B/);
  assert.match(await text("#chargeResult"), /多出 20 kg TNT/);
  await open("#chargeFormulaDetails");
  assert.match(await page.locator("#chargeFormula").innerText(), /100 kg × 1.5 = 150 kg TNT/);
  await close("#chargeFormulaDetails");
  await open("#chargeDamageDetails");
  await page.locator("#chargeDamageA").fill("20");
  await page.locator("#chargeDamageB").fill("9");
  assert.match(await text("#chargeDamageResult"), /向上取整为 5 枚 B/);
  assert.match(await text("#chargeDamageResult"), /自定义 HP/);
  await page.locator("#chargeSwap").click();
  assert.equal(await page.locator("#chargeMassA").inputValue(), "80");
  assert.equal(await page.locator("#chargeFactorB").inputValue(), "1.5");
  assert.equal(await page.locator("#chargeCount").inputValue(), "2");
  await page.locator("#chargeMassB").fill("");
  assert.equal(await page.locator("#chargeResult strong").count(), 0);
  assert.equal(await page.locator(".conversion-chart svg").count(), 0);
  await page.locator("#chargeMassB").fill("100");
  await page.locator("#chargeCount").fill("0");
  assert.match(await text("#chargeResult strong"), /0 枚 B/);
  assert.equal(await page.locator("#chargeLess").isDisabled(), true);
  await page.locator("#chargeCount").fill("1.5");
  assert.equal(await page.locator("#chargeResult strong").count(), 0);
  assert.equal(await page.locator("#chargeMore").isDisabled(), true);
  await page.locator("#chargeCount").fill("1");
  await page.locator("#chargeMassA").fill("1.0000000000000002");
  await page.locator("#chargeFactorA").fill("1");
  await page.locator("#chargeMassB").fill("1");
  await page.locator("#chargeFactorB").fill("1");
  assert.match(await text("#chargeResult strong"), /2 枚 B/);
  await page.locator("#chargeMassA").fill("0.1");
  await page.locator("#chargeFactorA").fill("3");
  await page.locator("#chargeMassB").fill("0.3");
  assert.match(await text("#chargeResult strong"), /1 枚 B/);

  // Air-to-air: actual encounter inputs, model boundaries, replay and ARH/SARH distinction.
  assert.equal(await page.locator("#airWeapon option").count(), 10);
  assert.match(await text("#airResult"), /<5 m/);
  assert.equal(await page.locator("#airCompare button").count(), 3);
  assert.equal(await page.locator("#airPlot svg").count(), 1);
  await page.locator('#airCompare [data-mode="descend"]').click();
  assert.match(await text("#airAdvice"), /改变原交会平面/);
  await page.locator("#airTime").fill("500");
  assert.notEqual(await text("#airTimeValue"), "0.0 s");
  await page.locator("#airForm details > summary").filter({ hasText: "观测中断假设" }).click();
  await page.locator("#airGap").fill("2");
  await page.waitForFunction(() => document.querySelector("#airRecovery").textContent.includes("距离残差"));
  await page.locator("#airWeapon").selectOption("su_r_27er");
  await page.waitForFunction(() => document.querySelector("#airRecovery").textContent.includes("照射端"));
  await page.locator("#airRange").fill("");
  await page.waitForFunction(() => !document.querySelector("#airPlot svg"));
  assert.match(await text("#airResult"), /完整数值/);
  await page.locator('[data-air-preset="high"]').click();
  await page.locator("#airWeapon").selectOption("us_aim_120a");
  await page.waitForFunction(() => document.querySelector("#airPlot svg") !== null);
  await page.locator("#airForm details > summary").filter({ hasText: "观测中断假设" }).click();

  // Capture the novice flow, with all optional parameters folded away.
  await page.locator("#chargeWeaponA").selectOption("us_1000lb_mk_83_ldgp");
  await page.locator("#chargeWeaponB").selectOption("us_500lb_mk_82_ldgp");
  for (const id of ["#chargeCustomA", "#chargeCustomB", "#chargeDamageDetails"]) await close(id);
  await mkdir("../.artifacts/calculator-ui", { recursive: true });
  for (const [width, height] of [[1440, 1050], [390, 844], [320, 568]]) {
    await page.setViewportSize({ width, height });
    await page.waitForFunction(() => {
      const chart = document.querySelector("#rewardChart");
      return Math.abs(chart.querySelector("svg").viewBox.baseVal.width - chart.clientWidth) <= 1;
    });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `${width}: horizontal overflow`);
    assert.ok(await page.locator("#rewardChart text").first().evaluate(node => parseFloat(getComputedStyle(node).fontSize) >= 12), `${width}: unreadable chart text`);
    await page.locator("#airportStatus").screenshot({ path: `../.artifacts/calculator-ui/airport-${width}.png`, style: "bomana-site-header { visibility: hidden; }" });
    await checkOppositeEndpoints();
    await page.locator("#airportDiagramDetails").screenshot({ path: `../.artifacts/calculator-ui/airport-bars-${width}.png`, style: "bomana-site-header { visibility: hidden; }" });
    await page.locator("#explosiveConversion").screenshot({ path: `../.artifacts/calculator-ui/conversion-${width}.png`, style: "bomana-site-header { visibility: hidden; }" });
    await page.locator("#usefulActions").screenshot({ path: `../.artifacts/calculator-ui/rewards-${width}.png`, style: "bomana-site-header { visibility: hidden; }" });
    await page.locator("#airCombat").screenshot({ path: `../.artifacts/calculator-ui/air-${width}.png`, style: "bomana-site-header { visibility: hidden; }" });
  }
  if (!remote) {
    const coefficients = await browser.newPage();
    coefficients.on("pageerror", error => errors.push(error.message));
    await coefficients.goto(url);
    await coefficients.waitForFunction(() => document.querySelector("#calcPresetList [data-preset-id]") !== null);
    await coefficients.locator("#calcAircraftSearch").fill("mig_23mld");
    await coefficients.locator('[data-aircraft-id="mig_23mld"]').click();
    await coefficients.locator('[data-preset-id="mig_23mld_bomb_fab500m_62"]').click();
    assert.equal(await coefficients.locator('#calcRewardCount').innerText(), "6.2");
    assert.match(await coefficients.locator('[data-optimizer-priority-help]').textContent(), /7.8/);
    // Missing economy identity leaves an explicit unavailable coefficient instead of guessing a bomber.
    await coefficients.route("**/api/v1/calculator/aircraft.json", async route => {
      const response = await route.fetch(), payload = await response.json();
      payload.aircraft.find(row => row.id === "mig_23mld").reward = null;
      await route.fulfill({json: payload});
    });
    await coefficients.reload();
    await coefficients.waitForFunction(() => document.querySelector("#calcPresetList [data-preset-id]") !== null);
    await coefficients.locator("#calcAircraftSearch").fill("mig_23mld");
    await coefficients.locator('[data-aircraft-id="mig_23mld"]').click();
    await coefficients.locator('[data-preset-id="mig_23mld_bomb_fab500m_62"]').click();
    assert.equal(await coefficients.locator('#calcRewardCard').isVisible(), true);
    assert.equal(await coefficients.locator('#calcRewardCount').innerText(), "—");
    assert.doesNotMatch(await coefficients.locator('[data-optimizer-priority-help]').textContent(), /收益系数 ≥/);
    await coefficients.close();
    for (const failure of ["unavailable", "mixed-source"]) {
      const loadoutFailure = await browser.newPage();
      loadoutFailure.on("pageerror", error => errors.push(error.message));
      await loadoutFailure.route("**/api/v1/calculator/loadouts.json", async route => {
        if (failure === "unavailable") return route.fulfill({ status: 503, body: "Unavailable" });
        const response = await route.fetch(), payload = await response.json();
        payload.source.version = "0.0.1";
        await route.fulfill({ json: payload });
      });
      await loadoutFailure.goto(url);
      await loadoutFailure.waitForFunction(() => document.querySelector("#calcLoadoutCaption").textContent.includes("挂载排列未就绪"));
      assert.equal(await loadoutFailure.locator("#calcPresetDetail").isVisible(), false);
      assert.ok(await loadoutFailure.locator("#calcWeaponList [data-weapon-id]").count() > 0);
      assert.equal(await loadoutFailure.locator("#calcRewardCard").isVisible(), true);
      assert.equal(await loadoutFailure.locator("#calcRewardCount").innerText(), "—");
      await loadoutFailure.unroute("**/api/v1/calculator/loadouts.json");
      await loadoutFailure.locator("#calcAircraftSearch").fill("pe-8_m82");
      await loadoutFailure.locator('[data-aircraft-id="pe-8_m82"]').click();
      await loadoutFailure.waitForFunction(() => document.querySelectorAll("#calcPresetList [data-preset-id]").length === 6);
      await loadoutFailure.close();
    }
    const noRepair = await browser.newPage();
    noRepair.on("pageerror", error => errors.push(error.message));
    await noRepair.route("**/api/v1/calculator/index.json", async route => {
      const response = await route.fetch(); const payload = await response.json();
      delete payload.airport_repair;
      await route.fulfill({ json: payload });
    });
    await noRepair.goto(url);
    await noRepair.locator('#calcTargetSegments [data-value="airport_storage"]').click();
    await noRepair.waitForFunction(() => document.querySelector("#repairResult").textContent.includes("没有已核对"));
    assert.match(await noRepair.locator("#calcRepairSummary").innerText(), /没有已核对/);
    assert.equal(await noRepair.locator("#calcRepairDetail").textContent(), "");
    assert.equal(await noRepair.locator("#repairChart svg").count(), 0);
    const unavailable = await browser.newPage();
    unavailable.on("pageerror", error => errors.push(error.message));
    await unavailable.route("**/api/v1/calculator/**", route => route.fulfill({ status: 503, body: "Unavailable" }));
    await unavailable.goto(url);
    await unavailable.waitForFunction(() => document.querySelector("#calcSource").textContent.includes("数据未就绪"));
    await unavailable.locator("#chargeCustomA > summary").click();
    await unavailable.locator("#chargeMassA").fill("100");
    await unavailable.locator("#chargeFactorA").fill("1.5");
    assert.match(await unavailable.locator("#chargeResult strong").innerText(), /3 枚 B/);
    assert.match(await unavailable.locator("#rewardResult").innerText(), /收益数据加载失败/);
    const mixed = await browser.newPage();
    await mixed.route("**/api/v1/calculator/rewards.json", async route => {
      const response = await route.fetch(); const payload = await response.json();
      payload.source = { ...payload.source, version: "0.0.1" };
      await route.fulfill({ json: payload });
    });
    await mixed.goto(url);
    await mixed.waitForFunction(() => document.querySelector("#calcSource").textContent.includes("数据未就绪"));
    assert.equal(await mixed.locator("#rewardResult dd").count(), 0);
  }
  assert.deepEqual(errors, []);
  console.log(`Calculator Edge UI passed: simple defaults, live score/SL charts, automatic card rates, observation boundaries, search/swap, TNT/HP separation, custom parameters and desktop/mobile layout (${url})`);
} finally { await browser.close(); if (!remote) await new Promise(resolve => site.close(resolve)); }
