import { flightDisplayMode, observeFlightDisplayMode, type FlightDisplayMode } from "./flight-display-mode";
import type { StrikeEncyclopedia } from "./strike-encyclopedia";

/** User-owned calculator inputs, shared by desktop and paired Phone Web. */
export function bindStrikeBattleRating(encyclopedia: StrikeEncyclopedia, aircraft: HTMLSelectElement,
  roomBr: HTMLSelectElement, note: HTMLElement): void {
  const key = "bomana:damage-br-selection:v1";
  let mode = flightDisplayMode();
  let saved: Partial<{aircraftId: string; mode: FlightDisplayMode; roomBr: string}> | null = null;
  try { saved = JSON.parse(localStorage.getItem(key) ?? "null"); } catch { /* Session-only when storage is disabled. */ }
  if (typeof saved?.aircraftId === "string") {
    aircraft.value = encyclopedia.aircraft().some(row => row.id === saved.aircraftId) ? saved.aircraftId : "";
  }
  if (typeof saved?.roomBr === "string" && [...roomBr.options].some(option => option.value === saved.roomBr)) roomBr.value = saved.roomBr;
  let previousAircraft = aircraft.value;
  const refreshNote = (): void => {
    const value = encyclopedia.aircraftBattleRating(aircraft.value, mode);
    const name = mode === "air-realistic" ? "空历" : "全真";
    note.textContent = value === null
      ? "当前机型缺少此模式 BR；保留房间选择，请按实际房间手动调整。"
      : `按${name}展示模式参考：机型 BR ${value.toFixed(1)} 仅作默认；房间最高 BR 请按实际房间手动调整。`;
  };
  const save = (): void => {
    try { localStorage.setItem(key, JSON.stringify({aircraftId: aircraft.value, mode, roomBr: roomBr.value})); }
    catch { /* Keep user controls usable without browser storage. */ }
  };
  const useAircraftBr = (): void => {
    const value = encyclopedia.aircraftBattleRating(aircraft.value, mode);
    if (value !== null) roomBr.value = String(value);
    refreshNote();
  };
  if (saved && saved.mode !== mode) useAircraftBr();
  refreshNote();
  aircraft.addEventListener("change", () => {
    if (aircraft.value !== previousAircraft) useAircraftBr();
    previousAircraft = aircraft.value;
    save();
  });
  roomBr.addEventListener("change", save);
  observeFlightDisplayMode(next => {
    if (next === mode) return;
    mode = next;
    useAircraftBr();
    save();
  });
}
