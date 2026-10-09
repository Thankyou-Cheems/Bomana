import { describe, expect, it } from "vitest";
import { FlightRecordingEncoder, RecordingMatchBoundary, flightRecordingContext, recordingFrame, retainedRecordingChunks, RECORDING_MAX_BYTES, RECORDING_MAX_AGE_MS } from "./flight-recording";
import { PublicRuntime } from "./public-runtime";
import { editionPolicy } from "./edition-policy";
import type { Official8111Frame } from "./telemetry-source";
const raw = (at=0): Official8111Frame => ({ sampledAtMs:at,bridgeReachable:true,state:{valid:true,"H, m":2000},indicators:{type:"jh_7"},
  mapObjects:[{type:"aircraft",icon:"Player",x:.4,y:.5,name:"private name"}],mapInfo:{map_min:[0,0],map_max:[100,100],map_generation:2},
  availability:{state:true,indicators:true,mapObjects:true,mapInfo:true},gameChat:[{msg:"private chat"}] });
describe("local flight recording",()=>{
  it("records processed-state timing explicitly without copying the whole UI snapshot",()=>{
    const runtime=new PublicRuntime({edition:editionPolicy("Standard"),now:()=>1000});
    runtime.ingest(raw(1000));
    const snapshot=runtime.snapshot();
    const context=flightRecordingContext(snapshot);
    expect(context.contextSampledAtMs).toBe(snapshot.sampledAtMs);
    expect(context.timerRemainingSec).toBe(snapshot.timer.remainingSec);
    expect(context).not.toHaveProperty("checklist");
    expect(recordingFrame(raw(1100),context).context).toEqual(context);
    expect(flightRecordingContext(null)).toEqual({});
  });
  it("keeps only a contiguous recent suffix within time, capacity and match boundaries",()=>{
    const chunks=[0,1,2].map(fromMs=>({fromMs,session:"a",bytes:RECORDING_MAX_BYTES/3}));
    expect(retainedRecordingChunks(chunks,{session:"a",toMs:3,bytes:RECORDING_MAX_BYTES/3})).toEqual(chunks.slice(1));
    expect(retainedRecordingChunks(chunks,{session:"a",toMs:RECORDING_MAX_AGE_MS+2,bytes:1})).toEqual(chunks.slice(2));
    expect(retainedRecordingChunks(chunks,{session:"b",toMs:3,bytes:1})).toEqual([]);
  });
  it("preserves telemetry while excluding chat, credentials and names",()=>{
    const safe=recordingFrame({...raw(),state:{valid:true,token:123,password:"secret"}}, {phase:"alive",authorization:"credential",weaponId:"500_4"});
    expect(JSON.stringify(safe)).not.toMatch(/private|credential|password|token|gameChat/);
    expect(safe).toMatchObject({state:{valid:true},context:{phase:"alive",weaponId:"500_4"},mapObjects:[{icon:"Player",x:.4,y:.5}]});
  });
  it("recognizes the same ownship payloads as the flight runtime",()=>{
    for (const player of [{type:"player"}, {type:"aircraft",is_self:true}, {type:"aircraft",name:"Player"}, {type:"aircraft",icon:"player"}]) {
      for (const mapObjects of [[player], ...["objects","map_objects","items","data"].map(key=>({[key]:[player]}))]) {
        const frame=recordingFrame({...raw(),mapObjects},{});
        expect(new RecordingMatchBoundary().update(frame)).toBe("new");
        expect(JSON.stringify(frame)).not.toContain('"name"');
      }
    }
  });
  it("waits for initial map identity and retains the session during missing map info",()=>{
    const boundary=new RecordingMatchBoundary();
    expect(boundary.update(recordingFrame({...raw(),mapInfo:null},{}))).toBe("idle");
    expect(boundary.update(recordingFrame(raw(100),{}))).toBe("new");
    expect(boundary.update(recordingFrame({...raw(200),mapInfo:null},{}))).toBe("continue");
    expect(boundary.update(recordingFrame(raw(300),{}))).toBe("continue");
  });
  it("keeps ownship inside the object budget even when it arrives after 2000 targets",()=>{
    const mapObjects=[...Array.from({length:2000},()=>({type:"point_of_interest",x:0,y:0})),{type:"player",x:.5,y:.5}];
    const frame=recordingFrame({...raw(),mapObjects},{});
    expect(frame.mapObjects).toHaveLength(2000);
    expect(frame.mapObjectsTruncated).toBe(true);
    expect(new RecordingMatchBoundary().update(frame)).toBe("new");
  });
  it("starts each persisted chunk with a complete frame and records overload gaps",()=>{
    const encoder=new FlightRecordingEncoder();
    encoder.add(recordingFrame(raw(),{}));encoder.add(recordingFrame(raw(100),{}),3);
    const rows=encoder.take()!.text.trim().split("\n").map(row=>JSON.parse(row));
    expect(rows[0].set.state).toEqual({valid:true,"H, m":2000});expect(rows[1].set.state).toBeUndefined();expect(rows[1].droppedBefore).toBe(3);
    encoder.add(recordingFrame(raw(200),{}));expect(JSON.parse(encoder.take()!.text).set.state).toEqual(rows[0].set.state);
  });
  it("retains a match through disconnect and respawn, replaces it after hangar or map change",()=>{
    const boundary=new RecordingMatchBoundary(), frame=(at:number)=>recordingFrame(raw(at),{});
    expect(boundary.update(frame(0))).toBe("new");
    expect(boundary.update({...frame(100),bridgeReachable:false,state:null,mapObjects:null})).toBe("continue");
    expect(boundary.update(frame(200))).toBe("continue");
    boundary.update({...frame(1000),state:{valid:false},mapObjects:[]});
    expect(boundary.update(frame(2000))).toBe("continue");
    boundary.update({...frame(3000),state:{valid:false},mapObjects:[],availability:{state:true,mapObjects:true}});
    expect(boundary.update(frame(14000))).toBe("continue");
    boundary.update({...frame(15000),state:{valid:false},mapObjects:null,availability:{state:true,mapObjects:false}});
    boundary.update({...frame(26000),state:{valid:false},mapObjects:null,availability:{state:true,mapObjects:false}});
    expect(boundary.update(frame(27000))).toBe("new");
    expect(boundary.update({...frame(28000),mapInfo:{map_min:[0,0],map_max:[200,200],map_generation:3}})).toBe("new");
  });
});
