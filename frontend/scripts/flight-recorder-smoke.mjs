import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import { chromium } from "playwright-core";
import { createServer } from "vite";

const server=await createServer({server:{host:"127.0.0.1",port:0},plugins:[{name:"flight-recorder-fixture",configureServer(server){
  server.middlewares.use((req,res,next)=>{if(req.url!=="/flight-recorder-smoke")return next();res.setHeader("Content-Type","text/html");
    res.end('<!doctype html><title>Local recording regression</title><div id="settings"></div><span id="app-web-version">test</span>');});
}}]});
await server.listen();
const browser=await chromium.launch({channel:"msedge",headless:true});
try {
  const context=await browser.newContext({acceptDownloads:true}),page=await context.newPage();
  await page.goto(server.resolvedUrls.local[0]+"flight-recorder-smoke");
  const result=await page.evaluate(async()=>{
    const {mountFlightRecorder}=await import("/src/runtime/flight-recorder.ts");
    const recorder=mountFlightRecorder(document.getElementById("settings"),"Enhanced");
    const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
    const status=()=>document.querySelector('[data-recording-status]').textContent;
    for(let i=0;i<100&&!status().includes('自动记录中');i++)await wait(20);
    if(!status().includes('自动记录中'))throw new Error(status());
    const raw=at=>({sampledAtMs:at,bridgeReachable:true,state:{valid:true,'H, m':1500},indicators:{type:'jh_7'},
      mapInfo:{map_min:[-65536,-65536],map_max:[65536,65536],map_generation:2},
      mapObjects:[{type:'aircraft',icon:'Player',x:.3+at/1e9,y:.4,name:'DO_NOT_EXPORT_NAME'},
        {type:'point_of_interest',x:.056264,y:.910153}],gameChat:[{msg:'DO_NOT_EXPORT_CHAT'}],
      availability:{state:true,indicators:true,mapInfo:true,mapObjects:true}});
    const durations=[];
    for(let i=0;i<180;i++){
      const before=performance.now();recorder.record(raw(1_000_000+i*100),{phase:'alive',authorization:'DO_NOT_EXPORT_AUTH'});durations.push(performance.now()-before);
      await wait(2);
    }
    window.dispatchEvent(new Event('pagehide'));await wait(300);
    return {status:status(),maxPostMs:Math.max(...durations),meanPostMs:durations.reduce((a,b)=>a+b,0)/durations.length};
  });
  assert.match(result.status,/帧/);
  const download=page.waitForEvent("download");await page.locator('[data-recording-export]').click();
  const file=await (await download).path();
  const {readFile}=await import('node:fs/promises');const {gunzipSync}=await import('node:zlib');
  const exported=JSON.parse(await readFile(file,'utf8'));
  assert.equal(exported.schema,'bomana-flight-recording/v1');assert.ok(exported.chunks.length>=2);
  const decoded=exported.chunks.map(c=>{const bytes=Buffer.from(c.data,'base64');return(c.codec==='gzip'?gunzipSync(bytes):bytes).toString();}).join('');
  assert.doesNotMatch(decoded,/DO_NOT_EXPORT/);assert.match(decoded,/point_of_interest/);
  assert.ok(exported.chunks.reduce((n,c)=>n+c.frames,0)>100);
  const second=await context.newPage();await second.goto(server.resolvedUrls.local[0]+"flight-recorder-smoke");
  await second.evaluate(async()=>{const {mountFlightRecorder}=await import('/src/runtime/flight-recorder.ts');mountFlightRecorder(document.getElementById('settings'),'Standard');});
  await second.locator('[data-recording-status]').filter({hasText:'由另一页面记录'}).waitFor();
  await second.locator('[data-recording-clear]').click();
  await second.locator('[data-recording-status]').filter({hasText:'请在正在记录的页面清除'}).waitFor();
  await second.close();
  await page.reload();
  await page.evaluate(async()=>{const {mountFlightRecorder}=await import('/src/runtime/flight-recorder.ts');window.recorder=mountFlightRecorder(document.getElementById('settings'),'Enhanced');});
  await page.locator('[data-recording-status]').filter({hasText:/帧/}).waitFor();
  assert.match(await page.locator('[data-recording-status]').innerText(),/1[0-9][0-9] 帧/);
  await page.locator('[data-recording-status]').filter({hasText:'自动记录中'}).waitFor();
  await page.evaluate(async()=>{
    const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
    const frame={sampledAtMs:1_018_000,bridgeReachable:true,state:{valid:true},mapObjects:{objects:[{type:'player',x:.4,y:.5}]},mapInfo:null};
    window.recorder.record(frame);await wait(100);
    window.recorder.record({...frame,sampledAtMs:1_018_100,mapInfo:{map_min:[-65536,-65536],map_max:[65536,65536],map_generation:2}});
    await wait(100);window.dispatchEvent(new Event('pagehide'));await wait(200);
  });
  const resumedDownload=page.waitForEvent('download');await page.locator('[data-recording-export]').click();
  const resumed=JSON.parse(await readFile(await(await resumedDownload).path(),'utf8'));
  assert.equal(resumed.meta.session,exported.meta.session,'late map info must resume the prior recording');
  assert.equal(resumed.chunks.reduce((n,c)=>n+c.frames,0),exported.chunks.reduce((n,c)=>n+c.frames,0)+1);
  await page.clock.install({time:new Date(Date.now()+24*60*60*1000)});
  const laterDownload=page.waitForEvent('download');await page.locator('[data-recording-export]').click();
  const later=JSON.parse(await readFile(await(await laterDownload).path(),'utf8'));
  assert.deepEqual(later.chunks,resumed.chunks,'idle wall-clock time must preserve the last flight for later diagnosis');
  await page.evaluate(async()=>{
    const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
    const hangar={sampledAtMs:1_019_000,bridgeReachable:true,state:{valid:false},mapObjects:null,mapInfo:null,availability:{state:true,mapObjects:false}};
    window.recorder.record(hangar);await wait(100);window.dispatchEvent(new Event('pagehide'));await wait(150);
    window.recorder.record({...hangar,sampledAtMs:1_030_000});await wait(150);
  });
  const endedDownload=page.waitForEvent('download');await page.locator('[data-recording-export]').click();
  const ended=JSON.parse(await readFile(await(await endedDownload).path(),'utf8'));
  assert.equal(ended.meta.ended,true,'confirmed hangar must persist even after the preceding chunk was flushed');
  await page.reload();
  await page.evaluate(async()=>{const {mountFlightRecorder}=await import('/src/runtime/flight-recorder.ts');window.recorder=mountFlightRecorder(document.getElementById('settings'),'Enhanced');});
  await page.locator('[data-recording-status]').filter({hasText:'自动记录中'}).waitFor();
  await page.evaluate(async()=>{
    window.recorder.record({sampledAtMs:1_030_100,bridgeReachable:true,state:{valid:true},mapObjects:[{type:'player',x:.4,y:.5}],
      mapInfo:{map_min:[-65536,-65536],map_max:[65536,65536],map_generation:2}});
    await new Promise(resolve=>setTimeout(resolve,100));window.dispatchEvent(new Event('pagehide'));await new Promise(resolve=>setTimeout(resolve,150));
  });
  const freshDownload=page.waitForEvent('download');await page.locator('[data-recording-export]').click();
  const fresh=JSON.parse(await readFile(await(await freshDownload).path(),'utf8'));
  assert.notEqual(fresh.meta.session,ended.meta.session,'same-map reload after confirmed hangar starts a new recording');
  assert.equal(fresh.chunks.reduce((n,c)=>n+c.frames,0),1);
  await page.evaluate(async()=>{
    const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
    const hangar={sampledAtMs:1_031_000,bridgeReachable:true,state:{valid:false},mapObjects:null,mapInfo:null,availability:{state:true,mapObjects:false}};
    window.recorder.record(hangar);await wait(100);window.dispatchEvent(new Event('pagehide'));await wait(150);
    window.recorder.record({...hangar,sampledAtMs:1_042_000});await wait(150);
  });
  await page.locator('[data-recording-enabled]').uncheck();
  await page.locator('[data-recording-status]').filter({hasText:'已关闭'}).waitFor();
  await page.locator('[data-recording-enabled]').check();
  await page.locator('[data-recording-status]').filter({hasText:'自动记录中'}).waitFor();
  await page.evaluate(async()=>{
    window.recorder.record({sampledAtMs:1_042_100,bridgeReachable:true,state:{valid:true},mapObjects:[{type:'player',x:.4,y:.5}],
      mapInfo:{map_min:[-65536,-65536],map_max:[65536,65536],map_generation:2}});
    await new Promise(resolve=>setTimeout(resolve,100));
  });
  const reenabledDownload=page.waitForEvent('download');await page.locator('[data-recording-export]').click();
  const reenabled=JSON.parse(await readFile(await(await reenabledDownload).path(),'utf8'));
  assert.notEqual(reenabled.meta.session,fresh.meta.session,'re-enabling in the same page must not erase a confirmed ended marker before resume checks');
  assert.equal(reenabled.chunks.reduce((n,c)=>n+c.frames,0),1);
  await page.locator('[data-recording-clear]').click();
  await page.waitForFunction(()=>document.querySelector('[data-recording-status]').textContent.includes('0 帧'));
  await page.locator('[data-recording-enabled]').uncheck();
  await page.waitForFunction(()=>document.querySelector('[data-recording-status]').textContent.includes('已关闭'));
  await page.reload();
  await page.evaluate(async()=>{const {mountFlightRecorder}=await import('/src/runtime/flight-recorder.ts');mountFlightRecorder(document.getElementById('settings'),'Enhanced');});
  await page.waitForFunction(()=>document.querySelector('[data-recording-status]').textContent.includes('已关闭'));
  assert.equal(await page.locator('[data-recording-enabled]').isChecked(),false);
  await mkdir('../.artifacts/y66-live-20261009',{recursive:true});
  await writeFile('../.artifacts/y66-live-20261009/flight-recorder-export.json',JSON.stringify(exported));
  await writeFile('../.artifacts/y66-live-20261009/flight-recorder-browser.json',JSON.stringify(result,null,2));
  console.log(JSON.stringify({...result,chunks:exported.chunks.length,exportBytes:JSON.stringify(exported).length}));
}finally{await browser.close();await server.close();}
