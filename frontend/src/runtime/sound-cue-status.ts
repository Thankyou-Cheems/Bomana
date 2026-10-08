import type { SoundCues } from "./sound-cues";

/** Start enabled audio on entry; only expose a retry when playback is unavailable. */
export function bindSoundCueStatus(sound: SoundCues, parent: HTMLElement): () => void {
  const doc = parent.ownerDocument;
  const button = doc.createElement("button");
  button.type = "button"; button.id = "sound-ready"; button.className = "connection-retry";
  button.setAttribute("aria-live", "polite");
  parent.append(button);
  const update = (): void => {
    button.textContent = "恢复声音";
    button.title = "声音已开启；若浏览器暂停播放，点击页面即可恢复";
    button.hidden = !sound.enabled || sound.ready;
    button.disabled = !sound.enabled || sound.ready;
    button.dataset.ready = String(sound.ready);
  };
  const removeStatus = sound.observeStatus(update);
  const enable = (): void => { void sound.enable().catch(() => update()); };
  const gesture = (): void => { if (sound.enabled && !sound.ready) enable(); };
  const recover = (): void => {
    if (doc.visibilityState === "visible" && sound.enabled) void sound.recover().catch(() => update());
  };
  button.addEventListener("click", enable);
  doc.addEventListener("click", gesture);
  doc.addEventListener("keydown", gesture);
  doc.addEventListener("visibilitychange", recover);
  doc.defaultView?.addEventListener("pageshow", recover);
  if (sound.enabled) enable();
  return () => {
    removeStatus(); button.remove();
    doc.removeEventListener("click", gesture); doc.removeEventListener("keydown", gesture);
    doc.removeEventListener("visibilitychange", recover); doc.defaultView?.removeEventListener("pageshow", recover);
  };
}
