import assert from "node:assert/strict";
import { test } from "node:test";
import { gzipSync } from "node:zlib";
import { decodeFlightRecording } from "./flight-recording-read.mjs";
const recording=chunks=>({schema:"bomana-flight-recording/v1",chunks});
test("replay restores frame deltas and resets at independent retained chunks",()=>{
  const payload=recording([{codec:"gzip",data:gzipSync('{"atMs":1,"set":{"sampledAtMs":1,"state":{"valid":true}}}\n{"atMs":2,"set":{"sampledAtMs":2},"droppedBefore":3}\n').toString('base64')},
    {codec:"json",data:Buffer.from('{"atMs":3,"set":{"sampledAtMs":3,"state":null}}\n').toString('base64')}]);
  assert.deepEqual([...decodeFlightRecording(payload)],[{sampledAtMs:1,state:{valid:true}},{sampledAtMs:2,state:{valid:true},recordingDroppedBefore:3},{sampledAtMs:3,state:null}]);
});
test("replay rejects malformed schemas and compressed expansion beyond the recording budget",()=>{
  assert.throws(()=>[...decodeFlightRecording({schema:'other',chunks:[]})]);
  assert.throws(()=>[...decodeFlightRecording(recording([{codec:'gzip',data:gzipSync(Buffer.alloc(4*1024*1024+1)).toString('base64')}]))]);
});
