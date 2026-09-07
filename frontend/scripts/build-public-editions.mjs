import { spawnSync } from "node:child_process";
import { resolve } from "node:path";

for (const edition of ["Lite", "Standard"]) {
  const result = spawnSync(process.execPath, [resolve("scripts/build-editions.mjs"), edition], { stdio: "inherit" });
  if (result.error) throw result.error;
  if (result.status !== 0) process.exit(result.status ?? 1);
}
