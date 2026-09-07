import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { basename, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const frontendRoot = resolve(fileURLToPath(new URL("..", import.meta.url)));
const distRoot = resolve(frontendRoot, "dist");
const viteCli = resolve(frontendRoot, "node_modules", "vite", "bin", "vite.js");
const requested = process.argv[2];
const editions = requested ? [requested] : ["Lite", "Standard", "Enhanced"];
for (const edition of editions) {
  if (!["Lite", "Standard", "Enhanced"].includes(edition)) {
    throw new Error(`unknown edition: ${edition}`);
  }
}
if (!requested) rmSync(distRoot, { recursive: true, force: true });

for (const edition of editions) {
  const result = spawnSync(
    process.execPath,
    [viteCli, "build", ...(edition === "Enhanced" ? [] : ["--config", "vite.public.config.ts"])],
    {
      cwd: frontendRoot,
      env: { ...process.env, BOMANA_EDITION: edition },
      stdio: "inherit",
    },
  );
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(`${edition} frontend build failed`);
  if (edition === "Enhanced") writeEnhancedRetirementWorker();
  else writeServiceWorker(edition);
  auditEdition(edition);
}

function writeEnhancedRetirementWorker() {
  const root = resolve(distRoot, "Enhanced");
  writeFileSync(resolve(root, "service-worker.js"), `
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter((key) => key.startsWith("bomana-browser-Enhanced-")).map((key) => caches.delete(key)));
    await self.registration.unregister();
    await self.clients.claim();
  })());
});
`, "utf8");
}

function writeServiceWorker(edition) {
  const root = resolve(distRoot, edition);
  const files = walk(root).filter((path) => !path.endsWith("service-worker.js"));
  const digest = createHash("sha256");
  for (const path of files.sort()) digest.update(readFileSync(path));
  const revision = digest.digest("hex").slice(0, 16);
  const assets = ["./", ...files
    .filter((path) => !/\.(json|wasm)$/i.test(path))
    .map((path) => `./${path.slice(root.length + 1).replaceAll("\\", "/")}`)];
  writeFileSync(resolve(root, "service-worker.js"), `
const CACHE = ${JSON.stringify(`bomana-browser-${edition}-${revision}`)};
const PREFIX = ${JSON.stringify(`bomana-browser-${edition}-`)};
const ASSETS = ${JSON.stringify(assets)};
self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(ASSETS)));
});
self.addEventListener("activate", (event) => {
  event.waitUntil(caches.keys().then((keys) => Promise.all(
    keys.filter((key) => key.startsWith(PREFIX) && key !== CACHE).map((key) => caches.delete(key)),
  )));
});
self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") return;
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin || url.pathname.includes("/api/")) return;
  if (/\\.(json|wasm)$/i.test(url.pathname)) return;
  if (event.request.mode === "navigate") {
    event.respondWith(fetch(event.request).then((response) => {
      if (response.ok) {
        const copy = response.clone();
        event.waitUntil(caches.open(CACHE).then((cache) => cache.put("./index.html", copy)));
      }
      return response;
    }).catch(async () => (await caches.match("./index.html")) || Response.error()));
    return;
  }
  event.respondWith(caches.match(event.request).then((cached) => cached || fetch(event.request).then((response) => {
    if (response.ok && response.type === "basic") {
      const copy = response.clone();
      event.waitUntil(caches.open(CACHE).then((cache) => cache.put(event.request, copy)));
    }
    return response;
  })));
});
`, "utf8");
}

function auditEdition(edition) {
  const root = resolve(distRoot, edition);
  const absoluteFiles = walk(root);
  const files = absoluteFiles.map((path) => path.slice(root.length + 1).replaceAll("\\", "/"));
  const hasWasm = files.some((path) => path.endsWith(".wasm"));
  const hasGuidedCatalog = files.some((path) => path.includes("guided-catalog"));
  const hasPoweredCatalog = files.some((path) => path.includes("powered-weapon-catalog"));
  const hasBallisticCatalog = files.some((path) => path.includes("ballistic-bomb-catalog"));
  const hasAirfieldCatalog = files.some((path) => path.includes("ec-airfield-catalog"));
  const hasY66Calibration = files.some((path) => path.includes("y66-calibration"));
  const hasPipMiniMap = files.some((path) => path.includes("pip-mini-map"));
  const hasServiceWorker = files.includes("service-worker.js");
  const javascript = absoluteFiles
    .filter((path) => path.endsWith(".js"))
    .map((path) => readFileSync(path, "utf8"))
    .join("\n");
  if (files.some((path) => /[.](?:ttf|otf|woff2?|eot)$/i.test(path))) {
    throw new Error(`${edition} production Web bundle contains a distributed font`);
  }
  if (edition === "Enhanced") {
    if (!hasWasm || !hasGuidedCatalog || !hasPoweredCatalog || !hasBallisticCatalog || !hasAirfieldCatalog || !hasY66Calibration || !hasPipMiniMap) {
      throw new Error("Enhanced is missing its local solver closure");
    }
    const worker = readFileSync(resolve(root, "service-worker.js"), "utf8");
    if (!hasServiceWorker || worker.includes('addEventListener("fetch"') || !worker.includes("registration.unregister")) {
      throw new Error("Enhanced must ship only the offline-cache retirement worker");
    }
  } else if (hasWasm || hasGuidedCatalog || hasPoweredCatalog || hasBallisticCatalog || hasAirfieldCatalog || hasY66Calibration) {
    throw new Error(`${edition} leaked Enhanced solver assets`);
  } else if (!hasServiceWorker) {
    throw new Error(`${edition} is missing its public App service worker`);
  }
  if (hasPipMiniMap !== (edition !== "Lite")) {
    throw new Error(`${edition} has an incorrect navigation PiP map closure`);
  }
  if (!files.some((path) => path.includes("strike-encyclopedia"))) {
    throw new Error(`${edition} is missing the shared strike encyclopedia`);
  }
  if (edition === "Standard") {
    if (!javascript.includes("api/v1/mobile/pairing/start") || !javascript.includes("/mobile/Standard/")) {
      throw new Error("Standard is missing its direct local Mobile Pairing closure");
    }
    if (javascript.includes("/api/bomana/mobile-pairings")) {
      throw new Error("Standard leaked the Enhanced Mobile Pairing authorization endpoint");
    }
  }
  auditHeadingComposite(edition, root, absoluteFiles);
}

function auditHeadingComposite(edition, root, files) {
  const index = readFileSync(resolve(root, "index.html"), "utf8");
  const cssFiles = files.filter((path) => path.endsWith(".css") && index.includes(basename(path)));
  const css = cssFiles.map((path) => readFileSync(path, "utf8")).join("\n");
  const hasStandardBackdropNone = (declarations) => /(?:^|;)backdrop-filter:none!important(?:;|$)/.test(declarations);
  const headingBlocks = [...css.matchAll(/[.]heading-tape-wrap\{([^}]*)\}/g)].map((match) => match[1]);
  const overlay = css.match(/[.]heading-tape-wrap>[.]heading-release\{([^}]*)\}/)?.[1] ?? "";
  if (!headingBlocks.some(hasStandardBackdropNone) || !hasStandardBackdropNone(overlay)) {
    throw new Error(`${edition} production CSS lost the standard heading backdrop override`);
  }
}

function walk(root) {
  const output = [];
  for (const entry of readdirSync(root, { withFileTypes: true })) {
    const path = resolve(root, entry.name);
    if (entry.isDirectory()) output.push(...walk(path));
    else if (entry.isFile()) output.push(path);
  }
  return output;
}
