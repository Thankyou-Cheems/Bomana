import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import loadHighs from 'highs';
import {optimizeLoadout, createOptimizerSession, preferRecommendation} from '../../docs/calculator/loadout-optimizer.mjs';
import {rewardUi, empiricalSimScore} from '../../docs/calculator/model.mjs';
import {normalizeGuidanceSelection, toggleRecommendationFilter, weaponGuidanceKind} from '../../docs/calculator/recommendation-guidance.mjs';
const highs = await loadHighs();
const json = async file => JSON.parse(await readFile(new URL(`../../docs/api/v1/calculator/${file}.json`, import.meta.url)));
const catalog = await json('index'), data = await json('weapons'), loadouts = await json('loadouts');
const weapons = new Map(data.weapons.map(row => [row.id,row]));
const base = {lockedKeys:[],weapons,reward:catalog.reward,filters:{strictReward:true},mode:'custom_targets'};
const run = (input,N) => optimizeLoadout({...base,...input,targetCount:N},highs);
const preset = (id,items) => ({id,weapons:items,cells:items.map(([weapon,count]) => ({weapon,count,icon:'bombs_small',tier:1}))});
function checkPlan(result,map,hp) {
  assert.ok(['optimal','feasible'].includes(result.status),JSON.stringify(result));
  assert.equal(result.plan.length,result.targets);
  const used = new Map();
  for (const row of result.plan) {
    assert.ok(row.reduce((sum,[id,n])=>sum+map.get(id).dmg*n,0)>=hp-1e-7);
    for (const [id,n] of row) { assert.ok(Number.isSafeInteger(n)&&n>0); used.set(id,(used.get(id)||0)+n); }
  }
  for (const [id,n] of used) assert.ok(n<=result.preset.weapons.find(([weapon])=>weapon===id)[1]);
}

test('Tu-4 actual complete native presets meet N=1/3/4/max and optimize the full-carried curve at different HP',()=>{
  const presets = loadouts.aircraft.tu_4;
  for (const threshold of [3600,23310]) {
    const rows = presets.map(row=>{
      assert.equal(row.weapons.length,1);
      const [id,count]=row.weapons[0],weapon=weapons.get(id);
      return {row,capacity:Math.floor(count/Math.ceil(threshold/weapon.dmg)),reward:rewardUi(catalog.reward,row.rewardDamage)};
    });
    const maximum=Math.max(...rows.map(row=>row.capacity));
    for (const N of [...new Set([1,3,4,maximum,maximum+1])]) {
      const result=run({presets,threshold},N);checkPlan(result,weapons,threshold);
      const reachable=Math.min(N,maximum);
      assert.equal(result.targets,reachable);assert.equal(result.targetReached,N<=maximum);
      assert.equal(result.coverageProven,true);assert.equal(result.status,'optimal');
      assert.ok(Math.abs(result.reward-Math.max(...rows.filter(row=>row.capacity>=reachable).map(row=>row.reward)))<1e-8);
      assert.equal(result.totalReward,reachable*result.reward);
      assert.equal(result.estimatedSorties,Math.ceil(N/reachable));
    }
  }
});

test('requested N is a hard floor even when one zone gives a better coefficient or total reward',()=>{
  const map=new Map([['small',{dmg:100,rewardDmg:100,mass:1}],['large',{dmg:100000,rewardDmg:100000,mass:10}]]);
  const presets=[preset('single',[['small',1]]),preset('three',[['large',3]])];
  const result=run({presets,weapons:map,threshold:100},3);
  assert.equal(result.targets,3);assert.equal(result.preset.id,'three');
  assert.ok(result.totalReward<rewardUi(catalog.reward,100));
  assert.equal(run({presets,weapons:map,threshold:100},4).targets,3);
});

test('custom N compares the real first-knot reward jump and does not claim reachability when the bound is unresolved',()=>{
  const map=new Map([['below',{dmg:120000,rewardDmg:199000/3}],['above',{dmg:120000,rewardDmg:200000/3}]]);
  const input={presets:[preset('below',[['below',3]]),preset('above',[['above',3]])],weapons:map,threshold:100000};
  assert.equal(run(input,3).preset.id,'above');
  const unknown=optimizeLoadout({...base,...input,targetCount:3},{solve(){return {Status:'Unknown'};}});
  assert.equal(unknown.status,'unknown');assert.equal(unknown.preset,undefined);
});

test('indivisible oversized bombs cannot satisfy two zones; mixed integer allocations and locks remain legal',()=>{
  const map=new Map([['oversized',{dmg:500,rewardDmg:500}],['a',{dmg:60,rewardDmg:60}],['b',{dmg:40,rewardDmg:40}]]);
  const result=run({presets:[preset('large',[['oversized',1]])],weapons:map,threshold:100},4);
  assert.equal(result.targets,1);assert.equal(result.targetUpper,1);
  const limits={maxloadMass:-1,maxloadMassLeftConsoles:-1,maxloadMassRightConsoles:-1,maxDisbalance:-1};
  const option=(tier,id)=>({...preset(id,[[id,3]]),key:`${tier}:${id}`,tier,slot:tier,preset:id,mass:3,requires:[],bans:[]});
  const definition={columns:2,center:[],limits,options:[option(0,'a'),option(1,'b')]};
  const mixed=run({definition,weapons:map,threshold:100,lockedKeys:['0:a']},3);
  checkPlan(mixed,map,100);assert.equal(mixed.targets,3);assert.ok(mixed.keys.includes('0:a'));
  for(const row of mixed.plan)assert.deepEqual(new Map(row),new Map([['a',1],['b',1]]));
});

test('equal coefficient prefers less surplus and then carried mass, without counting spare capacity',()=>{
  const map=new Map([['a',{dmg:100,rewardDmg:100,mass:1}],['b',{dmg:80,rewardDmg:80,mass:1}],['c',{dmg:100,rewardDmg:100,mass:2}]]);
  const result=run({presets:[preset('spare',[['a',40]]),preset('mixed',[['a',1],['b',3]]),preset('heavy',[['c',3]]),preset('light',[['a',3]])],weapons:map,threshold:100},3);
  assert.equal(result.preset.id,'light');assert.equal(result.totalReward,30);
  assert.ok(preferRecommendation({...result,damage:300,mass:3},{...result,damage:340,mass:1,simplicity:{types:1,profiles:1}}));
  assert.equal(preferRecommendation({...result,damage:300,simplicity:{types:2,profiles:2}},{...result,damage:340,simplicity:{types:1,profiles:1}},{simpleLoadout:true}),false,'Explicit uniform preference stays ahead of the damage tie');
});

test('huge requests use the proven bound; invalid counts do not enter the solver; session reuses proven N results',()=>{
  let solves=0;
  const counted={solve(...args){solves++;return highs.solve(...args);}};
  const input={...base,presets:loadouts.aircraft.tu_4,threshold:23310};
  const session=createOptimizerSession(input,counted),start=performance.now();
  const three=session({mode:'custom_targets',targetCount:3});
  const afterThree=solves;
  assert.equal(session({mode:'custom_targets',targetCount:3}),three);assert.equal(solves,afterThree);
  const four=session({mode:'custom_targets',targetCount:4});checkPlan(four,weapons,23310);
  const huge=session({mode:'custom_targets',targetCount:1e9});assert.ok(huge.targets<100);assert.equal(huge.coverageProven,true);
  assert.ok(performance.now()-start<10000,'native N switches should stay bounded');
  for(const targetCount of [0,-1,1.5,NaN,Infinity,'3']) {
    const before=solves;assert.equal(session({mode:'custom_targets',targetCount}).status,'invalid');assert.equal(solves,before);
  }
  console.log(`Tu-4 session 3/4/huge: ${Math.round(performance.now()-start)}ms, ${solves} bounded solver calls; cached N: zero calls`);
});

test('guidance tri-state preserves legacy onlyGuided, excludes unknowns and complete mixed rows, and keeps manual conflicts',()=>{
  const restored=normalizeGuidanceSelection({onlyGuided:true,noGuided:true});
  assert.equal(restored.onlyGuided,true);assert.equal(restored.noGuided,false);
  assert.equal(restored.noHighDrag,true);assert.equal(restored.noRockets,true);
  const staleUnguided=normalizeGuidanceSelection({noGuided:true,noLaser:false,noOptical:false,noSatellite:false,noManual:false,noMissiles:false});
  for(const key of ['noLaser','noOptical','noSatellite','noManual','noMissiles'])assert.equal(staleUnguided[key],true,'Legacy unguided selection repairs contradictory saved child switches');
  assert.equal(normalizeGuidanceSelection({onlyGuided:false}).noGuided,false);
  assert.equal(toggleRecommendationFilter({onlyGuided:true,noGuided:false},'noGuided').onlyGuided,false);
  assert.equal(toggleRecommendationFilter({onlyGuided:false,noGuided:true},'onlyGuided').noGuided,false);
  const map=new Map([['plain',{dmg:100,rewardDmg:100,deliveryProfile:{guidance:'none'}}],['guided',{dmg:100,rewardDmg:100,guidanceModes:['satellite']}],['unknown',{dmg:100,rewardDmg:100}]]);
  assert.equal(weaponGuidanceKind(map.get('unknown')),'unknown');
  const presets=[preset('mixed',[['plain',1],['guided',1]]),preset('guided',[['guided',3]]),preset('unknown',[['unknown',3]]),preset('plain',[['plain',3]])];
  for(const mode of ['reward','targets','custom_targets','sim_score']){
    const result=optimizeLoadout({...base,presets,weapons:map,threshold:100,targetCount:3,mode,filters:{noGuided:true},scenario:{aircraftId:'test',targetId:'airport_dwelling',roomMaxBr:10.7,remainingHp:300}},highs);
    assert.equal(result.preset.id,'plain',mode);
  }
  const limits={maxloadMass:-1,maxloadMassLeftConsoles:-1,maxloadMassRightConsoles:-1,maxDisbalance:-1};
  const options=['guided','plain'].map((id,tier)=>({...preset(id,[[id,1]]),key:`${tier}:${id}`,tier,slot:tier,preset:id,mass:1,requires:[],bans:[]}));
  const result=run({definition:{columns:2,center:[],limits,options},weapons:map,threshold:100,lockedKeys:['0:guided'],filters:{noGuided:true}},2);
  assert.deepEqual(result.keys,['0:guided','1:plain']);
});

test('airport module recommendation matches finite-preset empirical scores for runway and auxiliary HP including partial HP caps',()=>{
  const presets=loadouts.aircraft.tu_4;
  for(const remainingHp of [160000,280000,50000,1000]) {
    const scenario={aircraftId:'tu_4',targetId:remainingHp===280000?'airport_airfield':'airport_storage',roomMaxBr:10.7,remainingHp};
    const result=optimizeLoadout({...base,presets,mode:'sim_score',threshold:null,scenario},highs);
    const expected=Math.max(...presets.map(row=>empiricalSimScore({...scenario,carried:row.weapons,weapons,reward:catalog.reward}).score));
    assert.equal(result.status,'optimal');assert.ok(Math.abs(result.score-expected)<1e-7);
    assert.ok(result.estimate.acceptedDamage<=remainingHp);assert.deepEqual(result.plan,[result.preset.weapons]);
  }
});
