import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {measuredFuelBurn,fuelInputIssues,workflowIds,workflowFromHash} from '../../docs/calculator/workflow-model.mjs';
import {returnFuelPlan} from '../../docs/calculator/model.mjs';
const root=new URL('../../docs/calculator/',import.meta.url);
const read=file=>readFileSync(new URL(file,root),'utf8');

test('two readings yield an explicit measured burn without changing the return model',()=>{
 assert.deepEqual(measuredFuelBurn({startKg:1000,endKg:970,seconds:30}),{burnKgMin:60});
 assert.equal(measuredFuelBurn({startKg:1000,endKg:970,seconds:90}).burnKgMin,20);
 const plan=returnFuelPlan({fuelKg:1000,burnKgMin:60,groundSpeedKmh:720,distanceKm:36,routePercent:20,reserveMin:5});
 assert.ok(Math.abs(plan.tripMin-3.6)<1e-12);assert.equal(plan.requiredKg,516);assert.equal(plan.marginKg,484);
});
test('measurement blanks, equal/increasing fuel, invalid intervals and overflow do not produce results',()=>{
 for(const input of [{startKg:null,endKg:900,seconds:60},{startKg:900,endKg:900,seconds:60},{startKg:900,endKg:950,seconds:60},{startKg:1000,endKg:900,seconds:0},{startKg:1000,endKg:900,seconds:-1},{startKg:-1,endKg:0,seconds:60},{startKg:NaN,endKg:900,seconds:60},{startKg:Infinity,endKg:900,seconds:60},{startKg:Number.MAX_VALUE,endKg:0,seconds:Number.MIN_VALUE}])assert.ok(measuredFuelBurn(input).error,JSON.stringify(input));
});
test('fuel field checks distinguish optional current fuel, required blanks, zero distance and invalid values',()=>{
 const values={fuelKg:null,fuelBurn:60,fuelSpeed:720,fuelDistance:0,fuelRoute:0,fuelReserve:0};
 assert.deepEqual(fuelInputIssues(values),[]);
 assert.equal(fuelInputIssues({...values,fuelBurn:0})[0].reason,'fuelPositive');
 assert.equal(fuelInputIssues({...values,fuelDistance:-1})[0].reason,'fuelNonnegative');
 assert.equal(fuelInputIssues({...values,fuelBurn:null})[0].reason,'fuelMissing');
 assert.equal(fuelInputIssues({...values,fuelKg:NaN})[0].reason,'fuelInvalid');
});
test('all eight tools have stable hash routes; unrelated top routes stay unrelated',()=>{
 assert.equal(workflowIds.length,8);for(const id of workflowIds)assert.equal(workflowFromHash('#'+id),id);
 for(const hash of ['','#calcForm','#combinationCalculator','#content','#missing','#returnFuel?x'])assert.equal(workflowFromHash(hash),null);
});
test('new UI strings exist in all languages with matching substitutions',()=>{
 const base=JSON.parse(read('locales/zh-CN.json'));
 for(const locale of ['zh-Hant','en']){
  const other=JSON.parse(read(`locales/${locale}.json`));
  for(const key of Object.keys(base).filter(key=>key.startsWith('workflow.'))){assert.ok(other[key]);assert.deepEqual(other[key].match(/{{\w+}}/g)?.sort(),base[key].match(/{{\w+}}/g)?.sort());}
 }
 for(const file of ['workflows.mjs','workflow-model.mjs'])for(const match of read(file).matchAll(/t\("(workflow\.[^"]+)"/g))assert.ok(base[match[1]],match[1]);
});
