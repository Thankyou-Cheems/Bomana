import type { SoundCues } from "./sound-cues";

/** Visible permission/readiness is separate from the user's saved mute intent. */
export function bindSoundCueStatus(sound: SoundCues, parent: HTMLElement): () => void {
  const doc = parent.ownerDocument;
  const button = doc.createElement("button");
  button.type = "button"; button.id = "sound-ready"; button.className = "connection-retry";
  button.setAttribute("aria-live", "polite");
  parent.append(button);
  const update = (): void => {
    button.textContent = !sound.enabled ? "提示音已关闭" : sound.ready ? "提示音已就绪" : "点按启用 / 恢复提示音";
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
  doc.addEventListener("pointerdown", gesture);
  doc.addEventListener("keydown", gesture);
  doc.addEventListener("visibilitychange", recover);
  doc.defaultView?.addEventListener("pageshow", recover);
  return () => {
    removeStatus(); button.remove();
    doc.removeEventListener("pointerdown", gesture); doc.removeEventListener("keydown", gesture);
    doc.removeEventListener("visibilitychange", recover); doc.defaultView?.removeEventListener("pageshow", recover);
  };
}
