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
    response.setHeader("Content-Type", ({ ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css", ".json": "application/json", ".webp": "image/webp", ".svg": "image/svg+xml" })[extension] || "application/octet-stream");
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
  assert.equal(await page.locator("#chargeMassA").inputValue(), "201.8");
  assert.equal(await page.locator("#chargeMassB").inputValue(), "87.1");
  assert.match(await page.locator("#chargeResult").innerText(), /272.43 kg TNT/);
  assert.match(await page.locator("#chargeResult strong").innerText(), /3 枚 B/);
  assert.match(await page.locator("#chargeDamageResult").innerText(), /向上取整为 2 枚 B/);
  assert.doesNotMatch(await page.locator("#chargeSourceA").innerText(), /特殊/);
  await page.locator("#chargeWeaponA").selectOption("su_zb_500");
  assert.match(await page.locator("#chargeSourceA").innerText(), /特殊任务伤害模型/);
  await page.locator("#chargeUseA").click();
  assert.equal(await page.locator("#chargeMassA").inputValue(), "201.8");
  await page.locator("#chargeMassA").fill("100");
  await page.locator("#chargeFactorA").fill("1.5");
  await page.locator("#chargeMassB").fill("80");
  await page.locator("#chargeTypeB").selectOption("tnt:1");
  await page.locator("#chargeCount").fill("2");
  assert.equal(await page.locator("#chargeDamageA").inputValue(), "");
  assert.equal(await page.locator("#chargeDamageB").inputValue(), "");
  assert.match(await page.locator("#chargeSourceA").innerText(), /自定义装药/);
  assert.match(await page.locator("#chargeResult").innerText(), /3.75 枚 B/);
  assert.match(await page.locator("#chargeResult strong").innerText(), /4 枚 B/);
  assert.match(await page.locator("#chargeResult").innerText(), /多出 20 kg TNT/);
  await page.locator("#conversionForm details summary").click();
  await page.locator("#chargeDamageA").fill("20");
  await page.locator("#chargeDamageB").fill("9");
  assert.match(await page.locator("#chargeDamageResult").innerText(), /向上取整为 5 枚 B/);
  assert.match(await page.locator("#chargeDamageResult").innerText(), /自定义 HP/);
  await page.locator("#chargeSwap").click();
  assert.equal(await page.locator("#chargeMassA").inputValue(), "80");
  assert.equal(await page.locator("#chargeFactorB").inputValue(), "1.5");
  assert.equal(await page.locator("#chargeCount").inputValue(), "2");
  await page.locator("#chargeMassB").fill("");
  assert.equal(await page.locator("#chargeResult strong").count(), 0);
  await page.locator("#chargeMassB").fill("100");
  await page.locator("#chargeCount").fill("0");
  assert.match(await page.locator("#chargeResult strong").innerText(), /0 枚 B/);
  await page.locator("#chargeCount").fill("1.5");
  assert.equal(await page.locator("#chargeResult strong").count(), 0);
  await page.locator("#chargeCount").fill("2");
  await mkdir("../.artifacts/calculator-ui", { recursive: true });
  for (const [width, height] of [[1440, 1050], [390, 844], [320, 568]]) {
    await page.setViewportSize({ width, height });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `${width}: horizontal overflow`);
    await page.locator("#explosiveConversion").screenshot({ path: `../.artifacts/calculator-ui/conversion-${width}.png` });
  }
  if (!remote) {
    const unavailable = await browser.newPage();
    unavailable.on("pageerror", error => errors.push(error.message));
    await unavailable.route("**/api/v1/calculator/**", route => route.fulfill({ status: 503, body: "Unavailable" }));
    await unavailable.goto(url);
    await unavailable.waitForFunction(() => document.querySelector("#calcSource").textContent.includes("数据未就绪"));
    await unavailable.locator("#chargeMassA").fill("100");
    await unavailable.locator("#chargeFactorA").fill("1.5");
    assert.match(await unavailable.locator("#chargeResult strong").innerText(), /3 枚 B/);
  }
  assert.deepEqual(errors, []);
  console.log(`Calculator Edge UI passed: catalog fillers, formulas, TNT/HP separation, custom parameters, swap, missing/zero/invalid inputs and desktop/mobile layout (${url})`);
} finally { await browser.close(); if (!remote) await new Promise(resolve => site.close(resolve)); }
