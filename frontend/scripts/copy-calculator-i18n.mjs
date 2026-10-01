import {cpSync, mkdirSync} from 'node:fs';
import {dirname, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
const source = dirname(fileURLToPath(import.meta.resolve('i18next/package.json')));
const destination = fileURLToPath(new URL('../../docs/calculator/vendor/', import.meta.url));
mkdirSync(destination, {recursive: true});
cpSync(resolve(source, 'dist/esm/i18next.js'), resolve(destination, 'i18next.mjs'));
cpSync(resolve(source, 'LICENSE'), resolve(destination, 'i18next.LICENSE'));
