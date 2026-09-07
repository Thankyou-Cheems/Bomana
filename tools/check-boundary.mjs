import { existsSync, readFileSync, readdirSync } from "node:fs";
import { resolve, relative } from "node:path";
import { execFileSync } from "node:child_process";

const root = resolve(import.meta.dirname, "..");
const files = JSON.parse(readFileSync(resolve(root, "public-source-files.json"), "utf8")).files;
const allowed = new Set(files);
const forbidden = /(?:^|\/)(?:enhanced_desktop|solver_wasm|research|releases|\.artifacts)(?:\/|$)|(?:edition-runtime|mobile-pairing-enhanced|enhanced-heading-guidance|tactical-map|y66-calibration|airfield-targeting|automatic-target|gamechat-zone-marks|bombing-window|weapon-envelope|terrain-repository|solver\.worker)\.(?:ts|json)$|(?:weapon_fire_control|offline_rigidbody_catalog|ec_airfield_catalog|ec_bombing_areas)\./;
for (const name of files) {
  if (forbidden.test(name)) throw new Error(`private source in public projection: ${name}`);
  if (!existsSync(resolve(root, name))) throw new Error(`public file missing: ${name}`);
  if (!/\.(?:ts|mjs|css|html)$/.test(name)) continue;
  const source = readFileSync(resolve(root, name), "utf8");
  if (/-----BEGIN (?:OPENSSH |RSA |EC )?PRIVATE KEY-----/.test(source)) throw new Error(`private key in source: ${name}`);
}
const typeFiles = execFileSync(process.execPath, [resolve(root, "frontend/node_modules/typescript/bin/tsc"), "--listFilesOnly", "--project", resolve(root, "frontend/tsconfig.json")], { encoding: "utf8" });
for (const file of typeFiles.trim().split(/\r?\n/)) {
  const name = relative(root, file).replaceAll("\\", "/");
  if (file.replaceAll("\\", "/").includes("/node_modules/") || name.startsWith("frontend/src/generated/")) continue;
  if (!allowed.has(name)) throw new Error(`type import escapes public source: ${name}`);
}
for (const name of walk(root)) {
  if (!allowed.has(name)) throw new Error(`unlisted file in public working tree: ${name}`);
}
console.log(`Public source boundary verified: ${files.length} files; no private runtime or solver.`);

function walk(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = resolve(directory, entry.name), name = relative(root, path).replaceAll("\\", "/");
    if ([".git", ".artifacts", "node_modules", "dist", "generated"].includes(entry.name)) return [];
    return entry.isDirectory() ? walk(path) : [name];
  });
}
