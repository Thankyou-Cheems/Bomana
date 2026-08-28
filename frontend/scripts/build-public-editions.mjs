import { rmSync } from "node:fs";
import { resolve } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const root = resolve(fileURLToPath(new URL("..", import.meta.url)));
rmSync(resolve(root, "dist"), { recursive: true, force: true });
for (const edition of ["Lite", "Standard"]) {
  const result = spawnSync(process.execPath, [resolve(root, "node_modules/vite/bin/vite.js"), "build"], {
    cwd: root,
    env: { ...process.env, BOMANA_EDITION: edition },
    stdio: "inherit",
  });
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(`${edition} build failed`);
}
