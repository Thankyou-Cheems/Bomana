import assert from "node:assert/strict";
import { chromium } from "playwright-core";

// Run through tools/smoke_mobile_pairing.ps1: Go provides a real isolated Bridge,
// local App assets and offline game responses. Pairing tokens stay out of logs.
const target = process.env.BOMANA_PAIRING_REPRO_URL;
assert.ok(target, "The Bridge browser fixture must provide its QR target");
function disableUsageReporting() {
  if (location.protocol === "http:") localStorage.setItem("bomana:dau:disabled:v1", "1");
}
const browser = await chromium.launch({ channel: "msedge", headless: true });
try {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true });
  await context.addInitScript(disableUsageReporting);
  const page = await context.newPage();
  page.setDefaultTimeout(10_000);
  const errors = [];
  const paymentRequests = [];
  let completions = 0;
  page.on("pageerror", error => errors.push(error.message));
  page.on("request", request => {
    if (new URL(request.url()).hostname === "pay.ruikang.wang") paymentRequests.push(new URL(request.url()).pathname);
  });
  page.on("response", response => {
    if (new URL(response.url()).pathname === "/api/v1/mobile/pairing/complete" && response.ok()) completions += 1;
  });

  await connect(target);
  assert.equal(completions, 1, "A first scan must consume its one-time claim");

  let currentQR = await rotate();
  await connect(currentQR);
  assert.equal(completions, 2, "Same-document rescanning must consume the new claim");

  await connect(currentQR);
  assert.equal(completions, 2, "The already paired phone must not consume its current claim twice");

  await page.goto("about:blank");
  currentQR = await rotate();
  await connect(currentQR);
  assert.equal(completions, 3, "A full navigation must not restore the revoked session over a new claim");

  await page.goto("about:blank");
  const reopened = new URL(currentQR);
  reopened.hash = "";
  await connect(reopened.toString());
  assert.equal(completions, 3, "Reopening without a QR must restore the current session");

  const otherPhone = await browser.newPage();
  await otherPhone.addInitScript(disableUsageReporting);
  const rejected = otherPhone.waitForResponse(response => new URL(response.url()).pathname === "/api/v1/mobile/pairing/complete");
  await otherPhone.goto(currentQR);
  assert.equal((await rejected).status(), 410, "Another phone must not replay a consumed claim");
  assert.equal(await otherPhone.locator("body").getAttribute("data-mobile-paired"), null);
  await otherPhone.close();

  assert.deepEqual(paymentRequests, [], "Standard pairing must not request CheemsPay");
  assert.deepEqual(errors, []);
  console.log("Standard mobile: first scan, same-tab rescan, same-claim reuse, stale-cache replacement, reopen and replay rejection passed");

  async function connect(url) {
    const connected = page.waitForResponse(response => new URL(response.url()).pathname === "/api/v1/capabilities" && response.ok())
      .then(() => true, () => false);
    await page.goto(url);
    assert.equal(await connected, true, "Scanned phone did not authenticate to the selected Bridge");
    assert.equal(await page.locator("body").getAttribute("data-mobile-paired"), "true");
    // Development-only offline roots intentionally cannot start App on LAN HTTP.
    // Signed release CI additionally requires the complete Standard UI to load.
    if (process.env.BOMANA_OFFLINE_ROOT_REQUIRE_PRODUCTION === "1") {
      await page.locator('body[data-edition="Standard"] #open-settings').waitFor();
    }
  }

  async function rotate() {
    const response = await fetch(`${process.env.BOMANA_PAIRING_CONTROL}/api/v1/mobile/pairing/rotate`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Origin: process.env.BOMANA_PAIRING_ORIGIN },
      body: JSON.stringify({ schema_version: 1, edition: "Standard" }),
    });
    assert.equal(response.status, 201);
    const descriptor = await response.json();
    const qr = new URL(target);
    qr.hash = new URLSearchParams({ "mobile-edition": "Standard", "mobile-pairing": descriptor.pairing_token }).toString();
    return qr.toString();
  }
} catch (error) {
  // Browser navigation exceptions can contain the entire sensitive fragment.
  console.error(String(error).replace(/#[^\s"']+/g, "#<REDACTED>"));
  process.exitCode = 1;
} finally {
  await browser.close();
}
