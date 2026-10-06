import test from "node:test";
import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import loadHighs from "highs";
import {optimizeLoadout, preferRecommendation} from "../../docs/calculator/loadout-optimizer.mjs";
import {validateLoadout} from "../../docs/calculator/custom-loadouts.mjs";
import {rewardUi} from "../../docs/calculator/model.mjs";
import {deliveryGroup} from "../../docs/calculator/loadout-simplicity.mjs";
import {availableGuidanceModes, guidanceExcluded, toggleRecommendationFilter, guidanceBurden, preferredGuidanceMode} from "../../docs/calculator/recommendation-guidance.mjs";

const highs = await loadHighs();
const catalog = JSON.parse(await readFile(new URL("../../docs/api/v1/calculator/index.json", import.meta.url)));
const weaponData = JSON.parse(await readFile(new URL("../../docs/api/v1/calculator/weapons.json", import.meta.url)));
const customData = JSON.parse(await readFile(new URL("../../docs/api/v1/calculator/custom-loadouts.json", import.meta.url)));
const presetData = JSON.parse(await readFile(new URL("../../docs/api/v1/calculator/loadouts.json", import.meta.url)));
const weapons = new Map(weaponData.weapons.map(row => [row.id, row]));
const limits = {maxloadMass: -1, maxloadMassLeftConsoles: -1, maxloadMassRightConsoles: -1, maxDisbalance: -1};
const option = (tier, id, count = 1, extra = {}) => ({key: `${tier}:${id}`, slot: tier, tier, preset: id, weapons: [[id, count]], mass: count,
  cells: [{weapon: id, count, icon: "bombs_small", tier: tier + 1}], requires: [], bans: [], modifications: [], requiredWeapons: [], ...extra});
const run = (definition, weaponMap, mode = "reward", lockedKeys = [], threshold = 100) => optimizeLoadout({definition, presets: [], lockedKeys, weapons: weaponMap, threshold, mode, reward: catalog.reward}, highs);

test("guidance selection and child switches stay synchronized in either direction", () => {
  const families = ['noLaser', 'noOptical', 'noSatellite', 'noManual'];
  let filters = toggleRecommendationFilter({}, 'onlyGuided');
  assert.equal(filters.noHighDrag, true);
  assert.equal(filters.noRockets, true);
  assert.equal(filters.noMissiles, false);
  for (const key of families) assert.equal(filters[key], false);
  filters = toggleRecommendationFilter(filters, 'noRockets');
  assert.equal(filters.onlyGuided, false, 'Allowing unguided rockets leaves guided-only');
  filters = toggleRecommendationFilter(filters, 'noGuided');
  for (const key of families) assert.equal(filters[key], true);
  assert.equal(filters.noMissiles, true);
  filters = toggleRecommendationFilter(filters, 'noManual');
  assert.equal(filters.noGuided, false, 'Allowing manual command guidance leaves unguided-only');
  assert.equal(filters.noManual, false);
  filters = toggleRecommendationFilter(filters, 'noManual');
  assert.equal(filters.noGuided, true, 'Closing the last guidance family selects unguided-only');
  filters = toggleRecommendationFilter(filters, 'noMissiles');
  assert.equal(filters.noGuided, false);
  for (const key of families) assert.equal(filters[key], false, 'Enabling missiles restores their guidance families');
});

test("guided-only recommendations filter complete presets and completions while preserving manual stations", () => {
  const map = new Map([
    ['plain',{kind:'bomb',dmg:100,deliveryProfile:{guidance:'none'}}],
    ['satellite',{kind:'bomb',dmg:110,satelliteGuidance:true,guidanceModes:['satellite']}],
    ['laser',{kind:'bomb',dmg:120,sensorOnlyGuidance:true,guidanceModes:['laser']}],
    ['command',{kind:'missile',dmg:130}],
  ]);
  const presets = [...map].map(([id]) => ({...option(0,id),id}));
  presets.push({...option(0,'mixed'),id:'mixed',weapons:[['satellite',1],['plain',1]]});
  for (const mode of ['reward','targets']) for (const guided of ['satellite','laser','command']) {
    const choices = presets.filter(row => ['plain','mixed',guided].includes(row.id));
    const definition = {columns:1,center:[0],limits,options:choices};
    const input = {presets:choices,lockedKeys:[],weapons:map,threshold:100,mode,reward:catalog.reward,filters:{onlyGuided:true}};
    for (const custom of [null,definition]) {
      const result = optimizeLoadout({...input,definition:custom},highs);
      assert.deepEqual(result.preset.weapons,[[guided,1]]);
    }
    const locked = optimizeLoadout({...input,definition,lockedKeys:['0:plain']},highs);
    assert.ok(locked.keys.includes('0:plain'));
  }
});

test("guidance switches use available multimode routes and cannot leave guided-only with all families excluded", () => {
  let filters = {onlyGuided:true,noLaser:false,noOptical:false,noSatellite:false,noManual:false};
  for (const key of ['noLaser','noOptical','noSatellite','noManual']) filters = toggleRecommendationFilter(filters,key);
  assert.equal(filters.onlyGuided,false);
  filters = toggleRecommendationFilter(filters,'onlyGuided');
  assert.equal(filters.onlyGuided,true);assert.equal(filters.noGuided,false);
  for (const key of ['noLaser','noOptical','noSatellite','noManual']) assert.equal(filters[key],false);
  const dual = {guidanceModes:['satellite','infrared']};
  assert.deepEqual(availableGuidanceModes(dual,{noSatellite:true}),['infrared']);
  assert.equal(guidanceExcluded(dual,{noOptical:true}),false);
  assert.equal(guidanceExcluded(dual,{noOptical:true,noSatellite:true}),true);
  assert.equal(guidanceBurden(dual,{noSatellite:true}),1);
  assert.equal(guidanceBurden(dual,{noOptical:true}),0);
  assert.equal(preferredGuidanceMode(dual,{noSatellite:true}),'infrared');
  assert.equal(preferredGuidanceMode(dual,{noOptical:true}),'satellite');
});

test("manual command guidance uses native evidence and every recommendation objective respects the same exclusions", () => {
  for (const id of ['de_fx1400','su_kh_23m','us_agm_12b_bullpup']) assert.deepEqual(weapons.get(id).guidanceModes,['manual'],id);
  const fritz=weapons.get('de_fx1400');
  assert.equal(fritz.deliveryProfile.guidance,'manual');
  assert.notEqual(deliveryGroup('manual',fritz),deliveryGroup('plain',{...fritz,guidanceModes:[],deliveryProfile:{...fritz.deliveryProfile,guidance:'none'}}),'Uniform-loadout preferences distinguish manual steering from unguided delivery');
  assert.equal(weapons.get('su_9m114').guidanceModes.includes('manual'),false,'SACLOS is not manual steering');
  const manual={kind:'missile',dmg:110,rewardDmg:110,guidanceModes:['manual']};
  const plain={kind:'bomb',dmg:100,rewardDmg:100,deliveryProfile:{guidance:'none'}};
  assert.equal(guidanceExcluded(manual,{noManual:true}),true);
  assert.equal(guidanceExcluded({kind:'missile',guidanceModes:[]},{noManual:true}),true,'Unknown family cannot bypass a category exclusion');
  assert.deepEqual(availableGuidanceModes({guidanceModes:['unrecognized']},{}),[]);
  assert.equal(preferredGuidanceMode(manual,{}),'manual');
  const map=new Map([['manual',manual],['plain',plain]]);
  const presets=['manual','plain'].map(id=>({id,weapons:[[id,1]],columns:1,cells:[],mass:1}));
  for(const mode of ['reward','targets','custom_targets','sim_score']){
    const result=optimizeLoadout({presets,lockedKeys:[],weapons:map,threshold:100,targetCount:1,mode,reward:catalog.reward,
      scenario:{aircraftId:'test',targetId:'airport_dwelling',roomMaxBr:10.7,remainingHp:100},filters:{noManual:true}},highs);
    assert.equal(result.preset.id,'plain',mode);
  }
  const definition={columns:2,center:[],limits,options:[option(0,'manual'),option(1,'plain')]};
  const result=optimizeLoadout({definition,presets:[],lockedKeys:['0:manual'],weapons:map,threshold:200,mode:'reward',reward:catalog.reward,filters:{noManual:true}},highs);
  assert.deepEqual(result.keys,['0:manual','1:plain'],'Manual station locks survive category exclusions');
});

test("fixed-target recommendations combine coordinate weapons with IR top-up and keep TV as a fallback", () => {
  const map = new Map([
    ['coordinate',{kind:'bomb',dmg:70,rewardDmg:40,guidanceModes:['satellite']}],
    ['ir',{kind:'missile',dmg:30,rewardDmg:0,guidanceModes:['infrared']}],
    ['tv',{kind:'missile',dmg:110,rewardDmg:0,guidanceModes:['tv']}],
  ]);
  const options = [option(0,'coordinate'),option(1,'ir'),option(0,'tv')];
  const definition = {columns:2,center:[0,1],limits,options};
  const presets = [{...option(0,'tv'),id:'tv'}, {...option(0,'mix'),id:'mix',weapons:[['coordinate',1],['ir',1]]}];
  for (const mode of ['reward','targets']) for (const custom of [null,definition]) {
    const input = {definition:custom,presets,lockedKeys:[],weapons:map,threshold:100,mode,reward:catalog.reward,filters:{onlyGuided:true}};
    const result = optimizeLoadout(input,highs);
    assert.deepEqual(result.preset.weapons,[['coordinate',1],['ir',1]]);
    assert.equal(result.reward,10);
    assert.equal(result.workload.designation,1);
    const tv = optimizeLoadout({...input,filters:{onlyGuided:true,noSatellite:true}},highs);
    assert.deepEqual(tv.preset.weapons,[['tv',1]]);
    assert.equal(optimizeLoadout({...input,filters:{onlyGuided:true,noOptical:true}},highs).status,'infeasible');
  }
});

test("same-source AGM-130 variants follow native modes instead of aircraft exceptions", () => {
  assert.deepEqual(weapons.get('su_kh_29t').guidanceModes,['tv']);
  assert.deepEqual(weapons.get('us_2000lb_agm_130a_12').guidanceModes,['satellite','infrared']);
  const definition = {columns:1,center:[0],limits,options:[option(0,'us_2000lb_agm_130a_12',3)]};
  const input = {definition,presets:[],lockedKeys:[],weapons,threshold:23310,mode:'reward',reward:catalog.reward};
  assert.ok(optimizeLoadout({...input,filters:{onlyGuided:true,noOptical:true}},highs).preset);
  const optical = optimizeLoadout({...input,filters:{onlyGuided:true,noSatellite:true}},highs);
  assert.ok(optical.preset);
  assert.ok(optical.workload.designation>0);
  assert.equal(optimizeLoadout({...input,filters:{onlyGuided:true,noSatellite:true,noOptical:true}},highs).status,'infeasible');
});

test("air-dropped mines remain eligible in native presets and custom completions", () => {
  const mineIds = weaponData.weapons.filter(weapon=>weapon.id.includes('_mine_')).map(weapon=>weapon.id);
  assert.ok(mineIds.includes('us_mine_mk13_mod0'));
  for (const id of mineIds) {
    const mine = weapons.get(id);
    assert.ok(mine?.dmg > 0, `${id} must have calculable damage`);
    assert.equal(mine.kind,'bomb');
    assert.equal(mine.role,'strike');
    const preset = Object.values(presetData.aircraft).flat().find(row=>row.weapons.length === 1 && row.weapons[0][0] === id);
    assert.ok(preset,`${id} must remain in native presets`);
    for (const mode of ['reward','targets']) {
      const result=optimizeLoadout({definition:null,presets:[preset],lockedKeys:[],weapons,threshold:mine.dmg,mode,reward:catalog.reward,filters:{noMissiles:true,noRockets:true,noLaser:true,noOptical:true,simpleLoadout:true}},highs);
      assert.ok(result.preset,`${id}:${mode}`);
      assert.ok(result.damage >= mine.dmg);
    }
  }
  const definition=Object.values(customData.aircraft).find(row=>row.options.some(option=>option.weapons.some(([id])=>id==='us_mine_mk13_mod0')));
  assert.ok(definition);
  const mineOption=definition.options.find(option=>option.weapons.some(([id])=>id==='us_mine_mk13_mod0'));
  const result=run(definition,weapons,'reward',[mineOption.key],weapons.get('us_mine_mk13_mod0').dmg);
  assert.ok(result.keys.includes(mineOption.key));
  assert.equal(validateLoadout(definition,result.keys).valid,true);
});

test("equal maximum rewards prefer fewer ammunition types before surplus damage", () => {
  const definition = {columns:3,center:[1],limits,options:[option(0,'a'),option(1,'b'),option(2,'c'),option(0,'uniform')]};
  const map = new Map([['a',{dmg:40}],['b',{dmg:30}],['c',{dmg:30}],['uniform',{dmg:110}]]);
  assert.deepEqual(run(definition,map).keys,['0:uniform']);
  const input = {definition,presets:[],lockedKeys:[],weapons:map,threshold:100,mode:'reward',reward:catalog.reward,filters:{simpleLoadout:true}};
  const simple = optimizeLoadout(input,highs);
  assert.deepEqual(simple.keys,['0:uniform']);
  assert.equal(simple.simplicity.types,1);
  const most = optimizeLoadout({...input, mode:'targets'},highs);
  assert.equal(most.targets,1);
  assert.equal(most.simplicity.types,1);
  const presets = [{...option(0,'a'),id:'mixed',weapons:[['a',1],['b',1],['c',1]]},{...option(0,'uniform'),id:'uniform'}];
  assert.equal(optimizeLoadout({...input,definition:null,presets},highs).presetId,'uniform');
});

test("near-cap rewards prefer uniform delivery while strict reward and lower bands preserve yield", () => {
  const map = new Map([['a',{dmg:9000}],['b',{dmg:9000}],['uniform',{dmg:18400}]]);
  const definition = {columns:2,center:[0,1],limits,options:[option(0,'a'),option(1,'b'),option(0,'uniform')]};
  const input = {definition,presets:[],lockedKeys:[],weapons:map,threshold:18000,mode:'reward',reward:catalog.reward};
  const balanced = optimizeLoadout(input,highs);
  assert.deepEqual(balanced.keys,['0:uniform']);
  assert.ok(balanced.reward >= 9.8 && balanced.reward < 10);
  assert.equal(balanced.maximumReward,10);
  assert.deepEqual(optimizeLoadout({...input,filters:{strictReward:true}},highs).keys,['0:a','1:b']);
  const lower = new Map([...map, ['uniform',{dmg:18800}]]);
  assert.deepEqual(optimizeLoadout({...input,weapons:lower},highs).keys,['0:a','1:b']);
  assert.deepEqual(optimizeLoadout({...input,weapons:lower,filters:{simpleLoadout:true}},highs).keys,['0:uniform']);
});

test("matching bomb delivery groups outrank fewer types with different delivery behavior", () => {
  const bomb = {kind:'bomb',dmg:6000,deliveryProfile:{guidance:'none',drag_area_mass:.001,area_mass:.01}};
  const map = new Map([['a',bomb],['b',bomb],['c',bomb],['rocket',{kind:'rocket',dmg:9000}],['missile',{kind:'missile',dmg:9000}]]);
  const presets = [{id:'same-bombs',weapons:[['a',1],['b',1],['c',1]],cells:[]}, {id:'mixed-powered',weapons:[['rocket',1],['missile',1]],cells:[]}];
  const result = optimizeLoadout({definition:null,presets,lockedKeys:[],weapons:map,threshold:18000,mode:'reward',reward:catalog.reward},highs);
  assert.equal(result.presetId,'same-bombs');
  assert.deepEqual(result.simplicity,{types:3,profiles:1});
});

test("simple completion keeps user stores and favors compatible bomb profiles", () => {
  const bomb = {kind:'bomb',dmg:60,deliveryProfile:{guidance:'none',drag_area_mass:.001,area_mass:.01}};
  const map = new Map([['locked',{...bomb,dmg:40}],['similar',bomb],['different',{...bomb,highDrag:true}]]);
  const definition = {columns:2,center:[0,1],limits,options:[option(0,'locked'),option(1,'different'),option(1,'similar')]};
  const result = optimizeLoadout({definition,presets:[],lockedKeys:['0:locked'],weapons:map,threshold:100,mode:'reward',reward:catalog.reward,filters:{simpleLoadout:true}},highs);
  assert.deepEqual(result.keys,['0:locked','1:similar']);
  assert.deepEqual(result.simplicity,{types:2,profiles:1});
  assert.notEqual(deliveryGroup('a',{...bomb,deliveryProfile:null}),deliveryGroup('b',{...bomb,deliveryProfile:null}));
  assert.notEqual(deliveryGroup('a',bomb),deliveryGroup('b',{...bomb,satelliteGuidance:true}));
  assert.notEqual(deliveryGroup('a',bomb),deliveryGroup('b',{...bomb,deliveryProfile:{...bomb.deliveryProfile,drag_area_mass:.01}}));
  assert.notEqual(deliveryGroup('a',bomb),deliveryGroup('b',{...bomb,deliveryProfile:{...bomb.deliveryProfile,lift_scale:20}}));
});

test("simple loadouts retain maximum target coverage and reject impossible locked completions", () => {
  const definition = {columns:2,center:[0,1],limits,options:[option(0,'a'),option(1,'b')]};
  const input = {definition,presets:[],lockedKeys:[],weapons:new Map([['a',{dmg:110}],['b',{dmg:110}]]),threshold:100,mode:'targets',reward:catalog.reward,filters:{simpleLoadout:true}};
  const result = optimizeLoadout(input,highs);
  assert.equal(result.targets,2);
  assert.deepEqual(result.simplicity,{types:2,profiles:2});
  assert.equal(result.singleZone.targets,1);
  assert.equal(result.singleZone.simplicity.types,1);
  assert.equal(optimizeLoadout({...input,lockedKeys:['missing']},highs).status,'infeasible');
});

test("timed worker results retain simplicity priority before rewards", () => {
  const quick = {preset:{},targets:1,reward:10,damage:100,mass:10,simplicity:{types:4,profiles:3}};
  const full = {...quick,reward:8,simplicity:{types:1,profiles:1}};
  assert.equal(preferRecommendation(quick,full,{simpleLoadout:true}),false);
  assert.equal(preferRecommendation(quick,full),true);
  assert.equal(preferRecommendation({...quick,targets:2},full,{simpleLoadout:true}),true);
  assert.equal(preferRecommendation({...quick,simplicity:{types:1,profiles:2}},full,{simpleLoadout:true}),false);
  assert.equal(preferRecommendation(quick,{status:'unknown'},{simpleLoadout:true}),true);
  assert.equal(preferRecommendation({status:'unknown'},full,{simpleLoadout:true}),false);
  const near = {...full,reward:9.9};
  assert.equal(preferRecommendation(near,quick),true);
  assert.equal(preferRecommendation(quick,near),false);
  assert.equal(preferRecommendation(quick,near,{strictReward:true}),true);
  assert.equal(preferRecommendation({...near,reward:9.79},quick),false);
  const manyLocks = {...quick,workload:{designation:3,shots:3}};
  const easier = {...near,simplicity:{types:5,profiles:4},workload:{designation:1,shots:2}};
  assert.equal(preferRecommendation(easier,manyLocks),true);
  assert.equal(preferRecommendation(easier,manyLocks,{strictReward:true}),false);
  assert.equal(preferRecommendation({...easier,reward:9.79},manyLocks),false);
});

test("reward-exempt strike weapons deal damage without lowering the bombing coefficient", () => {
  const definition = {columns: 2, center: [0, 1], limits, options: [option(0, "guided"), option(1, "bomb")]};
  const map = new Map([['guided', {dmg: 23000, rewardDmg: 0}], ['bomb', {dmg: 4000, rewardDmg: 4000}]]);
  const result = run(definition, map, "reward", [], 23310);
  assert.equal(result.damage, 27000);
  assert.equal(result.reward, 10);
});

test("quick filters omit only automatic candidates and preserve satellite multimode stores", () => {
  const definition = {columns: 1, center: [0], limits, options: [option(0,'laser'),option(0,'dual'),option(0,'drag'),option(0,'rocket')]};
  const map = new Map([['laser',{dmg:110,guidanceModes:['laser']}],['dual',{dmg:120,satelliteGuidance:true,guidanceModes:['laser','satellite']}],['drag',{dmg:105,highDrag:true}],['rocket',{dmg:101,kind:'rocket'}]]);
  const input={definition,presets:[],lockedKeys:[],weapons:map,threshold:100,mode:'reward',reward:catalog.reward,filters:{noLaser:true,noOptical:true,noHighDrag:true,noRockets:true}};
  assert.deepEqual(optimizeLoadout(input,highs).keys,['0:dual']);
  assert.deepEqual(optimizeLoadout({...input,lockedKeys:['0:laser']},highs).keys,['0:laser']);
});

test("native sensor filtering retains multimode GNSS variants", () => {
  assert.equal(weapons.get('us_gbu_12_paveway_2').sensorOnlyGuidance, true);
  for (const id of ['us_gbu_39', 'us_500lb_gbu_54b', 'fr_250kg_aasm_250_hammer_laser', 'fr_250kg_aasm_250_hammer_ir', 'su_kh_38ml']) {
    assert.equal(weapons.get(id).satelliteGuidance, true, id);
    assert.equal(weapons.get(id).sensorOnlyGuidance, false, id);
  }
});

test("real AGM-130 and Grom / KH-38 combinations retain the maximum reward", () => {
  for (const items of [[['us_2000lb_agm_130a_12',2],['us_gbu_39',2]],[['su_grom_2',2],['su_kh_38mt',3]]]) {
    const definition={columns:2,center:[0,1],limits,options:items.map(([id,count],tier)=>option(tier,id,count))};
    const result=run(definition,weapons,'reward',[],23310);
    assert.equal(result.reward,10);
    assert.ok(result.damage>=23310);
  }
});

test("real Su-34 automatic recommendations contain no AAM or anti-radiation stores", () => {
  const definition=customData.aircraft.su_34;
  const result=run(definition,weapons,'reward',[],23310);
  assert.ok(result.preset);
  for(const key of result.keys) for(const cell of definition.options.find(row=>row.key===key).cells) assert.ok(!['aam','arm'].includes(cell.role),cell.weapon);
});

test("non-strike options cannot be automatically added to improve the reward curve", () => {
  const definition = {columns: 2, center: [0, 1], limits, options: [option(0, "bomb"), option(1, "arm")]};
  const map = new Map([['bomb', {dmg: 199000}], ['arm', {dmg: 1000, role: 'arm'}]]);
  const result = run(definition, map, "reward", [], 190000);
  assert.deepEqual(result.keys, ['0:bomb']);
});

test("all excluded weapon roles are blocked in custom and mixed preset recommendations", () => {
  for (const role of ['aam', 'arm', 'ashm']) {
    const map = new Map([['bomb', {dmg:110}], ['excluded', {dmg:100, rewardDmg:0, role}], ['cell-only', {dmg:100,rewardDmg:0}]]);
    const bomb = option(0,'bomb'), excluded = option(0,'excluded');
    const definition = {columns:1,center:[0],limits,options:[bomb,excluded]};
    assert.deepEqual(run(definition,map).keys,[bomb.key],role);
    // Explicit user stores remain locked, as for every recommendation filter.
    assert.deepEqual(run(definition,map,'reward',[excluded.key]).keys,[excluded.key],role);
    const safe = {...bomb,id:'safe'}, mixed = {...excluded,id:'mixed',cells:[{weapon:'cell-only',role}],weapons:[['cell-only',1]]};
    const preset = optimizeLoadout({definition:null,presets:[safe,mixed],lockedKeys:[],weapons:map,threshold:100,mode:'reward',reward:catalog.reward},highs);
    assert.equal(preset.presetId,'safe',role);
  }
});

test("every catalog anti-radiation and anti-ship missile is excluded independently of aircraft", () => {
  const excluded = weaponData.weapons.filter(weapon=>['arm','ashm'].includes(weapon.role));
  assert.ok(excluded.some(weapon=>weapon.id==='us_agm_88c'&&weapon.role==='arm'));
  assert.ok(excluded.some(weapon=>weapon.id==='uk_alarm'&&weapon.role==='arm'));
  assert.ok(excluded.some(weapon=>weapon.id==='cn_cm_102'&&weapon.role==='arm'));
  assert.ok(excluded.some(weapon=>weapon.id==='us_agm_84d'&&weapon.role==='ashm'));
  assert.ok(excluded.some(weapon=>weapon.id==='su_kh_35u'&&weapon.role==='ashm'));
  assert.ok(excluded.some(weapon=>weapon.id==='jp_asm2'&&weapon.role==='ashm'));
  assert.equal(weapons.get('us_agm_84h_slam_er').role,'strike');
  for(const weapon of excluded) {
    const item=option(0,weapon.id);
    for(const mode of ['reward','targets']) assert.equal(run({columns:1,center:[0],limits,options:[item]},weapons,mode,[],1).status,'infeasible',weapon.id);
  }
  for(const definition of Object.values(customData.aircraft)) for(const option of definition.options) for(const cell of option.cells) {
    const role=weapons.get(cell.weapon)?.role;
    if(['arm','ashm'].includes(role)) assert.equal(cell.role,role,cell.weapon);
  }
});

test("more-zone recommendation compares total reward against a single zone", () => {
  const definition = {columns: 1, center: [0], limits, options: [option(0, 'small'), option(0, 'large', 2)]};
  const map = new Map([['small', {dmg: 24000}], ['large', {dmg: 200000}]]);
  const result = run(definition, map, 'targets', [], 23310);
  assert.equal(result.targets, 2);
  assert.equal(result.moreLoadoutUseful, false);
  assert.ok(result.singleZone.totalReward > result.totalReward);
});

test("single-zone optimum preserves selected stores and adds required pods under native constraints", () => {
  const a = option(0, "a", 1, {requires: [{slot: 1, preset: "pod"}], mass: 3});
  const pod = option(1, "pod", 0);
  const b = option(2, "b", 1, {mass: 3});
  const c = option(2, "c", 1, {mass: 4});
  const definition = {columns: 3, center: [1], limits: {maxloadMass: 8, maxloadMassLeftConsoles: 4, maxloadMassRightConsoles: 4, maxDisbalance: 1}, options: [a, pod, b, c]};
  const map = new Map([['a', {dmg: 60}], ['b', {dmg: 40}], ['c', {dmg: 65}], ['pod', {dmg: 1}]]);
  const result = run(definition, map, "reward", [a.key]);
  assert.equal(result.status, "optimal");
  assert.equal(result.damage, 100);
  assert.deepEqual(new Set(result.keys), new Set([a.key, pod.key, b.key]));
  assert.equal(validateLoadout(definition, result.keys).valid, true);
  const blocked = {...definition, options: [a, pod, {...b, bans: [{slot: 0, preset: "a"}]}, {...c, mass: 6}]};
  assert.equal(run(blocked, map, "reward", [a.key]).status, "infeasible");
});

test("most zones assigns indivisible bombs: three 80-HP bombs cover one 100-HP zone, not two", () => {
  const definition = {columns: 1, center: [0], limits, options: [option(0, "a", 3)]};
  const result = run(definition, new Map([['a', {dmg: 80}]]), "targets");
  assert.equal(result.status, "optimal");
  assert.equal(result.targets, 1);
  assert.deepEqual(result.plan, [[['a', 2]]]);
  const large = run({...definition, options: [option(0, "big")]}, new Map([['big', {dmg: 250}]]), "targets");
  assert.equal(large.targets, 1);
});

test("mixed per-zone allocation uses every weapon at most as many times as carried", () => {
  const definition = {columns: 2, center: [0, 1], limits, options: [option(0, "a", 3), option(1, "b", 3)]};
  const map = new Map([['a', {dmg: 60}], ['b', {dmg: 40}]]);
  const result = run(definition, map, "targets");
  assert.equal(result.targets, 3);
  for (const row of result.plan) assert.equal(row.reduce((sum, [id, count]) => sum + map.get(id).dmg * count, 0), 100);
});

test("rocket plans spend exact projectiles in each zone and report unused carried rounds", () => {
  const map = new Map([['rocket',{kind:'rocket',dmg:10}]]);
  const definition = {columns:1,center:[0],limits,options:[option(0,'rocket',28)]};
  const multi = run(definition,map,'targets');
  assert.equal(multi.targets,2);
  assert.deepEqual(multi.plan,[[['rocket',10]],[['rocket',10]]]);
  assert.deepEqual(multi.remaining,[['rocket',8]]);
  const single = run(definition,map);
  assert.deepEqual(single.plan,[[['rocket',10]]]);
  assert.deepEqual(single.remaining,[['rocket',18]]);
});

test("unknown weapon damage is excluded and cannot satisfy a locked requirement", () => {
  const definition = {columns: 1, center: [0], limits, options: [option(0, "unknown")]};
  assert.equal(run(definition, new Map(), "reward", ['0:unknown']).status, "infeasible");
});

test("the real reward-curve upward discontinuity is compared, not incorrectly pruned", () => {
  const definition = {columns: 1, center: [0], limits, options: [option(0, "below"), option(0, "above")]};
  const map = new Map([['below', {dmg: 199000}], ['above', {dmg: 200000}]]);
  const result = run(definition, map, "reward", [], 190000);
  assert.equal(result.damage, 200000);
  assert.ok(result.reward > rewardUi(catalog.reward, 199000));
});

test("fixed-only aircraft choose complete native presets instead of mixing their rows", () => {
  const map = new Map([['a', {dmg: 80, kg: 2}], ['b', {dmg: 60, kg: 1}], ['c', {dmg: 40, kg: 1}]]);
  const presets = [{id: 'three-a', weapons: [['a', 3]], cells: []}, {id: 'two-zones', weapons: [['b', 2], ['c', 2]], cells: []}];
  const result = optimizeLoadout({definition: null, presets, weapons: map, lockedKeys: [], threshold: 100, mode: 'targets', reward: catalog.reward}, highs);
  assert.equal(result.status, 'optimal');
  assert.equal(result.kind, 'preset');
  assert.equal(result.presetId, 'two-zones');
  assert.equal(result.targets, 2);
});

function bruteTargets(items, threshold) {
  const sums = Array(1 << items.length).fill(0), best = Array(sums.length).fill(0);
  for (let mask = 1; mask < sums.length; mask++) {
    for (let bit = 0; bit < items.length; bit++) if (mask & (1 << bit)) sums[mask] += items[bit];
    for (let sub = mask; sub; sub = (sub - 1) & mask) if (sums[sub] >= threshold) best[mask] = Math.max(best[mask], 1 + best[mask ^ sub]);
  }
  return best.at(-1);
}

test("both optimization modes match exhaustive option and bomb-allocation enumeration", () => {
  for (let seed = 1; seed <= 8; seed++) {
    const map = new Map([['a', {dmg: 31 + seed * 3}], ['b', {dmg: 54 + seed * 4}]]);
    const options = Array.from({length: 3}, (_, tier) => [option(tier, "a", 1 + (tier + seed) % 2), option(tier, "b")]).flat();
    const definition = {columns: 3, center: [1], limits, options};
    for (const mode of ["reward", "targets"]) {
      let expected = null;
      for (let encoded = 0; encoded < 27; encoded++) {
        let code = encoded; const selected = [];
        for (let tier = 0; tier < 3; tier++) { const pick = code % 3; code = Math.floor(code / 3); if (pick) selected.push(options[tier * 2 + pick - 1]); }
        const items = selected.flatMap(row => row.weapons.flatMap(([id, count]) => Array(count).fill(map.get(id).dmg)));
        const damage = items.reduce((sum, item) => sum + item, 0);
        const targets = mode === "reward" ? Number(damage >= 100) : bruteTargets(items, 100);
        if (!targets) continue;
        // Every enumerated loadout is below the reward cap. Unknown profiles
        // remain distinct, so the independent tie-break is distinct weapon IDs.
        const types = new Set(selected.flatMap(row => row.weapons.map(([id]) => id))).size;
        if (!expected || targets > expected.targets || targets === expected.targets &&
          (types < expected.types || types === expected.types && damage < expected.damage)) expected = {targets, types, damage};
      }
      const actual = run(definition, map, mode);
      assert.equal(actual.status, "optimal", `seed ${seed}, ${mode}`);
      assert.deepEqual({targets: actual.targets, types: actual.simplicity.types, damage: actual.damage}, expected, `seed ${seed}, ${mode}`);
    }
  }
});

test("real Typhoon locks survive both modes and every recommended configuration is valid", () => {
  const definition = customData.aircraft.ef_2000_typhoon_aesa;
  for (const mode of ["reward", "targets"]) {
    const result = run(definition, weapons, mode, ["11:mk18_slot11"], 23310);
    assert.ok(["optimal", "feasible"].includes(result.status), JSON.stringify(result));
    assert.ok(result.keys.includes("11:mk18_slot11"));
    assert.equal(validateLoadout(definition, result.keys).valid, true);
    assert.ok(result.plan.every(row => row.reduce((sum, [id, count]) => sum + weapons.get(id).dmg * count, 0) >= 23310 - 1e-8));
    console.log(`Typhoon ${mode}: ${result.status}, ${result.targets} zones, ${result.damage} HP`);
  }
});
