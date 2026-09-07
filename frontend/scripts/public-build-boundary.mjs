import { readFileSync, existsSync } from "node:fs";
import { resolve, relative } from "node:path";

/** Check the actual bundled module graph, including dynamic imports and CSS. */
export function publicBuildBoundary(repositoryRoot) {
  const exported = resolve(repositoryRoot, "public-source-files.json");
  const manifest = JSON.parse(readFileSync(existsSync(exported) ? exported : resolve(repositoryRoot, "tools/public-source/files.json"), "utf8"));
  const allowed = new Set(Array.isArray(manifest.files) ? manifest.files : Object.keys(manifest.files));
  const generated = new Set(["public-offline-assets.ts", "aircraft-parameters.json", "strike-encyclopedia.json", "strike-weapon-damage.json", "bombing-zone-splash.json", "bomana-logo.svg"]);
  return { name: "public-source-boundary", generateBundle() {
    for (const id of this.getModuleIds()) {
      if (id.startsWith("\0") || id.includes("/node_modules/") || !id.includes("/")) continue;
      const name = relative(repositoryRoot, id.split("?")[0]).replaceAll("\\", "/");
      if (allowed.has(name)) continue;
      if (name.startsWith("frontend/src/generated/") && generated.has(name.slice("frontend/src/generated/".length))) continue;
      throw new Error(`public build imported an unlisted module: ${name}`);
    }
  } };
}
