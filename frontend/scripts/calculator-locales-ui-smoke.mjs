import assert from 'node:assert/strict';
import {readFile, mkdir} from 'node:fs/promises';
import {createServer} from 'node:http';
import {resolve, sep, extname} from 'node:path';
import {chromium} from 'playwright-core';
const root=resolve('../docs');
const server=createServer(async(req,res)=>{
  let path=decodeURIComponent(new URL(req.url,'http://localhost').pathname);
  if(path.endsWith('/')) path+='index.html';
  const file=resolve(root,`.${path}`);
  if(!file.startsWith(root+sep)){res.writeHead(403).end();return;}
  try {res.setHeader('Content-Type',({'.mjs':'text/javascript','.js':'text/javascript','.css':'text/css','.json':'application/json','.wasm':'application/wasm','.webp':'image/webp'})[extname(file)]||'text/html; charset=utf-8');res.end(await readFile(file));}
  catch {res.writeHead(404).end();}
});
await new Promise(done=>server.listen(0,'127.0.0.1',done));
const browser=await chromium.launch({channel:'msedge',headless:true});
try {
  const page=await browser.newPage({viewport:{width:1440,height:1000}}), errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  await page.goto(`http://127.0.0.1:${server.address().port}/calculator/`);
  await page.locator('[data-preset-id]').first().waitFor();
  const count=await page.locator('#calcDestroyCount').textContent();
  assert.equal(await page.locator('.calculator-heading > #calculatorLanguage').count(),0);
  assert.equal(await page.locator('#calculatorLanguage [data-calculator-language]').count(),3);
  for(const [language,title] of [['en','Sim Sortie Toolbox'],['zh-Hant','全真出擊工具箱'],['zh-CN','全真出击工具箱'],['en','Sim Sortie Toolbox']]) {
    await page.locator(`[data-calculator-language="${language}"]`).click();
    await page.waitForFunction(lang=>document.documentElement.lang===lang,language);
    assert.equal(await page.locator('#calc-title').textContent(),title);
    assert.equal(await page.locator('#calcDestroyCount').textContent(),count);
  }
  await page.locator('#calcAircraftSearch').fill('taif');
  await page.locator('[data-aircraft-id="ef_2000_typhoon_aesa"]').click();
  await page.locator('[data-custom-body]').waitFor();
  await page.locator('[data-custom-tier="0"]').click();
  const option=page.locator('[data-custom-option]').filter({hasNotText:'Empty'}).first();
  const chosen=await option.getAttribute('data-custom-option');
  await option.click();
  await page.locator('[data-calculator-language="zh-Hant"]').click();
  await page.waitForFunction(()=>document.documentElement.lang==='zh-Hant');
  assert.equal(await page.locator('[data-custom-tier="0"]').getAttribute('data-custom-selected'),chosen);
  assert.equal(await page.locator('[data-custom-body]').isVisible(),true);
  await page.locator('[data-calculator-language="en"]').click();
  await page.waitForFunction(()=>document.documentElement.lang==='en');
  for (const filter of ['noOptical','noHighDrag','noRockets']) {
    await page.locator(`[data-optimizer-filter="${filter}"]`).click();
    assert.equal(await page.locator(`[data-optimizer-filter="${filter}"]`).getAttribute('aria-checked'),'false');
  }
  await mkdir('../.artifacts/calculator-ui',{recursive:true});
  for(const width of [1440,390,320]) {
    await page.setViewportSize({width,height:1000});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,`overflow at ${width}`);
    for (const button of await page.locator('#calculatorLanguage button').all()) {
      const box = await button.boundingBox();
      assert.ok(box && box.x >= 0 && box.x + box.width <= width && box.y >= 0 && box.y + box.height <= 1000, `language control stays reachable at ${width}`);
    }
    if (width < 1280) {
      await page.locator('#toolDirectoryToggle').click();
      const menu = await page.locator('#toolDirectoryLinks').boundingBox();
      assert.ok(menu && menu.x >= 0 && menu.x + menu.width <= width && menu.y >= 0 && menu.y + menu.height <= 1000, `jump menu stays within viewport at ${width}`);
      await page.locator('#toolDirectoryLinks a[href="#calcForm"]').click();
      assert.equal(await page.locator('#toolDirectoryToggle').getAttribute('aria-expanded'),'false');
    }
    await page.screenshot({path:`../.artifacts/calculator-ui/locale-en-${width}.png`,fullPage:true});
  }
  const untranslated=await page.locator('body').evaluate(body=>{
    const walker=document.createTreeWalker(body,NodeFilter.SHOW_TEXT), result=[];
    while(walker.nextNode()) {const node=walker.currentNode, element=node.parentElement;
      if(/[\u3400-\u9fff]/u.test(node.textContent)&&element.checkVisibility()&&!element.closest('#calculatorLanguage,script,noscript')) result.push(node.textContent.trim());}
    return result;
  });
  console.log('Remaining visible Chinese:',untranslated);
  assert.deepEqual(untranslated,[]);
  await page.reload();
  await page.waitForFunction(()=>document.documentElement.lang==='en');
  assert.equal(await page.locator('[data-calculator-language="en"]').getAttribute('aria-pressed'),'true');
  await page.locator('#toolDirectoryToggle').click();
  await page.locator('[data-calculator-language="zh-Hant"]').click();
  await page.waitForFunction(()=>document.documentElement.lang==='zh-Hant');
  assert.equal(await page.locator('[data-calculator-language="zh-Hant"]').getAttribute('aria-pressed'),'true');
  await page.locator('#toolDirectoryLinks').screenshot({path:'../.artifacts/calculator-ui/language-directory-mobile.png'});
  await page.setViewportSize({width:1440,height:1000});
  await page.locator('#toolDirectoryLinks').screenshot({path:'../.artifacts/calculator-ui/language-directory-desktop.png'});
  assert.deepEqual(errors,[]);
  console.log('Calculator locales passed: all languages, live results, preserved custom stores, pinyin, filters, persistence and layouts.');
} finally {await browser.close();await new Promise(done=>server.close(done));}
