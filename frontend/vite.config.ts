import { resolve } from "node:path";
import { defineConfig } from "vitest/config";

const edition = process.env.BOMANA_EDITION ?? "Standard";
if (edition !== "Lite" && edition !== "Standard") throw new Error(`unknown public edition: ${edition}`);

export default defineConfig({
  base: "./",
  define: { __BOMANA_EDITION__: JSON.stringify(edition) },
  build: {
    outDir: resolve("dist", edition),
    emptyOutDir: false,
    target: "es2022",
    sourcemap: false,
    assetsInlineLimit: 0,
  },
  test: { environment: "node", include: ["src/**/*.test.ts"] },
});
