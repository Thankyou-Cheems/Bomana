// Render the existing SVG only during maintenance; no renderer enters the EXE.
import { readFile, writeFile } from 'node:fs/promises';
import { createRequire } from 'node:module';

const require = createRequire(new URL('../frontend/package.json', import.meta.url));
const { chromium } = require('playwright-core');
const svg = await readFile(new URL('../bomana/assets/web/favicon.svg', import.meta.url), 'utf8');
const sizes = [16, 32, 48, 256];
const images = [];
const browser = await chromium.launch({ channel: 'msedge', headless: true });
try {
  const page = await browser.newPage({ deviceScaleFactor: 1 });
  await page.setContent(`<style>html,body{margin:0;background:transparent}svg{display:block;width:100vw;height:100vh}</style>${svg}`);
  for (const size of sizes) {
    await page.setViewportSize({ width: size, height: size });
    images.push(await page.screenshot({ omitBackground: true }));
  }
} finally {
  await browser.close();
}

// ICO directory followed by compressed PNG frames, including the large Explorer icon.
const directory = Buffer.alloc(6 + sizes.length * 16);
directory.writeUInt16LE(1, 2);
directory.writeUInt16LE(sizes.length, 4);
let offset = directory.length;
for (const [index, size] of sizes.entries()) {
  const entry = 6 + index * 16;
  directory[entry] = directory[entry + 1] = size === 256 ? 0 : size;
  directory.writeUInt16LE(1, entry + 4);
  directory.writeUInt16LE(32, entry + 6);
  directory.writeUInt32LE(images[index].length, entry + 8);
  directory.writeUInt32LE(offset, entry + 12);
  offset += images[index].length;
}
const icon = Buffer.concat([directory, ...images]);
await writeFile(new URL('../native/telemetry_gateway/cmd/bomana_basic/app.ico', import.meta.url), icon);
console.log(`Basic icon: ${icon.length} bytes, ${sizes.join('/')} px, from favicon.svg`);
