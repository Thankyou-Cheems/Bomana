import { cpSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const source = dirname(fileURLToPath(import.meta.resolve("highs")));
const destination = fileURLToPath(new URL("../../docs/calculator/solver/", import.meta.url));
mkdirSync(destination, {recursive: true});
for (const file of ["highs.mjs", "highs.wasm"]) cpSync(resolve(source, file), resolve(destination, file));
cpSync(resolve(source, "../LICENSE"), resolve(destination, "LICENSE"));
