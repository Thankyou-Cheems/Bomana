import { resolve } from "node:path";
import { defineConfig } from "vite";
// @ts-expect-error The build plugin is a shared Node.js module.
import { publicBuildBoundary } from "./scripts/public-build-boundary.mjs";

const edition = process.env.BOMANA_EDITION ?? "Standard";
if (edition !== "Lite" && edition !== "Standard") throw new Error("public Web supports Lite and Standard only");
export default defineConfig({
  root: resolve("public-web"),
  base: "./",
  publicDir: false,
  plugins: [publicBuildBoundary(resolve(".."))],
  define: { __BOMANA_EDITION__: JSON.stringify(edition) },
  build: { outDir: resolve("dist", edition), emptyOutDir: true, target: "es2022", sourcemap: false, assetsInlineLimit: 0 },
});
