import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";

import { fuzzySearchScore, rankFuzzyMatches } from "../../docs/calculator/search.mjs";
import { readableVehicle, vehicleName } from "../../docs/calculator/vehicle-names.mjs";
import { vehiclePinyin } from "../../docs/calculator/vehicle-pinyin.mjs";

const aircraft = [
  { id: "f_15_e", name: "F-15E Strike Eagle", long: "F-15E" },
  { id: "su_27", name: "Su-27", long: "Су-27" },
  { id: "a_10a", name: "A-10A Thunderbolt II", long: "A-10" },
];

test("game-font names become readable and remain searchable without losing variants", () => {
  assert.equal(vehicleName("\uF059F-16A", "israel"), "🇮🇱 F-16A");
  assert.equal(vehicleName("▄A-4PTM", "malaysia"), "🇲🇾 A-4PTM");
  assert.equal(vehicleName("◊米格-21", "germany"), "🇩🇪 米格-21");
  assert.equal(vehicleName("␗F-16A MLU", "china"), "🇨🇳 F-16A MLU");
  assert.equal(vehicleName("▄P-47", "ussr"), "〔苏联〕P-47");
  assert.equal(vehicleName("AV-8B+"), "AV-8B+");
  const row = readableVehicle({ id: "a_4e_early_iaf", country: "israel", name: "\uF059A-4E", long: "\uF059A-4E 早期型", name_en: "\uF059A-4E" });
  assert.ok(Number.isFinite(fuzzySearchScore("以色列 A4", [row.id, row.name, row.countryName])));
  assert.doesNotMatch([row.name, row.long, row.name_en].join(" "), /\p{Co}/u);
});

test("ignores punctuation, spaces, and case", () => {
  assert.ok(Number.isFinite(fuzzySearchScore("f15e", ["F-15E Strike Eagle"])));
  assert.ok(Number.isFinite(fuzzySearchScore("MK 83", ["us_1000lb_mk_83_ldgp"])));
  assert.ok(Number.isFinite(fuzzySearchScore("su 27", ["Su-27"])));
});

test("pinyin finds Chinese aircraft and every Eurofighter variant", () => {
  const rows = JSON.parse(readFileSync(new URL("../../docs/api/v1/calculator/aircraft.json", import.meta.url))).aircraft.map(readableVehicle);
  const search = query => rankFuzzyMatches(rows, query, row => [row.id, row.name, row.long, ...row.searchTerms], 24);
  const results = search("taif").map(row => row.id);
  for (const row of rows.filter(row => /^(ef_2000|typhoon_)/.test(row.id))) assert.ok(results.includes(row.id), row.id);
  assert.ok(search("jian10").some(row => row.name.includes("歼-10")));
  assert.ok(search("mige21").some(row => row.name.includes("米格-21")));
  assert.ok(search("mg21").some(row => row.name.includes("米格-21")));
  for (const [file, key] of [["aircraft", "aircraft"], ["rewards", "vehicles"]]) {
    const source = JSON.parse(readFileSync(new URL(`../../docs/api/v1/calculator/${file}.json`, import.meta.url)));
    for (const row of source[key]) for (const name of [row.name, row.long, row.name_en]) {
      for (const phrase of name?.match(/[\u3400-\u9fff]+/gu) || []) assert.ok(vehiclePinyin[phrase], `Run uv run tools/generate_vehicle_pinyin.py: ${phrase}`);
    }
  }
});

test("supports ordered fuzzy subsequences", () => {
  assert.ok(Number.isFinite(fuzzySearchScore("fse", ["F-15E Strike Eagle"])));
  assert.equal(fuzzySearchScore("f35", ["F-15E Strike Eagle"]), Number.POSITIVE_INFINITY);
});

test("ranks stronger matches ahead of loose subsequences", () => {
  const ranked = rankFuzzyMatches(aircraft, "f15", (item) => [item.id, item.name, item.long], 40);
  assert.equal(ranked[0].id, "f_15_e");
});

test("requires every query token to match", () => {
  const ranked = rankFuzzyMatches(aircraft, "strike eagle", (item) => [item.id, item.name, item.long], 40);
  assert.deepEqual(ranked.map((item) => item.id), ["f_15_e"]);
});
