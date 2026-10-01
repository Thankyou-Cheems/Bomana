import {readFileSync, writeFileSync} from 'node:fs';
import {Converter} from 'opencc-js';
const root = new URL('../../docs/calculator/locales/', import.meta.url);
const read = url => JSON.parse(readFileSync(url, 'utf8'));
const write = (name, data) => writeFileSync(new URL(name+'.json', root), JSON.stringify(data, null, 2)+'\n');
const traditional = Converter({from:'cn', to:'t'});
// Explicit UI resources remain independently editable. Only catalog names are
// generated when parameters change; English comes from the same game source.
const api = new URL('../../docs/api/v1/calculator/', import.meta.url);
const names = {}, english = {};
const add = (zh, en) => {if (!zh) return; names[zh] = traditional(zh); if(en) english[zh] = en;};
for (const row of read(new URL('weapons.json', api)).weapons) {add(row.name,row.name_en);add(row.short,row.short_en);}
for (const row of read(new URL('aircraft.json', api)).aircraft) {add(row.name,row.name_en);add(row.long,row.name_en);}
for (const row of read(new URL('rewards.json', api)).vehicles) add(row.name,row.name_en);
const custom=read(new URL('custom-loadouts.json', api));
for(const [id,name] of Object.entries(custom.names)) add(name, custom.names_en?.[id]);
for(const [zh,en] of Object.entries({'美国':'United States','苏联':'USSR','德国':'Germany','英国':'Britain','日本':'Japan','中国':'China','意大利':'Italy','法国':'France','瑞典':'Sweden','以色列':'Israel','泰国':'Thailand','瑞士':'Switzerland','荷兰':'Netherlands','比利时':'Belgium','希腊':'Greece','澳大利亚':'Australia','马来西亚':'Malaysia','芬兰':'Finland','匈牙利':'Hungary','南非':'South Africa','印度尼西亚':'Indonesia','特殊型号':'Special variant','战区基地（空战）':'Air battle base','战区基地（直升机）':'Helicopter base','机场跑道':'Airfield runway','机场油库 / 储存区':'Fuel / storage','机场停机 / 维修区':'Parking / repair area','机场生活区':'Living quarters','自定义挂载':'Custom loadout','推荐挂载':'Recommended loadout'})) add(zh,en);
write('catalog-zh-Hant',names);write('catalog-en',english);
if (process.argv.includes('--initialize-traditional')) write('zh-Hant',Object.fromEntries(Object.entries(read(new URL('zh-CN.json',root))).map(([key,text])=>[key,traditional(text)])));
