import { describe, expect, it } from "vitest";
import { DEFAULT_LANDING_SETTINGS, LandingAssist, landingGeometry, type LandingInput } from "./landing-assist";
import { landingPresentation } from "./landing-presentation";
import cases from "./landing-geometry-cases.json";
import { PublicRuntime } from "./public-runtime";
import { editionPolicy } from "./edition-policy";
import { publicFlight } from "./public-runtime-fixture";
import { FlightStatusPresenter } from "./flight-status-badges";
import { landingTapePresentation } from "./landing-tape";

function inboundSample(at: number): LandingInput {
  return { context: "auto|plane|1", sampledAtMs: at, fresh: true,
    navigation: { player: { x: .5, y: .7 }, mapScaleM: [20_000, 40_000], selectionMode: "auto", target: null,
      items: [{ id: "home", kind: "airfield", friendly: true, hostile: false, selected: false, label: "友方机场", x: .5, y: .475,
        runwayStart: [.5,.5], runwayEnd: [.5,.45], bearingDeg: 0, relativeDeg: 0, distanceKm: 8 }] },
    track: { valid: true, worldX:0,worldZ:0,velocityX:0,velocityZ:100,groundSpeedMps:100,headingDeg:0,residualM:0,sampleCount:4,sampleSpanMs:300 },
    altitudeM:500,iasKmh:300,verticalSpeedMps:-4,gearPercent:0,airbrakePercent:0,flapsPercent:0 };
}

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
  expect(landingTapePresentation(snapshot)).toMatchObject({active:true,mode:"自动返航",course:"机场 090°",distance:"距机场 28.7km",glide:null,lateralText:"正飞向机场",glideText:"返航中",speedText:"1000"});
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
  expect(landingTapePresentation(measured)).toMatchObject({fuelText:"400",fuelTone:"danger",fuelDetail:"约 2.0 分"});
  expect(landingTapePresentation({...measured,fuel:{...measured.fuel,source:"aircraft-estimate"}}).fuelDetail).toBe("40%");
  expect(landingTapePresentation({...measured,fuel:{...measured.fuel,initialKg:0,source:"aircraft-estimate"}}).fuelDetail).toBe("续航 —");
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
