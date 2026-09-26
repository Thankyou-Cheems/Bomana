import { describe, expect, it } from "vitest";
import { DEFAULT_LANDING_SETTINGS, LandingAssist, landingGeometry, landingAttitude, type LandingInput } from "./landing-assist";
import { landingPresentation } from "./landing-presentation";
import cases from "./landing-geometry-cases.json";
import configurationCases from "./landing-configuration-cases.json";
import { landingFlapReference } from "./landing-configuration";
import { AircraftParameters } from "./aircraft-parameters";
import { PublicRuntime } from "./public-runtime";
import { editionPolicy } from "./edition-policy";
import { publicFlight } from "./public-runtime-fixture";
import { FlightStatusPresenter } from "./flight-status-badges";
import { landingTapePresentation, LandingCueMotion } from "./landing-tape";

function inboundSample(at: number): LandingInput {
  return { context: "auto|plane|1", sampledAtMs: at, fresh: true,
    navigation: { player: { x: .5, y: .7 }, mapScaleM: [20_000, 40_000], selectionMode: "auto", target: null,
      items: [{ id: "home", kind: "airfield", friendly: true, hostile: false, selected: false, label: "友方机场", x: .5, y: .475,
        runwayStart: [.5,.5], runwayEnd: [.5,.45], bearingDeg: 0, relativeDeg: 0, distanceKm: 8 }] },
    track: { valid: true, worldX:0,worldZ:0,velocityX:0,velocityZ:100,groundSpeedMps:100,headingDeg:0,residualM:0,sampleCount:4,sampleSpanMs:300 },
    altitudeM:500,iasKmh:300,verticalSpeedMps:-4,gearPercent:0,airbrakePercent:0,flapsPercent:0 };
}

it("keeps one physical runway stable through sub-metre endpoint jitter", () => {
  const assist = new LandingAssist();
  for (let at = 1000; at <= 4000; at += 500) assist.update(inboundSample(at), () => 0);
  for (let at = 4100; at <= 6000; at += 100) {
    const input = inboundSample(at), offset = at % 200 === 0 ? .000005 : -.000005;
    const navigation = { ...input.navigation!, items: input.navigation!.items.map(r => ({ ...r,
      runwayStart: [r.runwayStart![0] + offset, r.runwayStart![1]] as const,
      runwayEnd: [r.runwayEnd![0] + offset, r.runwayEnd![1]] as const })) };
    const view = assist.update({ ...input, navigation }, () => 0);
    expect(view.status).toBe("guidance");
    expect(view.runwayKey).toBe(JSON.stringify([[.5,.5],[.5,.45]]));
    expect(view.geometry!.crossTrackM).toBe(0);
  }
});

it("withdraws guidance if two observed fields match the fixed runway anchor", () => {
  const assist = new LandingAssist();
  for (let at=1000;at<=4000;at+=500) assist.update(inboundSample(at),()=>0);
  const input=inboundSample(4100), home=input.navigation!.items[0]!;
  const result=assist.update({ ...input, navigation:{ ...input.navigation!, items:[home,{...home,id:"duplicate"}] } },()=>0);
  expect(result).toMatchObject({status:"unavailable",reason:"runway-changed",geometry:null});
});

it("recognizes a repair-pad position reset before the ground dwell and without a valid track", () => {
  const assist = new LandingAssist();
  for (let at = 1000; at <= 4000; at += 500) assist.update(inboundSample(at), () => 0);
  const stopped = (at: number, y: number): LandingInput => ({ ...inboundSample(at),
    navigation: { ...inboundSample(at).navigation!, player: { x: .5, y } }, altitudeM: 60,
    iasKmh: 0, verticalSpeedMps: 0, gearPercent: 100, track: null });
  expect(assist.update(stopped(4100, .47), () => 0).settings.enabled).toBe(true);
  expect(assist.update(stopped(4200, .495), () => 0).settings.enabled).toBe(false);
  expect(() => assist.configure({ ...assist.settings(), enabled:true }, inboundSample(4200).navigation)).toThrow("起飞阶段");
  for (let at = 4300; at <= 12000; at += 100) {
    const sample = { ...inboundSample(at), altitudeM: 65, gearPercent: 100, verticalSpeedMps: 6,
      navigation: { ...inboundSample(at).navigation!, player: { x: .5, y: .505 } } };
    expect(assist.update(sample, () => 0).settings.enabled).toBe(false);
  }
  // Once genuinely airborne the same field can be acquired for another landing.
  for (let at = 21000; at <= 24500; at += 500) assist.update(inboundSample(at), () => 0);
  expect(assist.settings().enabled).toBe(true);
});

it("returns the shared 8111 runtime to navigation on repair reset, before the next takeoff", async () => {
  const runtime = new PublicRuntime({ edition: editionPolicy("Standard") });
  const frame = (at: number, y: number, speed: number, altitude: number, vy: number, gear: number) => {
    const f = publicFlight(at);
    return { ...f, state: { ...f.state, "IAS, km/h": speed, "TAS, km/h": speed, "H, m": altitude, "Vy, m/s": vy, "gear, %": gear },
      mapObjects: [{type:"player", x:.5, y, dx:0, dy:-1}, {type:"airfield", side:"friendly", sx:.5, sy:.5, ex:.5, ey:.48}] };
  };
  for (let at=1000; at<=6000; at+=100) await runtime.ingest(frame(at,.58-at*.000001,300,500,-4,100));
  expect(runtime.snapshot().landing?.settings.enabled).toBe(true);
  await runtime.ingest(frame(6100,.485,0,60,0,100));
  const reset = await runtime.ingest(frame(6200,.499,0,60,0,100));
  expect(reset.landing?.settings.enabled).toBe(false);
  expect(landingTapePresentation(reset).active).toBe(false);
  for (let at=6300; at<=20000; at+=100) {
    const next = await runtime.ingest(frame(at,.499-(at-6300)*.0000005,200,65,4,100));
    expect(next.landing?.settings.enabled).toBe(false);
  }
});

it.each([[500, 0], [5, 200]])("does not treat height %dm / IAS %d above the runway as landed", (altitudeM, iasKmh) => {
  const assist = new LandingAssist();
  for (let at = 1000; at <= 4000; at += 500) assist.update(inboundSample(at), () => 0);
  for (let at = 4100; at <= 7000; at += 100) {
    const input = inboundSample(at);
    expect(assist.update({ ...input, navigation: { ...input.navigation!, player: { x: .5, y: .49 } },
      iasKmh, altitudeM, gearPercent: 100, verticalSpeedMps: 0 }, () => 0).settings.enabled).toBe(true);
  }
});

it.each([true, false])("clears landing on ground reset and stays out during gear-down takeoff (automatic=%s)", automatic => {
  const assist = new LandingAssist();
  for (let at = 1000; at <= 4000; at += 500) assist.update(inboundSample(at), () => 0);
  assist.configure({ ...assist.settings(), automatic }, inboundSample(4000).navigation);
  const ground = (at: number, y: number, speed: number): LandingInput => {
    const input = inboundSample(at);
    return { ...input, navigation: { ...input.navigation!, player: { x: .5, y } },
      altitudeM: 3, iasKmh: speed, verticalSpeedMps: 0, gearPercent: 100,
      track: { ...input.track!, velocityZ: speed / 3.6, groundSpeedMps: speed / 3.6 } };
  };
  for (let at = 4500; at <= 7000; at += 500) assist.update(ground(at, .47, 20), () => 0);
  const reset = ground(7100, .495, 0);
  expect(assist.update({ ...reset, track: null }, () => 0).settings.enabled).toBe(false);
  for (let at = 7200; at <= 13000; at += 200) {
    expect(assist.update(ground(at, .495 - (at - 7200) / 1000000, 200), () => 0).settings.enabled).toBe(false);
  }
});

it("reselects a sustained new airport-bound track without leaving landing mode, preserving manual choice", () => {
  for (const automatic of [true, false]) {
    const assist = new LandingAssist();
    const sample = (at: number, turn: boolean): LandingInput => {
      const input = inboundSample(at), home = input.navigation!.items[0]!;
      return { ...input, navigation: { ...input.navigation!, items: [home,
        { ...home, id: "other", label: "另一个机场", x: .9, runwayStart: [.9, .5], runwayEnd: [.9, .45] }] },
        track: { ...input.track!, velocityX: turn ? 80 : 0, velocityZ: 90 } };
    };
    for (let at = 1000; at <= 4000; at += 500) assist.update(sample(at, false));
    assist.configure({ ...assist.settings(), automatic, runwayElevationM: 123 }, sample(4000, false).navigation);
    for (let at = 4500; at <= 7500; at += 500) {
      const view = assist.update(sample(at, true));
      expect(view.settings.enabled).toBe(true);
      expect(view.settings.runwayId).toBe(automatic && at === 7500 ? "other" : "home");
    }
    expect(assist.settings().runwayElevationM).toBe(automatic ? null : 123);
  }
});

it("rejects transient target changes, broken observations and list ordinal changes during reacquisition", () => {
  const assist = new LandingAssist();
  for (let at = 1000; at <= 4000; at += 500) assist.update(inboundSample(at));
  for (let at = 4500; at <= 10000; at += 500) {
    const input = inboundSample(at), home = input.navigation!.items[0]!;
    assist.update({ ...input, fresh: at !== 6500,
      navigation: { ...input.navigation!, items: [home, { ...home, id: at < 8500 ? "other" : "renumbered", runwayStart: [.9, .5], runwayEnd: [.9, .45] }] },
      track: { ...input.track!, velocityX: 80, velocityZ: 90 } });
    expect(assist.settings().runwayId).toBe(at === 10000 ? "renumbered" : "home");
  }
});

it("keeps a short final stable, then releases it after a deliberate turn toward another airport", () => {
  const assist = new LandingAssist();
  for (let at = 1000; at <= 4000; at += 500) assist.update(inboundSample(at));
  for (let at = 4500; at <= 11000; at += 500) {
    const input = inboundSample(at), home = input.navigation!.items[0]!;
    const turned = at >= 8000;
    assist.update({ ...input, navigation: { ...input.navigation!, player: { x: .5, y: .55 }, items: [home,
      { ...home, id: "other", runwayStart: [turned ? .625 : .54, .5], runwayEnd: [turned ? .625 : .54, .45] }] },
      track: { ...input.track!, velocityX: turned ? 83.333333333 : 26.666666667, velocityZ: 100 } });
    expect(assist.settings().runwayId).toBe(at === 11000 ? "other" : "home");
  }
});

it("provides every observed runway for display without borrowing the selected runway's elevation", () => {
  const assist = new LandingAssist(), input = inboundSample(1000), home = input.navigation!.items[0]!;
  const nav = { ...input.navigation!, items: [home, { ...home, id: "enemy", friendly: false, hostile: true, runwayStart: [.6, .5] as const, runwayEnd: [.6, .45] as const }] };
  assist.configure({ ...DEFAULT_LANDING_SETTINGS, enabled: true, automatic: false }, nav);
  assist.configure({ ...assist.settings(), runwayElevationM: 123 }, nav);
  const view = assist.update({ ...input, navigation: nav });
  expect(view.runways).toHaveLength(1);
  expect(view.nearbyRunways).toHaveLength(2);
  expect(view.nearbyRunways!.find(r => r.id === "home")!.geometry.heightM).toBe(377);
  expect(view.nearbyRunways!.find(r => r.id === "enemy")!.geometry.heightM).toBeNull();
  expect(assist.update({ ...input, navigation: nav, fresh: false }).nearbyRunways).toEqual([]);
  const base = new PublicRuntime({ edition: editionPolicy("Standard") }).snapshot();
  const tape = landingTapePresentation({ ...base, landing: view });
  expect(tape.otherRunways).toHaveLength(1);
  expect(tape.otherRunways[0]!.scene).toBeNull();
  const away = landingTapePresentation({ ...base, flight: { ...base.flight, headingDeg: 180 }, landing: view });
  expect(away.otherRunways).toEqual([]);
});

it("uses optional TAS and attitude without treating IAS or missing bank as measured pose", () => {
  expect(landingAttitude(360, 0, 5, -5, 0)).toEqual({ tasMps: 100, pitchDeg: 5, rollDeg: 0 });
  expect(landingAttitude(null, -5, null, 5, null)).toEqual({ tasMps: null, pitchDeg: null, rollDeg: null });
  expect(landingAttitude(360, -5, null, null, 30).pitchDeg).toBeCloseTo(Math.asin(-.05) * 180 / Math.PI);
});

it("animates correction direction without inventing a glide path or retaining an outage", () => {
  const runtime = new PublicRuntime({ edition: editionPolicy("Standard") });
  const assist = new LandingAssist(), input = inboundSample(1000);
  assist.configure({ ...DEFAULT_LANDING_SETTINGS, enabled: true, automatic: false, runwayElevationM: 0 }, input.navigation);
  assist.configure({ ...assist.settings(), runwayElevationM: 0 }, input.navigation);
  const live = assist.update(input), base = runtime.snapshot();
  const view = (landing = live) => landingTapePresentation({ ...base, landing });
  const initial = view();
  expect(initial.scene).toBe("glide");
  expect(initial.glide).toBeGreaterThan(0); // too high: the correction is below ownship
  const motion = new LandingCueMotion();
  motion.observe(initial, 0);
  const left = { ...initial, runway: { ...initial.runway!, across: -800, height: 200 } };
  motion.observe(left, 100);
  expect(motion.step(190)!.across).toBeLessThan(0);
  expect(motion.step(190)!.across).toBeGreaterThan(-800);
  motion.observe(left, 190); // repeated telemetry must not restart an unchanged animation
  expect(motion.step(1000)).toEqual(left.runway);
  expect(motion.isMoving(1000)).toBe(false);
  motion.observe(initial, 1000, true);
  for (const stage of ["return", "intercept", "runway", "past-runway"] as const) {
    const changed = view({ ...live, geometry: { ...live.geometry!, stage } });
    expect(changed.glide).toBeNull();
    motion.observe(changed, 1100);
    expect(motion.step(1100)).toEqual(changed.runway);
  }
  expect(view({ ...live, geometry: { ...live.geometry!, heightM: null } }).glide).toBeNull();
  const lost = view({ ...live, status: "unavailable", reason: "telemetry", geometry: null });
  motion.observe(lost, 1200);
  expect(motion.step(1200)).toBeNull();
  expect(motion.isMoving(1200)).toBe(false);
  motion.observe(initial, 1300);
  motion.observe(left, 1301, true);
  expect(motion.step(1301)).toEqual(left.runway);
  expect(motion.isMoving(1301)).toBe(false);
  motion.observe({ ...initial, cueKey: "another-runway" }, 1302);
  expect(motion.step(1302)).toEqual(initial.runway);
});

it("keeps the runway continuous through stage changes and list renumbering", () => {
  const assist = new LandingAssist(), input = inboundSample(1000);
  assist.configure({ ...DEFAULT_LANDING_SETTINGS, enabled: true }, input.navigation);
  const landing = assist.update(input, () => 0);
  const base = new PublicRuntime({ edition: editionPolicy("Standard") }).snapshot();
  const a = landingTapePresentation({ ...base, navigation: input.navigation, landing });
  const b = landingTapePresentation({ ...base, navigation: input.navigation, landing: { ...landing,
    geometry: { ...landing.geometry!, stage: "intercept", crossTrackM: 200 } } });
  expect(b.cueKey).toBe(a.cueKey);
  const motion = new LandingCueMotion();
  motion.observe(a, 0); motion.observe(b, 100);
  expect(motion.step(101)!.across).toBeGreaterThan(-200);
  const renamed = landingTapePresentation({ ...base, navigation: { ...input.navigation!,
    items: input.navigation!.items.map(item => ({ ...item, id: "renumbered" })) },
    landing: { ...landing, settings: { ...landing.settings, runwayId: "renumbered" } } });
  expect(renamed.cueKey).toBe(a.cueKey);
  expect(a.course).toContain("友方机场");
});

it("shows known airport elevation at long range without creating a glide command", () => {
  const runtime = new PublicRuntime({ edition: editionPolicy("Standard") });
  const assist = new LandingAssist(), input = inboundSample(1000);
  assist.configure({ ...DEFAULT_LANDING_SETTINGS, enabled: true, automatic: false }, input.navigation);
  const live = assist.update(input), base = runtime.snapshot();
  const view = (heightM: number | null, airportDistanceM = 30000) => landingTapePresentation({ ...base,
    landing: { ...live, geometry: { ...live.geometry!, stage: "return", heightM, airportDistanceM } } });
  expect(view(3000)).toMatchObject({ scene: "return", glide: null, airportHeightText: "↓3000m" });
  expect(view(3000).runway!.height).toBe(3000);
  expect(view(-500).runway!.height).toBe(-500);
  expect(view(null).runway).toBeNull();
  const motion = new LandingCueMotion();
  motion.observe(view(3000), 0);
  motion.observe(view(null), 10);
  expect(motion.step(10)).toBeNull(); // no easing a missing datum away
});

it("preserves correction velocity across samples and settles without overshoot", () => {
  const base = landingTapePresentation(new PublicRuntime({ edition: editionPolicy("Standard") }).snapshot());
  const view = (across: number) => ({ ...base, runway: { across, along: 5000, height: 400, length: 2000, angle: 0, slope: .05, approach: true }, cueKey: "same-valid-approach" });
  const motion = new LandingCueMotion();
  motion.observe(view(0), 0);
  motion.observe(view(600), 10);
  const before = motion.step(99)!.across;
  const current = motion.step(100)!.across;
  motion.observe(view(800), 100);
  const after = motion.step(101)!.across;
  expect((after - current) / (current - before)).toBeGreaterThan(.9);
  expect((after - current) / (current - before)).toBeLessThan(1.1);
  motion.observe(view(-800), 120);
  for (let t = 130; t <= 1500; t += 10) expect(motion.step(t)!.across).toBeGreaterThanOrEqual(-800);
  expect(motion.step(1500)!.across).toBe(-800);
  expect(motion.isMoving(1500)).toBe(false);
});

it.each(["stable", "reordered", "missing"])("restores navigation after repeated landings with %s airport observations", async variant => {
  const runtime = new PublicRuntime({ edition: editionPolicy("Standard") });
  let at = 1000;
  const home = { type: "airfield", side: "friendly", sx: .5, sy: .5, ex: .5, ey: .48 };
  const other = { type: "airfield", side: "friendly", sx: .8, sy: .5, ex: .8, ey: .48 };
  let y = .58;
  const fly = async (seconds: number, vy: number, dy: number, airports: object[]) => {
    for (let step = 0; step < seconds * 10; step++, at += 100) {
      y += dy * .0001;
      const f = publicFlight(at);
      await runtime.ingest({ ...f, state: { ...f.state, "Vy, m/s": vy, "IAS, km/h": dy ? 360 : 0 },
        mapObjects: [{ type: "player", x: .5, y, dx: 0, dy }, ...airports] });
    }
  };
  for (let cycle = 0; cycle < 3; cycle++) {
    y = .58;
    await fly(12, -4, -1, [home, other]);
    expect(runtime.snapshot().landing?.settings.enabled, `approach ${cycle}`).toBe(true);
    y = .49;
    await fly(3, 0, 0, [home, other]);
    const airports = variant === "reordered" ? [other, home] : variant === "missing" ? [other] : [home, other];
    await fly(40, 5, -1, airports);
    expect(runtime.snapshot().landing?.settings.enabled, `departure ${cycle}`).toBe(false);
    expect(landingTapePresentation(runtime.snapshot()).active).toBe(false);
  }
});

it("keeps excessive-descent advice visible without static touchdown explanations", () => {
  const input = inboundSample(1000), assist = new LandingAssist();
  assist.update(input);
  assist.configure({ ...DEFAULT_LANDING_SETTINGS, enabled: true }, input.navigation);
  assist.configure({ ...assist.settings(), runwayElevationM: 100 }, input.navigation);
  const descending = assist.update({ ...input, verticalSpeedMps: -12 });
  expect(descending.geometry?.referenceDescentMps).not.toBeNull();
  expect(landingPresentation(descending).descentAdvice).toBe("下沉偏快 · 减小下沉率");
  expect(landingPresentation(assist.update(input)).descentAdvice).toBe("");
  expect(landingPresentation(assist.update({ ...input, fresh: false })).descentAdvice).toBe("");
});

it("corrects a drifting ground track before the aircraft leaves the runway centerline", () => {
  const input = inboundSample(1000), assist = new LandingAssist();
  assist.update(input);
  assist.configure({ ...DEFAULT_LANDING_SETTINGS, enabled: true }, input.navigation);
  const runtime = new PublicRuntime({ edition: editionPolicy("Standard") });
  for (const drift of [-20, 20]) {
    const landing = assist.update({ ...input,
      navigation: { ...input.navigation!, player: { x: .5, y: .55 } },
      track: { ...input.track!, velocityX: drift, velocityZ: 80 },
    });
    expect(Math.sign(landing.geometry!.trackErrorDeg!), "the fresh ground-track axes are already correct").toBe(Math.sign(drift));
    const tape = landingTapePresentation({ ...runtime.snapshot(), landing });
    expect(Math.sign(tape.lateral!), "guide against sideways motion while position is still centered").toBe(-Math.sign(drift));
  }
});

it.each(configurationCases)("flap reference: $name", test => {
  const profile = AircraftParameters.parse({schema_version:1,unit_to_fm:{test:"test"},flight_models:{test:{speed:null,fuel:null,landing:test.profile}},loadouts:{}}).landing("test");
  expect(landingFlapReference(profile, test.percent, test.ias, test.previous)).toEqual(test.expected);
});

it("uses fresh flap observations for compact warnings and withdraws them during a telemetry gap", () => {
  const profile = AircraftParameters.parse({schema_version:1,unit_to_fm:{test:"test"},flight_models:{test:{speed:null,fuel:null,landing:configurationCases[1]!.profile}},loadouts:{}}).landing("test");
  const assist = new LandingAssist(), input = { ...inboundSample(1000), aircraft: profile, iasKmh:400, flapsPercent:25 };
  assist.update(input); assist.configure({ ...DEFAULT_LANDING_SETTINGS, enabled:true }, input.navigation);
  const runtime = new PublicRuntime({ edition:editionPolicy("Standard") });
  const live = assist.update(input);
  expect(live.flapReference).toMatchObject({risk:"over-limit",limitIasKmh:397});
  expect(landingTapePresentation({...runtime.snapshot(), landing:live})).toMatchObject({config:"襟翼超限",speedTone:"danger",speedDetail:"翼参 ≤397"});
  const missing = assist.update({...input, fresh:false});
  expect(missing.flapReference).toEqual({risk:"unknown",limitIasKmh:null,next:null});
  expect(landingTapePresentation({...runtime.snapshot(), landing:missing}).config).not.toContain("超限");
  expect(assist.update({...input, fresh:true, iasKmh:380}).flapReference?.risk).toBe("near-limit");
});

it("acquires a sustained inbound runway, holds it through dropouts, and exits after turning away", () => {
  const assist = new LandingAssist();
  for (let at=1000;at<4000;at+=500) expect(assist.update(inboundSample(at)).settings.enabled).toBe(false);
  expect(assist.update(inboundSample(4000)).settings).toMatchObject({enabled:true,automatic:true,runwayId:"home",reverse:false});
  const missing=inboundSample(4500);
  expect(assist.update({...missing,navigation:{...missing.navigation!,items:[]}})).toMatchObject({status:"unavailable",reason:"runway-missing"});
  expect(assist.update(inboundSample(5000)).settings.runwayId).toBe("home");
  for (let at=5500;at<=13500;at+=500) {
    const input=inboundSample(at);
    const result=assist.update({...input,track:{...input.track!,velocityZ:-100}});
    expect(result.settings.enabled).toBe(at<13500);
  }
  for(let at=14000;at<=18000;at+=500) expect(assist.update(inboundSample(at)).settings.enabled).toBe(false);
  assist.configure({...assist.settings(),automatic:false,enabled:false},inboundSample(18000).navigation);
  for(let at=30000;at<=35000;at+=500) expect(assist.update(inboundSample(at)).settings.enabled).toBe(false);
  expect(assist.update({...inboundSample(36000),context:"new-sortie"}).settings.automatic).toBe(false);
});

it("keeps automatic landing dwell history out of stale command projections", () => {
  const assist = new LandingAssist();
  expect(assist.update(inboundSample(1000)).settings.enabled).toBe(false);
  expect(assist.project({ ...inboundSample(1500), fresh: false }).settings.enabled).toBe(false);
  expect(assist.update(inboundSample(1500)).settings.enabled).toBe(false);
  expect(assist.update(inboundSample(3000)).settings.enabled).toBe(false);
  expect(assist.update(inboundSample(4000)).settings.enabled).toBe(true);
});

it("keeps a manual runway through reorder but never revives its elevation after endpoint change", () => {
  const assist = new LandingAssist(), input = inboundSample(1000);
  assist.update(input);
  assist.configure({...DEFAULT_LANDING_SETTINGS,enabled:true,automatic:false},input.navigation);
  assist.configure({...assist.settings(),runwayElevationM:123},input.navigation);
  const reordered = {...input,sampledAtMs:1500,navigation:{...input.navigation!,items:input.navigation!.items.map(r=>({...r,id:"renumbered"}))}};
  expect(assist.update(reordered)).toMatchObject({status:"guidance",elevationM:123,settings:{runwayId:"renumbered"}});
  const changed = {...reordered,sampledAtMs:2000,navigation:{...reordered.navigation,items:reordered.navigation.items.map(r=>({...r,runwayEnd:[.51,.45] as const}))}};
  expect(assist.update(changed)).toMatchObject({reason:"runway-changed",settings:{runwayElevationM:null}});
  expect(assist.update({...reordered,sampledAtMs:2500})).toMatchObject({status:"guidance",elevationM:null});
});

it("does not enter on departure, lateral flybys, hostile runways or intermittent observations", () => {
  for(const mode of ["departing","near-departure","flyby","hostile","gap"]) {
    const assist=new LandingAssist();
    for(let at=1000;at<=8000;at+=500) {
      const input=inboundSample(at);
      const next=mode==="departing"?{...input,verticalSpeedMps:5,track:{...input.track!,velocityZ:-100}}
        :mode==="near-departure"?{...input,verticalSpeedMps:5,navigation:{...input.navigation!,player:{x:.5,y:.54}}}
        :mode==="flyby"?{...input,track:{...input.track!,velocityX:100,velocityZ:0}}
        :mode==="hostile"?{...input,navigation:{...input.navigation!,items:input.navigation!.items.map(r=>({...r,hostile:true}))}}
        :{...input,fresh:at%1500!==0};
      expect(assist.update(next).settings.enabled,mode).toBe(false);
    }
  }
});

it("enters while flying level toward the runway before reducing speed or extending gear", () => {
  const assist = new LandingAssist();
  for (let at=1000;at<=4000;at+=500) {
    const snapshot = assist.update({...inboundSample(at),iasKmh:500,verticalSpeedMps:0,gearPercent:0});
    expect(snapshot.settings.enabled).toBe(at===4000);
  }
});

it.each([30,80])("activates and stays active while returning toward a friendly airport %d km away", distanceKm => {
  const assist = new LandingAssist();
  for (let at=1000;at<=15000;at+=500) {
    const input = inboundSample(at);
    const snapshot = assist.update({...input,iasKmh:500,verticalSpeedMps:0,
      navigation:{...input.navigation!,player:{x:.5,y:.5+distanceKm/200-(at-1000)*.0000005},mapScaleM:[20_000,200_000],
        items:input.navigation!.items.map(r=>({...r,distanceKm,runwayEnd:[.5,.49]}))}});
    expect(snapshot.settings.enabled,`return acquisition at ${at}`).toBe(at>=4000);
    if (at>=4000) expect(snapshot.geometry).toMatchObject({stage:"return",airportBearingDeg:0,airportTrackErrorDeg:0,glideDeviationM:null,referenceDescentMps:null});
  }
});

it.each(["side-on", "fast", "climbing", "optional-fields-missing"])("activates on an airport-bound %s return before final approach", variant => {
  const assist = new LandingAssist();
  for (let at=1000;at<=15000;at+=500) {
    const input = {...inboundSample(at),iasKmh:500,verticalSpeedMps:0};
    const snapshot = assist.update(variant === "side-on" ? {...input,
      navigation:{...input.navigation!,player:{x:.1,y:.475}},
      track:{...input.track!,velocityX:100,velocityZ:0,headingDeg:90}}
      : variant === "fast" ? {...input,iasKmh:1000} : variant === "climbing" ? {...input,verticalSpeedMps:5}
        : {...input,iasKmh:null,verticalSpeedMps:null,gearPercent:null});
    expect(snapshot.settings.enabled,`${variant} return at ${at}`).toBe(at>=4000);
  }
});

it("acquires a side-on airport despite small nearest-end changes during the return", () => {
  const assist = new LandingAssist();
  for (let at=1000;at<=4000;at+=500) {
    const input = inboundSample(at);
    const result = assist.update({...input,verticalSpeedMps:0,
      navigation:{...input.navigation!,player:{x:.1,y:.475+(at%1000===0?.00002:-.00002)}},
      track:{...input.track!,velocityX:100,velocityZ:0}});
    expect(result.settings.enabled).toBe(at===4000);
  }
});

it("transitions from airport return to the locked runway's final guidance", () => {
  const assist = new LandingAssist();
  for(let at=1000;at<=4000;at+=500) {
    const input=inboundSample(at);
    assist.update({...input,navigation:{...input.navigation!,player:{x:.1,y:.475}},
      track:{...input.track!,velocityX:100,velocityZ:0}});
  }
  const selected = assist.settings().runwayId;
  const input=inboundSample(4500);
  assist.configure({...assist.settings(),runwayElevationM:100},input.navigation);
  const result=assist.update({...input,navigation:{...input.navigation!,player:{x:.5,y:.55}},altitudeM:220});
  expect(result.settings.runwayId).toBe(selected);
  expect(result.geometry?.stage).toBe("final");
  expect(result.geometry?.thresholdDistanceM).toBeCloseTo(2000,7);
  expect(result.geometry?.glideDeviationM).toBeCloseTo(.1844414339,7);
});

it("shows airport bearing and direct distance on the return tape from actual 8111 motion", async () => {
  const runtime=new PublicRuntime({edition:editionPolicy("Standard")});
  for(let at=1000;at<=6500;at+=100) {
    const f=publicFlight(at);
    await runtime.ingest({...f,state:{...f.state,"IAS, km/h":1000,"Vy, m/s":5},
      mapInfo:{valid:true,map_min:[-50000,-50000],map_max:[50000,50000]},
      mapObjects:[{type:"player",x:.2+at*.000002,y:.5,dx:1,dy:0},{type:"airfield",side:"friendly",sx:.5,sy:.51,ex:.5,ey:.49}]});
  }
  const snapshot=runtime.snapshot();
  expect(snapshot.landing?.settings.enabled).toBe(true);
  expect(snapshot.landing?.geometry).toMatchObject({stage:"return",airportBearingDeg:90,airportTrackErrorDeg:0,glideDeviationM:null});
  expect(landingTapePresentation(snapshot)).toMatchObject({active:true,mode:"自动返航",course:"机场 1 · 090°",distance:"距机场 28.7km",glide:null,lateralText:"正飞向机场",glideText:"返航中",speedText:"1000"});
  expect(landingTapePresentation(snapshot).lateral).toBeCloseTo(0,7);
  expect(landingPresentation(snapshot.landing)).toMatchObject({stage:"返航机场",distance:"距机场 28.7 km",course:"机场方位 090°"});
  expect(landingTapePresentation(snapshot).aria).toContain("燃油");
});

it("switches the shared runtime automatically from actual 8111 ground-track samples", async () => {
  const runtime=new PublicRuntime({edition:editionPolicy("Standard")});
  for(let at=1000;at<=6500;at+=100) {
    const f=publicFlight(at);
    await runtime.ingest({...f,state:{...f.state,"IAS, km/h":300,"Vy, m/s":-4},
      mapInfo:{valid:true,map_min:[-10000,-20000],map_max:[10000,20000]},
      mapObjects:[{type:"player",x:.5,y:.7-at*.0000025,dx:0,dy:-1},{type:"airfield",side:"friendly",sx:.5,sy:.5,ex:.5,ey:.45}]});
  }
  const snapshot=runtime.snapshot();
  expect(snapshot.landing?.settings).toMatchObject({enabled:true,automatic:true,reverse:false});
  const tape=landingTapePresentation(snapshot);
  expect(tape.active).toBe(true);expect(tape.aria).toContain("燃油");expect(tape.speedText).toBe("300");
  const measured={...snapshot,fuel:{...snapshot.fuel!,available:true,currentKg:400,percent:40,source:"measured" as const,stable:true,remainingMinutes:2}};
  expect(landingTapePresentation(measured)).toMatchObject({fuelText:"120",fuelTone:"danger",fuelDetail:"约 120 秒"});
  expect(landingTapePresentation({...measured,fuel:{...measured.fuel,remainingMinutes:4.25}})).toMatchObject({fuelText:"255",fuelTone:"caution"});
  expect(landingTapePresentation({...measured,fuel:{...measured.fuel,remainingMinutes:8.5}})).toMatchObject({fuelText:"510",fuelTone:"reference"});
  for (const fuel of [{...measured.fuel,source:"aircraft-estimate" as const},{...measured.fuel,stable:false},{...measured.fuel,remainingMinutes:-1},{...measured.fuel,remainingMinutes:NaN}]) {
    expect(landingTapePresentation({...measured,fuel})).toMatchObject({fuelText:"—",fuelDetail:"— 秒"});
  }
  expect(landingTapePresentation({...measured,sortieContinuity:{...measured.sortieContinuity,state:"no-data-grace"}}).fuelText).toBe("—");
  for (const [arrestorHook,brakeChute,equipmentText] of [[true,false,"钩✓ 伞×"],[false,true,"钩× 伞✓"],[null,undefined,"钩? 伞?"]] as const) {
    const view = landingTapePresentation({...measured,landing:{...snapshot.landing!,aircraft:{gearIasKmh:null,gearControl:null,arrestorHook,brakeChute}}});
    expect(view.equipmentText).toBe(equipmentText);
    expect(view.aria).toContain("仅为静态配备，非当前展开或挂索状态");
  }
  expect(landingTapePresentation({...measured,landing:{...snapshot.landing!,reason:"telemetry",iasKmh:null}})).toMatchObject({fuelText:"—",speedText:"—"});
});

describe("landing geometry shared with Go", () => {
  it.each(cases)("$name", test => {
    const result = landingGeometry({ ...test, scale: [test.scale[0]!,test.scale[1]!], start:[test.start[0]!,test.start[1]!],
      end:[test.end[0]!,test.end[1]!], velocity:test.velocity ? [test.velocity[0]!,test.velocity[1]!] : null });
    for (const [key,value] of Object.entries(test.expected)) {
      const actual = result[key as keyof typeof result];
      if (typeof value === "number") expect(actual).toBeCloseTo(value, 7); else expect(actual).toBe(value);
    }
  });
});

async function sample() {
  const runtime = new PublicRuntime({ edition:editionPolicy("Standard"), now:()=>2000 });
  for (const at of [0,1000,2000]) await runtime.ingest(publicFlight(at));
  const navigation = runtime.snapshot().navigation!;
  const input: LandingInput = {context:"map|plane|1",fresh:true,navigation,track:null,altitudeM:300,iasKmh:250,verticalSpeedMps:-4,gearPercent:null,airbrakePercent:0,flapsPercent:null};
  const assist = new LandingAssist();assist.update(input);
  return {runtime,assist,input};
}
it("locks its own runway/direction and leaves strike/navigation selection alone", async () => {
  const {runtime}=await sample();const original=runtime.snapshot().navigation?.target;
  const result=await runtime.command({type:"landing.configure",landing:{...DEFAULT_LANDING_SETTINGS,enabled:true}});
  expect(result.landing?.status).toBe("guidance");expect(result.navigation?.target).toEqual(original);
  const runway=result.landing!.settings.runwayId,reverse=result.landing!.settings.reverse;
  const changed={...publicFlight(2200),mapObjects:[{type:"player",x:.2,y:.9,dx:0,dy:-1},...(publicFlight(2200).mapObjects as unknown[]).slice(1)]};
  const next=await runtime.ingest(changed);
  expect(next.landing!.settings.runwayId).toBe(runway);expect(next.landing!.settings.reverse).toBe(reverse);
});
it("does not reuse a height after switching approach direction",async()=>{
  const {assist,input}=await sample();assist.configure({...DEFAULT_LANDING_SETTINGS,enabled:true},input.navigation);
  assist.configure({...assist.settings(),runwayElevationM:100},input.navigation);
  expect(assist.update(input).elevationM).toBe(100);
  assist.configure({...assist.settings(),reverse:!assist.settings().reverse},input.navigation);
  expect(assist.update(input).elevationM).toBeNull();
});
it("withdraws geometry on gaps, missing runway and changed endpoints instead of switching airports",async()=>{
  const {assist,input}=await sample();assist.configure({...DEFAULT_LANDING_SETTINGS,enabled:true},input.navigation);
  expect(assist.update({...input,fresh:false}).geometry).toBeNull();
  expect(assist.update({...input,navigation:{...input.navigation!,items:[]}}).reason).toBe("runway-missing");
  const changed=input.navigation!.items.map(t=>t.id===assist.settings().runwayId?{...t,runwayEnd:[.3,.8] as const}:t);
  expect(assist.update({...input,navigation:{...input.navigation!,items:changed}}).reason).toBe("runway-changed");
  expect(assist.update(input).status).toBe("guidance");
  assist.configure({...assist.settings(),runwayElevationM:100},input.navigation);
  const newNavigation={...input.navigation!,items:changed};
  assist.configure(assist.settings(),newNavigation);
  expect(assist.update({...input,navigation:newNavigation}).elevationM).toBeNull();
});
it("clears parameters on a different aircraft/map/sortie context",async()=>{
  const {assist,input}=await sample();assist.configure({...DEFAULT_LANDING_SETTINGS,enabled:true,targetIasKmh:250},input.navigation);
  expect(assist.update({...input,context:"map|other-plane|1"}).settings).toEqual(DEFAULT_LANDING_SETTINGS);
});
it("preserves missing optional observations and rejects Lite commands",async()=>{
  const {runtime}=await sample();const f=publicFlight(2300),state={...f.state};delete state["gear, %"];delete state["IAS, km/h"];
  const result=await runtime.ingest({...f,state});
  expect(result.landing!.iasKmh).toBeNull();expect(result.landing!.gearPercent).toBeNull();
  expect(landingPresentation(result.landing).configuration).toContain("起落架未知");
  const lite=new PublicRuntime({edition:editionPolicy("Lite")});
  await expect(lite.command({type:"landing.configure",landing:{...DEFAULT_LANDING_SETTINGS,enabled:true}})).rejects.toThrow("disabled");
});
it("disables live geometry during 8111 Holdover",async()=>{
  const {runtime}=await sample();await runtime.command({type:"landing.configure",landing:{...DEFAULT_LANDING_SETTINGS,enabled:true}});
  const next=await runtime.ingest({...publicFlight(2300),holdover:{state:true,indicators:false,mapObjects:false}});
  expect(next.landing?.status).toBe("unavailable");expect(next.landing?.geometry).toBeNull();
});
it("keeps the selected approach through a transient missing indicators response",async()=>{
  const {runtime}=await sample();await runtime.command({type:"landing.configure",landing:{...DEFAULT_LANDING_SETTINGS,enabled:true}});
  const f=publicFlight(2400);
  for (const at of [2400,2500]) {
    const gap=await runtime.ingest({...f,sampledAtMs:at,indicators:null,availability:{...f.availability,indicators:false}});
    expect(gap.landing?.settings.enabled).toBe(true);expect(gap.landing?.geometry).toBeNull();
  }
  expect((await runtime.ingest(publicFlight(2700))).landing?.status).toBe("guidance");
});
it("warns on partial deployment immediately, uses IAS, and withdraws on missing observations",async()=>{
  const {assist,input}=await sample();
  const aircraft={gearIasKmh:500,gearControl:true,arrestorHook:true};
  const observe=(iasKmh:number|null,gearPercent:number|null)=>assist.update({...input,aircraft,iasKmh,gearPercent});
  expect(observe(501,10).gearRisk).toBe("over-limit");
  expect(observe(496,10).gearRisk).toBe("over-limit");
  expect(observe(480,10).gearRisk).toBe("near-limit");
  expect(observe(439,10).gearRisk).toBe("reference");
  expect(observe(550,0).gearRisk).toBe("extension-too-fast");
  expect(observe(null,100).gearRisk).toBe("unknown");
  expect(observe(600,null).gearRisk).toBe("unknown");
  expect(landingPresentation(observe(490,100)).arrestor).toContain("静态支持");
  expect(landingPresentation(assist.update({...input,aircraft:{...aircraft,arrestorHook:null}})).arrestor).toContain("未确认");
  const fixed=assist.update({...input,gearPercent:0,iasKmh:600,aircraft:{...aircraft,gearControl:false}});
  expect(fixed.gearRisk).toBe("reference");
  expect(landingPresentation(fixed).configuration).toContain("无起落架收放控制");
});
it("replaces the unretracted-gear warning only while landing is enabled",async()=>{
  const {runtime}=await sample();
  const frame=publicFlight(2300);
  await runtime.ingest({...frame,state:{...frame.state,"gear, %":100}});
  expect(runtime.snapshot().alerts).toContain("起落架未收起");
  const enabled=await runtime.command({type:"landing.configure",landing:{...DEFAULT_LANDING_SETTINGS,enabled:true}});
  expect(enabled.alerts).not.toContain("起落架未收起");
  expect(new FlightStatusPresenter().update(enabled).gear).toMatchObject({text:"放轮 100%",tone:"info"});
  const unavailable={...enabled,landing:{...enabled.landing!,gearPercent:null}};
  expect(new FlightStatusPresenter().update(unavailable).gear.visible).toBe(false);
  const over={...enabled,landing:{...enabled.landing!,gearRisk:"over-limit" as const}};
  expect(new FlightStatusPresenter().update(over).gear).toMatchObject({tone:"danger",text:"起落架超参考限速"});
  const disabled=await runtime.command({type:"landing.configure",landing:{...enabled.landing!.settings,enabled:false}});
  expect(disabled.alerts).toContain("起落架未收起");
});
