import assert from "node:assert/strict";
import test from "node:test";

import { fuzzySearchScore, rankFuzzyMatches } from "../../docs/calculator/search.mjs";

const aircraft = [
  { id: "f_15_e", name: "F-15E Strike Eagle", long: "F-15E" },
  { id: "su_27", name: "Su-27", long: "Су-27" },
  { id: "a_10a", name: "A-10A Thunderbolt II", long: "A-10" },
];

test("ignores punctuation, spaces, and case", () => {
  assert.ok(Number.isFinite(fuzzySearchScore("f15e", ["F-15E Strike Eagle"])));
  assert.ok(Number.isFinite(fuzzySearchScore("MK 83", ["us_1000lb_mk_83_ldgp"])));
  assert.ok(Number.isFinite(fuzzySearchScore("su 27", ["Su-27"])));
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
