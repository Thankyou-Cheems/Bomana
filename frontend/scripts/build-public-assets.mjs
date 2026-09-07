import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { writeOfflineAssetModule } from "./offline-asset-builder.mjs";

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const generatedRoot = resolve(repositoryRoot, "frontend/src/generated");
const publicRuntimeAssets = [
  "aircraft_parameters.json",
  "strike_encyclopedia.json",
  "strike_weapon_damage.json",
  "bombing_zone_splash.json",
];
const publicOfflineAssets = [
  ["aircraft-parameters", "reference", "aircraft-parameters.json"],
  ["strike-encyclopedia", "reference", "strike-encyclopedia.json"],
  ["strike-weapon-damage", "weapon", "strike-weapon-damage.json"],
  ["bombing-zone-splash", "reference", "bombing-zone-splash.json"],
];

export function buildPublicAssets() {
  const manifest = JSON.parse(readFileSync(resolve(repositoryRoot, "bomana/data/parameter_set.json"), "utf8"));
  for (const asset of publicRuntimeAssets) {
    const bytes = readFileSync(resolve(repositoryRoot, "bomana/data", asset));
    if (createHash("sha256").update(bytes).digest("hex") !== manifest.files[asset]) {
      throw new Error(`public parameter set is stale: ${asset}`);
    }
  }
  for (const [asset, expected] of Object.entries(manifest.calculator_files)) {
    const bytes = readFileSync(resolve(repositoryRoot, "docs/api/v1/calculator", asset));
    if (createHash("sha256").update(bytes).digest("hex") !== expected) {
      throw new Error(`public calculator data is stale: ${asset}`);
    }
  }
  mkdirSync(generatedRoot, { recursive: true });
  writeFileSync(
    resolve(generatedRoot, "bomana-logo.svg"),
    readFileSync(resolve(repositoryRoot, "bomana", "assets", "web", "favicon.svg")),
  );
  for (const asset of publicRuntimeAssets) {
    writeFileSync(
      resolve(generatedRoot, asset.replaceAll("_", "-")),
      readFileSync(resolve(repositoryRoot, "bomana", "data", asset)),
    );
  }
  writeOfflineAssetModule(generatedRoot, "public-offline-assets.ts", "PUBLIC", "public", publicOfflineAssets);
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) buildPublicAssets();
