import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { StrikeEncyclopedia } from "./strike-encyclopedia";
import { AircraftParameters } from "./aircraft-parameters";

async function loadJson(name: string): Promise<Readonly<Record<string, unknown>>> {
  return JSON.parse(await readFile(
    fileURLToPath(new URL(`../generated/${name}`, import.meta.url)),
    "utf8",
  )) as Readonly<Record<string, unknown>>;
}

describe("StrikeEncyclopedia", () => {
  it("uses exact-unit air-mode BRs and the packaged source ceiling", () => {
    const encyclopedia = new StrikeEncyclopedia({
      encyclopedia: {economic_rank_max: 42}, weapons: {weapons: []}, splash: {},
      aircraftWeapons: {summary: {economic_rank_max: 42}, aircraft: [
        {id: "q_5l", weapons: [], battle_ratings: {arcade: 11, realistic: 10, simulator: 10.7, ground_simulator: 10.3}},
        {id: "variant", weapons: [], battle_ratings: {simulator: 15}},
        {id: "unknown", weapons: []},
      ]},
    });
    expect(encyclopedia.aircraftBattleRating("q_5l", "simulator")).toBe(10.7);
    expect(encyclopedia.aircraftBattleRating("q_5l", "air-realistic")).toBe(10);
    expect(encyclopedia.aircraftBattleRating("variant", "simulator")).toBe(15);
    expect(encyclopedia.aircraftBattleRating("unknown", "simulator")).toBeNull();
    expect(encyclopedia.aircraftBattleRating("absent", "simulator")).toBeNull();
    expect(encyclopedia.roomMaxBattleRatings().at(-1)).toBe(15);
  });
  it("matches the existing GBU-31 BR 14.7 damage calculator", async () => {
    const encyclopedia = new StrikeEncyclopedia({
      encyclopedia: await loadJson("strike-encyclopedia.json"),
      weapons: await loadJson("strike-weapon-damage.json"),
      aircraftWeapons: AircraftParameters.parse(await loadJson("aircraft-parameters.json")).strikeCatalog(),
      splash: await loadJson("bombing-zone-splash.json"),
    });
    expect(encyclopedia.calculate({
      roomMaxBr: 14.7,
      targetKind: "bombing_point",
      weaponId: "us_2000lb_gbu31_usaf",
    })).toMatchObject({
      targetMissionHp: 25_900,
      damagePerHitMissionHp: 10_982.625,
      fullDestroyCount: 3,
      fireTriggerCount: 3,
      practicalCount: 3,
    });
    expect(encyclopedia.calculate({
      roomMaxBr: 14.7,
      targetKind: "airport_module",
      airportModule: "airfield",
      weaponId: "us_2000lb_gbu31_usaf",
    })).toMatchObject({ targetMissionHp: 280_000, fullDestroyCount: 26 });
  });

  it("filters the calculator catalog by the exact aircraft mapping", async () => {
    const encyclopedia = new StrikeEncyclopedia({
      encyclopedia: await loadJson("strike-encyclopedia.json"),
      weapons: await loadJson("strike-weapon-damage.json"),
      aircraftWeapons: AircraftParameters.parse(await loadJson("aircraft-parameters.json")).strikeCatalog(),
      splash: await loadJson("bombing-zone-splash.json"),
    });
    const ids = encyclopedia.weapons("a-20g").map((weapon) => weapon.weaponId);
    expect(ids).toEqual(["us_250lb_anm57", "us_500lb_anm64a1", "us_m8bazooka"]);
    expect(ids).not.toContain("us_2000lb_gbu31_usaf");
  });
});
