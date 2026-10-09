import { readFile, stat } from "node:fs/promises";
import { createWriteStream } from "node:fs";
import { once } from "node:events";
import { gunzipSync } from "node:zlib";
import { pathToFileURL } from "node:url";

/** Expand independent chunks into replayable official frames; never execute input. */
export function* decodeFlightRecording(recording) {
  if(recording?.schema!=="bomana-flight-recording/v1"||!Array.isArray(recording.chunks)||recording.chunks.length>5000)throw new Error("Unsupported flight recording");
  let total=0;
  for(const chunk of recording.chunks){
    if(!["gzip","json"].includes(chunk.codec)||typeof chunk.data!=="string"||chunk.data.length>6*1024*1024)throw new Error("Invalid recording chunk");
    const compressed=Buffer.from(chunk.data,"base64");
    const bytes=chunk.codec==="gzip"?gunzipSync(compressed,{maxOutputLength:4*1024*1024}):compressed;
    total+=bytes.length;if(bytes.length>4*1024*1024||total>2*1024*1024*1024)throw new Error("Recording exceeds decode budget");
    let frame={};
    for(const line of bytes.toString("utf8").trim().split("\n")){
      const row=JSON.parse(line);
      if(!Number.isFinite(row.atMs)||!row.set||typeof row.set!=="object"||Array.isArray(row.set))throw new Error("Invalid recording frame");
      frame={...frame,...row.set};
      yield {...frame,...(row.droppedBefore?{recordingDroppedBefore:row.droppedBefore}:{})};
    }
  }
}
if(process.argv[1]&&import.meta.url===pathToFileURL(process.argv[1]).href){
  const [input,output]=process.argv.slice(2);
  if(!input||!output)throw new Error("Usage: node frontend/scripts/flight-recording-read.mjs recording.json replay.jsonl");
  if((await stat(input)).size>48*1024*1024)throw new Error("Recording is larger than 48 MiB");
  const recording=JSON.parse(await readFile(input,"utf8"));
  const stream=createWriteStream(output,{flags:"wx"});
  let frames=0,dropped=0;
  try {
    for(const frame of decodeFlightRecording(recording)){
      if(!stream.write(JSON.stringify(frame)+"\n"))await once(stream,"drain");
      frames++;dropped+=frame.recordingDroppedBefore??0;
    }
    stream.end();await once(stream,"finish");
  }catch(error){stream.destroy();throw error;}
  console.log(JSON.stringify({schema:recording.schema,frames,dropped,output}));
}
