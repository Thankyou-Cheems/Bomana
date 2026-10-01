import { readFileSync, writeFileSync } from "node:fs";
import { stripTypeScriptTypes } from "node:module";

// The static calculator uses the same reporter as the App, without a bundler.
const source = new URL("../src/runtime/anonymous-daily-active.ts", import.meta.url);
const destination = new URL("../../docs/calculator/anonymous-daily-active.mjs", import.meta.url);
const outputText = stripTypeScriptTypes(readFileSync(source, "utf8").replaceAll("\r\n", "\n")).replace(/[ \t]+$/gm, "");
writeFileSync(destination, "// Generated from frontend/src/runtime/anonymous-daily-active.ts.\n" + outputText);
