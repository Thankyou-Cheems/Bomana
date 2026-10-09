import { FLIGHT_RECORDING_SCHEMA, FlightRecordingEncoder, RecordingMatchBoundary, recordingFrame, retainedRecordingChunks,
  RECORDING_CHUNK_BYTES, RECORDING_CHUNK_MS } from "./flight-recording";
import type { RecordingContext } from "./flight-recording";
import type { Official8111Frame } from "./telemetry-source";

interface Chunk { id?: number; session: string; fromMs: number; toMs: number; frames: number; bytes: number; codec: "gzip" | "json"; data: Blob }
interface Meta { id: string; session: string; map: string; edition: string; version: string; startedAtMs: number; toMs: number; ended: boolean }
type Message = { type: "frame"; frame: Official8111Frame; context: RecordingContext; dropped: number }
  | { type: "enable"; enabled: boolean } | { type: "export" | "clear" | "flush"; requestId?: number };
let db: IDBDatabase | null = null;
let encoder = new FlightRecordingEncoder();
let boundary = new RecordingMatchBoundary();
let meta: Meta | null = null;
let enabled = true, ownsLock = false, stopped = false, sessionReady = false;
let releaseLock: (() => void) | undefined;
let queue = Promise.resolve();

function request<T>(operation: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => { operation.onsuccess = () => resolve(operation.result); operation.onerror = () => reject(operation.error); });
}
function finished(tx: IDBTransaction): Promise<void> {
  return new Promise((resolve, reject) => { tx.oncomplete = () => resolve(); tx.onerror = tx.onabort = () => reject(tx.error ?? new Error("recording transaction aborted")); });
}
async function open(): Promise<IDBDatabase> {
  if (db) return db;
  const operation = indexedDB.open("bomana-flight-recording-v1", 1);
  operation.onupgradeneeded = () => {
    operation.result.createObjectStore("chunks", { keyPath: "id", autoIncrement: true });
    operation.result.createObjectStore("meta", { keyPath: "id" });
  };
  db = await request(operation);
  db.onversionchange = () => { db?.close(); db = null; };
  return db;
}
async function rows(): Promise<Chunk[]> { return request((await open()).transaction("chunks").objectStore("chunks").getAll()); }
async function status(message?: string): Promise<void> {
  const chunks = await rows();
  self.postMessage({ type: "status", enabled, owner: ownsLock, stopped, bytes: chunks.reduce((n,c)=>n+c.bytes,0),
    frames: chunks.reduce((n,c)=>n+c.frames,0), fromMs: chunks[0]?.fromMs ?? null, toMs: chunks.at(-1)?.toMs ?? null, message });
}
async function acquire(): Promise<void> {
  if (ownsLock || !enabled || stopped) return;
  if (!navigator.locks) { stopped = true; await status("此浏览器暂不支持本地飞行记录"); return; }
  void navigator.locks.request("bomana-flight-recording-writer", { ifAvailable: true }, async lock => {
    if (!lock || !enabled || stopped) return;
    ownsLock = true; sessionReady = false;
    try { await status(); await new Promise<void>(resolve => { releaseLock = resolve; }); }
    finally { ownsLock = false; releaseLock = undefined; }
  }).catch(() => fail());
}
async function flush(): Promise<void> {
  if (!ownsLock || !meta) return;
  if (!encoder.frames) {
    if (boundary.ended && !meta.ended) {
      const tx = (await open()).transaction("meta", "readwrite"), done = finished(tx);
      meta.ended = boundary.ended;
      tx.objectStore("meta").put(meta);
      await done;
    }
    return;
  }
  const raw = encoder.take()!;
  const input = new Blob([raw.text]);
  const codec = typeof CompressionStream === "function" ? "gzip" : "json";
  const data = codec === "gzip" ? await new Response(input.stream().pipeThrough(new CompressionStream("gzip"))).blob() : input;
  const chunk: Chunk = { session: meta.session, fromMs: raw.fromMs, toMs: raw.toMs, frames: raw.frames, bytes: data.size, codec, data };
  const existing = await rows();
  const keep = new Set(retainedRecordingChunks(existing, chunk).map(old => old.id));
  const tx = (await open()).transaction(["chunks", "meta"], "readwrite"), done = finished(tx);
  const store = tx.objectStore("chunks");
  for (const old of existing) if (!keep.has(old.id!)) store.delete(old.id!);
  store.add(chunk);
  meta.toMs = chunk.toMs; meta.ended = boundary.ended;
  tx.objectStore("meta").put(meta);
  await done;
  await status();
}
async function capture(message: Extract<Message, { type: "frame" }>): Promise<void> {
  if (!enabled || !ownsLock || stopped) return;
  const frame = recordingFrame(message.frame, message.context);
  const decision = boundary.update(frame);
  if (decision === "idle") { await flush(); return; }
  if (decision === "new" || !sessionReady) {
    await flush();
    const map = boundary.mapKey;
    const old = await request<Meta | undefined>((await open()).transaction("meta").objectStore("meta").get("latest"));
    // Reloading the same sortie continues it; a confirmed hangar/new map does not.
    const resume = !sessionReady && old && !old.ended && old.map === map && old.edition === message.context.edition
      && message.frame.sampledAtMs >= old.toMs && message.frame.sampledAtMs - old.toMs < 5 * 60_000;
    meta = resume ? old : { id: "latest", session: crypto.randomUUID(), map, edition: String(message.context.edition),
      version: String(message.context.version ?? ""), startedAtMs: message.frame.sampledAtMs, toMs: message.frame.sampledAtMs, ended: false };
    sessionReady = true;
  }
  encoder.add(frame, message.dropped);
  if (encoder.bytes >= RECORDING_CHUNK_BYTES || encoder.toMs - encoder.fromMs >= RECORDING_CHUNK_MS) await flush();
}
async function exportRecording(requestId?: number): Promise<void> {
  await flush();
  const tx = (await open()).transaction(["chunks", "meta"]);
  const [chunks, storedMeta] = await Promise.all([
    request<Chunk[]>(tx.objectStore("chunks").getAll()), request(tx.objectStore("meta").get("latest")),
  ]);
  const parts: BlobPart[] = [`{"schema":${JSON.stringify(FLIGHT_RECORDING_SCHEMA)},"meta":${JSON.stringify(storedMeta ?? null)},"chunks":[`];
  for (const [index, chunk] of chunks.entries()) {
    const bytes = new Uint8Array(await chunk.data.arrayBuffer());
    let binary = "";
    for (let i=0;i<bytes.length;i+=8192) binary += String.fromCharCode(...bytes.subarray(i,i+8192));
    parts.push((index ? "," : "") + JSON.stringify({ fromMs:chunk.fromMs,toMs:chunk.toMs,frames:chunk.frames,codec:chunk.codec,data:btoa(binary) }));
  }
  parts.push("]}");
  self.postMessage({type:"export",requestId,blob:new Blob(parts,{type:"application/json"})});
}
function fail(): void {
  stopped = true; encoder = new FlightRecordingEncoder(); releaseLock?.();
  self.postMessage({type:"status",enabled,owner:false,stopped:true,message:"本地记录暂停：浏览器存储不可用或空间不足"});
}
async function clear(): Promise<void> {
  encoder = new FlightRecordingEncoder(); boundary = new RecordingMatchBoundary(); meta = null; sessionReady = false;
  const tx = (await open()).transaction(["chunks","meta"],"readwrite"), done=finished(tx);
  tx.objectStore("chunks").clear();tx.objectStore("meta").clear();await done;await status();
}
async function handle(message: Message): Promise<void> {
  try {
    if (message.type === "frame") await capture(message);
    else if (message.type === "enable") {
      enabled = message.enabled;
      if (!enabled) { await flush(); releaseLock?.(); }
      else { stopped = false; await acquire(); }
      await status();
    } else if (message.type === "flush") await flush();
    else if (message.type === "export") await exportRecording(message.requestId);
    else if (message.type === "clear") {
      // Other tabs cannot erase the active writer's pending chunk.
      if (ownsLock) await clear();
      else if (navigator.locks) await navigator.locks.request("bomana-flight-recording-writer", { ifAvailable: true }, async lock => {
        if (lock) await clear(); else await status("请在正在记录的页面清除");
      });
    }
  } catch { fail(); if (message.type === "export") self.postMessage({type:"export",requestId:message.requestId,error:true}); }
  finally { if (message.type === "frame") self.postMessage({type:"ack"}); }
}
self.onmessage = (event: MessageEvent<Message>) => { queue = queue.then(() => handle(event.data)); };
setInterval(() => { queue = queue.then(acquire).catch(fail); }, 10_000);
