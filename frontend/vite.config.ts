import { defineConfig } from "vitest/config";
import publicConfig from "./vite.public.config";

export default defineConfig({ ...publicConfig, root: ".", test: { environment: "node", include: ["src/**/*.test.ts"] } });
