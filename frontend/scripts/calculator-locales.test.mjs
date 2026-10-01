import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {parse} from '@babel/parser';
const root=new URL('../../docs/calculator/',import.meta.url);
const read=file=>readFileSync(new URL(file,root),'utf8');
const base=JSON.parse(read('locales/zh-CN.json'));
const variables=text=>[...text.matchAll(/{{([^}]+)}}/g)].map(match=>match[1]).sort();

test('all locales include complete messages and preserve interpolation variables',()=>{
  for(const locale of ['en','zh-Hant']) {
    const messages=JSON.parse(read(`locales/${locale}.json`));
    assert.deepEqual(Object.keys(messages).sort(),Object.keys(base).sort());
    for(const key of Object.keys(base)) {
      assert.ok(messages[key].trim(),key);
      assert.deepEqual(variables(messages[key]),variables(base[key]),`${locale}:${key}`);
    }
  }
});

test('UI translation references resolve in the canonical resource',()=>{
  const check=key=>assert.ok(Object.hasOwn(base,key),`missing ${key}`);
  for(const file of ['app.js','air-ui.mjs','charts.mjs','loadouts.mjs','custom-loadout-ui.mjs','combination-ui.mjs','optimizer-ui.mjs','custom-loadouts.mjs','air-model.mjs']) {
    const tree=parse(read(file),{sourceType:'module'});
    const visit=node=>{
      if(!node||typeof node!=='object')return;
      if(node.type==='CallExpression'&&node.callee.name==='t'&&node.arguments[0]?.type==='StringLiteral') check(node.arguments[0].value);
      for(const value of Object.values(node)) if(Array.isArray(value)) value.forEach(visit);else if(value&&typeof value==='object'&&value.type)visit(value);
    };
    visit(tree);
  }
  for(const match of read('index.html').matchAll(/data-i18n(?:-[a-z-]+)?="([^"]+)"/g))check(match[1]);
});
