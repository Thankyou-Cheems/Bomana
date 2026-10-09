import type { Official8111Frame } from "./telemetry-source";
import type { RecordingContext } from "./flight-recording";

const preference = "bomana:flight-recording:enabled:v1";
/** One in-flight frame bounds worker input even on overloaded machines. */
export function mountFlightRecorder(host: HTMLElement, edition: string) {
  const panel=document.createElement("fieldset");panel.className="control-group flight-recording";
  panel.innerHTML=`<legend>本地飞行记录</legend><label><input type="checkbox" data-recording-enabled checked>自动记录近期一局</label>
    <p class="control-help">仅保存在本机，保留最后一局中最多 3 小时 / 32 MiB 的数据，停飞后仍可导出。不含聊天或授权信息，不会自动上传。</p>
    <p data-recording-status role="status">等待飞行数据</p><button type="button" class="ghost-btn" data-recording-export>导出记录</button>
    <button type="button" class="ghost-btn" data-recording-clear>清除记录</button>`;
  host.append(panel);
  const checkbox=panel.querySelector<HTMLInputElement>("input")!,status=panel.querySelector<HTMLElement>("[data-recording-status]")!;
  const exportButton=panel.querySelector<HTMLButtonElement>("[data-recording-export]")!;
  const clearButton=panel.querySelector<HTMLButtonElement>("[data-recording-clear]")!;
  let enabled=true,busy=false,dropped=0,worker:Worker|null=null,failed=false;
  try { enabled=localStorage.getItem(preference)!=="false"; } catch { /* Session-only preference. */ }
  checkbox.checked=enabled;
  try { worker=new Worker(new URL("./flight-recorder.worker.ts",import.meta.url),{type:"module"}); }
  catch { failed=true;status.textContent="此浏览器暂不支持本地飞行记录"; }
  worker?.addEventListener("error",()=>{ failed=true;busy=false;status.textContent="本地飞行记录暂不可用";exportButton.disabled=false; });
  worker?.addEventListener("message",event=>{
    const message=event.data;
    if(message.type==="ack")busy=false;
    else if(message.type==="status"){
      failed=message.stopped===true;
      status.textContent=message.message ?? `${!enabled?"自动记录已关闭":message.owner?"自动记录中":"由另一页面记录"} · ${((message.bytes??0)/1048576).toFixed(1)} MiB · ${message.frames??0} 帧`;
    }else if(message.type==="export"){
      exportButton.disabled=false;
      if(message.error){status.textContent="导出失败，请检查浏览器存储";return;}
      const url=URL.createObjectURL(message.blob),link=document.createElement("a");
      link.href=url;link.download=`Bomana-flight-${new Date().toISOString().replaceAll(":","-")}.json`;link.click();
      setTimeout(()=>URL.revokeObjectURL(url),60_000);
    }
  });
  const configure=()=>worker?.postMessage({type:"enable",enabled});configure();
  checkbox.addEventListener("change",()=>{enabled=checkbox.checked;try{localStorage.setItem(preference,String(enabled));}catch{}configure();});
  window.addEventListener("storage",event=>{if(event.key===preference){enabled=event.newValue!=="false";checkbox.checked=enabled;configure();}});
  exportButton.addEventListener("click",()=>{if(!worker)return;exportButton.disabled=true;worker.postMessage({type:"export"});});
  clearButton.addEventListener("click",()=>worker?.postMessage({type:"clear"}));
  const flush=()=>worker?.postMessage({type:"flush"});
  window.addEventListener("pagehide",flush);
  document.addEventListener("visibilitychange",()=>{if(document.hidden)flush();});
  return {
    record(frame:Official8111Frame,context:RecordingContext={}){
      if(!enabled||failed||!worker)return;
      if(busy){dropped++;return;}
      busy=true;
      // Do not even send gameChat into the recorder worker.
      const {gameChat:_chat,...telemetry}=frame;
      worker.postMessage({type:"frame",frame:telemetry,context:{...context,edition,version:document.getElementById("app-web-version")?.textContent??""},dropped});
      dropped=0;
    },
  };
}
